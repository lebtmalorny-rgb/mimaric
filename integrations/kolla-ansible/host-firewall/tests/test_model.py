"""Behavioral tests: partial evidence must never become an allow policy."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'ansible/module_utils/powerops_firewall_model.py'


def fixture():
    model = {
        'enabled_flags': {'enable_mistral': True},
        'groups': {'loadbalancer': ['lb'], 'mistral-api': ['node-a']},
        'network_addresses': {'lb': {'api': '192.0.2.2'},
                              'node-a': {'api': '192.0.2.3'}},
        'ports': {'mistral_api_listen_port': '18989'},
        'ssh_port': 2222, 'unresolved_names': [],
    }
    catalog = {'schema_version': 1, 'services': {'mistral': {
        'enable_flag': 'enable_mistral', 'coverage': 'partial',
        'source_evidence': '0809 roles/mistral/defaults/main.yml',
        'flows': [{'id': 'mistral-api-backend', 'protocol': 'tcp',
                   'port_var': 'mistral_api_listen_port',
                   'destination_group': 'mistral-api', 'network': 'api',
                   'source_groups': ['loadbalancer']}],
    }}}
    observation = {'timestamp': '2026-09-10T10:00:00+00:00', 'commands': {
        'ss': {'argv': ['ss', '-H', '-lntu'], 'rc': 0, 'stdout': '',
               'stderr': '', 'available': True, 'truncated': False,
               'timed_out': False},
    }}
    return model, catalog, observation


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.exists(), 'Report model is not implemented')
        spec = importlib.util.spec_from_file_location('fw_model', MODULE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def report(self, model=None, catalog=None, observation=None, host='node-a'):
        m, c, o = fixture()
        return self.module.build_report(host, model if model is not None else m,
                                        catalog if catalog is not None else c,
                                        observation if observation is not None else o)

    def codes(self, report):
        return {b['code'] for b in report['blockers']}

    def test_backend_flow_uses_effective_listen_port_and_exact_peers(self):
        report = self.report()
        self.assertEqual([{
            'id': 'mistral-api-backend', 'service': 'mistral',
            'protocol': 'tcp', 'port': 18989, 'network': 'api',
            'destination': '192.0.2.3',
            'sources': [{'host': 'lb', 'address': '192.0.2.2'}],
            'evidence': '0809 roles/mistral/defaults/main.yml',
        }], report['candidate_flows'])
        self.assertFalse(report['apply_ready'])
        self.assertIn('APPLY_NOT_IMPLEMENTED', self.codes(report))
        self.assertIn('PARTIAL_SERVICE_COVERAGE', self.codes(report))
        self.assertEqual(2222, report['ssh']['inventory_port'])
        self.assertFalse(report['ssh']['access_verified'])

    def test_unknown_enabled_and_unresolved_flags_are_blockers(self):
        model, _, _ = fixture()
        model['enabled_flags'].update(enable_unknown=True, enable_broken='maybe')
        report = self.report(model=model)
        self.assertIn('UNKNOWN_ENABLED_FLAG', self.codes(report))
        self.assertIn('INVALID_ENABLE_FLAG', self.codes(report))
        self.assertIsNone(report['enabled_flags']['enable_broken'])

    def test_false_strings_do_not_enable_services(self):
        for value in (False, 'false', 'False', 'no', 'off', '0', 0):
            with self.subTest(value=value):
                model, _, _ = fixture()
                model['enabled_flags']['enable_mistral'] = value
                report = self.report(model=model)
                self.assertEqual([], report['candidate_flows'])
                self.assertNotIn('PARTIAL_SERVICE_COVERAGE', self.codes(report))

    def test_invalid_ports_are_not_guessed_or_disclosed(self):
        for value in (0, 65536, True, 1.5, '8989/tcp', 'secret-value', None):
            with self.subTest(value=value):
                model, _, _ = fixture()
                model['ports']['mistral_api_listen_port'] = value
                report = self.report(model=model)
                self.assertEqual([], report['candidate_flows'])
                self.assertIn('INVALID_PORT', self.codes(report))
                self.assertNotIn('secret-value', json.dumps(report))

    def test_no_rules_on_unrelated_host(self):
        self.assertEqual([], self.report(host='compute')['candidate_flows'])

    def test_missing_group_or_address_never_widens_source(self):
        for target in ('group', 'source', 'destination'):
            with self.subTest(target=target):
                model, _, _ = fixture()
                if target == 'group':
                    model['groups'].pop('loadbalancer')
                else:
                    model['network_addresses'].pop('lb' if target == 'source' else 'node-a')
                report = self.report(model=model)
                self.assertEqual([], report['candidate_flows'])
                self.assertTrue({'MISSING_GROUP', 'MISSING_ADDRESS'} & self.codes(report))

    def test_invalid_or_ambiguous_ip_is_not_policy(self):
        for address in ('0.0.0.0', '::', '224.0.0.1', 'host.example',
                        '192.0.2.0/24', ['192.0.2.2', '192.0.2.4']):
            model, _, _ = fixture()
            model['network_addresses']['lb']['api'] = address
            report = self.report(model=model)
            self.assertEqual([], report['candidate_flows'])
            self.assertIn('INVALID_ADDRESS', self.codes(report))

    def test_ipv6_is_normalized_and_family_mismatch_blocks(self):
        model, _, _ = fixture()
        model['network_addresses'] = {
            'lb': {'api': '2001:db8:0::2'}, 'node-a': {'api': '2001:db8::3'}}
        flow = self.report(model=model)['candidate_flows'][0]
        self.assertEqual('2001:db8::2', flow['sources'][0]['address'])
        model['network_addresses']['lb']['api'] = '192.0.2.2'
        self.assertIn('ADDRESS_FAMILY_MISMATCH', self.codes(self.report(model=model)))
        self.assertEqual([], self.report(model=model)['candidate_flows'])

    def test_observation_errors_and_absence_are_explicit(self):
        self.assertIn('OBSERVATION_MISSING', self.codes(self.report(observation={})))
        for changes, code in (({'rc': 1}, 'PROBE_FAILED'),
                              ({'truncated': True}, 'PROBE_TRUNCATED'),
                              ({'timed_out': True}, 'PROBE_TIMEOUT'),
                              ({'available': False}, 'PROBE_UNAVAILABLE')):
            _, _, observation = fixture()
            observation['commands']['ss'].update(changes)
            self.assertIn(code, self.codes(self.report(observation=observation)))

    def test_observed_listener_is_not_an_automatic_allow(self):
        _, _, observation = fixture()
        observation['commands']['ss']['stdout'] = 'tcp LISTEN 0 128 0.0.0.0:12345'
        report = self.report(observation=observation)
        self.assertEqual([18989], [flow['port'] for flow in report['candidate_flows']])
        self.assertIn('12345', report['observations']['commands']['ss']['stdout'])

    def test_unrelated_secrets_are_not_serialized(self):
        model, catalog, observation = fixture()
        model['hostvars'] = {'password': 'do-not-report-this'}
        observation['invocation'] = {'secret': 'do-not-report-this'}
        report = self.report(model=model, catalog=catalog, observation=observation)
        self.assertNotIn('do-not-report-this', json.dumps(report))

    def test_inputs_are_not_mutated_and_output_is_stable(self):
        args = fixture()
        before = copy.deepcopy(args)
        a = self.module.build_report('node-a', *args)
        self.assertEqual(before, args)
        self.assertEqual(a, self.module.build_report('node-a', *args))

    def test_missing_enable_or_unresolved_variable_is_not_disabled(self):
        model, _, _ = fixture()
        model['enabled_flags'].clear()
        model['unresolved_names'] = ['api_interface']
        report = self.report(model=model)
        self.assertIn('MISSING_ENABLE_FLAG', self.codes(report))
        self.assertIn('UNRESOLVED_VARIABLE', self.codes(report))

    def test_ssh_missing_is_not_assumed_to_be_22(self):
        model, _, _ = fixture()
        model['ssh_port'] = None
        report = self.report(model=model)
        self.assertIsNone(report['ssh']['inventory_port'])
        self.assertIn('SSH_PORT_UNRESOLVED', self.codes(report))

    def test_invalid_catalog_is_reported_not_accepted(self):
        report = self.report(catalog={'schema_version': 999, 'services': {}})
        self.assertIn('INVALID_CATALOG', self.codes(report))
        self.assertEqual([], report['candidate_flows'])


if __name__ == '__main__':
    unittest.main()
