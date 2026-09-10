"""Use real bounded child processes; never call the machine's firewall tools."""
import importlib.util
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'ansible/module_utils/powerops_firewall_probe.py'


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.exists(), 'Read-only probe is not implemented')
        spec = importlib.util.spec_from_file_location('fw_probe', MODULE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def run_code(self, code, **limits):
        return self.module.run_readonly([sys.executable, '-c', code], **limits)

    def test_captures_success_and_failure_separately(self):
        result = self.run_code('import sys; print("observed"); print("denied", file=sys.stderr); sys.exit(4)')
        self.assertEqual(4, result['rc'])
        self.assertEqual('observed\n', result['stdout'])
        self.assertEqual('denied\n', result['stderr'])
        self.assertTrue(result['available'])
        self.assertFalse(result['timed_out'])
        self.assertFalse(result['truncated'])

    def test_missing_program_is_not_an_empty_success(self):
        result = self.module.run_readonly(['/nonexistent-powerops-fixture/binary'])
        self.assertFalse(result['available'])
        self.assertNotEqual(0, result['rc'])

    def test_output_is_bounded_and_overflow_is_explicit(self):
        result = self.run_code('import os; os.write(1, b"a" * 1000000)', max_bytes=128)
        self.assertTrue(result['truncated'])
        self.assertEqual('a' * 128, result['stdout'])

    def test_stderr_is_bounded_too(self):
        result = self.run_code('import os; os.write(2, b"b" * 1000000)', max_bytes=128)
        self.assertTrue(result['truncated'])
        self.assertEqual(128, len(result['stderr'].encode()))

    def test_utf8_boundary_stays_within_byte_limit(self):
        result = self.run_code('import os; os.write(1, "ж".encode() * 1000)', max_bytes=127)
        self.assertTrue(result['truncated'])
        self.assertLessEqual(len(result['stdout'].encode()), 127)

    def test_timeout_terminates_only_owned_process_group(self):
        start = time.monotonic()
        result = self.run_code('import os,time; print(os.getpid(), flush=True); time.sleep(30)', timeout=1)
        self.assertTrue(result['timed_out'])
        self.assertLess(time.monotonic() - start, 4)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(result['stdout'].strip()), 0)

    def test_child_inheriting_pipes_cannot_hold_runner_forever(self):
        start = time.monotonic()
        result = self.run_code('import os,time; child=os.fork(); time.sleep(30) if child == 0 else None', timeout=1)
        self.assertTrue(result['timed_out'])
        self.assertLess(time.monotonic() - start, 4)

    def test_invalid_limits_do_not_start_subprocess(self):
        for limits in ({'timeout': 0}, {'timeout': 121}, {'max_bytes': 0},
                       {'max_bytes': 4194305}, {'timeout': True}):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                self.run_code('raise SystemExit("should not run")', **limits)

    def test_snapshot_dispatches_only_known_read_only_commands(self):
        calls = []

        def runner(argv, **kwargs):
            calls.append(argv)
            return {'argv': argv, 'rc': 0, 'stdout': '', 'stderr': '',
                    'available': True, 'truncated': False, 'timed_out': False}

        with patch.object(self.module, 'run_readonly', side_effect=runner):
            result = self.module.collect_snapshot(timeout=3, max_bytes=512)
        self.assertIn(['ip', '-j', 'address', 'show'], calls)
        self.assertIn(['nft', '-j', 'list', 'ruleset'], calls)
        self.assertIn(['firewall-cmd', '--permanent', '--list-all-zones'], calls)
        self.assertIn(['firewall-cmd', '--list-all-policies'], calls)
        allowed = {
            ('ip', '-j', 'address', 'show'), ('ip', '-j', '-4', 'route', 'show', 'table', 'all'),
            ('ip', '-j', '-6', 'route', 'show', 'table', 'all'), ('ss', '-H', '-lntu'),
            ('nft', '-j', 'list', 'ruleset'), ('iptables-save',), ('ip6tables-save',),
            ('firewall-cmd', '--state'), ('firewall-cmd', '--get-active-zones'),
            ('firewall-cmd', '--list-all-zones'), ('firewall-cmd', '--permanent', '--list-all-zones'),
            ('firewall-cmd', '--list-all-policies'), ('firewall-cmd', '--permanent', '--list-all-policies'),
            ('systemctl', 'show', 'firewalld.service', 'nftables.service', '--property=Id,ActiveState,SubState,UnitFileState'),
            ('sysctl', 'net.bridge.bridge-nf-call-iptables', 'net.bridge.bridge-nf-call-ip6tables'),
        }
        self.assertEqual(allowed, {tuple(argv) for argv in calls})
        self.assertEqual(len(calls), len(result['commands']))
        self.assertIn('timestamp', result)


if __name__ == '__main__':
    unittest.main()
