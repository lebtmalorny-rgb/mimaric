import json
from pathlib import Path
import unittest

from support import AnsibleFixture
from firewalld_fixtures import command


class ProjectionTests(AnsibleFixture):
    def setUp(self):
        super().setUp()
        self.assertTrue((self.playdir / 'action_plugins/powerops_firewall_model.py').exists(),
                        'Controller projection is not implemented')
        (self.playdir / 'projection.yml').write_text('''---
- hosts: baremetal
  gather_facts: false
  vars_files:
    - roles/host-firewall/vars/catalog.yml
  tasks:
    - powerops_firewall_model:
        stage: project
      register: host_firewall_projection
      no_log: true
    - powerops_firewall_model:
        stage: aggregate
        hosts: "{{ ansible_play_hosts_all }}"
      register: report
      run_once: true
      no_log: true
    - copy:
        content: "{{ report.bundle | to_nice_json }}"
        dest: "{{ playbook_dir }}/projection.json"
        mode: '0600'
      delegate_to: localhost
      run_once: true
      no_log: true
''')

    def project(self, extra=None):
        result = self.run_play('projection.yml', extra)
        self.assert_success(result)
        content = (self.playdir / 'projection.json').read_text()
        self.assertNotIn('SECRET_MUST_NOT_APPEAR', content)
        return json.loads(content)['reports']['node-a']

    def test_effective_globals_extra_vars_and_inventory_are_used(self):
        globals_file = self.base / 'globals.yml'
        globals_file.write_text('mistral_api_listen_port: 18000\n')
        result = self.run_play('projection.yml', {'mistral_api_listen_port': 18989},
                               options=('-e', '@' + str(globals_file), '-e', 'mistral_api_listen_port=19999'))
        self.assert_success(result)
        report = json.loads((self.playdir / 'projection.json').read_text())['reports']['node-a']
        self.assertEqual([19999], [flow['port'] for flow in report['candidate_flows']])
        self.assertEqual('192.0.2.3', report['candidate_flows'][0]['destination'])
        self.assertEqual(2222, report['ssh']['inventory_port'])

    def test_default_jinja_and_unrelated_undefined_secret(self):
        report = self.project()
        self.assertEqual(8989, report['candidate_flows'][0]['port'])
        self.assertNotIn('broken_unrelated_variable', json.dumps(report))

    def test_missing_measurement_makes_collection_incomplete(self):
        self.observation['commands'].pop('ss', None)
        self.write_inventory()
        self.project()
        bundle = json.loads((self.playdir / 'projection.json').read_text())
        self.assertFalse(bundle['collection_complete'])
        self.assertIn({'code': 'PROBE_MISSING', 'subject': 'ss'},
                      bundle['reports']['node-a']['blockers'])

    def test_unresolved_selected_value_does_not_abort_or_leak(self):
        report = self.project({'mistral_api_listen_port': '{{ missing_secret_value }}'})
        self.assertEqual([], report['candidate_flows'])
        self.assertIn('UNRESOLVED_VARIABLE', {b['code'] for b in report['blockers']})
        self.assertNotIn('missing_secret_value', json.dumps(report))

    def test_unknown_and_disabled_services_are_distinct(self):
        report = self.project({'enable_new_service': True, 'enable_mistral': 'false'})
        self.assertEqual([], report['candidate_flows'])
        self.assertIn({'code': 'UNKNOWN_ENABLED_FLAG', 'subject': 'enable_new_service'}, report['blockers'])
        self.assertFalse(report['enabled_flags']['enable_mistral'])

    def test_disabled_haproxy_does_not_invent_backend_traffic(self):
        report = self.project({'enable_haproxy': False})
        self.assertEqual([], report['candidate_flows'])

    def test_keystone_external_backend_requires_resolved_enabled_external_vip(self):
        baremetal = self.inventory_data['all']['children']['baremetal']['children']
        baremetal['keystone'] = {'hosts': {'node-a': {}}}
        self.write_inventory()
        for setting in (False, '{{ missing_external_vip_setting }}', None, True, 'missing'):
            with self.subTest(setting=setting):
                extra = {'enable_mistral': False, 'enable_keystone': True,
                         'keystone_internal_listen_port': 15001, 'keystone_public_listen_port': 15000}
                if setting != 'missing':
                    extra['haproxy_enable_external_vip'] = setting
                report = self.project(extra)
                expected = [15000, 15001] if setting is True else [15001]
                self.assertEqual(expected, sorted(f['port'] for f in report['candidate_flows']))
                self.assertNotIn('missing_external_vip_setting', json.dumps(report))

    def test_address_not_observed_on_interface_is_not_used(self):
        report = self.project({'api_interface_address': '192.0.2.100'})
        self.assertEqual([], report['candidate_flows'])
        self.assertIn('UNRESOLVED_VARIABLE', {b['code'] for b in report['blockers']})

    def test_failed_explicit_address_never_falls_back_to_observed_address(self):
        self.observation['commands']['addresses']['stdout'] = json.dumps([
            {'ifname': 'ethapi', 'addr_info': [
                {'family': 'inet', 'local': '192.0.2.3', 'scope': 'global'},
            ]},
        ])
        self.write_inventory()
        for override in ('{{ missing_binding_address }}', None):
            with self.subTest(override=override):
                report = self.project({'api_interface_address': override})
                self.assertEqual([], report['candidate_flows'])
                self.assertIn({'code': 'UNRESOLVED_VARIABLE', 'subject': 'api_interface_address'},
                              report['blockers'])
                self.assertNotIn('missing_binding_address', json.dumps(report))


