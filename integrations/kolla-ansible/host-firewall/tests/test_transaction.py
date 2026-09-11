"""Run real durable transactions; replace only firewall and OS supervision."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


MODULE = Path(__file__).resolve().parents[1] / 'ansible/module_utils/powerops_firewall_transaction.py'
SSH = 'rule priority="-30000" port port="2222" protocol="tcp" accept'
DROP = 'rule priority="30000" drop'


class Firewall:
    def __init__(self):
        self.state = {'runtime': [], 'permanent': [], 'foreign': 'unchanged'}
        self.changes = []
        self.fail_after = None

    def snapshot(self):
        return copy.deepcopy(self.state)

    def change(self, area, operation, rule):
        self.changes.append((area, operation, rule))
        if operation == 'add':
            self.state[area].append(rule)
        else:
            self.state[area].remove(rule)
        self.state[area].sort()
        if self.fail_after == len(self.changes):
            raise RuntimeError('reply lost after successful write')


class Clock:
    boot_id = 'boot-one'
    now = 1000.0

    def monotonic(self):
        return self.now


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.exists(), 'Firewall transaction implementation is missing')
        spec = importlib.util.spec_from_file_location('firewall_transaction', MODULE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'state'
        self.firewall = Firewall()
        self.clock = Clock()
        self.active = True
        self.manager = self.module.TransactionManager(
            self.root, self.firewall, self.clock, lambda: self.active)
        self.plan = {'plan_id': 'a' * 64, 'host': 'node-a', 'ssh_port': 2222,
                     'rules': [SSH, DROP], 'required_checks': ['ssh-fresh', 'api'],
                     'rollback_timeout': 300, 'expected': self.firewall.snapshot()}

    def begin(self):
        return self.manager.begin(self.plan)

    def verify(self, txn):
        return self.manager.verify(txn['id'], txn['nonce'], ['ssh-fresh', 'api'])

    def test_runtime_then_verified_permanent_and_noop_repeat(self):
        txn = self.begin()
        self.assertEqual('ARMED', txn['state'])
        self.assertEqual([], self.firewall.changes)
        self.manager.apply_runtime(txn['id'])
        self.assertEqual(sorted([SSH, DROP]), self.firewall.state['runtime'])
        self.assertEqual([], self.firewall.state['permanent'])
        self.verify(txn)
        self.assertEqual('COMMITTED', self.manager.commit(txn['id'])['state'])
        self.assertEqual(sorted([SSH, DROP]), self.firewall.state['permanent'])
        self.plan['expected'] = self.firewall.snapshot()
        count = len(self.firewall.changes)
        self.assertFalse(self.begin()['changed'])
        self.assertEqual(count, len(self.firewall.changes))

    def test_unverified_or_incomplete_checks_cannot_persist(self):
        txn = self.begin()
        self.manager.apply_runtime(txn['id'])
        self.assertRaises(self.module.TransactionError, self.manager.commit, txn['id'])
        self.assertRaises(self.module.TransactionError, self.manager.verify,
                          txn['id'], txn['nonce'], ['ssh-fresh'])
        self.assertRaises(self.module.TransactionError, self.manager.verify,
                          txn['id'], 'stale-nonce', ['ssh-fresh', 'api'])
        self.assertEqual([], self.firewall.state['permanent'])

    def test_expiry_survives_new_helper_process_and_blocks_late_commit(self):
        txn = self.begin()
        self.manager.apply_runtime(txn['id'])
        self.verify(txn)
        self.clock.now += 301
        restored = self.module.TransactionManager(
            self.root, self.firewall, self.clock, lambda: True)
        self.assertRaises(self.module.TransactionError, restored.commit, txn['id'])
        result = restored.recover_expired()
        self.assertEqual('ROLLED_BACK', result['state'])
        self.assertEqual([], self.firewall.state['runtime'])
        self.assertEqual('unchanged', self.firewall.state['foreign'])

    def test_lost_write_reply_is_reconciled_before_rollback(self):
        txn = self.begin()
        self.firewall.fail_after = 1
        self.assertRaises(RuntimeError, self.manager.apply_runtime, txn['id'])
        self.firewall.fail_after = None
        result = self.manager.rollback(txn['id'])
        self.assertEqual('ROLLED_BACK', result['state'])
        self.assertEqual([], self.firewall.state['runtime'])

    def test_permanent_partial_failure_restores_both_snapshots(self):
        txn = self.begin()
        self.manager.apply_runtime(txn['id'])
        self.verify(txn)
        self.firewall.fail_after = len(self.firewall.changes) + 1
        self.assertRaises(RuntimeError, self.manager.commit, txn['id'])
        self.firewall.fail_after = None
        self.manager.rollback(txn['id'])
        self.assertEqual(self.plan['expected'], self.firewall.snapshot())

    def test_firewalld_reload_of_partial_permanent_still_recovers(self):
        txn = self.begin()
        self.manager.apply_runtime(txn['id'])
        self.verify(txn)
        self.firewall.fail_after = len(self.firewall.changes) + 1
        self.assertRaises(RuntimeError, self.manager.commit, txn['id'])
        self.firewall.fail_after = None
        self.firewall.state['runtime'] = self.firewall.state['permanent'][:]
        self.clock.now += 301
        self.assertEqual('ROLLED_BACK', self.manager.recover_expired()['state'])
        self.assertEqual(self.plan['expected'], self.firewall.snapshot())

    def test_no_watchdog_or_bad_plan_does_not_create_transaction(self):
        self.active = False
        self.assertRaises(self.module.TransactionError, self.begin)
        self.assertFalse(self.root.exists())
        self.active = True
        for changes in ({'ssh_port': True}, {'rules': [DROP]},
                        {'rollback_timeout': 10}, {'required_checks': []},
                        {'expected': {'runtime': [], 'permanent': [], 'foreign': 'drift'}}):
            with self.subTest(changes=changes):
                plan = dict(self.plan, **changes)
                self.assertRaises(self.module.TransactionError, self.manager.begin, plan)
        self.assertEqual([], self.firewall.changes)

    def test_active_transaction_cannot_be_replaced(self):
        txn = self.begin()
        self.assertRaises(self.module.TransactionError, self.begin)
        self.assertEqual(txn['id'], self.manager.status()['id'])

    def test_foreign_owned_rule_drift_is_not_overwritten(self):
        txn = self.begin()
        self.manager.apply_runtime(txn['id'])
        self.firewall.state['runtime'].append('foreign-owned-change')
        before = self.firewall.snapshot()
        self.assertRaises(self.module.TransactionError, self.manager.rollback, txn['id'])
        self.assertEqual(before, self.firewall.snapshot())

    def test_manual_rollback_rejects_older_transaction(self):
        txn = self.begin()
        self.manager.apply_runtime(txn['id'])
        self.verify(txn)
        self.manager.commit(txn['id'])
        self.plan['expected'] = self.firewall.snapshot()
        self.plan['rules'] = [SSH, 'rule priority="-20000" port port="443" protocol="tcp" accept', DROP]
        self.begin()
        self.assertRaises(self.module.TransactionError, self.manager.rollback, txn['id'])

    def test_checkmode_and_path_validation_never_write(self):
        self.assertRaises(self.module.TransactionError, self.manager.rollback, '../owner')
        self.assertFalse(self.root.exists())
        self.root.symlink_to(Path(self.tmp.name))
        self.assertRaises(self.module.TransactionError, self.begin)
        self.assertEqual([], self.firewall.changes)

    def test_saved_state_is_private_and_original_snapshot_immutable(self):
        txn = self.begin()
        path = self.root / 'transactions' / (txn['id'] + '.json')
        self.assertEqual(0o600, path.stat().st_mode & 0o777)
        self.assertEqual(0o700, self.root.stat().st_mode & 0o777)
        before = json.loads(path.read_text())['before']
        self.manager.apply_runtime(txn['id'])
        self.assertEqual(before, json.loads(path.read_text())['before'])
