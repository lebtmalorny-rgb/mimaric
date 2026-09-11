"""Run the delivered CLI patch against 0809, with isolated OS boundaries."""
import configparser
import hashlib
import importlib.util
import json
import os
from pathlib import PurePosixPath
import shutil
import subprocess
import sys
import unittest
import zipfile

from support import AnsibleFixture, ROOT
import test_apply


class KollaCliTests(AnsibleFixture):
    def setUp(self):
        super().setUp()
        for module in ('cliff', 'pbr', 'yaml'):
            if importlib.util.find_spec(module) is None:
                self.skipTest('CLI tests require cliff, pbr and PyYAML')
        metadata = json.loads((ROOT.parents[2] / 'baselines/0809.json').read_text())
        expected = metadata['archives']['kolla-ansible']
        archive_path = next((p / expected['file'] for p in ROOT.parents
                             if (p / expected['file']).is_file()), None)
        if archive_path is None:
            self.skipTest('CLI tests require the declared 0809 archive')
        self.assertEqual(expected['sha256'], hashlib.sha256(archive_path.read_bytes()).hexdigest())
        # Use real Kolla Python code and entry-point declarations, retaining the
        # minimal Ansible fixture inventory instead of enabling a real cloud.
        with zipfile.ZipFile(archive_path) as archive:
            for name in archive.namelist():
                relative = PurePosixPath(*PurePosixPath(name).parts[1:])
                self.assertFalse(relative.is_absolute() or '..' in relative.parts)
                if str(relative) == 'setup.cfg' or (
                        relative.parts and relative.parts[0] == 'kolla_ansible'
                        and relative.suffix == '.py'):
                    target = self.tree / str(relative)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(name))
        patch = ROOT / 'patches/0001-add-host-firewall-command.patch'
        if patch.exists():
            result = subprocess.run(['git', 'apply', '--check', str(patch)],
                                    cwd=self.tree, text=True, capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr)
            subprocess.run(['git', 'apply', str(patch)], cwd=self.tree, check=True)
        config = configparser.ConfigParser()
        config.read(self.tree / 'setup.cfg')
        # Importlib/Cliff consume the actual patched setup.cfg registrations.
        dist = self.tree / 'kolla_ansible-20.0.0.dist-info'
        dist.mkdir()
        (dist / 'METADATA').write_text('Metadata-Version: 2.1\nName: kolla-ansible\nVersion: 20.0.0\n')
        (dist / 'entry_points.txt').write_text('\n'.join(
            '[' + group + ']\n' + values.strip() + '\n'
            for group, values in config['entry_points'].items()))
        self.configdir = self.base / 'config'
        self.configdir.mkdir()
        (self.configdir / 'globals.yml').write_text('{}\n')
        self.env['PYTHONPATH'] = str(self.tree)
        self.env['KOLLA_ANSIBLE_DATA_FILES_PATH'] = str(self.tree)
        self.env['POWEROPS_TEST_MUTATION_MARKER'] = str(self.base / 'mutations')
        self.env['POWEROPS_TEST_PROBE_MARKER'] = str(self.base / 'probe-called')
        self.plan = self.base / 'approved-report.json'

    def run_cli(self, *options):
        common = [] if options == ('--help',) else [
            '--configdir', str(self.configdir), '-i', str(self.inventory)]
        return subprocess.run([
            sys.executable, '-m', 'kolla_ansible.cmd.kolla_ansible',
            'host-firewall', *common, *options,
        ], env=self.env, cwd=self.tree, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)

    def test_registered_command_exposes_modes_without_contacting_hosts(self):
        result = self.run_cli('--help')
        self.assert_success(result)
        self.assertIn('--mode {report,apply,rollback}', result.stdout)
        self.assertFalse((self.base / 'probe-called').exists())

    def test_default_report_loads_globals_d_and_extra_vars_without_passwords(self):
        self.install_probe_fixture()
        (self.configdir / 'globals.yml').write_text(
            'host_firewall_mode: apply\nmistral_api_listen_port: 18000\n')
        globals_d = self.configdir / 'globals.d'
        globals_d.mkdir()
        (globals_d / '10-ports.yml').write_text('mistral_api_listen_port: 19000\n')
        result = self.run_cli('--limit', 'baremetal')
        self.assert_success(result)
        self.assertEqual(19000, self.read_bundle()['reports']['node-a']['candidate_flows'][0]['port'])
        result = self.run_cli('-e', 'mistral_api_listen_port=20000',
                              '-e', 'host_firewall_mode=rollback', '--limit', 'baremetal')
        self.assert_success(result)
        bundle = self.read_bundle()
        self.assertEqual(['lb', 'node-a'], bundle['selected_hosts'])
        self.assertEqual(20000, bundle['reports']['node-a']['candidate_flows'][0]['port'])
        self.assertFalse((self.base / 'mutations').exists())
        self.assertFalse((self.configdir / 'passwords.yml').exists())

    def test_apply_reaches_transaction_and_manual_rollback_restores_it(self):
        values = test_apply.ApplyTests.prepare_apply_fixture(self)
        params = self.base / 'apply.json'
        # The explicit CLI mode wins over a conflicting value in the vars file.
        values['host_firewall_mode'] = 'report'
        params.write_text(json.dumps(values))
        result = self.run_cli('--mode', 'apply', '--limit', 'node-a', '-e', '@' + str(params))
        self.assert_success(result)
        rows = [json.loads(line) for line in (self.base / 'mutations').read_text().splitlines()]
        self.assertEqual(['inspect', 'begin', 'apply-runtime', 'verify', 'commit'],
                         [row['action'] for row in rows])
        state = json.loads((self.base / 'firewall.json').read_text())
        self.assertIn('rule priority="30000" drop', state['runtime'])
        self.assertEqual(state['runtime'], state['permanent'])
        txid = json.loads((self.base / 'transaction/current.json').read_text())['id']
        result = self.run_cli('--mode', 'rollback', '--limit', 'node-a',
                              '-e', 'host_firewall_rollback_transaction_id=' + txid)
        self.assert_success(result)
        state = json.loads((self.base / 'firewall.json').read_text())
        self.assertEqual([], state['runtime'])
        self.assertEqual([], state['permanent'])

    def test_apply_without_approved_report_fails_before_remote_tasks(self):
        self.install_probe_fixture()
        result = self.run_cli('--mode', 'apply')
        self.assertNotEqual(0, result.returncode)
        self.assertIn('APPROVED_REPORT_REQUIRED', result.stdout)
        self.assertFalse((self.base / 'probe-called').exists())
        self.assertFalse((self.base / 'mutations').exists())

    def test_check_initialization_keeps_remote_files_and_rules_unchanged(self):
        result = self.run_cli('--mode', 'apply', '--check', '-e', json.dumps({
            'host_firewall_initialize': True,
            'host_firewall_allow_initial_reload': True,
        }))
        self.assert_success(result)
        self.assertFalse((self.base / 'probe-called').exists())
        self.assertFalse((self.base / 'mutations').exists())

    def test_rollback_failure_preserves_ansible_exit_code_and_stops_next_host(self):
        shutil.copyfile(ROOT / 'tests/fixtures/manage.py', self.playdir / 'library/powerops_firewall_manage.py')
        self.env['POWEROPS_TEST_MUTATION_FAIL'] = '1'
        result = self.run_cli('--mode', 'rollback', '-e',
                              'host_firewall_rollback_transaction_id=b932ba67-4814-48fb-9aa5-50c379f3a59e')
        self.assertEqual(2, result.returncode, result.stdout)
        rows = (self.base / 'mutations').read_text().splitlines()
        self.assertEqual(1, len(rows))

    def test_partial_workflow_options_are_rejected_before_ansible(self):
        for option in ('--playbook', '--tags', '--skip-tags'):
            with self.subTest(option=option):
                result = self.run_cli(option, 'anything')
                self.assertNotEqual(0, result.returncode)
                self.assertIn('requires the complete host-firewall playbook', result.stdout)
                self.assertFalse((self.base / 'probe-called').exists())

    def test_invalid_mode_is_rejected_before_ansible(self):
        result = self.run_cli('--mode', 'force')
        self.assertNotEqual(0, result.returncode)
        self.assertIn('invalid choice', result.stdout)
        self.assertFalse((self.base / 'probe-called').exists())
