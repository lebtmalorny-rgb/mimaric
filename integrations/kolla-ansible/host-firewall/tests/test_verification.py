import importlib.util
from pathlib import Path
import unittest
from unittest import mock


class VerificationTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'ansible/module_utils/powerops_firewall_verification.py'
        spec = importlib.util.spec_from_file_location('verification', path)
        self.v = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.v)

    def test_fresh_ssh_has_no_connection_reuse_or_host_key_bypass(self):
        argv = self.v.ssh_command({'connection': 'ssh', 'host': '192.0.2.2', 'port': 2222, 'user': 'operator'})
        self.assertIn('ControlMaster=no', argv)
        self.assertIn('ControlPath=none', argv)
        self.assertIn('StrictHostKeyChecking=yes', argv)
        self.assertIn('2222', argv)
        self.assertEqual('/bin/true', argv[-1])

    def test_invalid_checks_and_ssh_are_rejected_before_network(self):
        for checks in ([], [{'id': 'ssh-fresh', 'type': 'tcp', 'host': '192.0.2.2', 'port': 80}],
                       [{'id': 'api', 'type': 'shell', 'command': 'true'}],
                       [{'id': 'api', 'type': 'tcp', 'host': 'any.example', 'port': True}],
                       [{'id': 'api', 'type': 'http', 'url': 'http://user:secret@example/a', 'status': 200}]):
            with self.subTest(checks=checks), self.assertRaises(ValueError):
                self.v.validate_checks(checks)
        for field, value in [('host', '-oProxyCommand=bad'), ('port', True), ('connection', 'local'),
                             ('ssh_common_args', '-o StrictHostKeyChecking=no')]:
            config = {'connection': 'ssh', 'host': '192.0.2.2', 'port': 22, 'user': 'operator'}
            config[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.v.ssh_command(config)

    def test_tcp_failure_cannot_be_reported_as_verified(self):
        checks = [{'id': 'api', 'type': 'tcp', 'host': '192.0.2.2', 'port': 8989}]
        with mock.patch.object(self.v.subprocess, 'run', return_value=mock.Mock(returncode=0)), \
                mock.patch.object(self.v.socket, 'create_connection', side_effect=OSError()):
            self.assertRaises(ValueError, self.v.verify,
                              {'connection': 'ssh', 'host': '192.0.2.2', 'port': 22, 'user': 'operator'}, checks)
