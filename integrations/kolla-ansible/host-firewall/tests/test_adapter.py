"""Exercise adapter output and write scope against the firewalld 1.3.4 API."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest import mock


class Transport:
    def __init__(self):
        self.calls = []
        self.runtime = {'description': 'kolla-host-firewall:owner',
                        'ingress_zones': ['ANY'], 'egress_zones': ['HOST'],
                        'target': 'CONTINUE', 'priority': -500, 'rich_rules': []}
        self.permanent = copy.deepcopy(self.runtime)
        self.version = '1.3.4'
        self.runtime_present = True
        self.permanent_present = True
        self.foreign_policy = None

    def __call__(self, path, interface, method, *args):
        self.calls.append((path, interface, method, args))
        if method == 'Get':
            return {'version': self.version, 'state': 'RUNNING',
                    'FirewallBackend': 'nftables'}[args[1]]
        if method == 'getPolicies':
            return (['kolla-host-input'] if self.runtime_present else []) + (['other'] if self.foreign_policy else [])
        if method == 'getPolicyNames':
            return ['kolla-host-input'] if self.permanent_present else []
        if method == 'getPolicyByName':
            return '/policy/owned'
        if method == 'getPolicySettings':
            if args[0] == 'other':
                return copy.deepcopy(self.foreign_policy)
            return copy.deepcopy(self.runtime)
        if method == 'getSettings':
            return copy.deepcopy(self.permanent)
        if method in ('getZones', 'getZoneNames', 'getAllRules', 'getAllPassthroughs',
                      'getIPSets', 'getServiceNames', 'getIcmpTypeNames', 'getHelperNames',
                      'getIPSetNames'):
            return []
        if method == 'getDefaultZone':
            return 'public'
        if method == 'queryPanicMode':
            return False
        if method == 'setPolicySettings':
            if len(args) != 2:
                raise AssertionError('1.3.4 has two positional arguments')
            self.runtime.update(args[1])
            return None
        if method == 'update':
            self.permanent.update(args[0])
            return None
        if method == 'addPolicy':
            self.permanent = copy.deepcopy(args[1])
            self.permanent_present = True
            return '/policy/owned'
        if method == 'reload':
            self.runtime = copy.deepcopy(self.permanent)
            self.runtime_present = True
            return None
        raise AssertionError('Unexpected D-Bus call: %s' % ((path, interface, method, args),))


class AdapterTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'ansible/module_utils/powerops_firewall_firewalld.py'
        self.assertTrue(path.exists(), 'Firewalld adapter is missing')
        spec = importlib.util.spec_from_file_location('firewalld_adapter', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.bus = Transport()
        self.adapter = self.module.FirewalldAdapter('owner', transport=self.bus)

    def test_runtime_write_only_owned_rich_rules_and_permanent_unchanged(self):
        self.adapter.change('runtime', 'add', 'rule priority="30000" drop')
        self.assertEqual(['rule priority="30000" drop'], self.bus.runtime['rich_rules'])
        self.assertEqual([], self.bus.permanent['rich_rules'])
        writes = [c for c in self.bus.calls if c[2] == 'setPolicySettings']
        self.assertEqual(('kolla-host-input', {'rich_rules': ['rule priority="30000" drop']}), writes[0][3])

    def test_permanent_write_does_not_reload_or_change_runtime(self):
        self.adapter.change('permanent', 'add', 'rule priority="30000" drop')
        self.assertEqual([], self.bus.runtime['rich_rules'])
        self.assertEqual(['rule priority="30000" drop'], self.bus.permanent['rich_rules'])

    def test_wrong_owner_immutable_fields_and_unknown_fields_block_writes(self):
        for key, value in (('description', 'someone else'), ('target', 'ACCEPT'),
                           ('ingress_zones', ['public']), ('priority', -100),
                           ('services', ['ssh']), ('unknown-setting', True)):
            with self.subTest(key=key):
                self.bus = Transport()
                self.adapter = self.module.FirewalldAdapter('owner', transport=self.bus)
                self.bus.runtime[key] = value
                self.assertRaises(self.module.FirewalldError, self.adapter.change,
                                  'runtime', 'add', 'rule priority="30000" drop')
                self.assertFalse(any(c[2] in ('setPolicySettings', 'update') for c in self.bus.calls))

    def test_unsupported_version_fails_closed(self):
        self.bus.version = '2.0.0'
        self.assertRaises(self.module.FirewalldError, self.adapter.snapshot)

    def test_dbus_calls_are_pinned_to_unique_owner_not_activatable_name(self):
        dbus = mock.Mock()
        bus = dbus.SystemBus.return_value
        bus.name_has_owner.return_value = True
        bus.get_name_owner.return_value = ':1.42'
        with mock.patch.dict('sys.modules', {'dbus': dbus}):
            adapter = self.module.FirewalldAdapter('owner')
            adapter.call(self.module.PATH, self.module.BUS, 'queryPanicMode')
            bus.get_object.assert_called_with(':1.42', self.module.PATH, introspect=False)
            bus.get_object.side_effect = OSError('old daemon exited')
            self.assertRaises(OSError, adapter.call, self.module.PATH, self.module.BUS, 'queryPanicMode')
            self.assertTrue(all(call.args[0] == ':1.42' for call in bus.get_object.call_args_list))

    def test_snapshot_separates_runtime_and_permanent(self):
        self.bus.runtime['rich_rules'] = ['rule priority="30000" drop']
        result = self.adapter.snapshot()
        self.assertEqual([], result['permanent'])
        self.assertEqual(['rule priority="30000" drop'], result['runtime'])
        self.assertRegex(result['foreign'], r'^[0-9a-f]{64}$')

    def test_partial_initialization_can_be_retried_but_never_adopted(self):
        self.bus.runtime_present = False
        result = self.adapter.prepare(allow_reload=True)
        self.assertTrue(result['changed'])
        self.assertTrue(self.bus.runtime_present)
        self.assertFalse(any(c[2] == 'addPolicy' for c in self.bus.calls))

    def test_initialization_requires_reload_approval_and_preserves_empty_policy(self):
        self.bus.runtime_present = self.bus.permanent_present = False
        self.assertRaises(self.module.FirewalldError, self.adapter.prepare)
        self.assertFalse(any(c[2] in ('addPolicy', 'reload') for c in self.bus.calls))
        self.assertTrue(self.adapter.prepare(allow_reload=True)['changed'])
        self.assertEqual([], self.bus.runtime['rich_rules'])
        self.assertFalse(self.adapter.prepare(allow_reload=True)['changed'])

    def test_earlier_host_policy_reject_is_a_conflict(self):
        self.bus.foreign_policy = {'priority': -1000, 'ingress_zones': ['ANY'],
                                   'egress_zones': ['HOST'], 'target': 'DROP'}
        self.assertRaises(self.module.FirewalldError, self.adapter.forward_guard)
