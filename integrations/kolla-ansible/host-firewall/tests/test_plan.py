"""A partial diagnostic report must not turn into a restrictive apply plan."""
import copy
import importlib.util
from pathlib import Path
import unittest


class PlanTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'ansible/module_utils/powerops_firewall_plan.py'
        self.assertTrue(path.exists(), 'Apply plan validation is missing')
        spec = importlib.util.spec_from_file_location('firewall_apply_plan', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.report = {'host': 'node-a', 'ssh': {'inventory_port': 2222},
                       'blockers': [{'code': 'SSH_ACCESS_NOT_VERIFIED', 'subject': ''}],
                       'candidate_flows': [{'protocol': 'tcp', 'port': 443,
                           'destination': '2001:db8::2',
                           'sources': [{'address': '2001:db8::1'}]}]}

    def test_ssh_any_family_and_exact_service_sources(self):
        rules = self.module.rules_from_report(self.report)
        self.assertIn('rule priority="-30000" port port="2222" protocol="tcp" accept', rules)
        self.assertIn('rule family="ipv6" priority="-20000" source address="2001:db8::1/128" destination address="2001:db8::2/128" port port="443" protocol="tcp" accept', rules)
        self.assertEqual('rule priority="30000" drop', rules[-1])

    def test_partial_unknown_or_invalid_data_cannot_be_applied(self):
        for code in ('PARTIAL_SERVICE_COVERAGE', 'UNKNOWN_ENABLED_FLAG', 'PROBE_FAILED'):
            report = copy.deepcopy(self.report)
            report['blockers'].append({'code': code, 'subject': ''})
            self.assertRaises(self.module.PlanError, self.module.rules_from_report, report)
        for value in (None, True, '22', 0, 65536):
            report = copy.deepcopy(self.report)
            report['ssh']['inventory_port'] = value
            self.assertRaises(self.module.PlanError, self.module.rules_from_report, report)

    def test_empty_sources_and_wrong_family_are_rejected_not_widened(self):
        for sources in ([], [{'address': '192.0.2.1'}], [{'address': '0.0.0.0/0'}]):
            report = copy.deepcopy(self.report)
            report['candidate_flows'][0]['sources'] = sources
            self.assertRaises(self.module.PlanError, self.module.rules_from_report, report)

    def test_plan_identity_changes_with_rule_and_host_selection(self):
        first = self.module.report_digest({'selected_hosts': ['a'], 'reports': {'a': self.report}})
        self.report['ssh']['inventory_port'] = 22
        second = self.module.report_digest({'selected_hosts': ['a'], 'reports': {'a': self.report}})
        self.assertNotEqual(first, second)
