"""Offline contract tests; never contact an OpenStack or SSH endpoint."""
import json
import contextlib
import configparser
import io
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

import jinja2
import yaml

PLAYBOOK = Path(__file__).resolve().parents[1] / 'collect-mistral.yml'
EX = '92ccf1f3-e96c-4abd-b37c-57c8d8859e2f'


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PLAYBOOK.is_file(), 'Standalone Mistral playbook is not implemented')
        self.plays = yaml.safe_load(PLAYBOOK.read_text())
        source = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(
            self.plays[0]['vars']['mistral_diag_source']).render()
        self.mod = types.ModuleType('mistral_diag_test')
        exec(compile(source, str(PLAYBOOK), 'exec'), self.mod.__dict__)
        self.tmp = tempfile.TemporaryDirectory(prefix='mistral-diag-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = self.mod.validate({})

    def test_defaults_have_only_three_controllers_and_four_api_endpoints(self):
        controllers = self.plays[0]['vars']['mistral_diag_controllers']
        self.assertEqual([v['ip'] for v in controllers], ['10.101.25.150', '10.101.25.151', '10.101.25.152'])
        self.assertEqual(len(self.cfg['api_endpoints']), 4)
        self.assertTrue(all(u.endswith(':8989/v2') for u in self.cfg['api_endpoints']))
        self.assertFalse(self.plays[0]['become'])
        self.assertFalse(self.plays[-1]['become'])

    def test_config_rejects_unsafe_endpoints_and_unbounded_values(self):
        for bad in ({'api_endpoints': ['http://user:password@10.1.1.1:8989/v2']},
                    {'api_endpoints': ['file:///etc/passwd']},
                    {'api_endpoints': ['http://10.1.1.1:8989/v2?token=foo']},
                    {'execution_ids': [';shutdown']}, {'api_timeout': 1000},
                    {'max_bytes': 1000000000}, {'unexpected': 'field'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.mod.validate(bad)

    def test_safe_keystone_timeouts_survive_whitelist_config_redaction(self):
        path = self.root / 'mistral.conf'
        path.write_text('[keystone_authtoken]\nhttp_connect_timeout=10\ntoken_cache_time=300\npassword=CANARY_PASSWORD\n')
        real_read = configparser.ConfigParser.read
        def fake_read(parser, *args, **kwargs):
            return real_read(parser, str(path))
        output = io.StringIO()
        with mock.patch.object(configparser.ConfigParser, 'read', fake_read), mock.patch('signal.signal'), mock.patch('signal.alarm'), contextlib.redirect_stdout(output):
            exec(self.mod.CONFIG_PROBE, {})
        clean = self.mod.redact(output.getvalue())
        self.assertIn('http_connect_timeout', clean)
        self.assertIn('token_cache_time', clean)
        self.assertIn('300', clean)
        self.assertNotIn('CANARY_PASSWORD', clean)

    def test_structurally_malformed_reports_do_not_abort_txt(self):
        for idx, bad in enumerate(({'checks':'malformed'}, {'checks':[None]}, {'checks':[{'name':[], 'status':'ok'}]})):
            directory = self.root / str(idx)
            directory.mkdir()
            (directory / 'node.json').write_text(json.dumps({'report':bad, 'transport':{'rc':0}}))
            out = self.mod.write_report(str(directory), ['node'])
            self.assertEqual(out['status'],'PARTIAL')
            self.assertIn('COLLECTOR_ERROR', Path(out['report']).read_text())

    def test_insufficient_budget_does_not_start_in_container_process(self):
        argv_seen = []
        def run(argv,*args,**kwargs):
            argv_seen.append(argv)
            return dict(status='ok',rc=0,truncated=False,output='mistral_api\timage\tUp\nrabbitmq\timage\tUp\n' if argv[:3] == ['podman','ps','-a'] else '')
        with mock.patch.object(self.mod,'run',side_effect=run):
            self.mod.host(dict(self.cfg,command_timeout=1,log_root=str(self.root)))
        self.assertFalse(any(argv[:2] == ['podman','exec'] for argv in argv_seen))

    def test_haproxy_expired_deadline_does_not_open_socket(self):
        with mock.patch.object(self.mod.socket,'socket') as sock:
            result = self.mod.haproxy_evidence(self.cfg,config_root=self.root,deadline=time.monotonic()-1)
        sock.assert_not_called()
        self.assertEqual(result['status'],'skipped_budget')

    def test_in_container_watchdog_never_rounds_down_to_disabled(self):
        commands = []
        def run(argv, available, *args, **kwargs):
            commands.append((argv, available))
            output = 'mistral_api\timage\tUp\n' if argv[:3] == ['podman','ps','-a'] else '{}'
            return dict(status='ok',rc=0,truncated=False,output=output)
        ticks = iter([0])
        with mock.patch.object(self.mod,'run',side_effect=run), mock.patch.object(
                self.mod.time,'monotonic',side_effect=lambda: next(ticks,176.96)):
            self.mod.host(dict(self.cfg,total_timeout=180,log_root=str(self.root)))
        wrappers = [(argv, available) for argv, available in commands if argv[:2] == ['podman','exec']]
        self.assertTrue(wrappers)
        for argv, available in wrappers:
            duration = float(argv[6][:-1])
            self.assertGreater(duration,0)
            self.assertLess(duration+1,available)

    def test_redaction_keeps_request_ids_but_no_credentials(self):
        raw = ('X-Auth-Token: issued-test-secret\nAuthorization: Bearer hidden-header\n'
               'password="hidden password" amqp://name:hidden-url@host/vhost\n'
               'req-aabb remaining issued-test-secret\n')
        result = self.mod.redact(raw, ['issued-test-secret'])
        for secret in ('issued-test-secret', 'hidden-header', 'hidden password', 'hidden-url'):
            self.assertNotIn(secret, result)
        self.assertIn('req-aabb', result)
        clean = self.mod.sanitize({'input': {'password': 'hidden-input'}, 'Env': ['OS_PASSWORD=hidden']})
        self.assertNotIn('hidden', json.dumps(clean))

    def test_prefixed_opaque_payloads_and_structured_secrets_are_masked(self):
        for raw in ('2026-09-09 08:00:00 req-safe input={"api_key":"PAYLOAD_CANARY"}',
                    '2026-09-09 08:00:00 req-safe data={"password":["PAYLOAD_CANARY"]}',
                    '2026-09-09 08:00:00 req-safe input={\n "other": "PAYLOAD_CANARY"\n}',
                    '2026-09-09 08:00:00 req-safe output={not-json:\n PAYLOAD_CANARY\n}'):
            with self.subTest(raw=raw):
                result = self.mod.redact(raw)
                self.assertNotIn('PAYLOAD_CANARY', result)
                self.assertIn('req-safe', result)

    def test_successful_http_wrong_list_shape_is_not_a_collected_execution_list(self):
        def probe(cfg, endpoint, path, token):
            return dict(name='GET ' + path, endpoint=endpoint, path=path, status='ok',
                        http_status=200, data={'error': 'not a list'})
        with mock.patch.object(self.mod, 'run', return_value=dict(status='ok', rc=0, output='secret\n', truncated=False)), mock.patch.object(self.mod, 'probe', side_effect=probe):
            data = self.mod.api(self.cfg)
        rows = [r for r in data['checks'] if r.get('path','').startswith('executions?')]
        self.assertTrue(rows)
        self.assertTrue(all(r['status'] != 'ok' for r in rows))

    def test_api_payload_budget_prevents_capture_beyond_reserved_capacity(self):
        with mock.patch.object(self.mod, 'run', return_value=dict(status='ok',rc=0,output='secret\n',truncated=False)), mock.patch.object(self.mod, 'probe') as probe:
            data = self.mod.api(dict(self.cfg,max_total_bytes=1))
        probe.assert_not_called()
        self.assertTrue(any(r['status'] == 'skipped_budget' for r in data['checks']))
        self.assertEqual(data['payload_capacity_reserved_bytes'], 0)

    def test_haproxy_uses_actual_kolla_fragment_and_validated_socket_mount(self):
        root = self.root / 'haproxy'
        (root / 'services.d').mkdir(parents=True)
        (root / 'haproxy.cfg').write_text('defaults\n  timeout server 1m\n')
        (root / 'services.d' / 'mistral-api.cfg').write_text('listen mistral_api\n  bind 10.101.25.150:8989\n  server controller 10.101.25.151:8989 check\n')
        result = self.mod.haproxy_evidence(self.cfg, config_root=root, socket_paths=[])
        self.assertTrue(any('listen mistral_api' in v for v in result['config']))
        self.assertTrue(any('timeout server 1m' in v for v in result['config']))
        self.assertEqual(self.mod.haproxy_socket_paths([
            {'Source':'/var/lib/containers/storage/volumes/haproxy_socket/_data',
             'Destination':'/var/lib/kolla/haproxy'}]),
            ['/var/lib/containers/storage/volumes/haproxy_socket/_data/haproxy.sock'])

    def test_subprocess_timeout_and_output_limit_are_bounded(self):
        began = time.monotonic()
        result = self.mod.run([sys.executable, '-c', 'import time; print("ready",flush=True); time.sleep(5)'], .15, 1024)
        self.assertEqual(result['status'], 'timeout')
        self.assertLess(time.monotonic() - began, 2)
        result = self.mod.run([sys.executable, '-c', 'print("x" * 50000)'], 2, 1024)
        self.assertEqual(result['status'], 'output_limit')
        self.assertLessEqual(len(result['output']), 1024)

    def test_subprocess_closed_stdout_cannot_defeat_deadline(self):
        began = time.monotonic()
        result = self.mod.run([sys.executable, '-c', 'import os,time; os.close(1); os.close(2); time.sleep(5)'], .15, 1024)
        self.assertEqual(result['status'], 'timeout')
        self.assertLess(time.monotonic() - began, 2)

    def test_token_command_stderr_warnings_do_not_corrupt_token_stdout(self):
        row = self.mod.run([sys.executable, '-c', 'import sys; print("TOKEN"); print("deprecation warning",file=sys.stderr)'],
                           2, 1024, discard_stderr=True)
        self.assertEqual(row['output'].strip(), 'TOKEN')

    def test_real_curl_against_loopback_http_only(self):
        if os.environ.get('MISTRAL_DIAG_REAL_HTTP') != '1':
            self.skipTest('Explicit loopback-only HTTP integration run')
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append(self.headers.get('X-Auth-Token'))
                if 'slow' in self.path:
                    time.sleep(2)
                self.send_response(200)
                self.send_header('X-Openstack-Request-Id','req-real-curl')
                self.end_headers()
                try:
                    self.wfile.write(b'{"executions":[]}')
                except BrokenPipeError:
                    pass
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker = threading.Thread(target=server.serve_forever,daemon=True)
        worker.start()
        try:
            endpoint = 'http://127.0.0.1:%d/v2' % server.server_port
            good = self.mod.probe(self.cfg,endpoint,'executions?limit=1','LOCAL_HTTP_CANARY')
            self.assertEqual(good['status'],'ok')
            self.assertEqual(good['request_id'],'req-real-curl')
            slow = self.mod.probe(dict(self.cfg,api_timeout=1),endpoint,'executions?slow=1','LOCAL_HTTP_CANARY')
            self.assertEqual(slow['status'],'timeout')
            self.assertLess(slow['duration_seconds'],2)
            self.assertEqual(received, ['LOCAL_HTTP_CANARY','LOCAL_HTTP_CANARY'])
            self.assertNotIn('LOCAL_HTTP_CANARY',json.dumps([good,slow]))
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def http_result(self, code=200, body=None):
        body = {'executions': []} if body is None else body
        return dict(status='ok', rc=0, truncated=False, duration_seconds=.1,
                    output='HTTP/1.1 %d OK\r\nX-Openstack-Request-Id: req-test\r\nDate: today\r\n\r\n%s\nMISTRAL_DIAG_METRICS %d 0.001 0.010 0.100\n' % (code, json.dumps(body), code))

    def test_http_token_only_in_stdin_no_redirect_or_proxy(self):
        with mock.patch.object(self.mod, 'run', return_value=self.http_result()) as run:
            row = self.mod.probe(self.cfg, self.cfg['api_endpoints'][0], 'executions?limit=1', 'issued-test-secret')
        argv = run.call_args.args[0]
        self.assertNotIn('issued-test-secret', str(argv))
        self.assertIn('issued-test-secret', run.call_args.kwargs['stdin'])
        self.assertNotIn('-L', argv)
        self.assertNotIn('--location', argv)
        self.assertIn('--noproxy', argv)
        self.assertNotIn('issued-test-secret', json.dumps(row))
        self.assertEqual(row['request_id'], 'req-test')
        self.assertEqual(row['http_status'], 200)
        self.assertEqual(row['total_seconds'], .1)

    def test_http_errors_and_timeouts_are_not_success(self):
        with mock.patch.object(self.mod, 'run', return_value=self.http_result(504)):
            row = self.mod.probe(self.cfg, self.cfg['api_endpoints'][0], 'workflows?limit=1', 'secret')
        self.assertEqual(row['status'], 'http_error')
        with mock.patch.object(self.mod, 'run', return_value=dict(status='timeout', rc=-9, output='', truncated=False)):
            row = self.mod.probe(self.cfg, self.cfg['api_endpoints'][0], 'workflows?limit=1', 'secret')
        self.assertEqual(row['status'], 'timeout')
        self.assertIsNone(row['http_status'])

    def test_missing_auth_is_recorded_without_hiding_other_evidence(self):
        with mock.patch.object(self.mod, 'run', return_value=dict(status='error', rc=1, output='OS_PASSWORD=hidden', truncated=False)):
            data = self.mod.api(self.cfg)
        self.assertTrue(any(c['name'] == 'authentication' and c['status'] != 'ok' for c in data['checks']))
        self.assertNotIn('hidden', json.dumps(data))
        self.assertEqual(data['selected_execution_ids'], [])

    def test_previous_ids_retained_even_when_latest_list_no_longer_contains_them(self):
        previous = self.root / 'api_before.json'
        previous.write_text(json.dumps({'report': {'selected_execution_ids': [EX]}}))
        paths = []
        def probe(cfg, endpoint, path, token):
            paths.append(path)
            return dict(name='GET ' + path, endpoint=endpoint, path=path, status='ok',
                        http_status=200, data={'executions': [], 'tasks': []})
        with mock.patch.object(self.mod, 'run', return_value=dict(status='ok', rc=0, output='issued-test-secret\n', truncated=False)), mock.patch.object(self.mod, 'probe', side_effect=probe):
            data = self.mod.api(self.cfg, str(previous))
        self.assertIn(EX, data['selected_execution_ids'])
        self.assertTrue(any(p.startswith('executions/' + EX) for p in paths))
        self.assertNotIn('issued-test-secret', json.dumps(data))
        self.assertTrue(all('fields=' in p for p in paths if p.startswith(('executions/', 'tasks?'))))

    def test_api_payload_projection_discards_arbitrary_execution_data(self):
        body = {'id': EX, 'state': 'RUNNING', 'result': 'PAYLOAD_CANARY',
                'published_global': {'api_key': 'PAYLOAD_CANARY'}, 'runtime_context': 'PAYLOAD_CANARY'}
        with mock.patch.object(self.mod, 'run', return_value=self.http_result(body=body)):
            row = self.mod.probe(self.cfg, self.cfg['api_endpoints'][0], 'executions/' + EX, 'secret')
        self.assertNotIn('PAYLOAD_CANARY', json.dumps(row))
        self.assertEqual(row['data']['state'], 'RUNNING')

    def test_empty_and_invalid_stdout_preserve_transport_diagnostics(self):
        for value in ('', 'unparseable diagnostic stdout'):
            with self.subTest(value=value):
                directory = self.root / ('run' + str(len(value)))
                directory.mkdir()
                (directory / 'ultra1-6.json').write_text(json.dumps({'report':value,
                    'transport':{'rc':255,'unreachable':True,'msg':'SSH host key verification failed'}}))
                result = self.mod.write_report(str(directory), ['ultra1-6'])
                text = Path(result['report']).read_text()
                self.assertIn('UNREACHABLE', text)
                self.assertIn('SSH host key verification failed', text)

    def test_host_collection_never_mutates_services(self):
        commands = []
        def run(argv, *args, **kwargs):
            commands.append(argv)
            if argv[:3] == ['podman', 'ps', '-a']:
                output = 'mistral_api\timage\tUp\nmistral_engine\timage\tUp\nrabbitmq\timage\tUp\nhaproxy\timage\tUp\n'
            else:
                output = '{}'
            return dict(status='ok', rc=0, output=output, truncated=False)
        with mock.patch.object(self.mod, 'run', side_effect=run):
            self.mod.host(dict(self.cfg, log_root=str(self.root)))
        for argv in commands:
            self.assertFalse(set(argv) & {'restart', 'reconfigure', 'purge_queue', 'stop', 'start', 'kill', 'delete', 'update', 'evacuate', 'resume'})
            self.assertNotIn('--debug', argv)
            self.assertNotIn('inspect .', ' '.join(argv))
        self.assertTrue(any('rabbitmqctl' in v for v in commands))
        self.assertTrue(any('database_probe' in ' '.join(v) for v in commands))
        for argv in commands:
            if argv[:2] == ['podman', 'exec']:
                self.assertIn('timeout', argv)

    def test_report_survives_missing_corrupt_and_unreachable_sections(self):
        (self.root / 'api_before.json').write_text(json.dumps({'report': {'checks': [], 'selected_execution_ids': []}}))
        (self.root / 'api_after.json').write_text('broken-json')
        (self.root / 'ultra1-6.json').write_text(json.dumps({'transport': {'unreachable': True, 'msg': 'password=hidden'}, 'report': {}}))
        result = self.mod.write_report(str(self.root), ['ultra1-6', 'ultra1-7'])
        target = Path(result['report'])
        text = target.read_text()
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertIn('UNREACHABLE', text)
        self.assertIn('MISSING', text)
        self.assertIn('INVALID', text)
        self.assertNotIn('hidden', text)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            self.mod.write_report(str(self.root), ['ultra1-6'])

    def test_log_tail_is_bounded_and_redacted(self):
        log = self.root / 'api.log'
        log.write_text('2026-09-09 08:00:00 ERROR password=hidden req-test\n' * 50)
        row = self.mod.read_log(log, dict(self.cfg, max_log_bytes=1024,
            since='2026-09-09T07:00:00Z', until='2026-09-09T09:00:00Z'))
        self.assertNotIn('hidden', row['output'])
        self.assertTrue(row['truncated'])
        self.assertLessEqual(len(row['output'].encode()), 1024)


if __name__ == '__main__':
    unittest.main()
