import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class SetupScriptTests(unittest.TestCase):
    def test_worker_must_be_healthy_and_is_polled_every_five_seconds(self):
        source=Path(__file__).resolve().parents[1]
        for ready_after in (3,0):
            with self.subTest(ready_after=ready_after),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                shutil.copyfile(source/'setup.sh',root/'setup.sh')
                (root/'.env').write_text('QBITTORRENT_URL=http://192.0.2.10:8080\n')
                binary=root/'bin';binary.mkdir()
                docker=binary/'docker'
                docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\ncase "$*" in\n'
                    '*"--entrypoint python3"*) printf "%s\\n" "synthetic-control-token-12345678901234567890";;\n'
                    '*"exec -T worker python3 -m media_mcp.monitor.health"*)\n'
                    ' count=0; if [ -f "$COUNT_FILE" ]; then count=$(cat "$COUNT_FILE"); fi\n'
                    ' count=$((count+1)); printf "%s" "$count" > "$COUNT_FILE"\n'
                    ' if [ "$READY_AFTER" -gt 0 ] && [ "$count" -ge "$READY_AFTER" ]; then exit 0; fi; exit 1;;\n'
                    'esac\nexit 0\n')
                docker.chmod(0o755)
                (binary/'sleep').write_text('#!/bin/sh\nprintf "sleep %s\\n" "$*" >> "$CALL_LOG"\nexit 0\n')
                (binary/'sleep').chmod(0o755)
                environment={key:value for key,value in os.environ.items()
                             if not key.startswith(('MEDIA_','QBITTORRENT_','JACKETT_'))}
                environment.update(PATH=str(binary)+':'+os.environ['PATH'],CALL_LOG=str(root/'calls'),
                                   COUNT_FILE=str(root/'count'),READY_AFTER=str(ready_after))
                result=subprocess.run(['sh',str(root/'setup.sh'),'local'],env=environment,capture_output=True,text=True)
                self.assertEqual(result.returncode,0 if ready_after else 1,result.stderr)
                self.assertEqual(int((root/'count').read_text()),ready_after or 60)
                self.assertIn('sleep 5',(root/'calls').read_text())
                self.assertIn('media_mcp.monitor.dependencies',(root/'calls').read_text())
                self.assertEqual('检查全部通过' in result.stdout,bool(ready_after))

    def test_restarting_control_api_polls_every_five_seconds_then_fails(self):
        source=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            shutil.copyfile(source/'setup.sh',root/'setup.sh')
            (root/'.env').write_text('MEDIA_LOCAL_CONTROL_PORT=19613\nQBITTORRENT_URL=http://192.0.2.10:8080\n')
            binary=root/'bin';binary.mkdir()
            docker=binary/'docker'
            docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\ncase "$*" in\n'
                '*"--entrypoint python3"*) printf "%s\\n" "synthetic-control-token-12345678901234567890";;\n'
                '*"exec -T web"*) exit 1;;\n'
                '*"ps --all --quiet web"*) printf "%s\\n" "fixture-container";;\n'
                '*"inspect --format"*) printf "%s\\n" "restarting:3";;\nesac\nexit 0\n')
            docker.chmod(0o755)
            (binary/'sleep').write_text('#!/bin/sh\nprintf "sleep %s\\n" "$*" >> "$CALL_LOG"\nexit 0\n')
            (binary/'sleep').chmod(0o755)
            environment={key:value for key,value in os.environ.items()
                         if not key.startswith(('MEDIA_','QBITTORRENT_','JACKETT_'))}
            environment.update(PATH=str(binary)+':'+os.environ['PATH'],CALL_LOG=str(root/'calls'))
            result=subprocess.run(['sh',str(root/'setup.sh'),'local'],env=environment,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('restarting:3',result.stderr)
            self.assertIn('19613',result.stderr)
            self.assertIn('sh setup.sh local logs',result.stderr)
            self.assertEqual((root/'calls').read_text().count('exec -T web'),60)
            self.assertIn('sleep 5',(root/'calls').read_text())
            self.assertNotIn('synthetic-control-token',result.stdout+result.stderr)

    def test_cloud_port_only_proxy_setup_automatically_pairs_without_printing_secret(self):
        source=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            shutil.copyfile(source/'setup.sh',root/'setup.sh')
            (root/'.env').write_text('MEDIA_WEB_PORT=19514\nMEDIA_WEB_BIND_HOST=127.0.0.1\nMEDIA_CONTROL_PORT=29213\nJACKETT_URL=http://127.0.0.1:19117\n')
            binary=root/'bin';binary.mkdir()
            docker=binary/'docker'
            docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\n'
                'printf "mode=%s bind=%s control_port=%s\\n" "$MEDIA_WEB_MODE" "$MEDIA_WEB_BIND_HOST" "$MEDIA_CONTROL_PORT" >> "$CALL_LOG"\n'
                'case "$*" in *"-m media_mcp.platform.pairing"*) mkdir -p state; printf "%s" "synthetic-private-pairing-value-123456789" > state/control-token;; esac\nexit 0\n')
            docker.chmod(0o755)
            env={k:v for k,v in os.environ.items() if not k.startswith('MEDIA_')}
            env.update(PATH=str(binary)+':'+os.environ['PATH'],CALL_LOG=str(root/'calls'))
            result=subprocess.run(['sh',str(root/'setup.sh'),'cloud'],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            recorded=(root/'calls').read_text()
            self.assertIn('-m media_mcp.platform.pairing',recorded)
            self.assertIn('mode=proxy bind=0.0.0.0',recorded)
            self.assertIn('control_port=29213',recorded)
            self.assertIn('19514/healthz',recorded)
            self.assertNotIn('synthetic-private',result.stdout+result.stderr)
            self.assertEqual((root/'state/control-token').stat().st_mode&0o777,0o600)
            self.assertNotIn('MEDIA_WEB_PUBLIC_URL',(root/'.env').read_text())
            (root/'calls').write_text('')
            result=subprocess.run(['sh',str(root/'setup.sh'),'cloud'],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertNotIn('-m media_mcp.platform.pairing',(root/'calls').read_text())

    def test_dependency_selection_is_independent_for_each_url(self):
        source = Path(__file__).resolve().parents[1]
        cases = (
            ('', ('qbittorrent', 'jackett')),
            ('QBITTORRENT_URL=\nJACKETT_URL=\n', ('qbittorrent', 'jackett')),
            ('QBITTORRENT_URL=http://192.0.2.10:8080\n', ('jackett',)),
            ('JACKETT_URL=http://192.0.2.11:9117\n', ('qbittorrent',)),
            ('QBITTORRENT_URL=http://192.0.2.10:8080\nJACKETT_URL=http://192.0.2.11:9117\n', ()),
        )
        for configuration, managed in cases:
            with self.subTest(managed=managed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                shutil.copyfile(source/'setup.sh', root/'setup.sh')
                (root/'.env').write_text(configuration)
                binary = root/'bin'
                binary.mkdir()
                docker = binary/'docker'
                docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\n'
                    'case "$*" in *"--entrypoint python3"*) printf "%s\\n" "test-generated-control-token-32-characters";; esac\nexit 0\n')
                docker.chmod(0o755)
                calls = root/'calls'
                env = {k:v for k,v in os.environ.items() if k not in ('QBITTORRENT_URL', 'JACKETT_URL')}
                env.update(PATH=str(binary)+':'+os.environ['PATH'], CALL_LOG=str(calls))
                for command in ('up', 'logs', 'stop'):
                    result = subprocess.run(['sh', str(root/'setup.sh'), command], cwd=root,
                                            env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                recorded = calls.read_text()
                self.assertIn('up -d mcp worker', recorded)
                for dependency in ('qbittorrent', 'jackett'):
                    if dependency in managed:
                        self.assertIn('run --rm --no-deps init-'+dependency, recorded)
                        self.assertIn('up -d '+dependency, recorded)
                        self.assertTrue(any('stop worker mcp' in line and dependency in line
                                            for line in recorded.splitlines()))
                    else:
                        self.assertNotIn(dependency, recorded)
                # Host URL overrides must agree with Compose, even when .env is empty.
                calls.unlink()
                (root/'.env').write_text('')
                env.update(QBITTORRENT_URL='http://192.0.2.10:8080', JACKETT_URL='http://192.0.2.11:9117')
                result = subprocess.run(['sh', str(root/'setup.sh')], cwd=root,
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('init-', calls.read_text())

    def test_entrypoint_initializes_private_config_and_prints_only_after_health(self):
        source=Path(__file__).resolve().parents[1]
        for healthy in (True,False):
            with self.subTest(healthy=healthy),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                for name in ('setup.sh','.env.example'):shutil.copyfile(source/name,root/name)
                (root/'.env').write_text((root/'.env.example').read_text()+'\nCODEX_TOKEN_FILE=./state/codex-token\n# preserved private configuration\n')
                (root/'.env').chmod(0o644)
                binary=root/'bin';binary.mkdir()
                docker=binary/'docker'
                docker.write_text('#!/bin/sh\ncase "$*" in\n*"--entrypoint python3"*) printf "%s\\n" "test-generated-control-token-32-characters"; exit 0;;\n*"compose version"*) exit 0;;\n*"exec -T mcp"*) exit '+('0' if healthy else '1')+';;\n*"exec -T worker"*) exit 0;;\n*) exit 0;;\nesac\n')
                docker.chmod(0o755)
                (binary/'sleep').write_text('#!/bin/sh\nexit 0\n');(binary/'sleep').chmod(0o755)
                env={**os.environ,'PATH':str(binary)+':'+os.environ['PATH']}
                result=subprocess.run(['sh',str(root/'setup.sh')],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0 if healthy else 1,result.stderr)
                self.assertEqual('MCP 已启动' in result.stdout,healthy)
                values=(root/'.env').read_text()
                self.assertIn('# preserved private configuration',values)
                self.assertNotIn('GENERATE',values)
                self.assertEqual((root/'.env').stat().st_mode & 0o777,0o600)
                self.assertIn('MEDIA_AUTH_MODE=none',values)
                self.assertNotIn('DB_CODE=',values)
                self.assertNotIn('MEDIA_OWNER_PASSWORD=',values)

    def test_local_and_cloud_groups_run_together_without_cloud_address(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(source/'setup.sh', root/'setup.sh')
            (root/'.env').write_text('QBITTORRENT_URL=http://192.0.2.10:8080\nMEDIA_LOCAL_CONTROL_BIND=192.168.8.1\nMEDIA_LOCAL_CONTROL_PORT=19613\nMEDIA_GATEWAY_PORT=19614\n')
            binary = root/'bin'
            binary.mkdir()
            docker = binary/'docker'
            docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\n'
                'case "$*" in *"--entrypoint python3"*) printf "%s\\n" "test-generated-control-token-32-characters";; esac\nexit 0\n')
            docker.chmod(0o755)
            calls = root/'calls'
            env = {k:v for k,v in os.environ.items() if k not in (
                'QBITTORRENT_URL','JACKETT_URL','MEDIA_CATALOG_URL','MEDIA_CONTROL_URL','MEDIA_WEB_PUBLIC')}
            env.update(PATH=str(binary)+':'+os.environ['PATH'], CALL_LOG=str(calls))
            result = subprocess.run(['sh',str(root/'setup.sh'),'local'],cwd=root,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            local = calls.read_text()
            self.assertIn('up -d worker web',local)
            self.assertIn('compose.local.yml',local)
            self.assertIn('19613/healthz',local)
            self.assertIn('192.168.8.1:19613/healthz',local)
            self.assertNotIn('up -d mcp',local)
            self.assertNotIn('init-jackett',local)
            calls.unlink()
            result = subprocess.run(['sh',str(root/'setup.sh'),'cloud'],cwd=root,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            cloud = calls.read_text()
            self.assertIn('compose.cloud.yml',cloud)
            self.assertIn('19614/healthz',cloud)
            self.assertIn('up -d mcp web',cloud)
            self.assertIn('init-jackett',cloud)
            self.assertNotIn('worker',cloud)
            self.assertNotIn('qbittorrent',cloud)

    def test_unsafe_explicit_deployment_profiles_fail_before_starting(self):
        source=Path(__file__).resolve().parents[1]
        cases=(('cloud','MEDIA_WEB_PUBLIC=true\nMEDIA_WEB_PUBLIC_URL=http://media.test\n','HTTPS'),
               ('cloud','MEDIA_WEB_PUBLIC=true\nMEDIA_WEB_PUBLIC_URL=https://media.test\nMEDIA_ADMIN_BIND=0.0.0.0\n','MEDIA_ADMIN_BIND'),
               ('standalone','MEDIA_MULTI_USER=true\nMEDIA_AUTH_MODE=none\n','MEDIA_AUTH_MODE=platform'))
        for topology,configuration,_ in cases:
            with self.subTest(topology=topology,configuration=configuration),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                shutil.copyfile(source/'setup.sh',root/'setup.sh')
                (root/'.env').write_text(configuration)
                binary=root/'bin'; binary.mkdir()
                docker=binary/'docker'
                docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\nexit 0\n')
                docker.chmod(0o755)
                calls=root/'calls'
                env={k:v for k,v in os.environ.items() if not k.startswith('MEDIA_')}
                env.update(PATH=str(binary)+':'+os.environ['PATH'],CALL_LOG=str(calls))
                args=['sh',str(root/'setup.sh')]+([] if topology=='standalone' else [topology])
                result=subprocess.run(args,env=env,capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0,result.stdout)
                self.assertNotIn('up -d',calls.read_text())

    def test_empty_generated_token_never_starts_services(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(source/'setup.sh',root/'setup.sh')
            (root/'.env').write_text('QBITTORRENT_URL=http://192.0.2.10:8080\nJACKETT_URL=http://192.0.2.11:9117\n')
            binary = root/'bin'
            binary.mkdir()
            docker = binary/'docker'
            docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\nexit 0\n')
            docker.chmod(0o755)
            calls = root/'calls'
            env = {**os.environ,'PATH':str(binary)+':'+os.environ['PATH'],'CALL_LOG':str(calls)}
            result = subprocess.run(['sh',str(root/'setup.sh')],cwd=root,env=env,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertNotIn('up -d',calls.read_text())
            self.assertFalse((root/'state/control-token').exists())
