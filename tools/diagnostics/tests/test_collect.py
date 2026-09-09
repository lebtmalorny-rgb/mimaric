"""Offline tests: no OpenStack, SSH, container or BMC access."""
import gzip
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "files" / "collect.py"
NOTIFICATION = "a1e7d8e9-cb63-4c7f-9dd1-52e0a0cea0af"


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "Diagnostic collector is not implemented")
        spec = importlib.util.spec_from_file_location("powerops_collect", SCRIPT)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.tmp = tempfile.TemporaryDirectory(prefix="powerops-diag-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.mod.validate_config({
            "since": "2026-09-07T12:25:00Z", "until": "2026-09-07T12:45:00Z",
            "notification_id": NOTIFICATION,
            "server_ids": ["85387b2a-32fe-48b2-be94-df20701d2659"],
            "compute_hosts": ["ultra1-2.ultra1.test.pvs.un.sbt"],
        })

    def test_secrets_removed_without_destroying_request_id(self):
        text = '''password="alpha beta" os_password=gamma
{"application_credential_secret": "delta", "token": "epsilon"}
X-Auth-Token: zeta
Authorization: Bearer eta
https://admin:theta@service/v1?token=iota
--os-password kappa
-----BEGIN PRIVATE KEY-----
lambda
-----END PRIVATE KEY-----
req-12345 host=ultra1-2
custom-header: mu-secret-from-env
'''
        result = self.mod.redact(text, ["mu-secret-from-env"])
        for secret in ("alpha beta", "gamma", "delta", "epsilon", "zeta", "eta",
                       "theta", "iota", "kappa", "lambda", "mu-secret-from-env"):
            self.assertNotIn(secret, result)
        self.assertIn("req-12345 host=ultra1-2", result)

    def test_nested_sensitive_structures_are_not_saved(self):
        value = {"driver_info": {"address": "private-bmc", "password": "hidden"},
                 "Env": ["SECRET=hidden"], "state": "power on",
                 "rows": [{"OS_PASSWORD": "secret-value"}]}
        result = self.mod.sanitize(value)
        self.assertEqual(result["state"], "power on")
        self.assertNotIn("private-bmc", json.dumps(result))
        self.assertNotIn("secret-value", json.dumps(result))
        self.assertNotIn("SECRET=", json.dumps(result))

    def test_prefixed_json_escaped_quoted_secret_is_masked_at_io_boundaries(self):
        line = '2026-09-07 12:33:00 ERROR ' + json.dumps({'password': 'first"SECOND_SECRET', 'request_id': 'req-123'})
        log = self.root / 'masakari-engine.log'
        log.write_text(line + '\n')
        command = self.mod.run_command([sys.executable, '-c', 'print(' + repr(line) + ')'], 2, 4096)
        logfile = self.mod.read_log(log, self.config)
        for result in (command, logfile):
            self.assertNotIn('SECOND_SECRET', result['output'])
            self.assertIn('req-123', result['output'])
        for partial in ('prefix password="first\\"SECOND_SECRET', 'prefix password="SECOND_SECRET\\'):
            self.assertNotIn('SECOND_SECRET', self.mod.redact(partial))

    def test_unreadable_log_directory_is_reported_while_other_logs_are_kept(self):
        blocked = self.root / 'masakari'
        blocked.mkdir()
        healthy = self.root / 'nova'
        healthy.mkdir()
        (healthy / 'compute.log').write_text('2026-09-07 12:33:00 INFO retained evidence\n')
        original = Path.iterdir
        def iterdir(path):
            if path == blocked:
                raise PermissionError('cannot read masakari directory')
            return original(path)
        with mock.patch.object(Path, 'iterdir', iterdir), mock.patch.object(self.mod, 'run_command',
                return_value=dict(status='ok', rc=0, output='', truncated=False)):
            report = self.mod.Collector(dict(self.config, log_root=str(self.root))).host()
        self.assertTrue(any(r['status'] == 'discovery_error' and r['path'] == str(blocked)
                            for r in report['logs']))
        self.assertTrue(any('retained evidence' in r['output'] for r in report['logs']))

    def test_timezones_normalized_and_invalid_input_rejected(self):
        cfg = self.mod.validate_config({"since": "2026-09-07T15:25:00+03:00",
                                        "until": "2026-09-07T15:45:00+03:00"})
        self.assertEqual(cfg["since"], "2026-09-07T12:25:00Z")
        for bad in ({"since": "2026-09-08T00:00:00Z", "until": "2026-09-07T00:00:00Z"},
                    {"notification_id": "-f yaml; power off"},
                    {"compute_hosts": ["--all-projects"]},
                    {"max_file_bytes": -1}, {"command_timeout": 0},
                    {"since": "2026-09-07 12:00:00"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.mod.validate_config(bad)

    def test_command_timeout_preserves_sanitized_partial_output(self):
        began = time.monotonic()
        result = self.mod.run_command(
            [sys.executable, "-c", "import time; print('password=hidden', flush=True); time.sleep(5)"],
            timeout=0.15, max_bytes=4096)
        self.assertEqual(result["status"], "timeout")
        self.assertLess(time.monotonic() - began, 2)
        self.assertNotIn("hidden", result["output"])

    def test_command_nonzero_missing_and_output_limit_are_distinct(self):
        failed = self.mod.run_command([sys.executable, "-c", "print('failure'); exit(3)"], 2, 4096)
        self.assertEqual((failed["status"], failed["rc"]), ("error", 3))
        missing = self.mod.run_command([str(self.root / "absent")], 2, 4096)
        self.assertEqual(missing["status"], "missing_command")
        large = self.mod.run_command([sys.executable, "-c", "print('x' * 1000000)"], 2, 1024)
        self.assertEqual(large["status"], "output_limit")
        self.assertTrue(large["truncated"])
        self.assertLessEqual(len(large["output"].encode()), 1200)

    def test_command_timeout_also_applies_after_stdout_is_closed(self):
        began = time.monotonic()
        result = self.mod.run_command([sys.executable, "-c",
                                       "import os,time; os.close(1); os.close(2); time.sleep(5)"], 0.15, 4096)
        self.assertEqual(result["status"], "timeout")
        self.assertLess(time.monotonic() - began, 2)

    def test_truncated_url_cannot_expose_userinfo_before_the_at_sign(self):
        raw = "https://admin:TOPSECRET123@service.example/v1"
        result = self.mod.run_command([sys.executable, "-c", "print(" + repr(raw) + ")"],
                                     2, raw.index("@"))
        self.assertEqual(result["status"], "output_limit")
        self.assertNotIn("TOPSECRET", result["output"])

    def test_escaped_json_password_is_fully_redacted_not_only_first_word(self):
        text = json.dumps({"message": 'password="TOPSECRET123 with spaces"'})
        output = self.mod.redact(text)
        self.assertNotIn("TOPSECRET123", output)
        self.assertNotIn("with spaces", output)

    def test_gzip_scan_limit_cannot_expose_cut_url_credentials(self):
        raw = "2026-09-07 12:33:00 ERROR https://admin:TOPSECRET123@service.example/v1\n"
        path = self.root / "engine.log.1.gz"
        with gzip.open(path, "wt") as stream:
            stream.write(raw)
        result = self.mod.read_log(path, dict(self.config, max_scan_bytes=raw.index("@")))
        self.assertTrue(result["scan_truncated"])
        self.assertNotIn("TOPSECRET", result["output"])

    def test_log_window_keeps_traceback_and_redacts_before_storage(self):
        data = ("2026-09-07 12:20:00 INFO old\nold continuation\n"
                "2026-09-07 12:33:00 ERROR req-12345\n"
                "Traceback (most recent call last):\n  password='hidden'\n"
                "ValueError: fence failed\n"
                "2026-09-07 12:50:00 INFO later\nlater continuation\n")
        path = self.root / "engine.log"
        path.write_text(data)
        result = self.mod.read_log(path, self.config)
        self.assertEqual(result["status"], "ok")
        self.assertIn("Traceback", result["output"])
        self.assertIn("ValueError: fence failed", result["output"])
        for absent in ("hidden", "old continuation", "later continuation"):
            self.assertNotIn(absent, result["output"])
        self.assertEqual(result["records"], 1)

    def test_gzip_rotation_and_apache_timestamps(self):
        path = self.root / "api.log.1.gz"
        with gzip.open(path, "wt") as stream:
            stream.write('client [07/Sep/2026:12:33:01 +0000] "GET /v1 HTTP/1.1" 500\n')
        result = self.mod.read_log(path, self.config)
        self.assertIn('"GET /v1 HTTP/1.1" 500', result["output"])
        self.assertEqual(result["records"], 1)

    def test_unparseable_and_truncated_logs_are_explicit(self):
        path = self.root / "engine.log"
        path.write_text("password=hidden\n" * 1000)
        config = dict(self.config, max_scan_bytes=1024, max_file_bytes=512)
        result = self.mod.read_log(path, config)
        self.assertEqual(result["status"], "unparsed_time")
        self.assertTrue(result["scan_truncated"])
        self.assertNotIn("hidden", result["output"])

    def test_log_discovery_excludes_symlinks_fifos_and_configuration(self):
        service = self.root / "masakari"
        service.mkdir()
        (service / "engine.log").write_text("log")
        (service / "passwords.yml").write_text("secret")
        (service / "leak.log").symlink_to(service / "passwords.yml")
        os.mkfifo(service / "pipe.log")
        files = self.mod.discover_logs(str(self.root), 20)
        self.assertEqual([p.name for p in files], ["engine.log"])
        rejected = self.mod.read_log(service / "leak.log", self.config)
        self.assertEqual(rejected["status"], "read_error")

    def test_api_plan_only_requests_selected_read_resources(self):
        jobs = self.mod.api_jobs(self.config)
        commands = [argv for _, argv in jobs]
        self.assertIn(["openstack", "notification", "show",
                       NOTIFICATION, "-f", "json"], commands)
        for command in commands:
            self.assertNotIn("--debug", command)
            self.assertFalse(set(command) & {"create", "delete", "set", "update",
                                             "evacuate", "stop", "start", "token"})
        server_show = next(c for c in commands if c[1:3] == ["server", "show"])
        self.assertIn("OS-EXT-SRV-ATTR:host", server_show)
        self.assertNotIn("driver_info", server_show)

    def test_ironic_limits_api_request_fields_not_only_output_columns(self):
        config = dict(self.config, node_id="edebd181-6865-4134-8657-0e318efd4336")
        command = next(argv for name, argv in self.mod.api_jobs(config) if name == "ironic_node")
        self.assertIn("--fields", command, "-c alone still requests the full node including driver_info")
        fields = command[command.index("--fields") + 1:command.index("-f")]
        self.assertEqual(set(fields), {"uuid", "name", "power_state", "target_power_state", "last_error",
                                       "provision_state", "network_interface", "maintenance"})

    def test_budget_exhaustion_records_skips_and_does_not_run_command(self):
        collector = self.mod.Collector(dict(self.config, total_timeout=0.01))
        time.sleep(0.02)
        result = collector.command("should-not-run", [sys.executable, "-c", "exit(99)"])
        self.assertEqual(result["status"], "skipped_budget")
        self.assertIsNone(result["rc"])

    def test_openstack_timeout_is_enforced_by_process_not_unsupported_cli_option(self):
        seen = []
        def external_process(argv, timeout, *args):
            seen.append((argv, timeout))
            return dict(status='ok', rc=0, output='[]', truncated=False)
        with mock.patch.object(self.mod, 'run_command', external_process):
            self.mod.Collector(dict(self.config, api_timeout=7)).api()
        for argv, timeout in seen:
            self.assertNotIn('--os-api-timeout', argv)
            self.assertLessEqual(timeout, 7)

    def test_policy_denial_retains_rule_but_auth_headers_remain_redacted(self):
        text = ('ERROR ironic.common.policy Rejecting authorization: baremetal:node:list_all is disallowed by policy\n'
                'Authorization: Bearer private-token\n'
                'headers: {"authorization": "Bearer other-token"}\n')
        actual = self.mod.redact(text)
        self.assertIn('baremetal:node:list_all is disallowed by policy', actual)
        self.assertNotIn('private-token', actual)
        self.assertNotIn('other-token', actual)

    def test_rejected_authorization_values_are_not_mistaken_for_policy_diagnostics(self):
        for value in ('Bearer RAW_ACCESS_VALUE_123', 'Basic YWRtaW46cGFzc3dvcmQ=',
                      'unexpected-private-value',
                      'baremetal:node:list_all is disallowed by policy Bearer RAW_ACCESS_VALUE_123'):
            with self.subTest(value=value):
                actual = self.mod.redact('WARNING Rejecting Authorization: ' + value)
                self.assertNotIn(value, actual)
                self.assertIn('[REDACTED]', actual)

    def test_vmove_details_are_collected_for_cli_uuid_column_variants(self):
        identifier = "de084e2d-2324-48a5-8fde-31a2b7aa1bab"
        for column in ("uuid", "UUID", "ID", "vmove_uuid"):
            def external_cli(argv, *args):
                output = "[]"
                if argv[1:4] == ["notification", "vmove", "list"]:
                    output = json.dumps([{column: identifier, "status": "failed"}])
                if argv[1:4] == ["notification", "vmove", "show"]:
                    self.assertEqual(argv[4:6], [NOTIFICATION, identifier])
                    output = json.dumps({"uuid": identifier, "status": "failed", "message": "NoValidHost"})
                return dict(status="ok", rc=0, output=output, truncated=False)
            with self.subTest(column=column), mock.patch.object(self.mod, "run_command", external_cli):
                report = self.mod.Collector(self.config).api()
                details = [row for row in report["checks"] if row["name"] == "vmove_" + identifier]
                self.assertEqual(len(details), 1, "VMove details were silently lost")
                self.assertIn("NoValidHost", details[0]["output"])

    def test_host_discovers_only_scoped_containers_and_reads_safe_inspect_fields(self):
        service = self.root / "masakari"
        service.mkdir()
        (service / "engine.log").write_text("2026-09-07 12:33:00 INFO event\n")
        seen = []

        def external_command(argv, *args):
            seen.append(argv)
            output = ""
            if argv[:2] == ["podman", "ps"]:
                output = "masakari_engine\tregistry/masakari:0509\tUp\nconsul_management\tconsul:1\tUp\nunrelated\timage\tUp\n"
            elif argv[:2] == ["podman", "inspect"]:
                self.assertIn("--format", argv)
                self.assertNotIn(".Config", " ".join(argv))
                self.assertNotIn(".Env", " ".join(argv))
                output = "id sha256:example image running true 0 timestamp"
            elif argv[:2] == ["podman", "logs"]:
                self.assertIn("--since", argv)
                self.assertIn("--until", argv)
                output = "2026-09-07T12:33:00Z ERROR password=hidden"
            return dict(status="ok", rc=0, output=output, truncated=False)

        with mock.patch.object(self.mod, "run_command", external_command):
            report = self.mod.Collector(dict(self.config, log_root=str(self.root))).host()
        self.assertEqual([a[-1] for a in seen if a[:2] == ["podman", "inspect"]],
                         ["masakari_engine", "consul_management"])
        self.assertEqual([a[1] for a in seen if a[0] == "podman"],
                         ["--version", "ps", "inspect", "inspect", "logs", "logs"])
        self.assertNotIn("hidden", json.dumps(report))
        self.assertIn("2026-09-07 12:33:00 INFO event", report["logs"][0]["output"])

    def test_container_and_journal_line_caps_mark_potential_truncation(self):
        def external_command(argv, *args):
            output = ""
            if argv[:2] == ["podman", "ps"]:
                output = "masakari_engine\timage\tUp\n"
            elif argv[:2] == ["podman", "logs"]:
                output = "entry\n" * 3
            elif argv[0] == "journalctl":
                output = "entry\n" * 500
            return dict(status="ok", rc=0, output=output, truncated=False)
        with mock.patch.object(self.mod, "run_command", external_command):
            report = self.mod.Collector(dict(self.config, log_root=str(self.root), container_log_lines=3)).host()
        for name in ("clock_journal", "container_log_masakari_engine"):
            check = next(row for row in report["checks"] if row["name"] == name)
            self.assertTrue(check["truncated"], name + " hit its line cap but was reported complete")

    def test_text_report_includes_unreachable_missing_and_errors_with_private_permissions(self):
        run = self.root / "run"
        run.mkdir(mode=0o700)
        (run / "api.json").write_text(json.dumps({"transport": {"rc": 0}, "report": {
            "checks": [{"name": "notification", "status": "error", "output": "password=hidden"}],
            "logs": []}}))
        (run / "ultra1-6.json").write_text(json.dumps({"transport": {"rc": 0},
                                                      "report": {"checks": [], "logs": []}}))
        (run / "ultra1-2.json").write_text(json.dumps({"transport": {"unreachable": True}, "report": {}}))
        self.assertTrue(hasattr(self.mod, "write_report"), "A single plain-text report is not implemented")
        result = self.mod.write_report(run, ["ultra1-6", "ultra1-2", "ultra1-3"])
        self.assertEqual(result["status"], "PARTIAL")
        report = Path(result["report"])
        self.assertEqual(report.suffix, ".txt")
        self.assertEqual(stat.S_IMODE(report.stat().st_mode), 0o600)
        text = report.read_text()
        self.assertIn("ultra1-2: UNREACHABLE", text)
        self.assertIn("ultra1-3: MISSING", text)
        self.assertIn("notification: error", text)
        self.assertNotIn("hidden", text)
        self.assertEqual(list(self.root.glob("*.gz")), [])
        with self.assertRaises(FileExistsError):
            self.mod.write_report(run, ["ultra1-6"])

    def test_text_report_parses_json_before_redacting_and_keeps_real_newlines(self):
        run = self.root / "run"
        run.mkdir()
        report = {"checks": [{"name": "error", "status": "error",
                              "output": 'password="[REDACTED]"\nTraceback: useful evidence'}], "logs": []}
        (run / "api.json").write_text(json.dumps({"transport": {"rc": 0}, "report": json.dumps(report)}))
        self.assertTrue(hasattr(self.mod, "write_report"), "A single plain-text report is not implemented")
        result = self.mod.write_report(run, [])
        text = Path(result["report"]).read_text()
        self.assertIn('\nTraceback: useful evidence', text)

    def test_malformed_collector_output_is_preserved_and_marked_not_silently_dropped(self):
        run = self.root / "run"
        run.mkdir()
        (run / "api.json").write_text(json.dumps({"transport": {"rc": 0},
                                                   "report": "shell banner\nTraceback: diagnostic failed password=hidden"}))
        result = self.mod.write_report(run, [])
        text = Path(result["report"]).read_text()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertIn("api: COLLECTOR_ERROR", text)
        self.assertIn("Traceback: diagnostic failed", text)
        self.assertNotIn("hidden", text)


if __name__ == "__main__":
    unittest.main()
