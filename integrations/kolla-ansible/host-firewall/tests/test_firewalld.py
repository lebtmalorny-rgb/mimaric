"""Prerequisites must distinguish an absent dependency from missing evidence."""
import importlib.util
from pathlib import Path
import unittest

from firewalld_fixtures import command, installed_firewalld
from test_model import fixture


class FirewalldTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'ansible/module_utils/powerops_firewall_model.py'
        spec = importlib.util.spec_from_file_location('firewalld_model', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.commands = installed_firewalld()

    def report(self):
        model, catalog, observation = fixture()
        observation['commands'].update(self.commands)
        result = self.module.build_report('node-a', model, catalog, observation)
        self.assertIn('firewalld', result, 'Report must assess firewalld prerequisites')
        return result

    def test_installed_versions_and_empty_supported_policy_list(self):
        report = self.report()
        details = report['firewalld']
        self.assertEqual({'installed': True, 'versions': [
            {'version': '1.3.4', 'release': '18.sl9_7^1', 'arch': 'noarch'},
        ]}, details['packages']['firewalld'])
        self.assertTrue(details['packages']['python3-firewall']['installed'])
        self.assertEqual('1.3.4', details['cli_version'])
        self.assertEqual({'state': True, 'runtime_policies': True,
                          'permanent_policies': True}, details['api'])
        self.assertTrue(details['service']['running'])
        self.assertTrue(details['service']['enabled'])
        self.assertFalse(details['service']['masked'])
        self.assertFalse(any(b['code'].startswith('FIREWALLD_') for b in report['blockers']))
        self.assertFalse(report['apply_ready'])

    def test_absent_packages_report_missing_without_losing_other_diagnostics(self):
        for key, package in (('firewalld_package', 'firewalld'),
                             ('firewalld_python_package', 'python3-firewall')):
            with self.subTest(package=package):
                self.commands = installed_firewalld()
                self.commands[key] = command('package %s is not installed\n' % package, rc=1)
                report = self.report()
                self.assertIs(False, report['firewalld']['packages'][package]['installed'])
                self.assertIn({'code': 'FIREWALLD_PACKAGE_MISSING', 'subject': package}, report['blockers'])
                self.assertEqual(18989, report['candidate_flows'][0]['port'])

    def test_package_query_errors_are_unknown_not_not_installed(self):
        for response in (
            command(rc=1, stderr='error: cannot open Packages database'),
            command(rc=None, available=False),
            command('firewalld\t1.3.4\t18.sl9\tnoarch\n', timed_out=True),
            command('package firewalld is not installed\n', rc=1, truncated=True),
            command('package firewalld is not installed\n', rc=1, stderr='database error'),
            command(), command('unexpected output'),
            command('another-package\t1.3.4\t18.sl9\tnoarch\n'),
        ):
            with self.subTest(response=response):
                self.commands['firewalld_package'] = response
                report = self.report()
                self.assertIsNone(report['firewalld']['packages']['firewalld']['installed'])
                self.assertIn({'code': 'FIREWALLD_PACKAGE_UNKNOWN', 'subject': 'firewalld'}, report['blockers'])

    def test_service_inactive_disabled_masked_and_missing_are_explicit(self):
        for load, active, sub, unit, code in (
            ('loaded', 'inactive', 'dead', 'enabled', 'FIREWALLD_NOT_RUNNING'),
            ('loaded', 'failed', 'failed', 'enabled', 'FIREWALLD_NOT_RUNNING'),
            ('loaded', 'active', 'running', 'disabled', 'FIREWALLD_NOT_ENABLED'),
            ('loaded', 'active', 'running', 'enabled-runtime', 'FIREWALLD_NOT_ENABLED'),
            ('masked', 'inactive', 'dead', 'masked', 'FIREWALLD_MASKED'),
            ('not-found', 'inactive', 'dead', '', 'FIREWALLD_NOT_LOADED'),
        ):
            with self.subTest(load=load, active=active, unit=unit):
                self.commands['firewalld_service'] = command(
                    'Id=firewalld.service\nLoadState=%s\nActiveState=%s\nSubState=%s\nUnitFileState=%s\n'
                    % (load, active, sub, unit))
                report = self.report()
                service = report['firewalld']['service']
                self.assertEqual(active, service['active_state'])
                self.assertEqual(unit, service['unit_file_state'])
                self.assertIn(code, {b['code'] for b in report['blockers']})

    def test_bad_service_evidence_never_confirms_running(self):
        good = self.commands['firewalld_service']['stdout']
        for response in (command(), command(good, rc=1), command(good, truncated=True),
                         command(good.replace('firewalld.service', 'nftables.service')),
                         command(good.replace('ActiveState=active\n', ''))):
            with self.subTest(response=response):
                self.commands['firewalld_service'] = response
                report = self.report()
                self.assertIsNone(report['firewalld']['service']['running'])
                self.assertIn('FIREWALLD_SERVICE_UNKNOWN', {b['code'] for b in report['blockers']})

    def test_failed_api_calls_are_not_proof_of_unsupported_version(self):
        for name in ('state', 'runtime_policies', 'permanent_policies'):
            with self.subTest(name=name):
                self.commands = installed_firewalld()
                self.commands['firewalld_' + name] = command(rc=1, stderr='Not authorized')
                report = self.report()
                self.assertIs(False, report['firewalld']['api'][name])
                self.assertEqual('1.3.4', report['firewalld']['cli_version'])
                self.assertIn({'code': 'FIREWALLD_API_UNAVAILABLE', 'subject': name}, report['blockers'])

    def test_incomplete_api_evidence_and_invalid_state_are_unknown(self):
        for name, response in (
            ('state', command()), ('state', command('not running\n')),
            ('runtime_policies', command(timed_out=True)),
            ('permanent_policies', command(rc=None, available=False)),
        ):
            with self.subTest(name=name):
                self.commands = installed_firewalld()
                self.commands['firewalld_' + name] = response
                report = self.report()
                self.assertIsNone(report['firewalld']['api'][name])
                self.assertIn({'code': 'FIREWALLD_API_UNKNOWN', 'subject': name}, report['blockers'])

    def test_cli_version_not_guessed_from_repository_or_package(self):
        for response in (command(), command('1.3.4\n', timed_out=True),
                         command('1.3.4\n', rc=1), command('garbage\n')):
            with self.subTest(response=response):
                self.commands['firewalld_version'] = response
                report = self.report()
                self.assertIsNone(report['firewalld']['cli_version'])
                self.assertIn('FIREWALLD_VERSION_UNKNOWN', {b['code'] for b in report['blockers']})

    def test_missing_all_evidence_is_unknown_not_absent(self):
        self.commands = {}
        report = self.report()
        self.assertIsNone(report['firewalld']['packages']['firewalld']['installed'])
        self.assertIsNone(report['firewalld']['service']['running'])
        self.assertIsNone(report['firewalld']['api']['state'])
