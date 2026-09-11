import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import link_fault as cli
except ImportError:
    cli = None


class CliTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(cli, "operator CLI is missing")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.args = ["--host", "operator@compute-1", "--interface", "ens3",
                     "--run-id", "nic-001", "--state-dir", self.tmp.name + "/runs"]

    def invoke(self, args, transport=None):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(args, transport=transport)
        return code, json.loads(output.getvalue())

    def test_plan_and_unarmed_start_never_access_host(self):
        def forbidden(*args):
            raise AssertionError("plan tried SSH")
        for action in ("plan", "start"):
            code, result = self.invoke([action] + self.args, forbidden)
            self.assertEqual(code, 0)
            self.assertEqual(result["request"]["fault"]["duration"], 300)
            self.assertEqual(result["phase"], "PLAN")
        self.assertFalse((Path(self.tmp.name) / "runs").exists())

    def test_changed_target_for_existing_run_is_rejected_before_ssh(self):
        calls = []
        def transport(args, request):
            calls.append(request)
            return {"phase": "DOWN", "result": "INCOMPLETE"}
        self.invoke(["start"] + self.args + ["--execute"], transport)
        changed = ["start"] + self.args + ["--host", "compute-2", "--execute"]
        code, result = self.invoke(changed, transport)
        self.assertEqual(code, 2)
        self.assertIn("different", result["error"])
        self.assertEqual(len(calls), 1)

    def test_unknown_ssh_outcome_is_journalled_without_retry(self):
        calls = []
        def timeout(args, request):
            calls.append(request)
            raise subprocess.TimeoutExpired("ssh", 25)
        code, result = self.invoke(["start"] + self.args + ["--execute"], timeout)
        self.assertEqual(code, 3)
        self.assertEqual(result["phase"], "UNKNOWN")
        self.assertEqual(len(calls), 1)
        saved = json.loads((Path(self.tmp.name) / "runs/nic-001/result.json").read_text())
        self.assertEqual(saved["phase"], "UNKNOWN")

    def test_stand_runner_nonce_is_forwarded_and_pinned_for_status(self):
        calls = []
        def transport(args, request):
            calls.append(request)
            return {'phase':'RESTORED','result':'COMPLETED'}
        self.invoke(['status'] + self.args + ['--intent-nonce', 'a' * 32], transport)
        code, result = self.invoke(['status'] + self.args + ['--intent-nonce', 'b' * 32], transport)
        self.assertEqual('a' * 32, calls[0]['fault']['nonce'])
        self.assertEqual(1,len(calls)); self.assertEqual(2,code)

    def test_shell_and_option_inputs_are_rejected(self):
        for field, value in [("--host", "host;touch /tmp/pwn"), ("--host", "-oProxyCommand=x"),
                             ("--interface", "ens3;id"), ("--run-id", "../escape"),
                             ("--duration", "0"), ("--duration", "3601")]:
            with self.subTest(field=field, value=value), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    self.invoke(["plan"] + self.args + [f"{field}={value}"])

    def test_transport_sends_source_over_stdin_without_shell(self):
        args = cli.parser().parse_args(["start"] + self.args + ["--execute"])
        request = {"action": "start", "fault": {"run_id": "nic-001", "interface": "ens3", "duration": 300}}
        response = subprocess.CompletedProcess([], 0, '{"phase":"SUBMITTING","result":"INCOMPLETE"}', "")
        with patch("link_fault.subprocess.run", return_value=response) as run:
            result = cli.call_remote(args, request)
        argv = run.call_args.args[0]
        kw = run.call_args.kwargs
        self.assertEqual(argv[0], "ssh")
        self.assertIn("BatchMode=yes", argv)
        self.assertIn("StrictHostKeyChecking=yes", argv)
        self.assertIn("operator@compute-1", argv)
        self.assertFalse(kw.get("shell", False))
        envelope = json.loads(kw["input"])
        self.assertEqual(envelope["request"], request)
        self.assertIn("def dispatch(", envelope["source"])
        self.assertEqual(result["phase"], "SUBMITTING")


if __name__ == "__main__":
    unittest.main()
