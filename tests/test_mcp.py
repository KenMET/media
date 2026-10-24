import asyncio
import unittest
from fastmcp import Client
from media_mcp.server import create_server


class Service:
    def search_titles(self, query, kind, year):
        return {'titles':[{'title_id':'movie:1','title':query}]}
    def start(self,*args):
        return {'job_id':'a'*32,'stage':'queued'}
    def library(self,*args):
        raise RuntimeError('private SQL credential that must not be returned')


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_structured_calls_and_skill(self):
        async with Client(create_server(Service())) as client:
            tools = {t.name:t for t in await client.list_tools()}
            self.assertIn('media_run_subtitles',tools)
            self.assertFalse(tools['media_start_acquisition'].annotations.readOnlyHint)
            result = await client.call_tool('media_search_titles',{'query':'Example','kind':'movie'})
            self.assertEqual(result.structured_content['data']['titles'][0]['title_id'],'movie:1')
            result = await client.call_tool('media_start_acquisition',{'plan_id':'a'*32,'revision':1,'idempotency_key':'request-123'})
            self.assertEqual(result.structured_content['data']['stage'],'queued')
            skill = await client.call_tool('media_get_workflow')
            self.assertIn('media_plan_acquisition',skill.structured_content['workflow'])
            resource = await client.read_resource('media://skills/media-acquire')
            self.assertIn('media-acquire',resource[0].text)
            result = await client.call_tool('media_get_library',{'title_id':'movie:1'})
            self.assertEqual(result.structured_content['error_code'],'dependency_unavailable')
            self.assertNotIn('credential',str(result))

    async def test_invalid_schema_does_not_reach_handler(self):
        async with Client(create_server(Service())) as client:
            with self.assertRaises(Exception):
                await client.call_tool('media_start_acquisition',{'plan_id':'a','revision':1,'idempotency_key':'tiny'})
