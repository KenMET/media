import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from media_mcp.adapters.tmdb import TMDB
from media_mcp.platform.storage_status import storage_status
import test_catalog


class SearchTests(unittest.TestCase):
    def test_multi_preserves_provider_relevance_and_filters_people(self):
        provider=TMDB();provider.get=Mock(return_value={'results':[
            {'id':2,'media_type':'tv','name':'First'},
            {'id':3,'media_type':'person','name':'Person'},
            {'id':1,'media_type':'movie','title':'Second'}]})
        rows=provider.search('Name')
        self.assertEqual([x['title_id'] for x in rows],['tv:2','movie:1'])
        provider.get.assert_called_once_with('search/multi',query='Name',include_adult='false')

    def test_disk_usage_reports_mount_and_unavailable_path(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{
            'MEDIA_DOWNLOAD_ROOT':root,'MEDIA_LIBRARY_ROOT':str(Path(root)/'missing')}):
            rows=storage_status()
            self.assertTrue(rows[0]['available']);self.assertGreater(rows[0]['free'],0)
            self.assertFalse(rows[1]['available'])


class TopRatedTests(unittest.TestCase):
    setUp=test_catalog.CatalogTests.setUp
    def test_historical_scores_use_top_rated_not_trending(self):
        self.tmdb.get.return_value={'results':[{'id':389,'title':'Classic','vote_average':8.5}]}
        result=self.catalog.discover('tmdb','movie','top')
        self.assertEqual(result['items'][0]['title_id'],'movie:389')
        self.tmdb.get.assert_called_once_with('movie/top_rated',page=1)
        self.catalog.discover('tmdb','movie','top');self.assertEqual(self.tmdb.get.call_count,1)
