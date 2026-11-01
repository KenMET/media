"""Read-only retained-version summaries with disposable media and SQLite."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from media_mcp.application.job_outcomes import refresh_job_outcome
from media_mcp.storage.client import DatabaseClient
from media_mcp.storage.records import Records
from media_mcp.runtime.state import MediaJobs


class JobOutcomeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root = Path(temp.name);self.downloads=root/'downloads';self.library=root/'library'
        self.downloads.mkdir();self.library.mkdir()
        env=patch.dict(os.environ,{'MEDIA_DB_PATH':str(root/'state/media.sqlite3'),
            'MEDIA_DOWNLOAD_ROOT':str(self.downloads),'MEDIA_LIBRARY_ROOT':str(self.library)})
        env.start();self.addCleanup(env.stop)
        self.db=DatabaseClient();Records(self.db).initialize();MediaJobs().initialize()
        self.db.execute('CREATE TABLE media_link (id INTEGER PRIMARY KEY,source_path TEXT,target_path TEXT,status TEXT,reason TEXT,media_type TEXT,media_tmdb_id INTEGER,season INTEGER,episode INTEGER)')
        self.source=self.downloads/'new'/'movie.mkv';self.source.parent.mkdir();self.source.write_bytes(b'new')
        self.old=self.downloads/'old.mkv';self.old.write_bytes(b'old');self.target=self.library/'Movie.mkv';os.link(self.old,self.target)
        self.db.execute("INSERT INTO media_link VALUES (1,:source,'','unlinked','quality_not_comparable; {}','movie',1,NULL,NULL)",{'source':str(self.source)})
        self.db.execute("INSERT INTO media_link VALUES (2,:source,:target,'linked','verified','movie',1,NULL,NULL)",{'source':str(self.old),'target':str(self.target)})
        for stage,state,result in [('ingest','needs_review',{}),('subtitle','succeeded',{'media_count':0})]:
            self.db.execute("INSERT INTO media_processing_job(delivery_key,stage,path,state,result_json,next_attempt_at,created_at,updated_at) VALUES ('key',:stage,:path,:state,:result,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",{'stage':stage,'path':str(self.source.parent),'state':state,'result':json.dumps(result)})
        self.db.execute("UPDATE media_processing_job SET error='no_media_processed',result_json=:result WHERE stage='ingest'",{'result':json.dumps({'failed':0,'review':0})})
        self.row={'data':{'source_path':str(self.source.parent),'delivery_hash':'key','identity':{'title_id':'movie:1'}}}

    def test_existing_hardlink_and_actual_zero_media_subtitle_are_explicit(self):
        public={'processing':[{'stage':'subtitle','state':'queued'}]}
        before=self.db.execute('SELECT COUNT(*) FROM media_processing_job').scalar()
        refresh_job_outcome(self.db,self.row,public)
        self.assertTrue(public['library_outcome']['explains_review'])
        self.assertTrue(public['library_outcome']['quality_review'])
        self.assertTrue(public['library_outcome']['subtitle_no_media'])
        self.assertEqual(public['library_outcome']['items'][0]['name'],'Movie.mkv')
        self.assertEqual(public['processing'][1]['state'],'succeeded')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM media_processing_job').scalar(),before)
        self.assertEqual(self.target.read_bytes(),b'old');self.assertEqual(self.source.read_bytes(),b'new')

    def test_missing_or_non_hardlinked_target_never_claims_an_existing_link(self):
        self.target.unlink();self.target.write_bytes(b'copy')
        public={};refresh_job_outcome(self.db,self.row,public)
        self.assertNotIn('library_outcome',public)
        self.target.unlink();public={};refresh_job_outcome(self.db,self.row,public)
        self.assertNotIn('library_outcome',public)

    def test_other_identity_and_neighbor_delivery_paths_are_not_adopted(self):
        self.row['data']['identity']['title_id']='movie:2'
        public={};refresh_job_outcome(self.db,self.row,public);self.assertNotIn('library_outcome',public)
        self.row['data']['identity']['title_id']='movie:1';self.row['data']['source_path']=str(self.downloads/'ne')
        public={};refresh_job_outcome(self.db,self.row,public);self.assertNotIn('library_outcome',public)

    def test_other_processing_failures_are_not_hidden_by_retention(self):
        self.db.execute("UPDATE media_processing_job SET state='retry',error='subtitle_incomplete' WHERE stage='subtitle'")
        public={};refresh_job_outcome(self.db,self.row,public)
        self.assertFalse(public['library_outcome']['explains_review'])
        self.assertFalse(public['library_outcome']['subtitle_no_media'])
