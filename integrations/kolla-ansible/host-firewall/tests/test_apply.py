"""Real Ansible orchestration, with only remote OS and SSH boundaries replaced."""
import json
from pathlib import Path
import shutil

from support import AnsibleFixture, ROOT


class ApplyTests(AnsibleFixture):
    def setUp(self):
        super().setUp()
        self.env['POWEROPS_TEST_MUTATION_MARKER'] = str(self.base / 'mutations')
        self.plan = self.base / 'approved-report.json'

    def install_manage_fixture(self):
        source = ROOT / 'tests/fixtures/manage.py'
        self.assertTrue(source.exists(), 'Mutation OS fixture is missing')
        shutil.copyfile(source, self.playdir / 'library/powerops_firewall_manage.py')

    def test_real_manage_module_dependencies_package_in_ansible_check_mode(self):
        (self.playdir / 'manage-check.yml').write_text('''---
- hosts: node-a
  gather_facts: false
  tasks:
    - powerops_firewall_manage:
        action: preflight
      check_mode: true
''')
        result = self.run_play('manage-check.yml')
        self.assert_success(result)
        self.assertFalse((self.base / 'mutations').exists())

    def prepare_apply_fixture(self):
        self.install_probe_fixture()
        self.env['POWEROPS_TEST_PROBE_MARKER'] = str(self.base / 'probe-called')
        # An isolated SSH-only test host: no enabled OpenStack services. This is
        # deliberately not a claim that the partial production catalog is complete.
        for key in self.inventory_data['all']['vars']:
            if key.startswith('enable_'):
                self.inventory_data['all']['vars'][key] = False
        self.write_inventory()
        self.assert_success(self.run_play('host-firewall.yml', options=('--limit', 'node-a')))
        bundle = self.read_bundle()
        self.plan.write_text(json.dumps(bundle))
        shutil.copyfile(ROOT / 'tests/fixtures/transaction_os.py', self.playdir / 'library/powerops_firewall_manage.py')
        shutil.copyfile(ROOT / 'tests/fixtures/verify.py', self.playdir / 'action_plugins/powerops_firewall_verify.py')
        return {'host_firewall_mode': 'apply', 'host_firewall_plan_file': str(self.plan),
                'host_firewall_plan_id': bundle['plan_id'], 'host_firewall_verification_checks': [
                    {'id': 'api', 'type': 'tcp', 'host': '192.0.2.8', 'port': 443}]}

    def test_actual_entrypoint_runtime_verify_commit_and_noop_second_apply(self):
        values = self.prepare_apply_fixture()
        self.assert_success(self.run_play('host-firewall.yml', values, options=('--limit', 'node-a')))
        actions = [json.loads(row)['action'] for row in (self.base / 'mutations').read_text().splitlines()]
        self.assertEqual(['inspect', 'begin', 'apply-runtime', 'verify', 'commit'], actions)
        state = json.loads((self.base / 'firewall.json').read_text())
        self.assertEqual(state['runtime'], state['permanent'])
        self.assertIn('rule priority="30000" drop', state['runtime'])
        self.assert_success(self.run_play('host-firewall.yml', values, options=('--limit', 'node-a')))
        actions = [json.loads(row)['action'] for row in (self.base / 'mutations').read_text().splitlines()]
        self.assertEqual(['inspect', 'begin'], actions[-2:])

    def test_failed_post_apply_check_restores_runtime_without_persisting(self):
        values = self.prepare_apply_fixture()
        self.env['POWEROPS_TEST_VERIFY_FAIL'] = '2'
        result = self.run_play('host-firewall.yml', values, options=('--limit', 'node-a'))
        self.assertNotEqual(0, result.returncode)
        actions = [json.loads(row)['action'] for row in (self.base / 'mutations').read_text().splitlines()]
        self.assertEqual(['inspect', 'begin', 'apply-runtime', 'rollback'], actions)
        state = json.loads((self.base / 'firewall.json').read_text())
        self.assertEqual([], state['runtime'])
        self.assertEqual([], state['permanent'])

    def test_changed_inventory_rejects_stale_report_before_mutations(self):
        values = self.prepare_apply_fixture()
        self.inventory_data['all']['vars']['ansible_port'] = 22
        self.write_inventory()
        result = self.run_play('host-firewall.yml', values, options=('--limit', 'node-a'))
        self.assertNotEqual(0, result.returncode)
        self.assertIn('FRESH_REPORT_MISMATCH', result.stdout)
        self.assertFalse((self.base / 'mutations').exists())

    def test_apply_requires_report_before_any_host_change(self):
        result = self.run_play('host-firewall.yml', {'host_firewall_mode': 'apply'})
        self.assertNotEqual(0, result.returncode)
        self.assertFalse((self.base / 'mutations').exists())

    def test_prepare_requires_explicit_reload_permission(self):
        result = self.run_play('host-firewall.yml', {
            'host_firewall_mode': 'apply', 'host_firewall_initialize': True})
        self.assertNotEqual(0, result.returncode)
        self.assertIn('INITIAL_RELOAD_APPROVAL_REQUIRED', result.stdout)
        self.assertFalse((self.base / 'mutations').exists())

    def test_check_prepare_never_installs_files_or_calls_mutation(self):
        result = self.run_play('host-firewall.yml', {
            'host_firewall_mode': 'apply', 'host_firewall_initialize': True,
            'host_firewall_allow_initial_reload': True}, options=('--check',))
        self.assert_success(result)
        self.assertFalse((self.base / 'mutations').exists())

    def test_incomplete_saved_report_blocks_apply(self):
        self.plan.write_text(json.dumps({'selected_hosts': ['lb', 'node-a'],
            'reports': {host: {'host': host, 'ssh': {'inventory_port': 2222},
                'candidate_flows': [], 'blockers': [
                    {'code': 'PARTIAL_SERVICE_COVERAGE', 'subject': 'mistral'}]}
                for host in ('lb', 'node-a')}}))
        result = self.run_play('host-firewall.yml', {
            'host_firewall_mode': 'apply', 'host_firewall_plan_file': str(self.plan),
            'host_firewall_plan_id': 'a' * 64})
        self.assertNotEqual(0, result.returncode)
        self.assertFalse((self.base / 'mutations').exists())

    def test_manual_rollback_calls_remote_restore_for_exact_transaction(self):
        self.install_manage_fixture()
        txid = 'b932ba67-4814-48fb-9aa5-50c379f3a59e'
        result = self.run_play('host-firewall.yml', {
            'host_firewall_mode': 'rollback',
            'host_firewall_rollback_transaction_id': txid})
        self.assert_success(result)
        rows = [json.loads(line) for line in (self.base / 'mutations').read_text().splitlines()]
        self.assertEqual(2, len(rows))
        self.assertTrue(all(row == {'action': 'rollback', 'txid': txid} for row in rows))

    def test_failed_first_rollback_stops_second_host(self):
        self.install_manage_fixture()
        self.env['POWEROPS_TEST_MUTATION_FAIL'] = '1'
        result = self.run_play('host-firewall.yml', {
            'host_firewall_mode': 'rollback',
            'host_firewall_rollback_transaction_id': 'b932ba67-4814-48fb-9aa5-50c379f3a59e'})
        self.assertNotEqual(0, result.returncode)
        self.assertTrue((self.base / 'mutations').exists(), 'Rollback must reach its remote implementation')
        self.assertEqual(1, len((self.base / 'mutations').read_text().splitlines()))
