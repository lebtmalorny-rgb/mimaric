"""Run actual Ansible against local fixture commands; no real cloud/SSH/container."""
import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).with_name("fake_cloud_tools.py")
PLAYBOOK = ROOT / "collect-mistral.yml"
TOKEN = "FAKE_ISSUED_TOKEN_MUST_NOT_LEAK"
SECRET = "FAKE_PASSWORD_MUST_NOT_LEAK"
ANSIBLE = Path(sys.executable).with_name("ansible-playbook")


@unittest.skipUnless(os.environ.get("MISTRAL_DIAG_RUN_ANSIBLE") == "1", "Explicit offline Ansible integration run")
class AnsibleOfflineTests(unittest.TestCase):
    def exercise(self, mode):
        with tempfile.TemporaryDirectory(prefix="mistral-ansible-fixture-") as tmp:
            root = Path(tmp)
            commands = root / "bin"
            commands.mkdir()
            runner = commands / "fixture"
            runner.write_text("#!" + sys.executable + "\n" + FIXTURE.read_text())
            runner.chmod(0o700)
            for name in ("openstack","curl","hostname","podman","date","uptime","free","df","ps","timedatectl","ss","journalctl"):
                (commands / name).symlink_to(runner)
            docs = yaml.safe_load(PLAYBOOK.read_text())
            source = docs[0]["vars"]["mistral_diag_source"]
            # Only transport/defaults/environment are replaced. Embedded program and
            # task sequence remain identical to the deliverable; no network tool runs.
            docs[0]["vars"]["mistral_diag_controllers"] = [
                {"name": "fixture-node", "fqdn": "mistral-fixture.invalid", "ip": "127.0.0.1"}]
            docs[0]["vars"]["mistral_diag_defaults"]["api_endpoints"] = [
                "http://127.0.0.1:%d/v2" % p for p in (18989, 18990)]
            docs[0]["vars"]["mistral_diag_defaults"]["log_root"] = str(root / "empty-logs")
            env = {"PATH": str(commands) + os.pathsep + os.environ["PATH"],
                   "MISTRAL_FIXTURE_DIR": str(root)}
            if mode != "success":
                env["MISTRAL_FIXTURE_" + mode] = "1"
            for play in docs:
                play["environment"] = env
                for task in play["tasks"]:
                    if "ansible.builtin.add_host" in task:
                        task["ansible.builtin.add_host"]["ansible_connection"] = "local"
                    if os.environ.get("MISTRAL_DIAG_DEBUG_FIXTURE") and task["name"].startswith("Preserve every host"):
                        task["no_log"] = False
            self.assertEqual(docs[0]["vars"]["mistral_diag_source"], source)
            rendered = root / "collect.yml"
            rendered.write_text(yaml.safe_dump(docs, sort_keys=False, width=1000))
            variables = {"mistral_diag_become": False,
                         "mistral_diag_remote_python": sys.executable,
                         "mistral_diag_output_parent": str(root / "artifacts"),
                         "ansible_python_interpreter": sys.executable}
            (root / "ansible.cfg").write_text("[defaults]\n")
            ansible_env = dict(os.environ, ANSIBLE_LOCAL_TEMP=str(root / "ansible-local"),
                               ANSIBLE_REMOTE_TEMP=str(root / "ansible-remote"),
                               ANSIBLE_NOCOLOR="1", ANSIBLE_CONFIG=str(root / "ansible.cfg"))
            ansible_env.update(env)
            result = subprocess.run([str(ANSIBLE), "-i", "localhost,", str(rendered),
                                     "-e", json.dumps(variables)],
                                    env=ansible_env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, timeout=80)
            self.assertEqual(result.returncode, 0, result.stdout[-9000:])
            files = list((root / "artifacts").iterdir())
            self.assertEqual(len(files), 1, str(files))
            self.assertEqual(files[0].suffix, ".txt")
            report = files[0].read_text()
            self.assertEqual(stat.S_IMODE(files[0].stat().st_mode), 0o600)
            for secret in (TOKEN, SECRET):
                self.assertNotIn(secret, result.stdout)
                self.assertNotIn(secret, report)
            for section in ("api_before", "api_after", "fixture-node"):
                self.assertIn(section, report)
            if mode == "success":
                self.assertIn("PAUSED", report)
                self.assertIn("req-fixture-log", report)
                self.assertIn("database_probe", report)
            elif mode == "AUTH_FAIL":
                self.assertIn("authentication_failed", report)
                self.assertIn("req-fixture-log", report)
            elif mode == "API_FAIL":
                self.assertIn("http_error", report)
                self.assertIn("504", report)
                self.assertIn("req-fixture-log", report)
            else:
                self.assertIn("COLLECTOR_ERROR", report)
                self.assertIn("wrong-host.invalid", report)
            print("Offline Ansible mode=%s: one private TXT, no test secrets, exit=0" % mode)

    def test_real_ansible_success_with_two_snapshots(self):
        self.exercise("success")

    def test_real_ansible_auth_failure_still_collects_controller(self):
        self.exercise("AUTH_FAIL")

    def test_real_ansible_api_504_still_collects_controller(self):
        self.exercise("API_FAIL")

    def test_real_ansible_wrong_identity_still_writes_report(self):
        self.exercise("WRONG_HOST")


if __name__ == "__main__":
    unittest.main()
