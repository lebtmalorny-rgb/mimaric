import json
import unittest
import uuid
from unittest import mock

import requests

from powerops_watcher_guard.gate import Gate, GuardConflict, GuardDenied, GuardUnavailable
from fake_etcd import Etcd, Response, b64


class GateTests(unittest.TestCase):
    def setUp(self):
        self.etcd = Etcd()
        self.post = mock.patch('requests.post', side_effect=self.etcd.post).start()
        self.addCleanup(mock.patch.stopall)
        self.gate = Gate('http://127.0.0.1:2379')

    def allowed(self):
        blocked = self.gate.initialize('operator', 'initial setup')
        return self.gate.resume(blocked['revision'], 'operator', 'recovered')

    def test_missing_state_denies_status_admit_and_resume(self):
        for operation in (self.gate.status, self.gate.admit,
                          lambda: self.gate.resume(1, 'operator', 'recovered')):
            with self.assertRaises(GuardDenied):
                operation()

    def test_initialize_persists_blocked_and_never_overwrites(self):
        state = self.gate.initialize('operator', 'setup')
        self.assertIs(state['blocked'], True)
        self.assertEqual('operator', state['actor'])
        self.assertGreater(state['revision'], 0)
        self.assertEqual(state, Gate('http://127.0.0.1:2379').status())
        self.assertEqual(state, self.gate.initialize('other', 'again'))
        with self.assertRaises(GuardDenied):
            self.gate.admit()

    def test_resume_creates_new_epoch_and_old_epochs_never_admit(self):
        first = self.allowed()
        self.assertEqual(first['epoch'], self.gate.admit())
        blocked = self.gate.hold(str(uuid.uuid4()), 'compute-1')
        second = self.gate.resume(blocked['revision'], 'operator', 'recovered')
        self.assertEqual(3, len({first['epoch'], blocked['epoch'], second['epoch']}))
        with self.assertRaises(GuardDenied):
            self.gate.admit(first['epoch'])
        self.assertEqual(second['epoch'], self.gate.admit(second['epoch']))

    def test_hold_initializes_and_duplicate_after_resume_does_not_reblock(self):
        incident = str(uuid.uuid4())
        held = self.gate.hold(incident, 'compute-1')
        self.assertIs(held['blocked'], True)
        self.assertEqual(held, self.gate.hold(incident, 'compute-1'))
        allowed = self.gate.resume(held['revision'], 'operator', 'recovered')
        reconstructed = Gate('http://127.0.0.1:2379')
        self.assertEqual(allowed, reconstructed.hold(incident, 'compute-1'))
        marker = self.etcd.data[b64('/powerops/watcher-automation/v1/incidents/' + incident)]
        self.assertEqual(str(held['revision']), marker['mod_revision'])

    def test_admission_observed_before_hold_denied_if_txn_follows_hold(self):
        state = self.allowed()
        self.etcd.before_txn = lambda: self.gate.hold(str(uuid.uuid4()), 'compute-1')
        with self.assertRaises(GuardConflict):
            self.gate.admit(state['epoch'])
        self.assertIs(self.gate.status()['blocked'], True)

    def test_admission_does_not_retry_into_resumed_generation(self):
        state = self.allowed()
        def incident_and_resume():
            held = self.gate.hold(str(uuid.uuid4()), 'compute-1')
            self.gate.resume(held['revision'], 'operator', 'recovered')
        self.etcd.before_txn = incident_and_resume
        with self.assertRaises(GuardConflict):
            self.gate.admit()
        self.assertNotEqual(state['epoch'], self.gate.admit())

    def test_new_incident_defeats_stale_resume(self):
        held = self.gate.hold(str(uuid.uuid4()), 'compute-1')
        self.etcd.before_txn = lambda: self.gate.hold(str(uuid.uuid4()), 'compute-2')
        with self.assertRaises(GuardConflict):
            self.gate.resume(held['revision'], 'operator', 'recovered')
        self.assertEqual('compute-2', self.gate.status()['host'])
        self.assertIs(self.gate.status()['blocked'], True)

    def test_hold_retries_collision_with_resume_and_remains_blocked(self):
        held = self.gate.hold(str(uuid.uuid4()), 'compute-1')
        self.etcd.before_txn = lambda: self.gate.resume(held['revision'], 'operator', 'recovered')
        result = self.gate.hold(str(uuid.uuid4()), 'compute-2')
        self.assertIs(result['blocked'], True)
        self.assertEqual('compute-2', result['host'])

    def test_two_incidents_both_persist_with_cas_collision(self):
        one, two = str(uuid.uuid4()), str(uuid.uuid4())
        self.etcd.before_txn = lambda: self.gate.hold(two, 'compute-2')
        held = self.gate.hold(one, 'compute-1')
        allowed = self.gate.resume(held['revision'], 'operator', 'recovered')
        self.assertEqual(allowed, self.gate.hold(one, 'compute-1'))
        self.assertEqual(allowed, self.gate.hold(two, 'compute-2'))

    def test_prefixes_have_independent_state_and_incident_history(self):
        other = Gate('http://127.0.0.1:2379', prefix='/other')
        incident = str(uuid.uuid4())
        self.allowed()
        other.hold(incident, 'other-compute')
        self.assertIs(self.gate.status()['blocked'], False)
        self.assertIs(self.gate.hold(incident, 'compute')['blocked'], True)

    def test_network_ambiguity_is_denied_without_retry_or_secret_leak(self):
        self.allowed()
        self.before_error_calls = self.post.call_count
        self.post.side_effect = requests.Timeout('http://secret:password@backend')
        with self.assertRaises(GuardUnavailable) as caught:
            self.gate.hold(str(uuid.uuid4()), 'compute')
        self.assertNotIn('password', str(caught.exception))
        # A timeout of the first read must not turn into any mutation retry.
        self.assertEqual(1, self.post.call_count - self.before_error_calls)

    def test_applied_hold_with_lost_response_is_denied_and_replay_is_idempotent(self):
        self.allowed()
        incident = str(uuid.uuid4())
        transactions = []
        def lose_response(url, **kwargs):
            response = self.etcd.post(url, **kwargs)
            if url.endswith('/txn'):
                transactions.append(response)
                raise requests.Timeout('secret backend details')
            return response
        self.post.side_effect = lose_response
        with self.assertRaises(GuardUnavailable):
            self.gate.hold(incident, 'compute')
        self.assertEqual(1, len(transactions))
        self.post.side_effect = self.etcd.post
        held = self.gate.status()
        self.assertIs(held['blocked'], True)
        allowed = self.gate.resume(held['revision'], 'operator', 'recovered')
        self.assertEqual(allowed, self.gate.hold(incident, 'compute'))

    def test_hold_cas_collisions_are_bounded_without_writing_incident(self):
        self.allowed()
        collision_count = 0
        incident = str(uuid.uuid4())
        def collide():
            nonlocal collision_count
            collision_count += 1
            # An unrelated revision-changing writer at the guard key.
            key = b64('/powerops/watcher-automation/v1/state')
            self.etcd.revision += 1
            self.etcd.put(key, self.etcd.data[key]['value'])
            self.etcd.before_txn = collide
        self.etcd.before_txn = collide
        with self.assertRaises(GuardConflict):
            self.gate.hold(incident, 'compute')
        self.assertGreater(collision_count, 1)
        self.assertLessEqual(collision_count, 16)
        self.assertNotIn(b64('/powerops/watcher-automation/v1/incidents/' + incident),
                         self.etcd.data)

    def test_http_redirect_and_invalid_json_do_not_admit(self):
        self.allowed()
        response = Response({'header': {'revision': '1'}})
        response.status_code = 307
        self.post.side_effect = None
        self.post.return_value = response
        with self.assertRaises(GuardUnavailable):
            self.gate.admit()
        response.status_code = 200
        response.json = mock.Mock(side_effect=ValueError('secret response'))
        with self.assertRaises(GuardUnavailable):
            self.gate.admit()

    def test_duplicate_transaction_json_fields_are_denied(self):
        self.allowed()
        def duplicate_result(url, **kwargs):
            response = self.etcd.post(url, **kwargs)
            if url.endswith('/txn'):
                body = json.dumps(response.body)
                raw_response = requests.Response()
                raw_response.status_code = 200
                raw_response._content = ('{"succeeded":false,' + body[1:]).encode()
                return raw_response
            return response
        self.post.side_effect = duplicate_result
        with self.assertRaises(GuardUnavailable):
            self.gate.admit()

    def test_admission_requires_complete_matching_transaction_snapshot(self):
        self.allowed()
        def corrupt_result(url, **kwargs):
            response = self.etcd.post(url, **kwargs)
            if url.endswith('/txn'):
                response.body['responses'] = []
            return response
        self.post.side_effect = corrupt_result
        with self.assertRaises(GuardUnavailable):
            self.gate.admit()

    def test_expiring_state_and_corrupt_incident_marker_deny(self):
        incident = str(uuid.uuid4())
        held = self.gate.hold(incident, 'compute')
        key = b64('/powerops/watcher-automation/v1/state')
        self.etcd.data[key]['lease'] = '99'
        with self.assertRaises(GuardUnavailable):
            self.gate.resume(held['revision'], 'operator', 'done')
        del self.etcd.data[key]['lease']
        marker = b64('/powerops/watcher-automation/v1/incidents/' + incident)
        self.etcd.data[marker]['value'] = b64('{"schema":1}')
        with self.assertRaises(GuardUnavailable):
            self.gate.hold(incident, 'compute')

    def test_duplicate_json_fields_and_oversized_revision_are_protocol_errors(self):
        self.allowed()
        key = b64('/powerops/watcher-automation/v1/state')
        import base64
        state = base64.b64decode(self.etcd.data[key]['value']).decode()
        duplicate = state[:-1] + ',"blocked":false}'
        self.etcd.data[key]['value'] = b64(duplicate)
        with self.assertRaises(GuardUnavailable):
            self.gate.admit()
        self.post.side_effect = None
        self.post.return_value = Response({'header': {'revision': '1'}, 'count': '1',
                                          'kvs': [{'key': key, 'mod_revision': '9' * 5000}]})
        with self.assertRaises(GuardUnavailable):
            self.gate.status()

    def test_unencodable_input_denied_before_network(self):
        with self.assertRaises(GuardDenied):
            self.gate.initialize('operator', '\ud800')
        self.assertEqual([], self.etcd.requests)

    def test_malformed_protocol_denied(self):
        for body in (None, [], {}, {'header': {}}, {'header': {'revision': 'bad'}},
                     {'header': {'revision': '1'}, 'kvs': 'bad'},
                     {'header': {'revision': '1'}, 'kvs': [{'value': '!'}]},
                     {'header': {'revision': '1'}, 'error': 'secret'}):
            with self.subTest(body=body):
                self.post.side_effect = None
                self.post.return_value = Response(body)
                with self.assertRaises(GuardDenied):
                    self.gate.admit()

    def test_malformed_state_cannot_be_resumed_or_held_over(self):
        self.allowed()
        key = b64('/powerops/watcher-automation/v1/state')
        for field, value in [('blocked', 'false'), ('epoch', 'bad'), ('schema', 2),
                             ('reason', ''), ('actor', None), ('incident_id', 'bad')]:
            with self.subTest(field=field):
                original = self.etcd.data[key]['value']
                import base64
                state = json.loads(base64.b64decode(original))
                state[field] = value
                self.etcd.data[key]['value'] = b64(json.dumps(state))
                for op in (self.gate.admit,
                           lambda: self.gate.resume(self.etcd.revision, 'operator', 'done'),
                           lambda: self.gate.hold(str(uuid.uuid4()), 'compute')):
                    with self.assertRaises(GuardDenied):
                        op()
                self.etcd.data[key]['value'] = original

    def test_invalid_text_uuid_revision_and_endpoint_rejected(self):
        for actor in ('', '  ', 'a' * 256, None, 1, 'a\nsecret'):
            with self.assertRaises((GuardDenied, ValueError)):
                self.gate.initialize(actor, 'reason')
        for reason in ('', ' ', 'r' * 1025):
            with self.assertRaises((GuardDenied, ValueError)):
                self.gate.initialize('actor', reason)
        for incident in ('', '../state', 'not-uuid'):
            with self.assertRaises((GuardDenied, ValueError)):
                self.gate.hold(incident, 'compute')
        for revision in (0, -1, True, '1', 1.5):
            with self.assertRaises((GuardDenied, ValueError)):
                self.gate.resume(revision, 'actor', 'reason')
        for endpoint in ('file:///tmp/etcd', 'http://u:secret@host:2379',
                         'http://host:2379?secret=1', 'http://host/#secret'):
            with self.assertRaises((GuardDenied, ValueError)):
                Gate(endpoint)
        for prefix in ('', '/', 'relative', '/x/../y', '/x//y'):
            with self.assertRaises((GuardDenied, ValueError)):
                Gate('http://host:2379', prefix=prefix)

    def test_tls_verification_client_certificate_timeout_and_no_redirect(self):
        gate = Gate('https://etcd.test:2379', timeout=2.5, ca_file='/ca.pem',
                    cert_file='/cert.pem', key_file='/key.pem')
        with self.assertRaises(GuardDenied):
            gate.status()
        params = self.etcd.requests[-1][1]
        self.assertEqual('/ca.pem', params['verify'])
        self.assertEqual(('/cert.pem', '/key.pem'), params['cert'])
        self.assertEqual(2.5, params['timeout'])
        self.assertIs(params['allow_redirects'], False)
        with self.assertRaises(GuardDenied):
            self.gate.status()
        self.assertIs(self.etcd.requests[-1][1]['verify'], True)

    def test_invalid_timeout_or_tls_config_rejected(self):
        for kwargs in ({'timeout': 0}, {'timeout': float('nan')}, {'timeout': float('inf')},
                       {'key_file': '/key'}, {'ca_file': False}):
            with self.assertRaises((GuardDenied, ValueError)):
                Gate('https://host:2379', **kwargs)


if __name__ == '__main__':
    unittest.main()
