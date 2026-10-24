import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class StartScriptTests(unittest.TestCase):
    def test_entrypoint_initializes_private_config_and_prints_only_after_health(self):
        source=Path(__file__).resolve().parents[1]
        for healthy in (True,False):
            with self.subTest(healthy=healthy),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                for name in ('start.sh','.env.example'):shutil.copyfile(source/name,root/name)
                (root/'.env').write_text((root/'.env.example').read_text()+'\n# preserved private configuration\n')
                (root/'.env').chmod(0o644)
                binary=root/'bin';binary.mkdir()
                docker=binary/'docker'
                docker.write_text('#!/bin/sh\ncase "$*" in\n*"compose version"*) exit 0;;\n*"exec -T mcp"*) exit '+('0' if healthy else '1')+';;\n*"exec -T worker"*) exit 1;;\n*) exit 0;;\nesac\n')
                docker.chmod(0o755)
                (binary/'sleep').write_text('#!/bin/sh\nexit 0\n');(binary/'sleep').chmod(0o755)
                env={**os.environ,'PATH':str(binary)+':'+os.environ['PATH']}
                result=subprocess.run(['sh',str(root/'start.sh')],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0 if healthy else 1,result.stderr)
                self.assertEqual('MCP 已启动' in result.stdout,healthy)
                values=(root/'.env').read_text()
                self.assertIn('# preserved private configuration',values)
                self.assertNotIn('GENERATE',values)
                self.assertEqual((root/'.env').stat().st_mode & 0o777,0o600)
                self.assertIn('MEDIA_AUTH_MODE=none',values)
                self.assertNotIn('DB_CODE=',values)
                self.assertNotIn('MEDIA_OWNER_PASSWORD=',values)
