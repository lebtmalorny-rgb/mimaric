"""Disposable Ansible fixtures, without production connections or firewall calls."""
import json
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    'probe_contract', ROOT / 'ansible/module_utils/powerops_firewall_probe.py')
_probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_probe)


class AnsibleFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='powerops-firewall-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.tree = self.base / 'kolla'
        shutil.copytree(ROOT / 'ansible', self.tree / 'ansible')
        self.playdir = self.tree / 'ansible'
        self.inventory = self.base / 'inventory.json'
        self.observation = {
            'timestamp': '2026-09-10T10:00:00+00:00',
            'commands': {'addresses': {
                'argv': ['ip', '-j', 'address', 'show'], 'rc': 0,
                'available': True, 'truncated': False, 'timed_out': False,
                'stderr': '', 'stdout': json.dumps([{'ifname': 'ethapi', 'addr_info': [
                    {'family': 'inet', 'local': '192.0.2.2', 'scope': 'global'},
                    {'family': 'inet', 'local': '192.0.2.3', 'scope': 'global'},
                ]}]),
            }},
        }
        for name, argv in _probe.COMMANDS.items():
            self.observation['commands'].setdefault(name, {
                'argv': argv, 'rc': 0, 'available': True, 'truncated': False,
                'timed_out': False, 'stdout': '', 'stderr': '',
            })
        self.inventory_data = {
            'all': {'vars': {
                'ansible_connection': 'local', 'ansible_python_interpreter': sys.executable,
                'host_firewall_become': False, 'api_interface': '{{ network_interface }}',
                'network_interface': 'ethapi', 'api_address_family': 'ipv4',
                'enable_mistral': '{{ enable_openstack_core | bool }}',
                'enable_openstack_core': 'yes', 'enable_haproxy': 'yes',
                'enable_keystone': False, 'enable_ironic': False, 'enable_masakari': False,
                'mistral_api_listen_port': '{{ mistral_api_port }}',
                'mistral_api_port': '8989', 'mistral_api_public_port': '443',
                'ansible_port': 2222,
                'database_password': 'SECRET_MUST_NOT_APPEAR',
                'broken_unrelated_variable': '{{ undefined_unrelated_secret }}',
                'host_firewall_observation': {'snapshot': self.observation},
                'host_firewall_fixture_marker': str(self.base / 'probe-called'),
            }, 'children': {
                'baremetal': {'children': {
                    'mistral-api': {'hosts': {'node-a': {'api_interface_address': '192.0.2.3'}}},
                    'loadbalancer': {'hosts': {'lb': {'api_interface_address': '192.0.2.2'}}},
                }},
                'outside': {'hosts': {'outside': {'ansible_connection': 'firewall_unreachable'}}},
            }},
        }
        self.write_inventory()
        self.cfg = self.base / 'ansible.cfg'
        self.cfg.write_text('[defaults]\nlocal_tmp = %s\nremote_tmp = %s\n'
                            'retry_files_enabled = False\nhost_key_checking = True\n'
                            'interpreter_python = %s\n' % (
                                self.base / 'local-tmp', self.base / 'remote-tmp', sys.executable))
        self.env = dict(os.environ, ANSIBLE_CONFIG=str(self.cfg),
                        ANSIBLE_LOCAL_TEMP=str(self.base / 'local-tmp'),
                        ANSIBLE_LOG_PATH=str(self.base / 'ansible.log'),
                        ANSIBLE_NOCOLOR='1', ANSIBLE_STDOUT_CALLBACK='default')
        for key in ('ANSIBLE_CALLBACK_PLUGINS', 'ANSIBLE_CALLBACKS_ENABLED',
                    'ANSIBLE_INVENTORY', 'ANSIBLE_LIBRARY', 'ANSIBLE_ACTION_PLUGINS'):
            self.env.pop(key, None)

    def write_inventory(self):
        self.inventory.write_text(json.dumps(self.inventory_data))

    def run_play(self, name, extra=None, options=()):
        command = [shutil.which('ansible-playbook'), '-i', str(self.inventory), str(self.playdir / name)]
        if extra:
            extra_file = self.base / 'extra.json'
            extra_file.write_text(json.dumps(extra))
            command.extend(['-e', '@' + str(extra_file)])
        return subprocess.run(command + list(options), env=self.env, cwd=self.tree,
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=60)

    def assert_success(self, result):
        self.assertEqual(0, result.returncode, result.stdout[-12000:])
        self.assertNotIn('SECRET_MUST_NOT_APPEAR', result.stdout)

    def install_probe_fixture(self):
        # Replace only the OS boundary in the throwaway tree. Controller plugins
        # and the entire delivered playbook/role run unchanged under real Ansible.
        shutil.copyfile(ROOT / 'tests/fixtures/probe.py',
                        self.playdir / 'library/powerops_firewall_probe.py')
        (self.playdir / 'connection_plugins').mkdir(exist_ok=True)
        shutil.copyfile(ROOT / 'tests/fixtures/firewall_unreachable.py',
                        self.playdir / 'connection_plugins/firewall_unreachable.py')

    def read_bundle(self):
        paths = list((self.tree / 'artifacts').glob('host-firewall-*/report.json'))
        self.assertTrue(paths, 'No report artifact was created')
        self.report_path = max(paths, key=lambda p: p.stat().st_mtime_ns)
        text = self.report_path.read_text()
        self.assertNotIn('SECRET_MUST_NOT_APPEAR', text)
        return json.loads(text)
