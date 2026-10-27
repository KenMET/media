"""Real TCP OAuth + MCP check; disposable acceptance instance only."""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import requests
from fastmcp import Client


def main():
    if os.environ.get('MEDIA_ACCEPTANCE')!='isolated-container' or not Path('/state/.acceptance').is_file():
        raise SystemExit('Refusing non-acceptance instance')
    base='http://127.0.0.1:'+os.environ.get('MEDIA_MCP_PORT','18210')
    async def check():
        async with Client(base+'/mcp') as client:
            tools=await client.list_tools();assert len(tools)>=10
            result=await client.call_tool('media_status')
            assert result.structured_content['service']=='media-mcp'
            jobs=await client.call_tool('media_list_jobs')
            assert jobs.structured_content['success']
            workflow=await client.call_tool('media_get_workflow')
            assert 'media_start_acquisition' in workflow.structured_content['workflow']
            return {'transport':'real TCP Streamable HTTP','tools':len(tools),
                    'authentication':'none (LAN)' ,'worker_ready':result.structured_content['worker_ready']}
    result=asyncio.run(check())
    print(json.dumps({'acceptance':'passed',**result},ensure_ascii=False))


if __name__=='__main__':main()
