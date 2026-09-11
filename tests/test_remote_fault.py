"""Exercise the real journal; replace only Linux/systemd and the clock."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import remote_fault as rf
except ImportError:
    rf = None


class FakeSystem:
    def __init__(self):
        self.now = 10.0
        self.boot = "boot-a"
        self.device = {"ifname": "ens3", "ifindex": 4,
                       "address": "52:54:00:12:34:56", "flags": ["UP", "LOWER_UP"]}
        self.changes = []
        self.launches = []
        self.launch_error = False
        self.after_sleep = None
        self.down_error = False

    def link(self, interface):
        if interface != self.device["ifname"]:
            raise ValueError("no such device")
        return copy.deepcopy(self.device)

    def set_link(self, interface, up):
        self.changes.append((interface, up))
        self.device["flags"] = ["UP", "LOWER_UP"] if up else []
        if not up and self.down_error:
            raise TimeoutError("netlink reply lost after DOWN")

    def boot_id(self):
        return self.boot

    def clock(self):
        return self.now

    def wall(self):
        return 1700000000.0 + self.now

    def sleep(self, seconds):
        self.now += seconds
        if self.after_sleep:
            self.after_sleep()

    def launch(self, script, run_id, duration):
        self.launches.append((script, run_id, duration))
        # Intent must already be durable before the process is submitted.
        state = json.loads(script.with_name("state.json").read_text())
        if state["phase"] != "SUBMITTING":
            raise AssertionError("missing durable intent")
        if self.launch_error:
            raise TimeoutError("systemd reply lost")


class FaultTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(rf, "remote fault implementation is missing")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "private"
        self.system = FakeSystem()
        self.req = {"run_id": "nic-001", "interface": "ens3", "duration": 300}

    def start(self, **changes):
        return rf.start(self.req | changes, "# worker fixture\n", self.root, self.system)

    def test_repeat_never_resubmits_or_changes_deadline(self):
        self.start()
        result = rf.work("nic-001", self.root, self.system)
        self.assertEqual(result["result"], "COMPLETED")
        self.assertEqual(self.system.changes, [("ens3", False), ("ens3", True)])
        again = self.start()
        self.assertEqual(again["deadline"], result["deadline"])
        self.assertEqual(len(self.system.launches), 1)
        self.assertEqual(self.system.now, 310.0)

    def test_changed_arguments_are_rejected_for_existing_id(self):
        self.start()
        with self.assertRaises(ValueError):
            self.start(duration=301)
        self.assertEqual(len(self.system.launches), 1)

    def test_durable_nonce_prevents_reusing_an_older_same_boot_fault(self):
        self.start(nonce='a' * 32)
        rf.work('nic-001', self.root, self.system)
        with self.assertRaises(ValueError): self.start(nonce='b' * 32)
        self.assertEqual(1, len(self.system.launches))
        self.assertEqual('a' * 32, rf.read_state(self.root,'nic-001')['request']['nonce'])

    def test_initial_down_is_never_raised_or_scheduled(self):
        self.system.device["flags"] = []
        with self.assertRaises(ValueError):
            self.start()
        self.assertEqual(self.system.changes, [])
        self.assertEqual(self.system.launches, [])

    def test_other_run_cannot_claim_active_interface(self):
        self.start()
        with self.assertRaises(ValueError):
            self.start(run_id="nic-002")
        self.assertEqual(len(self.system.launches), 1)

    def test_another_interface_cannot_start_a_parallel_fault_on_same_host(self):
        self.start()
        with self.assertRaisesRegex(ValueError, "host.*run"):
            self.start(run_id="nic-002", interface="ens4")
        self.assertEqual(len(self.system.launches), 1)

    def test_lost_scheduler_reply_is_never_retried(self):
        self.system.launch_error = True
        result = self.start()
        self.assertIn("submit_error", result)
        self.start()
        self.assertEqual(len(self.system.launches), 1)
        self.assertEqual(self.system.changes, [])

    def test_restore_before_worker_prevents_late_down(self):
        self.start()
        restored = rf.restore("nic-001", self.root, self.system, "operator")
        self.assertEqual(restored["result"], "NOT_APPLIED")
        rf.work("nic-001", self.root, self.system)
        self.assertEqual(self.system.changes, [])

    def test_down_timeout_still_restores_without_second_down(self):
        self.start()
        self.system.down_error = True
        result = rf.work("nic-001", self.root, self.system)
        self.assertEqual(result["phase"], "RESTORED")
        self.assertEqual(result["result"], "INTERRUPTED")
        self.assertEqual(self.system.changes, [("ens3", False), ("ens3", True)])

    def test_early_external_up_is_not_a_successful_five_minute_fault(self):
        self.start()
        self.system.after_sleep = lambda: self.system.device.update(flags=["UP"])
        result = rf.work("nic-001", self.root, self.system)
        self.assertEqual(result["result"], "INTERRUPTED")
        self.assertLess(result["observed_seconds"], 300)
        self.assertEqual(self.system.changes, [("ens3", False)])

    def test_changed_boot_never_mutates_new_boot_network(self):
        self.start()
        self.system.after_sleep = lambda: setattr(self.system, "boot", "boot-b")
        result = rf.work("nic-001", self.root, self.system)
        self.assertEqual(result["phase"], "NEEDS_OPERATOR")
        self.assertEqual(self.system.changes, [("ens3", False)])

    def test_reconcile_new_boot_only_closes_journal_without_link_mutation(self):
        self.start()
        self.system.after_sleep = lambda: setattr(self.system, 'boot', 'boot-b')
        rf.work('nic-001', self.root, self.system)
        self.system.device['flags'] = ['UP']
        self.system.device['ifindex'] = 10
        result = rf.reconcile('nic-001', self.root, self.system)
        self.assertEqual(result['phase'], 'RESTORED')
        self.assertEqual(result['result'], 'INTERRUPTED_BY_REBOOT')
        self.assertEqual(result['identity']['boot_id'], 'boot-a')
        self.assertEqual(self.system.changes, [('ens3',False)])
        self.assertNotIn('observation_error', rf.status('nic-001', self.root, self.system))
        self.assertNotIn('observation_error', rf.reconcile('nic-001', self.root, self.system))

    def test_reconcile_refuses_new_mac_or_down(self):
        self.start(); self.system.boot = 'boot-b'
        self.system.device['address'] = 'other'
        with self.assertRaises(ValueError): rf.reconcile('nic-001', self.root, self.system)
        self.system.device['address'] = '52:54:00:12:34:56'
        self.system.device['flags'] = []
        with self.assertRaises(ValueError): rf.reconcile('nic-001', self.root, self.system)
        self.assertEqual(self.system.changes, [])

    def test_replaced_interface_is_not_touched(self):
        self.start()
        self.system.device["ifindex"] = 7
        result = rf.work("nic-001", self.root, self.system)
        self.assertEqual(result["phase"], "NEEDS_OPERATOR")
        self.assertEqual(self.system.changes, [])

    def test_repeat_restore_does_not_raise_interface_twice(self):
        self.start()
        rf.work("nic-001", self.root, self.system)
        rf.restore("nic-001", self.root, self.system, "operator")
        self.assertEqual(self.system.changes, [("ens3", False), ("ens3", True)])

    def test_five_minutes_are_measured_after_down_confirmation(self):
        self.start()
        original_set = self.system.set_link
        def slow_set(interface, up):
            original_set(interface, up)
            if not up:
                self.system.now += 2
        self.system.set_link = slow_set
        result = rf.work("nic-001", self.root, self.system)
        self.assertEqual(self.system.now, 312.0)
        self.assertEqual(result["observed_seconds"], 300.0)

    def test_failed_restore_journal_write_does_not_prevent_network_restore(self):
        self.start()
        actual_save = rf.save
        def fail_restore_write(root, state):
            if state["phase"] == "RESTORING":
                raise OSError("disk full")
            actual_save(root, state)
        with patch("remote_fault.save", side_effect=fail_restore_write):
            result = rf.work("nic-001", self.root, self.system)
        self.assertEqual(self.system.changes, [("ens3", False), ("ens3", True)])
        self.assertEqual(result["phase"], "RESTORED")

    def test_status_does_not_report_success_if_restored_link_drifted_down(self):
        self.start()
        rf.work("nic-001", self.root, self.system)
        self.system.device["flags"] = []
        result = rf.status("nic-001", self.root, self.system)
        self.assertIn("observation_error", result)

    def test_repeat_start_and_restore_recheck_without_overwriting_new_down(self):
        self.start()
        rf.work("nic-001", self.root, self.system)
        self.system.device["flags"] = []
        self.assertIn("observation_error", self.start())
        self.assertIn("observation_error", rf.restore("nic-001", self.root, self.system))
        self.assertEqual(self.system.changes, [("ens3", False), ("ens3", True)])

    def test_persistent_journal_write_failure_still_restores(self):
        self.start()
        actual_save = rf.save
        def broken_disk(root, state):
            if self.system.changes:
                raise OSError("read-only filesystem")
            actual_save(root, state)
        with patch("remote_fault.save", side_effect=broken_disk):
            result = rf.work("nic-001", self.root, self.system)
        self.assertEqual(self.system.changes, [("ens3", False), ("ens3", True)])
        self.assertEqual(result["result"], "INCOMPLETE")

    def test_systemd_recovery_retries_transient_up_failure(self):
        self.start()
        original_set = self.system.set_link
        def crash_after_down(interface, up):
            original_set(interface, up)
            if not up:
                raise SystemExit("worker killed")
        self.system.set_link = crash_after_down
        with self.assertRaises(SystemExit):
            rf.work("nic-001", self.root, self.system)
        tries = []
        def flaky_restore(interface, up):
            tries.append(up)
            if len(tries) == 1:
                raise OSError("temporary netlink error")
            original_set(interface, up)
        self.system.set_link = flaky_restore
        result = rf.recover("nic-001", self.root, self.system)
        self.assertEqual(result["phase"], "RESTORED")
        self.assertEqual(tries, [True, True])

    def test_lock_acquisition_has_a_deadline(self):
        with patch("remote_fault.fcntl.flock", side_effect=BlockingIOError), \
                patch("remote_fault.time.monotonic", side_effect=[10, 10, 21]), \
                patch("remote_fault.time.sleep"):
            with self.assertRaises(TimeoutError):
                with rf.locked(self.root):
                    self.fail("entered an unavailable lock")

    def test_systemd_registers_restoration_with_worker(self):
        commands = []
        with patch("remote_fault.subprocess.run", side_effect=lambda argv, **kw: commands.append(argv)), \
                patch("remote_fault.shutil.which", side_effect=lambda name: "/usr/bin/" + name):
            rf.LinuxSystem().launch(Path("/var/lib/powerops-link-test/nic-001/worker.py"), "nic-001", 300)
        self.assertEqual(len(commands), 1)
        argv = commands[0]
        self.assertIn("--property=RuntimeMaxSec=360", argv)
        self.assertIn("--property=TimeoutStopSec=150", argv)
        cleanup = [x for x in argv if x.startswith("--property=ExecStopPost=")]
        self.assertEqual(len(cleanup), 1)
        self.assertIn("_restore nic-001", cleanup[0])
        self.assertEqual(argv[-2:], ["_work", "nic-001"])
        self.assertNotIn("--scope", argv)


if __name__ == "__main__":
    unittest.main()
