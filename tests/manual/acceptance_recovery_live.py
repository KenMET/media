"""Probe the marked test stack before/offline/after a deliberate local restart."""
import json
import os
from pathlib import Path
import sys

import requests


def main():
    assert Path('/state/.acceptance').is_file()
    assert os.environ.get('MEDIA_ACCEPTANCE') == 'isolated-container'
    mode = sys.argv[1]
    private = Path('/state/live-recovery-session.json')
    base = 'http://127.0.0.1:18414'
    client = requests.Session()
    if mode == 'before':
        result = client.post(base+'/api/auth/login',json={'username':'compose-check',
            'password':'compose-acceptance-password-123'},timeout=15).json()
        assert result['success']
        payload = {'cookies':client.cookies.get_dict(),'csrf':result['data']['csrf']}
        private.write_text(json.dumps(payload)); private.chmod(0o600)
    payload = json.loads(private.read_text())
    client.cookies.update(payload['cookies'])
    client.headers['x-csrf-token'] = payload['csrf']
    response = client.get(base+'/api/status',timeout=20)
    if mode == 'offline':
        assert response.status_code == 503
        assert client.post(base+'/api/command',json={'operation':'jobs','arguments':{}},timeout=20).status_code == 503
        assert client.get(base+'/healthz',timeout=5).status_code == 200
        print(json.dumps({'acceptance':'passed','local_offline':True,'gateway_alive':True,
                          'task_reads_and_writes_fail_closed':503}))
        return
    assert response.status_code == 200
    assert response.json()['data']['worker_ready'] is True
    result = client.post(base+'/api/command',json={'operation':'jobs','arguments':{}},timeout=15).json()
    jobs = result['data']['jobs']
    assert len(jobs) == 1 and jobs[0]['stage'] == 'completed'
    manifest = json.loads(Path('/state/live-download.json').read_text())
    assert jobs[0]['job_id'] == manifest['job_id']
    tasks = requests.get('http://127.0.0.1:18411/api/v2/torrents/info',timeout=15).json()
    assert len(tasks) == 1 and tasks[0]['hash'] == manifest['infohash'] and tasks[0]['progress'] == 1
    print(json.dumps({'acceptance':'passed','phase':mode,'same_completed_task':True,
                      'torrent_count':1,'worker_ready':True}))
    if mode == 'after':
        client.post(base+'/api/auth/logout',json={},timeout=15).raise_for_status()
        private.unlink()


if __name__ == '__main__':
    main()
