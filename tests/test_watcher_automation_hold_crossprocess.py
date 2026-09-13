"""Opt-in Watcher/Masakari smoke against a disposable loopback etcd prefix."""

import base64
import json
import os
import subprocess
import sys
import unittest
from urllib.parse import urlsplit
import uuid

import requests

from powerops_watcher_guard.gate import Gate, GuardDenied


ENDPOINT = os.environ.get('POWEROPS_GUARD_TEST_ENDPOINT')


WATCHER_SCRIPT = r'''
import json
import os
import sys
from types import SimpleNamespace

from powerops_watcher_guard.gate import GuardDenied
from watcher import conf
from watcher.common import automation_guard

group = 'watcher_automation_guard'
conf.CONF.set_override('enabled', True, group=group)
conf.CONF.set_override('endpoint', os.environ['HOLD_ENDPOINT'], group=group)
conf.CONF.set_override('prefix', os.environ['HOLD_PREFIX'], group=group)
request = json.loads(os.environ['HOLD_REQUEST'])
try:
    if request['operation'] == 'admit-audit':
        result = automation_guard.admit_audit(
            SimpleNamespace(audit_type=request['audit_type']))
    else:
        automation_guard.validate_plan(
            SimpleNamespace(automation_epoch=request['epoch']))
        result = 'allowed'
    print(json.dumps({'result': result}))
except GuardDenied as error:
    print(json.dumps({'denied': type(error).__name__}))
    sys.exit(3)
'''


MASAKARI_SCRIPT = r'''
import json
import os

import masakari.conf
from masakari.objects import fields
from masakari.powerops import watcher_automation
from types import SimpleNamespace

group = 'watcher_automation_guard'
masakari.conf.CONF.set_override('enabled', True, group=group)
masakari.conf.CONF.set_override('endpoint', os.environ['HOLD_ENDPOINT'], group=group)
masakari.conf.CONF.set_override('prefix', os.environ['HOLD_PREFIX'], group=group)
request = json.loads(os.environ['HOLD_REQUEST'])
notification = SimpleNamespace(
    type=fields.NotificationType.COMPUTE_HOST,
    notification_uuid=request['incident_id'],
    payload={'event': 'STOPPED', 'host_status': 'NORMAL'},
)
result = watcher_automation.hold(notification, request['host'])
print(json.dumps(result, sort_keys=True))
'''


def _b64(value):
    return base64.b64encode(value).decode()


@unittest.skipUnless(ENDPOINT, 'set POWEROPS_GUARD_TEST_ENDPOINT to disposable local etcd')
class CrossProcessServiceSmokeTests(unittest.TestCase):
    def setUp(self):
        self.assertIn(
            urlsplit(ENDPOINT).hostname,
            ('127.0.0.1', 'localhost', '::1'),
            'Test only permits a disposable loopback etcd endpoint',
        )
        self.prefix = '/watcher-hold-crossprocess/' + str(uuid.uuid4())
        self.gate = Gate(ENDPOINT, prefix=self.prefix)
        self.addCleanup(self.delete_namespace)

    def delete_namespace(self):
        start = (self.prefix + '/').encode()
        end = start[:-1] + bytes([start[-1] + 1])
        response = requests.post(
            ENDPOINT + '/v3/kv/deleterange',
            json={'key': _b64(start), 'range_end': _b64(end)},
            timeout=5,
        )
        response.raise_for_status()

    def run_service(self, script, request, expected_code=0):
        environment = os.environ.copy()
        environment.update({
            'HOLD_ENDPOINT': ENDPOINT,
            'HOLD_PREFIX': self.prefix,
            'HOLD_REQUEST': json.dumps(request),
        })
        result = subprocess.run(
            [sys.executable, '-c', script],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        self.assertEqual(expected_code, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def test_epoch_lifecycle_across_real_service_helpers(self):
        initial = self.gate.initialize('test-operator', 'cross-process setup')
        allowed_e1 = self.gate.resume(
            initial['revision'], 'test-operator', 'initial checks complete')

        audit = self.run_service(WATCHER_SCRIPT, {
            'operation': 'admit-audit',
            'audit_type': 'CONTINUOUS',
        })
        self.assertEqual(allowed_e1['epoch'], audit['result'])

        incident_id = str(uuid.uuid4())
        held_e2 = self.run_service(MASAKARI_SCRIPT, {
            'incident_id': incident_id,
            'host': 'compute-1',
        })
        self.assertIs(held_e2['blocked'], True)
        self.assertNotEqual(allowed_e1['epoch'], held_e2['epoch'])

        denied = self.run_service(WATCHER_SCRIPT, {
            'operation': 'validate-plan',
            'epoch': allowed_e1['epoch'],
        }, expected_code=3)
        self.assertIn('denied', denied)

        allowed_e3 = self.gate.resume(
            held_e2['revision'], 'test-operator', 'recovery inspected')
        with self.assertRaises(GuardDenied):
            self.gate.admit(expected_epoch=allowed_e1['epoch'])

        denied = self.run_service(WATCHER_SCRIPT, {
            'operation': 'validate-plan',
            'epoch': allowed_e1['epoch'],
        }, expected_code=3)
        self.assertIn('denied', denied)
        audit = self.run_service(WATCHER_SCRIPT, {
            'operation': 'admit-audit',
            'audit_type': 'CONTINUOUS',
        })
        self.assertEqual(allowed_e3['epoch'], audit['result'])
        manual = self.run_service(WATCHER_SCRIPT, {
            'operation': 'validate-plan',
            'epoch': 'manual',
        })
        self.assertEqual('allowed', manual['result'])

        duplicate = self.run_service(MASAKARI_SCRIPT, {
            'incident_id': incident_id,
            'host': 'compute-1',
        })
        self.assertEqual(allowed_e3, duplicate)
        self.assertEqual(allowed_e3['epoch'], self.gate.admit())


if __name__ == '__main__':
    unittest.main()
