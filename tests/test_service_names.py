"""Role names, legacy configuration and bounded application-container migration."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch


class ServiceNamesTests(unittest.TestCase):
    source=Path(__file__).resolve().parents[1]

    def test_compose_roles_and_console_scripts_are_explicit(self):
        import yaml
        local=yaml.safe_load((self.source/'compose.local.yml').read_text())['services']
        cloud=yaml.safe_load((self.source/'compose.cloud.yml').read_text())['services']
        self.assertEqual({'local-control','local-worker','local-mcp'},set(local)-{'qbittorrent','jackett','init-qbittorrent','init-jackett'})
        self.assertEqual({'cloud-web','cloud-mcp'},set(cloud)-{'jackett','init-jackett'})
        self.assertEqual(local['local-control']['command'],['media-local-control'])
        self.assertEqual(cloud['cloud-web']['command'],['media-cloud-web'])
        scripts=tomllib.loads((self.source/'pyproject.toml').read_text())['project']['scripts']
        self.assertEqual(scripts['media-local-control'],scripts['media-web'])
        self.assertEqual(scripts['media-cloud-web'],scripts['media-gateway'])
        self.assertEqual(scripts['media-local-worker'],scripts['media-worker'])

    def test_explicit_mcp_commands_do_not_confuse_template_roles(self):
        from media_mcp.server import local_main,cloud_main
        for run,port,host in ((local_main,19610,'127.0.0.2'),(cloud_main,29610,'127.0.0.3')):
            server=Mock()
            with self.subTest(role=run.__name__),patch.dict(os.environ,{
                    'MEDIA_CLOUD_CONTROL_PORT':'29213','MEDIA_LOCAL_MCP_PORT':'19610',
                    'MEDIA_CLOUD_MCP_PORT':'29610','MEDIA_MCP_PORT':'18210',
                    'MEDIA_LOCAL_MCP_BIND':'127.0.0.2','MEDIA_CLOUD_MCP_BIND':'127.0.0.3',
                    'MEDIA_AUTH_MODE':'none'},clear=True),patch('media_mcp.server.create_server',return_value=server),patch('media_mcp.storage.media._client'),patch('media_mcp.server.Records'),patch('media_mcp.runtime.state.MediaJobs'),patch('media_mcp.server.MediaService'):
                run()
                self.assertEqual(server.run.call_args.kwargs['port'],port)
                self.assertEqual(server.run.call_args.kwargs['host'],host)

    def test_control_command_uses_local_listener_not_cloud_settings(self):
        from media_mcp.platform.api import main
        with patch.dict(os.environ,{'MEDIA_LOCAL_CONTROL_BIND':'127.0.0.2','MEDIA_LOCAL_CONTROL_PORT':'19613',
                'MEDIA_WEB_BIND_HOST':'127.0.0.1','MEDIA_WEB_PORT':'18213',
                'MEDIA_CLOUD_WEB_PORT':'29614','MEDIA_WEB_BOOTSTRAP_TOKEN':'fixture-only'},clear=True),patch('media_mcp.storage.media._client'),patch('media_mcp.platform.api.create_app'),patch('uvicorn.run') as run:
            main()
            self.assertEqual(run.call_args.kwargs['host'],'127.0.0.2')
            self.assertEqual(run.call_args.kwargs['port'],19613)

    def run_setup(self, root, settings, legacy_dir=None):
        shutil.copyfile(self.source/'setup.sh',root/'setup.sh')
        (root/'.env').write_text(settings)
        binary=root/'bin';binary.mkdir()
        docker=binary/'docker'
        docker.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$CALL_LOG"
case "$*" in
  *"--entrypoint python3"*) printf '%s' 'fixture-private-control-value-123456789';;
  *"ps --all --filter label=com.docker.compose.project=media-standalone --filter label=com.docker.compose.service=web"*)
    if [ -n "$LEGACY_DIR" ]; then printf '%s\\n' aabbccdd0011; fi;;
  *"inspect --format"*"aabbccdd0011"*) printf '%s\\n' "$LEGACY_DIR";;
esac
exit 0
''')
        docker.chmod(0o755)
        env={key:value for key,value in os.environ.items() if not key.startswith(('MEDIA_','QBITTORRENT_','JACKETT_'))}
        env.update(PATH=str(binary)+':'+os.environ['PATH'],CALL_LOG=str(root/'calls'),LEGACY_DIR=legacy_dir or '')
        result=subprocess.run(['sh',str(root/'setup.sh'),'local'],env=env,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        return result,(root/'calls').read_text()

    def test_migrate_only_same_working_directory_without_removing_volumes(self):
        for same in (True,False):
            with self.subTest(same=same),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                settings='QBITTORRENT_URL=http://127.0.0.1:19000\nMEDIA_LOCAL_DATA_DIR=./actual-media\nMEDIA_DATA_DIR=./wrong-media\nMEDIA_LOCAL_STATE_PATH=./actual-state\nMEDIA_STATE_PATH=./wrong-state\n'
                result,calls=self.run_setup(root,settings,str(root) if same else str(root.parent))
                self.assertEqual('stop aabbccdd0011' in calls,same)
                self.assertEqual('rm aabbccdd0011' in calls,same)
                self.assertNotIn('rm -v',calls)
                self.assertNotIn('down',calls)
                self.assertIn('up -d local-worker local-control',calls)
                self.assertTrue((root/'actual-media/downloads').is_dir())
                self.assertFalse((root/'wrong-media').exists())
                self.assertTrue((root/'actual-state').is_dir())
                self.assertFalse((root/'wrong-state').exists())
                self.assertEqual((root/'.env').read_text(),settings)
                self.assertNotIn('fixture-private-control-value',result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
