import base64
import importlib.util
from pathlib import Path
import sys
import unittest
import test_transaction


class BootTests(unittest.TestCase):
    begin = test_transaction.TransactionTests.begin
    verify = test_transaction.TransactionTests.verify
    def setUp(self):
        test_transaction.TransactionTests.setUp(self)
        directory = Path(__file__).resolve().parents[1] / 'ansible/module_utils'
        sys.path.insert(0, str(directory))
        self.addCleanup(sys.path.remove, str(directory))
        spec = importlib.util.spec_from_file_location('boot', directory / 'powerops_firewall_boot.py')
        self.boot = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.boot)
        self.policy_dir = Path(self.tmp.name) / 'policies'
        self.policy_dir.mkdir(mode=0o755)
        self.policy = self.policy_dir / 'kolla-host-input.xml'
        self.policy.write_bytes(b'original owned XML')
        self.plan['boot_image'] = base64.b64encode(self.policy.read_bytes()).decode()
        self.settings = {'description': 'kolla-host-firewall:owner', 'target': 'CONTINUE',
                         'priority': -500, 'ingress_zones': ['ANY'], 'egress_zones': ['HOST'],
                         'rich_rules': []}

    def test_partial_permanent_is_restored_before_firewalld_starts(self):
        txn = self.begin()
        self.manager.apply_runtime(txn['id'])
        self.verify(txn)
        self.firewall.fail_after = len(self.firewall.changes) + 1
        self.assertRaises(RuntimeError, self.manager.commit, txn['id'])
        self.firewall.fail_after = None
        self.settings['rich_rules'] = self.firewall.state['permanent'][:]
        self.policy.write_bytes(b'partial permanent XML')
        self.clock.boot_id = 'boot-two'
        self.boot.restore(self.root, self.policy, 'owner', lambda: self.settings, self.clock.boot_id)
        self.assertEqual(b'original owned XML', self.policy.read_bytes())
        self.firewall.state['runtime'] = []
        self.firewall.state['permanent'] = []
        self.assertEqual('ROLLED_BACK', self.manager.recover_expired()['state'])

    def test_boot_restore_never_overwrites_unknown_owner(self):
        self.begin()
        self.settings['description'] = 'other owner'
        self.assertRaises(ValueError, self.boot.restore, self.root, self.policy,
                          'owner', lambda: self.settings, 'boot-two')
        self.assertEqual(b'original owned XML', self.policy.read_bytes())

    def test_committed_transaction_is_not_reverted_on_boot(self):
        txn = self.begin()
        self.manager.apply_runtime(txn['id'])
        self.verify(txn)
        self.manager.commit(txn['id'])
        self.policy.write_bytes(b'committed XML')
        self.boot.restore(self.root, self.policy, 'owner', lambda: self.settings, 'boot-two')
        self.assertEqual(b'committed XML', self.policy.read_bytes())

    def test_torn_xml_during_journalled_permanent_write_can_be_restored(self):
        txn = self.begin()
        self.manager.apply_runtime(txn['id'])
        self.verify(txn)
        self.firewall.fail_after = len(self.firewall.changes) + 1
        self.assertRaises(RuntimeError, self.manager.commit, txn['id'])
        self.policy.write_bytes(b'<policy')
        def broken_parser():
            raise ValueError('truncated XML')
        self.boot.restore(self.root, self.policy, 'owner', broken_parser, 'boot-two')
        self.assertEqual(b'original owned XML', self.policy.read_bytes())

    def test_torn_xml_without_pending_write_fails_closed(self):
        self.begin()
        self.policy.write_bytes(b'<policy')
        def broken_parser():
            raise ValueError('truncated XML')
        self.assertRaises(ValueError, self.boot.restore, self.root, self.policy,
                          'owner', broken_parser, 'boot-two')
