"""Transport corruption fails closed; real-etcd verifies atomic range absence."""
import base64
import os

import pytest
from powerops_evacuation_guard import Guard, GuardDenied, GuardUnavailable, GuardConflict
from fake_etcd import Response
from test_guard import register, uid


@pytest.mark.parametrize('endpoint', ['ftp://host', 'http://u:secret@host', 'http://host?secret=1',
    'http://host#secret', 'http://host:bad', 'http://host:0', 'http://host:65536',
    'http://host/path', 'http://host:', 'http://host/?', 'http://host/#'])
def test_invalid_endpoint_rejected(endpoint):
    with pytest.raises(GuardDenied):
        Guard(endpoint)


@pytest.mark.parametrize('damage', ['nonobject', 'duplicate_response', 'bad_revision',
    'bad_payload', 'wrong_key', 'lease', 'false_success', 'missing_operation', 'delete_count'])
def test_malformed_backend_never_authorizes_work(guard, backend, monkeypatch, damage):
    if backend is None:
        pytest.skip('Corrupt response injection requires offline boundary fake')
    if damage in ('bad_payload', 'wrong_key', 'lease'):
        register(guard, 1)
        key = (guard.prefix + '/records/operations/' + uid(1)).encode()
        if damage == 'bad_payload':
            backend.data[key]['value'] = base64.b64encode(b'{"state":"WAITING"}').decode()
        elif damage == 'wrong_key':
            backend.data[key]['key'] = base64.b64encode(b'/wrong').decode()
        else:
            backend.data[key]['lease'] = '123'
        with pytest.raises(GuardUnavailable):
            guard.try_admit(uid(1), uid(301))
    else:
        original = backend.post
        def corrupt(url, **kwargs):
            result = original(url, **kwargs)
            if damage == 'nonobject':
                return Response([])
            if damage == 'bad_revision':
                result.body['header']['revision'] = True
            if url.endswith('/txn'):
                if damage == 'false_success':
                    result.body['succeeded'] = 'true'
                elif damage == 'missing_operation':
                    result.body['responses'] = []
                elif damage == 'duplicate_response':
                    result.body['responses'][0]['extra'] = {}
                elif damage == 'delete_count':
                    for response in result.body['responses']:
                        if 'response_delete_range' in response:
                            response['response_delete_range']['deleted'] = '0'
            return result
        register(guard, 1)
        monkeypatch.setattr('requests.post', corrupt)
        with pytest.raises(GuardUnavailable):
            if damage == 'delete_count':
                guard.deny_waiting(uid(1), uid(301), 'deadline')
            else:
                guard.try_admit(uid(1), uid(301))


def test_absent_claim_during_completion_retains_other_claims(guard, backend):
    if backend is None:
        pytest.skip('Corrupt backing store injection is offline only')
    from test_guard import proof
    register(guard, 1)
    guard.try_admit(uid(1), uid(301))
    del backend.data[(guard.prefix+'/claims/vms/'+uid(101)).encode()]
    with pytest.raises(GuardUnavailable):
        guard.complete(uid(1), uid(301), proof(1))
    assert guard.get_operation(uid(1))['state'] == 'RUNNING'
    register(guard, 2)
    from powerops_evacuation_guard import GuardBusy
    with pytest.raises(GuardBusy):
        guard.try_admit(uid(2), uid(302))


def test_configure_range_absence_excludes_real_phantom_claim(factory):
    """Break: dropping range_end or the compare lets a concurrent claim survive new limits."""
    if not os.environ.get('POWEROPS_EVACUATION_TEST_ENDPOINT'):
        pytest.skip('Requires actual etcd gateway range-compare semantics')
    g = factory()
    initial = g.initialize('test', 'atomic range absence')
    # Interleave creation after metadata read and before configure transaction,
    # while exercising actual etcd comparison/commit semantics.
    real_txn = g._etcd.txn
    def interleaved(compare, success):
        register(factory(), 1)
        return real_txn(compare, success)
    g._etcd.txn = interleaved
    with pytest.raises(GuardConflict):
        g.configure(initial['revision'], 4, 0, 'op', 'race')
    assert g.configuration()['max_parallel'] == 3
    assert g.get_operation(uid(1))['state'] == 'WAITING'


def test_configure_wins_against_creation_using_old_metadata(factory):
    if not os.environ.get('POWEROPS_EVACUATION_TEST_ENDPOINT'):
        pytest.skip('Requires actual etcd transaction semantics')
    g = factory()
    initial = g.initialize('test', 'metadata revision race')
    real_txn = g._etcd.txn
    def interleaved(compare, success):
        factory().configure(initial['revision'], 4, 0, 'op', 'race')
        return real_txn(compare, success)
    g._etcd.txn = interleaved
    with pytest.raises(GuardConflict):
        register(g, 1)
    assert g.configuration()['max_parallel'] == 4
    with pytest.raises(GuardUnavailable):
        g.get_operation(uid(1))


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1, True, 10**1000],
                         ids=['nan', 'infinite', 'negative', 'boolean', 'overflow'])
def test_invalid_numbers_are_sanitized_guard_denials(value):
    with pytest.raises(GuardDenied):
        Guard('http://host', cooldown=value)


def test_backend_duplicate_json_fields_rejected(guard, monkeypatch):
    import requests
    response = requests.Response()
    response.status_code = 200
    response._content = b'{"header":{"revision":"1"},"kvs":[],"kvs":[]}'
    monkeypatch.setattr('requests.post', lambda *a, **k: response)
    with pytest.raises(GuardUnavailable):
        guard.configuration()