class PlaybookTests(AnsibleFixture):
    def setUp(self):
        super().setUp()
        self.assertTrue((self.playdir / 'host-firewall.yml').exists(), 'Playbook is not implemented')
        self.install_probe_fixture()
        self.env['POWEROPS_TEST_PROBE_MARKER'] = str(self.base / 'probe-called')

    def test_read_only_report_permissions_and_repeat_run(self):
        foreign = self.base / 'foreign-firewall.rules'
        foreign.write_text('owned by another component\n')
        result = self.run_play('host-firewall.yml')
        self.assert_success(result)
        bundle = self.read_bundle()
        self.assertFalse(bundle['apply_ready'])
        self.assertTrue(bundle['collection_complete'])
        self.assertEqual(['lb', 'node-a'], bundle['selected_hosts'])
        self.assertEqual(['outside'], bundle['not_selected_hosts'])
        self.assertEqual(8989, bundle['reports']['node-a']['candidate_flows'][0]['port'])
        self.assertEqual(0o600, self.report_path.stat().st_mode & 0o777)
        self.assertEqual(0o700, self.report_path.parent.stat().st_mode & 0o777)
        markdown = self.report_path.with_suffix('.md')
        self.assertEqual(0o600, markdown.stat().st_mode & 0o777)
        self.assertIn('APPLY_REQUIRES_VERIFICATION', markdown.read_text())
        self.assertIn('firewalld', markdown.read_text())
        self.assertIn('1.3.4', markdown.read_text())
        self.assertTrue(bundle['reports']['node-a']['firewalld']['packages']['firewalld']['installed'])
        first = self.report_path.read_bytes()
        first_path = self.report_path
        self.assert_success(self.run_play('host-firewall.yml'))
        self.assertEqual(first, first_path.read_bytes())
        self.assertEqual(2, len(list((self.tree / 'artifacts').glob('host-firewall-*/report.json'))))
        self.assertEqual('owned by another component\n', foreign.read_text())

    def test_absent_package_is_reported_and_other_hosts_still_collected(self):
        self.observation['commands']['firewalld_package'] = command(
            'package firewalld is not installed\n', rc=1)
        self.write_inventory()
        self.assert_success(self.run_play('host-firewall.yml'))
        bundle = self.read_bundle()
        self.assertEqual(['lb', 'node-a'], bundle['selected_hosts'])
        for report in bundle['reports'].values():
            self.assertEqual('ok', report['collection_status'])
            self.assertIn({'code': 'FIREWALLD_PACKAGE_MISSING', 'subject': 'firewalld'}, report['blockers'])
            self.assertFalse(report['apply_ready'])
        self.assertIn('FIREWALLD_PACKAGE_MISSING', self.report_path.with_suffix('.md').read_text())

    def test_api_timeout_is_saved_without_aborting_report(self):
        self.observation['commands']['firewalld_runtime_policies'] = command(rc=-9, timed_out=True)
        self.write_inventory()
        self.assert_success(self.run_play('host-firewall.yml'))
        bundle = self.read_bundle()
        self.assertFalse(bundle['collection_complete'])
        self.assertIsNone(bundle['reports']['node-a']['firewalld']['api']['runtime_policies'])

    def test_apply_fails_before_remote_probe(self):
        result = self.run_play('host-firewall.yml', {'host_firewall_mode': 'apply'})
        self.assertNotEqual(0, result.returncode)
        self.assertFalse((self.base / 'probe-called').exists())
        self.assertFalse((self.tree / 'artifacts').exists())

    def test_skipping_preflight_does_not_allow_apply_probe(self):
        result = self.run_play('host-firewall.yml', {'host_firewall_mode': 'apply'},
                               options=('--skip-tags', 'always'))
        self.assertNotEqual(0, result.returncode)
        self.assertFalse((self.base / 'probe-called').exists())
        self.assertFalse((self.tree / 'artifacts').exists())

    def test_start_at_probe_in_apply_cannot_produce_a_successful_report(self):
        result = self.run_play('host-firewall.yml', {'host_firewall_mode': 'apply'}, options=(
            '--start-at-task', 'host-firewall : Collect bounded network and firewall observations'))
        self.assertNotEqual(0, result.returncode)
        self.assertFalse((self.base / 'probe-called').exists())
        self.assertFalse((self.tree / 'artifacts').exists())

    def test_limit_does_not_contact_excluded_hosts_or_invent_addresses(self):
        result = self.run_play('host-firewall.yml', options=('--limit', 'node-a'))
        self.assert_success(result)
        bundle = self.read_bundle()
        self.assertEqual(['node-a'], bundle['selected_hosts'])
        self.assertEqual([], bundle['reports']['node-a']['candidate_flows'])
        self.assertEqual(1, len((self.base / 'probe-called').read_text().splitlines()))

    def test_unreachable_host_is_retained_in_partial_report(self):
        result = self.run_play('host-firewall.yml', {'host_firewall_hosts': 'all'})
        self.assert_success(result)
        bundle = self.read_bundle()
        self.assertEqual('unreachable', bundle['reports']['outside']['collection_status'])
        self.assertEqual([], bundle['reports']['outside']['candidate_flows'])
        self.assertFalse(bundle['collection_complete'])

    def test_check_mode_still_collects_and_saves_report(self):
        self.assert_success(self.run_play('host-firewall.yml', options=('--check',)))
        bundle = self.read_bundle()
        self.assertFalse(bundle['apply_ready'])
        self.assertTrue((self.base / 'probe-called').exists())


if __name__ == '__main__':
    unittest.main()
