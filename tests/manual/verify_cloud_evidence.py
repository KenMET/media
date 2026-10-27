"""Verify retained disposable download evidence without accessing production mounts."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from acceptance_download_live import bdecode


def main():
    if os.environ.get('MEDIA_ACCEPTANCE') != 'isolated-container' or not Path('/state/.acceptance').is_file():
        raise SystemExit('Refusing unmarked acceptance state')
    connection=sqlite3.connect('file:/state/media.sqlite3?mode=ro',uri=True)
    rows=connection.execute('SELECT kind,state,data FROM media_mcp_record').fetchall()
    jobs=[json.loads(data) for kind,state,data in rows if kind=='acquisition' and state=='completed']
    assert len(jobs)==1
    plans=[json.loads(data) for kind,state,data in rows if kind=='plan']
    assert len(plans)==1
    info=bdecode(base64.b64decode(plans[0]['cloud_payload']['data']))[b'info']
    video=Path(jobs[0]['source_path'])
    assert str(video).startswith('/data/downloads/') and video.is_file()
    content=video.read_bytes()
    assert len(content)==info[b'length']
    piece_length=info[b'piece length']
    assert b''.join(hashlib.sha1(content[i:i+piece_length]).digest() for i in range(0,len(content),piece_length))==info[b'pieces']
    target=connection.execute("SELECT target_path FROM media_link WHERE status='linked'").fetchone()[0]
    assert str(target).startswith('/data/media_hub/') and os.path.samefile(video,target)
    cloud=sqlite3.connect('file:/cloud/catalog.sqlite3?mode=ro',uri=True)
    assert cloud.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='media_link'").fetchone()[0]==0
    assert Path('/state/control-pairing.sealed').read_text()==hashlib.sha256(Path('/cloud/control-token').read_text().strip().encode()).hexdigest()
    print(json.dumps({'acceptance':'passed','completed_jobs':1,'source_torrent_pieces_match':True,
        'hardlink_same_inode':True,'source_link_count':video.stat().st_nlink,
        'cloud_has_media_database':False,'pairing_seal_matches_private_credential':True}))


if __name__=='__main__':
    main()