def test_tls_verification_and_no_redirects_at_actual_http_boundary(monkeypatch):
    import requests
    sent = []
    def send(request, **kwargs):
        sent.append((request, kwargs))
        response = requests.Response()
        response.status_code = 302
        response.headers['Location'] = 'https://other.example/secret'
        response._content = b''
        response.request = request
        return response
    monkeypatch.setattr(requests.sessions.Session, 'send', lambda self, request, **kwargs: send(request, **kwargs))
    g = Guard('https://etcd.example', ca_file='/etc/ssl/test-ca.pem', cert_file='/etc/ssl/client.pem', key_file='/etc/ssl/client.key')
    with pytest.raises(GuardUnavailable):
        g.configuration()
    assert len(sent) == 1
    assert sent[0][1]['verify'] == '/etc/ssl/test-ca.pem'
    assert sent[0][1]['cert'] == ('/etc/ssl/client.pem', '/etc/ssl/client.key')
    assert sent[0][1]['allow_redirects'] is False


@pytest.mark.parametrize('damage', ['missing_config_reason', 'wrong_operation_request_binding', 'running_with_terminal_proof'])
def test_semantically_malformed_payload_is_rejected(guard, backend, damage):
    if backend is None:
        pytest.skip('Stored corruption requires HTTP boundary fake')
    import json
    from test_guard import proof
    if damage == 'missing_config_reason':
        key = (guard.prefix+'/metadata').encode()
    else:
        register(guard, 1)
        guard.try_admit(uid(1), uid(301))
        key = (guard.prefix+'/records/operations/'+uid(1)).encode()
    value = json.loads(base64.b64decode(backend.data[key]['value']))
    if damage == 'missing_config_reason':
        value['reason'] = None
    elif damage == 'wrong_operation_request_binding':
        value['attempt_uuid'] = uid(400)
        value['request_id'] = None
    else:
        value['result'] = proof(1)
    backend.data[key]['value'] = base64.b64encode(json.dumps(value).encode()).decode()
    with pytest.raises(GuardUnavailable):
        if damage == 'missing_config_reason':
            guard.configuration()
        else:
            guard.get_operation(uid(1))


@pytest.mark.parametrize('operation', ['admit', 'deny'])
@pytest.mark.parametrize('damage', ['error', 'unexpected_field', 'header_type',
    'header_error', 'header_revision', 'header_revision_mismatch', 'header_member_id'])
def test_nested_transaction_corruption_never_returns_transition_authority(
        guard, backend, monkeypatch, operation, damage):
    """Break: trusting arbitrary response_put/delete dictionaries authorizes an untrusted outcome."""
    if backend is None:
        pytest.skip('Nested response corruption is injected at the offline HTTP boundary')
    register(guard, 1)
    original = backend.post

    def corrupt(url, **kwargs):
        result = original(url, **kwargs)
        if url.endswith('/txn'):
            kind = 'response_put' if operation == 'admit' else 'response_delete_range'
            payload = next(r[kind] for r in result.body['responses'] if kind in r)
            if damage == 'error':
                payload['error'] = 'invalid transaction operation payload'
            elif damage == 'unexpected_field':
                payload['unexpected'] = {}
            elif damage == 'header_type':
                payload['header'] = []
            elif damage == 'header_error':
                payload['header']['error'] = 'invalid header'
            elif damage == 'header_revision':
                payload['header']['revision'] = True
            elif damage == 'header_revision_mismatch':
                payload['header']['revision'] = str(int(result.body['header']['revision']) - 1)
            else:
                payload['header']['member_id'] = '-1'
        return result

    monkeypatch.setattr('requests.post', corrupt)
    with pytest.raises(GuardUnavailable):
        if operation == 'admit':
            guard.try_admit(uid(1), uid(301))
        else:
            guard.deny_waiting(uid(1), uid(301), 'waiting deadline')
    # The server already committed: rejecting the response must not fabricate
    # a rollback or let a second caller execute the migration.
    assert guard.get_operation(uid(1))['state'] == ('RUNNING' if operation == 'admit' else 'DENIED')
    from powerops_evacuation_guard import GuardDuplicate
    with pytest.raises(GuardDuplicate):
        guard.try_admit(uid(1), uid(301))


@pytest.mark.parametrize('shape', ['revision_only', 'omitted_header', 'empty_header', 'uint64_defaults'])
def test_valid_nested_gateway_protobuf_defaults_still_authorize_once(guard, backend, monkeypatch, shape):
    if backend is None:
        pytest.skip('Gateway default variants are injected at the offline HTTP boundary')
    register(guard, 1)
    original = backend.post

    def shape_response(url, **kwargs):
        result = original(url, **kwargs)
        if url.endswith('/txn'):
            for response in result.body['responses']:
                payload = response['response_put']
                if shape == 'omitted_header':
                    payload.pop('header')
                elif shape == 'empty_header':
                    payload['header'] = {}
                elif shape == 'uint64_defaults':
                    payload['header'].update(cluster_id='0', member_id='9767282471509240863', raft_term='0')
                # revision_only is the actual etcd3.5.21 response observed by root.
        return result

    monkeypatch.setattr('requests.post', shape_response)
    assert guard.try_admit(uid(1), uid(301))['state'] == 'RUNNING'
