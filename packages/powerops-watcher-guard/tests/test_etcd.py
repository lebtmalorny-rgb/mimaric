"""Opt-in integration tests. Point ONLY at a disposable local etcd instance."""
import base64
from concurrent.futures import ThreadPoolExecutor
import os
import threading
import unittest
from unittest import mock
from urllib.parse import urlsplit
import uuid

import requests

from powerops_watcher_guard.gate import Gate, GuardConflict, GuardDenied


ENDPOINT = os.environ.get('POWEROPS_GUARD_TEST_ENDPOINT')


def b64(value):
    return base64.b64encode(value).decode()


@unittest.skipUnless(ENDPOINT, 'set POWEROPS_GUARD_TEST_ENDPOINT to disposable local etcd')
class RealEtcdTests(unittest.TestCase):
    def setUp(self):
        self.assertIn(urlsplit(ENDPOINT).hostname, ('127.0.0.1', 'localhost', '::1'),
                      'Tests only permit disposable loopback etcd endpoints')
        self.prefix = '/powerops-guard-test/' + str(uuid.uuid4())
        self.gate = self.new_gate()
        self.addCleanup(self.delete_test_namespace)

    def new_gate(self):
        return Gate(ENDPOINT, prefix=self.prefix)

    def delete_test_namespace(self):
        # Only this test's random namespace, never the configured guard default.
        start = (self.prefix + '/').encode()
        end = start[:-1] + bytes([start[-1] + 1])
        result = requests.post(ENDPOINT + '/v3/kv/deleterange',
                               json={'key': b64(start), 'range_end': b64(end)}, timeout=5)
        result.raise_for_status()

    def test_lifecycle_and_reconstructed_client_preserve_incident_history(self):
        with self.assertRaises(GuardDenied):
            self.gate.admit()
        initial = self.gate.initialize('operator', 'setup')
        self.assertEqual(initial, self.new_gate().status())
        self.assertIs(initial['blocked'], True)
        allowed = self.gate.resume(initial['revision'], 'operator', 'recovered')
        self.assertEqual(allowed['epoch'], self.new_gate().admit())
        incident = str(uuid.uuid4())
        held = self.new_gate().hold(incident, 'compute-1')
        with self.assertRaises(GuardDenied):
            self.gate.admit(allowed['epoch'])
        resumed = self.gate.resume(held['revision'], 'operator', 'recovered')
        self.assertEqual(resumed, self.new_gate().hold(incident, 'compute-1'))
        with self.assertRaises(GuardDenied):
            self.gate.admit(allowed['epoch'])

    def test_concurrent_admissions_are_ordered_before_hold_by_etcd_revision(self):
        initial = self.gate.initialize('operator', 'setup')
        allowed = self.gate.resume(initial['revision'], 'operator', 'recovered')
        original_post = requests.post
        successful_admissions = []
        lock = threading.Lock()
        def observe(url, **kwargs):
            response = original_post(url, **kwargs)
            request = kwargs.get('json', {})
            if url.endswith('/txn') and 'request_range' in request.get('success', [{}])[0]:
                result = response.json()
                if result.get('succeeded'):
                    with lock:
                        successful_admissions.append(int(result['header']['revision']))
            return response
        barrier = threading.Barrier(17)
        def admit():
            barrier.wait(timeout=10)
            try:
                return self.new_gate().admit(allowed['epoch'])
            except GuardDenied:
                return None
        def hold():
            barrier.wait(timeout=10)
            return self.new_gate().hold(str(uuid.uuid4()), 'compute-1')
        with mock.patch('requests.post', side_effect=observe):
            # Establish a known successful admission as well as racing calls.
            self.assertEqual(allowed['epoch'], self.gate.admit())
            with ThreadPoolExecutor(max_workers=17) as pool:
                admissions = [pool.submit(admit) for _ in range(16)]
                held = pool.submit(hold).result(timeout=20)
                outcomes = [future.result(timeout=20) for future in admissions]
        self.assertGreater(len(successful_admissions), 0)
        self.assertEqual(1 + sum(outcome is not None for outcome in outcomes),
                         len(successful_admissions))
        self.assertTrue(all(revision < held['revision'] for revision in successful_admissions))
        self.assertTrue(all(outcome in (None, allowed['epoch']) for outcome in outcomes))
        with self.assertRaises(GuardDenied):
            self.new_gate().admit()

    def test_concurrent_resume_and_new_incident_always_finish_held(self):
        held = self.gate.hold(str(uuid.uuid4()), 'compute-0')
        for index in range(10):
            barrier = threading.Barrier(2)
            def resume():
                barrier.wait(timeout=10)
                try:
                    return self.new_gate().resume(held['revision'], 'operator', 'recovered')
                except GuardConflict:
                    return None
            incident = str(uuid.uuid4())
            def hold():
                barrier.wait(timeout=10)
                return self.new_gate().hold(incident, 'compute-' + str(index + 1))
            with ThreadPoolExecutor(max_workers=2) as pool:
                resumed_future = pool.submit(resume)
                hold_future = pool.submit(hold)
                resumed = resumed_future.result(timeout=20)
                held = hold_future.result(timeout=20)
            if resumed is not None:
                self.assertLess(resumed['revision'], held['revision'])
            self.assertEqual(held, self.new_gate().status())
            self.assertIs(held['blocked'], True)

    def test_two_simultaneous_incidents_are_both_deduplicated_after_resume(self):
        incidents = [str(uuid.uuid4()), str(uuid.uuid4())]
        barrier = threading.Barrier(2)
        def hold(incident):
            barrier.wait(timeout=10)
            return self.new_gate().hold(incident, 'compute-1')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(hold, incidents))
        self.assertNotEqual(results[0]['revision'], results[1]['revision'])
        held = self.gate.status()
        resumed = self.gate.resume(held['revision'], 'operator', 'recovered')
        for incident in incidents:
            self.assertEqual(resumed, self.new_gate().hold(incident, 'compute-1'))


if __name__ == '__main__':
    unittest.main()
