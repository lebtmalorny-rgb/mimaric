"""Incident discovery tests; only the external command boundary is replaced."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / 'files' / 'collect.py'
H2 = 'ultra1-2.ultra1.test.pvs.un.sbt'
H3 = 'ultra1-3.ultra1.test.pvs.un.sbt'
HOST2 = 'e25179b1-32bf-4239-a323-81d285eee109'
HOST3 = '7743e04d-ed10-4f2b-b61b-8598d6c0362e'
SEGMENT = 'b045da78-bc53-435a-937e-f12d41a217b1'
NEW = '11111111-1111-4111-8111-111111111111'
OLD = 'a1e7d8e9-cb63-4c7f-9dd1-52e0a0cea0af'
VM = '85387b2a-32fe-48b2-be94-df20701d2659'
MOVE = 'de084e2d-2324-48a5-8fde-31a2b7aa1bab'
WORKFLOW = '22222222-2222-4222-8222-222222222222'
TASK = '33333333-3333-4333-8333-333333333333'


class IncidentTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('incident_collector', SCRIPT)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.cfg = self.mod.validate_config(dict(
            since='2026-09-08T10:00:00Z', until='2026-09-08T12:00:00Z',
            segment_id=SEGMENT, compute_hosts=[H2, H3]))
        self.calls = []
        self.old_only = False
        self.empty_hosts = False

    def cli(self, argv, *args):
        self.calls.append(argv)
        a = argv[1:]
        result = []
        if a == ['--version']:
            return dict(status='ok', rc=0, output='openstack 7.5.0\n', truncated=False)
        if a[:2] == ['segment', 'list']:
            result = [dict(uuid=SEGMENT, name='HA-Segment-01')]
        elif a[:3] == ['segment', 'host', 'list']:
            result = [dict(uuid=HOST2, name=H2, on_maintenance=False),
                      dict(uuid=HOST3, name=H3, on_maintenance=True)]
        elif a[:2] == ['notification', 'list']:
            self.assertIn('--filters', a, 'Discovery must use the requested host UUID')
            selected = a[a.index('--filters') + 1]
            self.assertIn(selected, ['source_host_uuid=' + HOST2, 'source_host_uuid=' + HOST3])
            if selected.endswith(HOST3):
                result = [dict(notification_uuid=OLD, source_host_uuid=HOST3,
                               generated_time='2026-09-07T12:32:58.000000')]
                if not self.old_only:
                    result.insert(0, dict(notification_uuid=NEW, source_host_uuid=HOST3,
                                          generated_time='2026-09-08T11:05:00.000000'))
        elif a[:2] == ['notification', 'show']:
            result = dict(notification_uuid=a[2], source_host_uuid=HOST3,
                          generated_time=('2026-09-07T12:32:58.000000' if a[2] == OLD
                                          else '2026-09-08T11:05:00.000000'), status='failed')
        elif a[:3] == ['notification', 'vmove', 'list']:
            result = [dict(uuid=MOVE, instance_uuid=VM)]
        elif a[:3] == ['notification', 'vmove', 'show']:
            result = dict(uuid=MOVE, instance_uuid=VM, status='failed', message='fence timeout')
        elif a[:2] == ['server', 'list']:
            result = [] if self.empty_hosts else [dict(ID=VM, Name='vm-on-ultra1-2', Status='ACTIVE')]
        elif a[:2] == ['server', 'show']:
            result = {'id': VM, 'status': 'ACTIVE', 'OS-EXT-SRV-ATTR:host': H2,
                      'OS-EXT-STS:task_state': None}
        elif a[:3] == ['baremetal', 'node', 'show']:
            result = dict(name=a[3], power_state='power on', target_power_state=None,
                          last_error='** Value Redacted - Requires baremetal:node:get:last_error permission. **')
        elif a[:3] == ['compute', 'service', 'list']:
            result = [{'Host': a[a.index('--host') + 1], 'Status': 'disabled', 'State': 'up'}]
        elif a[:2] == ['segment', 'show']:
            result = dict(uuid=SEGMENT, is_enabled=True)
        elif a[:3] == ['workflow', 'execution', 'list']:
            result = [{'ID': WORKFLOW, 'Workflow name': 'power_ops.planned_power_off',
                       'Created at': '2026-09-08 11:03:00', 'State': 'ERROR'}]
        elif a[:4] == ['workflow', 'execution', 'input', 'show']:
            result = dict(host=H3, instance_policy='require_empty')
        elif a[:4] == ['workflow', 'execution', 'output', 'show']:
            result = dict(result='planned power off failed')
        elif a[:3] == ['workflow', 'execution', 'show']:
            result = {'ID': WORKFLOW, 'State': 'ERROR', 'State info': 'Failure caused by error in tasks: power_off'}
        elif a[:3] == ['task', 'execution', 'list']:
            result = [{'ID': TASK, 'State': 'ERROR', 'Name': 'power_off'}]
        elif a[:3] == ['task', 'execution', 'show']:
            result = {'ID': TASK, 'State': 'ERROR', 'State info': 'instance entered an unsafe migration state'}
        elif a[:4] == ['task', 'execution', 'result', 'show']:
            result = dict(error='example request failure')
        return dict(status='ok', rc=0, output=json.dumps(result), truncated=False)

    def collect(self, cfg=None, **kwargs):
        with mock.patch.object(self.mod, 'run_command', self.cli):
            return self.mod.Collector(cfg or self.cfg).api(**kwargs)

    def test_discovers_both_hosts_recent_notifications_and_vm_history_without_old_ids(self):
        report = self.collect()
        requested = [c[3] for c in self.calls if c[1:3] == ['notification', 'show']]
        self.assertEqual(requested, [NEW])
        self.assertEqual([c[4] for c in self.calls if c[1:4] == ['baremetal', 'node', 'show']], [H2, H3])
        self.assertEqual(report['discovered_server_ids'], [VM])
        self.assertTrue(any(c[1:3] == ['server', 'show'] and c[3] == VM for c in self.calls))
        self.assertTrue(any(c[1:4] == ['server', 'event', 'list'] for c in self.calls))
        self.assertTrue(any(c[1:4] == ['server', 'migration', 'list'] for c in self.calls))
        self.assertTrue(any('fence timeout' in r['output'] for r in report['checks']))
        self.assertTrue(any('maintenance' in o.lower() and H3 in o for o in report['observations']))
        for c in self.calls:
            self.assertFalse(set(c) & {'create', 'set', 'update', 'delete', 'evacuate', 'token', '--debug'})

    def test_explicit_old_notification_warns_but_does_not_replace_current_discovery(self):
        report = self.collect(dict(self.cfg, notification_id=OLD))
        self.assertTrue(any('outside' in o and OLD in o for o in report['observations']))
        self.assertEqual({c[3] for c in self.calls if c[1:3] == ['notification', 'show']}, {OLD, NEW})

    def test_segment_and_workflow_discovery_require_no_incident_uuid(self):
        report = self.collect(dict(self.cfg, segment_id=''))
        self.assertEqual(report['selected_notification_ids'], [NEW])
        self.assertEqual(report['selected_workflow_ids'], [WORKFLOW])
        self.assertTrue(any('unsafe migration state' in r['output'] for r in report['checks']))

    def test_empty_host_without_notifications_is_not_a_server_discovery_failure(self):
        self.empty_hosts = True
        self.old_only = True
        report = self.collect()
        self.assertEqual(report['discovered_server_ids'], [])
        self.assertFalse(any(r['name'].startswith(('server_', 'events_', 'migrations_')) for r in report['checks']))

    def test_empty_current_host_lists_do_not_lose_vm_from_vmove(self):
        self.empty_hosts = True
        report = self.collect()
        self.assertEqual(report['discovered_server_ids'], [VM])

    def test_final_snapshot_tracks_previous_vm_after_it_left_both_hosts(self):
        self.empty_hosts = True
        self.old_only = True
        with tempfile.TemporaryDirectory() as directory:
            previous = Path(directory) / 'api.json'
            previous.write_text(json.dumps({'report': json.dumps({'discovered_server_ids': [VM]})}))
            report = self.collect(previous=previous)
        self.assertEqual(report['discovered_server_ids'], [VM])
        self.assertTrue(any(c[1:3] == ['server', 'show'] and c[3] == VM for c in self.calls))

    def test_redacted_api_field_is_reported_as_incomplete_not_empty_error(self):
        report = self.collect()
        nodes = [r for r in report['checks'] if r['name'].startswith('ironic_node_')]
        self.assertEqual(len(nodes), 2)
        self.assertTrue(all(r['status'] == 'restricted_fields' for r in nodes))
        self.assertTrue(all(r['error_kind'] == 'permission' for r in nodes))

    def test_missing_auth_stops_repeated_api_attempts_and_preserves_reason(self):
        calls = []
        def missing_auth(argv, *args):
            calls.append(argv)
            if argv[1:] == ['--version']:
                return dict(status='ok', rc=0, output='openstack 7.5.0', truncated=False)
            return dict(status='error', rc=1, output='Missing value auth-url required for auth plugin password', truncated=False)
        with mock.patch.object(self.mod, 'run_command', missing_auth):
            report = self.mod.Collector(self.cfg).api()
        self.assertEqual(len(calls), 2)
        self.assertEqual(report['checks'][-1]['error_kind'], 'auth_config')
        self.assertTrue(any('skipped' in o for o in report['observations']))

    def test_commands_record_timestamps_even_on_failure(self):
        with mock.patch.object(self.mod, 'run_command', return_value=dict(status='timeout', rc=-9, output='', truncated=False)):
            result = self.mod.Collector(self.cfg).command('probe', ['openstack', '--version'])
        self.assertLessEqual(self.mod.parse_time(result['started_at']), self.mod.parse_time(result['ended_at']))
        self.assertEqual(result['error_kind'], 'timeout')

    def test_host_includes_runtime_death_and_kernel_evidence_without_full_inspect(self):
        calls = []
        def host_command(argv, *args):
            calls.append(argv)
            output = 'masakari_hostmonitor\timage\tExited\n' if argv[:2] == ['podman', 'ps'] else ''
            return dict(status='ok', rc=0, output=output, truncated=False)
        with tempfile.TemporaryDirectory() as root, mock.patch.object(self.mod, 'run_command', host_command):
            self.mod.Collector(dict(self.cfg, log_root=root)).host()
        inspect = next(c for c in calls if c[:2] == ['podman', 'inspect'])
        for field in ('.State.Pid', '.State.Error', '.State.OOMKilled', '.State.FinishedAt'):
            self.assertIn(field, inspect[3])
        self.assertNotIn('.Config', inspect[3])
        self.assertTrue(any(c[0] == 'journalctl' and '-k' in c for c in calls))
        self.assertTrue(any(c[0] == 'journalctl' and 'podman.service' in c for c in calls))

    def test_required_final_snapshot_missing_is_not_collected(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / 'run'
            run.mkdir()
            (run / 'api.json').write_text(json.dumps({'transport': {'rc': 0}, 'report': {'checks': [], 'logs': []}}))
            result = self.mod.write_report(run, [], require_final_api=True)
            self.assertEqual(result['status'], 'PARTIAL')
            self.assertIn('api_after: MISSING', Path(result['report']).read_text())

    def test_default_window_is_relative_and_large_discovery_limits_are_rejected(self):
        before = dt.datetime.now(dt.timezone.utc)
        cfg = self.mod.validate_config({})
        self.assertLess(abs((self.mod.parse_time(cfg['until']) - before).total_seconds()), 2)
        self.assertEqual((self.mod.parse_time(cfg['until']) - self.mod.parse_time(cfg['since'])).total_seconds(), 3600)
        for bad in ({'max_notifications': 0}, {'max_servers': 101}):
            with self.assertRaises(ValueError):
                self.mod.validate_config(bad)

    def test_invalid_notification_uuid_remains_partial_without_being_executed(self):
        def invalid(argv, *args):
            result = self.cli(argv, *args)
            if argv[1:3] == ['notification', 'list']:
                result['output'] = json.dumps([{'notification_uuid': '--debug'}])
            return result
        with mock.patch.object(self.mod, 'run_command', invalid):
            report = self.mod.Collector(self.cfg).api()
        self.assertFalse(any(c[1:3] == ['notification', 'show'] for c in self.calls))
        self.assertTrue(any(r['status'] == 'parse_error' for r in report['checks']))

    def test_missing_workflow_plugin_preserves_other_service_evidence(self):
        def missing(argv, *args):
            result = self.cli(argv, *args)
            if argv[1:4] == ['workflow', 'execution', 'list']:
                result.update(status='error', rc=1, output="openstack: 'workflow execution list' is not an openstack command.")
            return result
        with mock.patch.object(self.mod, 'run_command', missing):
            report = self.mod.Collector(self.cfg).api()
        self.assertEqual(report['discovered_server_ids'], [VM])
        self.assertEqual(report['selected_notification_ids'], [NEW])
        failure = next(r for r in report['checks'] if r['name'] == 'workflows')
        self.assertEqual(failure['error_kind'], 'missing_plugin')

    def test_masakari_401_does_not_skip_independent_services(self):
        def unavailable(argv, *args):
            result = self.cli(argv, *args)
            if argv[1:3] == ['segment', 'list']:
                result.update(status='error', rc=1, output='Unauthorized (HTTP 401)')
            return result
        with mock.patch.object(self.mod, 'run_command', unavailable):
            report = self.mod.Collector(dict(self.cfg, segment_id='')).api()
        self.assertTrue(any(r['name'].startswith('ironic_node_') for r in report['checks']))
        self.assertEqual(report['selected_workflow_ids'], [WORKFLOW])

    def test_vm_migrated_before_first_snapshot_is_discovered_from_nova_history(self):
        self.empty_hosts = True
        self.old_only = True
        def history(argv, *args):
            result = self.cli(argv, *args)
            if '--host' in argv and 'migration' in argv:
                self.assertIn('--limit', argv)
                self.assertIn('--changes-since', argv)
                self.assertIn('--changes-before', argv)
                self.assertEqual(argv[argv.index('--os-compute-api-version') + 1], '2.66')
                result['output'] = json.dumps([{'Server UUID': VM, 'Source Compute': H3,
                                                'Dest Compute': 'outside.example', 'Status': 'completed'}])
            return result
        with mock.patch.object(self.mod, 'run_command', history):
            report = self.mod.Collector(self.cfg).api()
        self.assertEqual(report['discovered_server_ids'], [VM])
        self.assertTrue(any(c[1:4] == ['server', 'event', 'list'] for c in self.calls))

    def test_invalid_previous_snapshot_does_not_stop_current_api_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = Path(directory) / 'api.json'
            previous.write_text('{')
            report = self.collect(previous=previous)
        self.assertEqual(report['discovered_server_ids'], [VM])
        self.assertTrue(any(r['name'] == 'previous_snapshot' and r['status'] == 'parse_error'
                            for r in report['checks']))

    def test_limits_and_budget_exhaustion_are_visible(self):
        report = self.collect(dict(self.cfg, max_notifications=1))
        self.assertTrue(any(r.get('item_limit') == 1 and r.get('truncated') for r in report['checks']))
        runner = self.mod.Collector(self.cfg)
        runner.deadline = 0
        with mock.patch.object(self.mod, 'run_command') as command:
            report = runner.api()
        command.assert_not_called()
        self.assertTrue(any(r['status'] == 'skipped_budget' for r in report['checks']))

    def test_workflow_secrets_are_masked_in_final_report(self):
        def sensitive(argv, *args):
            result = self.cli(argv, *args)
            if argv[1:5] == ['workflow', 'execution', 'input', 'show']:
                result['output'] = json.dumps({'host': H3, 'password': 'PRIVATE_EXAMPLE_987'})
            if argv[1:5] == ['task', 'execution', 'result', 'show']:
                result['output'] = json.dumps({'error': 'Authorization: Bearer PRIVATE_EXAMPLE_987'})
            return result
        with mock.patch.object(self.mod, 'run_command', sensitive):
            report = self.mod.Collector(self.cfg).api()
        self.assertEqual(report['selected_workflow_ids'], [WORKFLOW])
        self.assertNotIn('PRIVATE_EXAMPLE_987', json.dumps(report))


if __name__ == '__main__':
    unittest.main()
