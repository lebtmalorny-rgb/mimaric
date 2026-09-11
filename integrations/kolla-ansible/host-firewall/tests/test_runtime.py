import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        folder = Path(__file__).resolve().parents[1] / 'ansible/module_utils'
        sys.path.insert(0, str(folder))
        self.addCleanup(sys.path.remove, str(folder))
        spec = importlib.util.spec_from_file_location('host_runtime', folder / 'powerops_firewall_runtime.py')
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_initial_reload_rejects_foreign_tables_and_iptables_rules(self):
        for table in ('{"nftables":[{"table":{"family":"ip","name":"ovn"}}]}',
                      '{"nftables":[{"table":{"family":"inet","name":"other-owner"}}]}'):
            with mock.patch.object(self.m, '_command', return_value=table):
                self.assertRaises(ValueError, self.m.initial_reload_guard)
        def command(argv):
            if argv[0] == 'nft':
                return '{"nftables":[{"table":{"family":"inet","name":"firewalld"}}]}'
            if argv[0] == 'iptables-save':
                return '*filter\n:INPUT ACCEPT [0:0]\n-A INPUT -j another-owner\nCOMMIT'
            return ''
        with mock.patch.object(self.m, '_command', side_effect=command):
            self.assertRaises(ValueError, self.m.initial_reload_guard)

    def test_initial_reload_guard_accepts_only_observed_empty_profile(self):
        calls = []
        def command(argv):
            calls.append(argv)
            if argv[0] == 'nft':
                return '{"nftables":[{"metainfo":{}},{"table":{"family":"inet","name":"firewalld"}}]}'
            if argv[0] in ('iptables-save', 'ip6tables-save'):
                return '*filter\n:INPUT ACCEPT [0:0]\n:FORWARD ACCEPT [0:0]\n:OUTPUT ACCEPT [0:0]\nCOMMIT'
            return ''
        with mock.patch.object(self.m, '_command', side_effect=command):
            self.m.initial_reload_guard()
        self.assertEqual(8, len(calls))
        self.assertTrue(all(not any(word in ('--reload', '--add-policy', 'start') for word in c) for c in calls))

    def test_checkmode_never_constructs_adapter_or_runs_commands(self):
        with mock.patch.object(self.m, '_command', side_effect=AssertionError('command executed')), \
                mock.patch.object(self.m, 'FirewalldAdapter', side_effect=AssertionError('D-Bus contacted')):
            for action in ('prepare', 'begin', 'apply-runtime', 'commit', 'rollback'):
                self.assertFalse(self.m.execute(action, {}, check_mode=True)['changed'])
