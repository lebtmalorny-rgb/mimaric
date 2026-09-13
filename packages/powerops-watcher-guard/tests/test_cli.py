import contextlib
import io
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from oslo_config import cfg

from powerops_watcher_guard import cli, config
from powerops_watcher_guard.gate import GuardDenied
from fake_etcd import Etcd


class CliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config_path = pathlib.Path(self.directory.name) / 'guard.conf'
        self.config_path.write_text('[watcher_automation_guard]\nendpoint=http://127.0.0.1:2379\n')
        self.etcd = Etcd()
        mock.patch('requests.post', side_effect=self.etcd.post).start()
        self.addCleanup(mock.patch.stopall)

    def run_cli(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            result = cli.main(['--config-file', str(self.config_path), *args])
        return result, output.getvalue(), errors.getvalue()

    def test_resume_requires_acknowledgement_revision_actor_reason(self):
        valid = ['resume', '--expected-revision', '2', '--actor', 'operator',
                 '--reason', 'recovered', '--acknowledge-recovery']
        for omit, count in [(1, 2), (3, 2), (5, 2), (7, 1)]:
            args = valid[:omit] + valid[omit + count:]
            result, output, errors = self.run_cli(*args)
            self.assertNotEqual(0, result)
            self.assertEqual('', output)
            self.assertIn('error', json.loads(errors))
        self.assertEqual({}, self.etcd.data)

    def test_initialize_status_resume_emit_json_and_exact_cas(self):
        code, output, _ = self.run_cli('initialize', '--actor', 'operator', '--reason', 'setup')
        self.assertEqual(0, code)
        initial = json.loads(output)
        self.assertIs(initial['blocked'], True)
        code, output, _ = self.run_cli('status')
        self.assertEqual(initial, json.loads(output))
        resume = ['resume', '--expected-revision', str(initial['revision']), '--actor', 'operator',
                  '--reason', 'recovered', '--acknowledge-recovery']
        code, output, _ = self.run_cli(*resume)
        self.assertEqual(0, code)
        self.assertIs(json.loads(output)['blocked'], False)
        code, output, errors = self.run_cli(*resume)
        self.assertNotEqual(0, code)
        self.assertEqual('', output)
        self.assertIn('error', json.loads(errors))

    def test_missing_state_and_credential_config_errors_are_json_without_secret(self):
        code, output, errors = self.run_cli('status')
        self.assertNotEqual(0, code)
        self.assertIn('error', json.loads(errors))
        self.config_path.write_text('[watcher_automation_guard]\nendpoint=http://user:secret@host\n')
        code, output, errors = self.run_cli('status')
        self.assertNotEqual(0, code)
        self.assertNotIn('secret', output + errors)
        self.assertIn('error', json.loads(errors))

    def test_config_builds_validated_gate_with_tls_and_is_disabled_by_default(self):
        conf = cfg.ConfigOpts()
        config.register_opts(conf)
        self.assertFalse(conf.watcher_automation_guard.enabled)
        for name, value in [('endpoint', 'https://etcd:2379'), ('prefix', '/isolated'),
                            ('timeout', 1.25), ('ca_file', '/ca'), ('cert_file', '/cert'),
                            ('key_file', '/key')]:
            conf.set_override(name, value, group='watcher_automation_guard')
        gate = config.from_conf(conf)
        with self.assertRaises(GuardDenied):
            gate.status()
        url, kwargs = self.etcd.requests[-1]
        self.assertEqual('https://etcd:2379/v3/kv/range', url)
        self.assertEqual('/ca', kwargs['verify'])
        self.assertEqual(('/cert', '/key'), kwargs['cert'])
        self.assertEqual(1.25, kwargs['timeout'])
        from base64 import b64decode
        self.assertEqual(b'/isolated/state', b64decode(kwargs['json']['key']))
        sample = cfg.ConfigOpts()
        for group, options in config.list_opts():
            sample.register_opts(options, group=group)
        self.assertFalse(sample.watcher_automation_guard.enabled)


if __name__ == '__main__':
    unittest.main()
