"""Local Ansible integration, including a deliberately unreachable SSH target.

Run explicitly with POWEROPS_RUN_ANSIBLE_TEST=1. No stand addresses are used.
OpenStack is replaced at its executable boundary, not by mocking the collector.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PlaybookTests(unittest.TestCase):
    def test_embedded_collector_matches_unit_tested_source(self):
        playbook = (ROOT / 'collect-v2.yml').read_text()
        embedded = playbook.split('      {% raw %}\n', 1)[1].split('      {% endraw %}', 1)[0]
        source = '\n'.join(line[6:] for line in embedded.splitlines()).rstrip()
        self.assertEqual(source, (ROOT / 'files' / 'collect.py').read_text().rstrip())

    @unittest.skipUnless(os.environ.get("POWEROPS_RUN_ANSIBLE_TEST") == "1", "explicit local Ansible test")
    def test_real_playbook_keeps_healthy_host_after_unreachable_and_api_error(self):
        self._run_playbook(use_inventory=True)

    @unittest.skipUnless(os.environ.get("POWEROPS_RUN_ANSIBLE_TEST") == "1", "explicit local Ansible test")
    def test_auth_failure_preserves_host_logs_and_both_api_snapshots(self):
        self._run_playbook(use_inventory=True, auth_failure=True)

    @unittest.skipUnless(os.environ.get("POWEROPS_RUN_ANSIBLE_TEST") == "1", "explicit local Ansible test")
    def test_reserved_snapshot_name_is_rejected_before_artifact_creation(self):
        self._run_playbook(use_inventory=False, reserved_target=True)

    @unittest.skipUnless(os.environ.get("POWEROPS_RUN_ANSIBLE_TEST") == "1", "explicit local Ansible test")
    def test_single_file_builds_inventory_and_writes_text_without_external_inventory(self):
        self._run_playbook(use_inventory=False)

    @unittest.skipUnless(os.environ.get("POWEROPS_RUN_ANSIBLE_TEST") == "1", "explicit local Ansible test")
    def test_identity_mismatch_skips_remote_log_collection_and_reports_reason(self):
        self._run_playbook(use_inventory=True, wrong_identity=True)

    @unittest.skipUnless(os.environ.get("POWEROPS_RUN_ANSIBLE_TEST") == "1", "explicit local Ansible test")
    def test_default_fqdns_connect_through_inventory_ips_with_key_checking(self):
        self._run_playbook(use_inventory=False, default_aliases=True)

    def _run_playbook(self, use_inventory, wrong_identity=False, default_aliases=False,
                      auth_failure=False, reserved_target=False):
        self.assertTrue((ROOT / "collect-v2.yml").is_file(), "Diagnostic playbook is not implemented")
        ansible = shutil.which("ansible-playbook")
        self.assertIsNotNone(ansible)
        # macOS's default TMPDIR can exceed OpenSSH's 104-byte ControlPath limit.
        with tempfile.TemporaryDirectory(prefix="powerops-at-", dir='/private/tmp') as temp:
            temp = Path(temp)
            binaries = temp / "bin"
            binaries.mkdir()
            fake = binaries / "openstack"
            fake.write_text("#!" + sys.executable + "\n" +
                            "import json,sys\n"
                            "args=sys.argv[1:]\n"
                            "if '--version' in args: print('openstack 8.1 test'); sys.exit(0)\n"
                            + ("print('Missing value auth-url required for auth plugin password'); sys.exit(1)\n"
                               if auth_failure else "") +
                            "if 'list' in args: print('[]'); sys.exit(0)\n"
                            "print('test API failure password=DO_NOT_PUBLISH_123'); sys.exit(1)\n")
            fake.chmod(0o700)
            hostname = binaries / 'hostname'
            hostname.write_text('#!' + sys.executable + '\nprint(' +
                                repr('wrong.example' if wrong_identity else 'healthy.example') + ')\n')
            hostname.chmod(0o700)
            ssh_calls = temp / 'ssh-calls.jsonl'
            if default_aliases:
                ssh = binaries / 'ssh'
                ssh.write_text('#!' + sys.executable + '\nimport json,sys\n' +
                               'with open(' + repr(str(ssh_calls)) + ', "a") as f: f.write(json.dumps(sys.argv[1:]) + "\\n")\n' +
                               'print("Host key verification failed.", file=sys.stderr)\nsys.exit(255)\n')
                ssh.chmod(0o700)
            logs = temp / "logs" / "masakari"
            logs.mkdir(parents=True)
            (logs / "masakari-engine.log").write_text(
                "2026-09-07 12:33:00 ERROR notification a1e7d8e9-cb63-4c7f-9dd1-52e0a0cea0af\n"
                "Traceback (most recent call last):\n  password=DO_NOT_PUBLISH_123\n"
                "ValueError: example failure\n")
            inventory = temp / "inventory.yml"
            inventory.write_text(json.dumps({"all": {"children": {"powerops_diag": {"hosts": {
                "healthy.example": {"ansible_connection": "local", "ansible_python_interpreter": sys.executable,
                                    "diag_become": False},
                "unreachable.example": {"ansible_connection": "ssh", "ansible_host": "127.0.0.1",
                                        "ansible_port": 1, "ansible_ssh_retries": 0,
                                        "ansible_ssh_common_args": "-o BatchMode=yes -o ConnectTimeout=1"}
            }}}}}))
            settings = temp / "settings.json"
            settings.write_text(json.dumps({"diag_python": sys.executable, "diag_output_parent": str(temp / "out"),
                                            "diag": {"since": "2026-09-07T12:25:00Z",
                                                     "until": "2026-09-07T12:45:00Z",
                                                     "notification_id": "a1e7d8e9-cb63-4c7f-9dd1-52e0a0cea0af",
                                                     "log_root": str(temp / "logs"), "total_timeout": 20,
                                                     "command_timeout": 2}}))
            if not use_inventory and not default_aliases:
                override = json.loads(settings.read_text())
                override.update(diag_hosts=['api_after' if reserved_target else '127.0.0.1'], diag_ssh_port=1)
                settings.write_text(json.dumps(override))
            standalone = temp / "powerops-diagnostics.yml"
            standalone.write_text((ROOT / "collect-v2.yml").read_text())
            env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                       ANSIBLE_LOCAL_TEMP=str(temp / "ansible-local"),
                       ANSIBLE_REMOTE_TEMP=str(temp / "ansible-remote"),
                       ANSIBLE_SSH_CONTROL_PATH_DIR=str(temp / "ssh-control"), ANSIBLE_NOCOLOR="1")
            if default_aliases:
                env['ANSIBLE_SSH_EXECUTABLE'] = str(binaries / 'ssh')
            # Never let the smoke test consume the developer's actual cloud credentials.
            for key in list(env):
                if key.startswith("OS_"):
                    del env[key]
            inventory_args = ['-i', str(inventory)] if use_inventory else []
            result = subprocess.run([ansible] + inventory_args + [str(standalone),
                                     "-e", "@" + str(settings)], env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=90)
            if reserved_target:
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertFalse((temp / 'out').exists(), result.stdout)
                return
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertNotIn("DO_NOT_PUBLISH_123", result.stdout)
            reports = list((temp / "out").glob("*.txt"))
            self.assertEqual(len(reports), 1, result.stdout)
            text = reports[0].read_text()
            if default_aliases:
                calls = [json.loads(line) for line in ssh_calls.read_text().splitlines()]
                addresses = {'ultra1-2': '10.101.25.146', 'ultra1-3': '10.101.25.147',
                             'ultra1-6': '10.101.25.150', 'ultra1-7': '10.101.25.151',
                             'ultra1-8': '10.101.25.152'}
                for short, address in addresses.items():
                    self.assertTrue(any(address in call for call in calls), calls)
                    self.assertFalse(any(short in call for call in calls), calls)
                    self.assertFalse(any(short + '.ultra1.test.pvs.un.sbt' in call for call in calls), calls)
                    self.assertIn(short + '.ultra1.test.pvs.un.sbt: UNREACHABLE', text)
                self.assertNotIn('StrictHostKeyChecking=no', json.dumps(calls))
                self.assertNotIn('UserKnownHostsFile=/dev/null', json.dumps(calls))
                self.assertIn('Host key verification failed.', text)
            else:
                unreachable = 'unreachable.example' if use_inventory else '127.0.0.1'
                self.assertIn(unreachable + ': UNREACHABLE', text)
                self.assertIn('ssh: connect to host 127.0.0.1 port 1:', text)
            self.assertNotIn('<error censored due to no log>', text)
            if auth_failure:
                self.assertIn('api_preflight: error [auth_config]', text)
                self.assertIn('Remaining API reads skipped', text)
            else:
                self.assertIn("notification: error", text)
            self.assertIn('HOST: api / PARTIAL', text)
            self.assertIn('HOST: api_after / PARTIAL', text)
            self.assertIn('"snapshot": "before"', text)
            self.assertIn('"snapshot": "after"', text)
            if use_inventory:
                self.assertIn("healthy.example:", text)
                if wrong_identity:
                    self.assertIn('identity mismatch', text.lower())
                    self.assertNotIn('ValueError: example failure', text)
                else:
                    self.assertIn("\nValueError: example failure", text)
            self.assertNotIn("DO_NOT_PUBLISH_123", text)
            self.assertEqual(list((temp / "out").iterdir()), reports)


if __name__ == "__main__":
    unittest.main()
