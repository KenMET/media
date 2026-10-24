import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from media_mcp.adapters.torrent import infohash
from media_mcp.config import contained, check_hardlinks
from media_mcp.application.identity import expected_identity,validate_identity


class Boundaries(unittest.TestCase):
    def test_exact_info_bytes_and_bad_payloads(self):
        info=b'd6:lengthi1e4:name1:xe'
        self.assertEqual(infohash(b'd4:info'+info+b'e'),hashlib.sha1(info).hexdigest())
        self.assertEqual(infohash(magnet='magnet:?xt=urn:btih:'+'A'*40),'a'*40)
        for bad in (b'not torrent',b'd4:infoi1ee',b'd4:infode4:infodee',b'd4:infodeeEXTRA'):
            with self.assertRaises(ValueError): infohash(bad)

    def test_path_escape_symlinks_and_real_hardlink(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); source=base/'downloads';library=base/'library'
            with patch.dict(os.environ,{'MEDIA_DOWNLOAD_ROOT':str(source),'MEDIA_LIBRARY_ROOT':str(library)}):
                check_hardlinks()
                file=source/'x.mkv';file.write_bytes(b'video')
                self.assertEqual(contained(str(file)),file)
                alias=source/'alias.mkv';alias.symlink_to(file)
                with self.assertRaises(ValueError):contained(str(alias))
                with self.assertRaises(ValueError):contained(str(base/'outside'),exists=False)
                self.assertEqual(list(library.iterdir()),[])

    def test_requested_identity_fence(self):
        token=expected_identity.set({'identity':{'kind':'tv','tmdb_id':1},'scope':{'season':2,'episodes':[1,2]}})
        try:
            validate_identity({'media_type':'tv','media_tmdb_id':1,'season':2,'episode':1})
            for value in ({'media_type':'movie','media_tmdb_id':1},
                          {'media_type':'tv','media_tmdb_id':1,'season':2,'episode':3}):
                with self.assertRaises(ValueError):validate_identity(value)
        finally:expected_identity.reset(token)
