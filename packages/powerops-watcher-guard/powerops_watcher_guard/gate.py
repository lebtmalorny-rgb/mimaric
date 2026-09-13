"""Linearizable etcd v3 admission; backend ambiguity always denies work."""
import base64
import binascii
import json
import math
from urllib.parse import urlsplit
import uuid

import requests


class GuardDenied(Exception):
    """Automatic work must not start."""


class GuardUnavailable(GuardDenied):
    """Backend or stored protocol data could not be trusted."""


class GuardConflict(GuardDenied):
    """The observed generation changed before the operation committed."""


def _text(value, name, maximum=255):
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise GuardDenied('Invalid ' + name)
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise GuardDenied('Invalid ' + name) from None
    return value


def _uuid(value, name):
    _text(value, name, 36)
    try:
        parsed = str(uuid.UUID(value))
    except (ValueError, AttributeError):
        raise GuardDenied('Invalid ' + name) from None
    if parsed != value.lower():
        raise GuardDenied('Invalid ' + name)
    return parsed


def _integer(value, minimum=1):
    if (type(value) is int or
            isinstance(value, str) and len(value) <= 19 and
            value.isascii() and value.isdecimal()):
        number = int(value)
        if minimum <= number <= 2 ** 63 - 1:
            return number
    raise GuardUnavailable('Invalid backend integer')


def _b64(value):
    return base64.b64encode(value.encode('utf-8')).decode('ascii')


def _json_value(value):
    return _b64(json.dumps(value, sort_keys=True, separators=(',', ':')))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


class Gate:
    """Shared durable guard. Instances never cache admission or allowed state."""

    _CAS_ATTEMPTS = 8

    def __init__(self, endpoint, prefix='/powerops/watcher-automation/v1',
                 timeout=5.0, ca_file=None, cert_file=None, key_file=None):
        _text(endpoint, 'endpoint', 2048)
        try:
            parsed = urlsplit(endpoint)
            if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.query or parsed.fragment or parsed.path not in ('', '/')
                    or any(char.isspace() for char in endpoint)):
                raise ValueError
            parsed.port
        except ValueError:
            raise GuardDenied('Invalid endpoint') from None
        _text(prefix, 'prefix', 1024)
        if (not prefix.startswith('/') or prefix.endswith('/') or
                any(part in ('', '.', '..') for part in prefix[1:].split('/'))):
            raise GuardDenied('Invalid prefix')
        if (type(timeout) not in (int, float) or not math.isfinite(timeout)
                or timeout <= 0):
            raise GuardDenied('Invalid timeout')
        for name, value in [('ca_file', ca_file), ('cert_file', cert_file),
                            ('key_file', key_file)]:
            if value is not None:
                _text(value, name, 4096)
        if key_file and not cert_file:
            raise GuardDenied('Client key requires certificate')
        self.endpoint = endpoint.rstrip('/')
        self.prefix = prefix
        self.timeout = float(timeout)
        self.verify = ca_file if ca_file is not None else True
        self.cert = (cert_file, key_file) if key_file else cert_file
        self._state_key = _b64(prefix + '/state')

    def _request(self, path, body):
        try:
            response = requests.post(
                self.endpoint + '/v3/kv/' + path, json=body,
                timeout=self.timeout, verify=self.verify, cert=self.cert,
                allow_redirects=False)
            if response.status_code != 200:
                raise GuardUnavailable('Backend request failed')
            result = response.json(object_pairs_hook=_unique_object)
            if not isinstance(result, dict) or 'error' in result:
                raise GuardUnavailable('Invalid backend response')
            self._revision(result)
            return result
        except (requests.RequestException, ValueError, OSError, RecursionError):
            # Never interpolate requests exceptions, URLs or backend error text.
            raise GuardUnavailable('Backend request unavailable') from None

    @staticmethod
    def _revision(response):
        if not isinstance(response, dict) or not isinstance(response.get('header'), dict):
            raise GuardUnavailable('Missing backend revision')
        return _integer(response['header'].get('revision'))

    def _decode_range(self, response, key):
        revision = self._revision(response)
        values = response.get('kvs', [])
        if (not isinstance(values, list) or len(values) > 1
                or _integer(response.get('count', '0'), minimum=0) != len(values)
                or response.get('more', False) is not False):
            raise GuardUnavailable('Invalid backend range')
        if not values:
            return None
        kv = values[0]
        if not isinstance(kv, dict) or kv.get('key') != key:
            raise GuardUnavailable('Invalid backend key')
        mod_revision = _integer(kv.get('mod_revision'))
        if (mod_revision > revision or
                _integer(kv.get('create_revision')) > mod_revision or
                _integer(kv.get('lease', '0'), minimum=0) != 0):
            raise GuardUnavailable('Invalid backend key metadata')
        _integer(kv.get('version'))
        try:
            value = json.loads(base64.b64decode(kv['value'], validate=True),
                               object_pairs_hook=_unique_object)
        except (KeyError, TypeError, ValueError, binascii.Error, UnicodeError,
                RecursionError):
            raise GuardUnavailable('Invalid backend value') from None
        if not isinstance(value, dict):
            raise GuardUnavailable('Invalid backend value')
        return value, mod_revision

    def _read(self, key):
        return self._decode_range(self._request('range', {
            'key': key, 'serializable': False}), key)

    @staticmethod
    def _validate_state(value, revision):
        fields = {'schema', 'epoch', 'blocked', 'incident_id', 'host', 'actor', 'reason'}
        if (set(value) != fields or type(value['schema']) is not int or value['schema'] != 1
                or type(value['blocked']) is not bool):
            raise GuardUnavailable('Invalid guard state schema')
        try:
            if _uuid(value['epoch'], 'epoch') != value['epoch']:
                raise GuardDenied('Invalid epoch')
            _text(value['actor'], 'actor')
            _text(value['reason'], 'reason', 1024)
            if value['incident_id'] is None:
                if value['host'] is not None:
                    raise GuardDenied('Invalid host')
            else:
                if _uuid(value['incident_id'], 'incident id') != value['incident_id']:
                    raise GuardDenied('Invalid incident id')
                _text(value['host'], 'host')
        except GuardDenied:
            raise GuardUnavailable('Invalid guard state') from None
        return dict(value, revision=revision)

    def _state(self, allow_missing=False):
        record = self._read(self._state_key)
        if record is None:
            if allow_missing:
                return None
            raise GuardDenied('Guard state is missing')
        return self._validate_state(*record)

    @staticmethod
    def _compare(key, revision):
        if revision == 0:
            return {'key': key, 'target': 'VERSION', 'result': 'EQUAL', 'version': '0'}
        return {'key': key, 'target': 'MOD', 'result': 'EQUAL',
                'mod_revision': str(revision)}

    def _txn(self, compare, success, failure=None):
        failure = failure or []
        result = self._request('txn', {'compare': compare, 'success': success,
                                       'failure': failure})
        succeeded = result.get('succeeded', False)
        if type(succeeded) is not bool:
            raise GuardUnavailable('Invalid backend transaction result')
        ops = success if succeeded else failure
        responses = result.get('responses', [])
        if not isinstance(responses, list) or len(responses) != len(ops):
            raise GuardUnavailable('Incomplete backend transaction')
        for operation, response in zip(ops, responses):
            kind = 'response_put' if 'request_put' in operation else 'response_range'
            if (not isinstance(response, dict) or set(response) != {kind}
                    or not isinstance(response[kind], dict)):
                raise GuardUnavailable('Invalid backend transaction operation')
        return succeeded, result

    @staticmethod
    def _put(key, value):
        return {'request_put': {'key': key, 'value': _json_value(value)}}

    @staticmethod
    def _new_state(blocked, actor, reason, incident_id=None, host=None):
        return {'schema': 1, 'epoch': str(uuid.uuid4()), 'blocked': blocked,
                'incident_id': incident_id, 'host': host, 'actor': actor, 'reason': reason}

    def _committed(self, state, response, previous_revision=0):
        revision = self._revision(response)
        if revision <= previous_revision:
            raise GuardUnavailable('Invalid committed revision')
        return self._validate_state(state, revision)

    def status(self):
        """Read validated state linearly; absence is a denial, never allowed."""
        return self._state()

    def initialize(self, actor, reason):
        """Create blocked state once. Existing state is never changed."""
        _text(actor, 'actor')
        _text(reason, 'reason', 1024)
        state = self._new_state(True, actor, reason)
        ok, result = self._txn(
            [self._compare(self._state_key, 0)], [self._put(self._state_key, state)],
            [{'request_range': {'key': self._state_key, 'serializable': False}}])
        if ok:
            return self._committed(state, result)
        record = self._decode_range(result['responses'][0]['response_range'], self._state_key)
        if record is None:
            raise GuardDenied('Guard state is missing')
        return self._validate_state(*record)

    def hold(self, incident_id, host, reason='Masakari host failure'):
        """Persist a distinct incident and hold atomically, without a lease."""
        incident_id = _uuid(incident_id, 'incident id')
        _text(host, 'host')
        _text(reason, 'reason', 1024)
        marker_key = _b64(self.prefix + '/incidents/' + incident_id)
        for _attempt in range(self._CAS_ATTEMPTS):
            previous = self._state(allow_missing=True)
            marker = self._read(marker_key)
            if marker is not None:
                value, _revision = marker
                if (set(value) != {'schema', 'incident_id', 'host'} or
                        type(value['schema']) is not int or value['schema'] != 1 or
                        value['incident_id'] != incident_id):
                    raise GuardUnavailable('Invalid incident marker')
                try:
                    _text(value['host'], 'host')
                except GuardDenied:
                    raise GuardUnavailable('Invalid incident marker') from None
                return self.status()
            revision = previous['revision'] if previous else 0
            state = self._new_state(True, 'masakari', reason, incident_id, host)
            marker_value = {'schema': 1, 'incident_id': incident_id, 'host': host}
            ok, result = self._txn(
                [self._compare(self._state_key, revision), self._compare(marker_key, 0)],
                [self._put(self._state_key, state), self._put(marker_key, marker_value)])
            if ok:
                return self._committed(state, result, revision)
        raise GuardConflict('Guard state changed repeatedly')

    def resume(self, expected_revision, actor, reason):
        """Explicit exact-revision CAS into a new unblocked epoch."""
        if type(expected_revision) is not int or not 1 <= expected_revision <= 2 ** 63 - 1:
            raise GuardDenied('Invalid expected revision')
        _text(actor, 'actor')
        _text(reason, 'reason', 1024)
        previous = self.status()
        if previous['revision'] != expected_revision:
            raise GuardConflict('Guard revision changed')
        state = self._new_state(False, actor, reason, previous['incident_id'], previous['host'])
        ok, result = self._txn([self._compare(self._state_key, expected_revision)],
                                [self._put(self._state_key, state)])
        if not ok:
            raise GuardConflict('Guard revision changed')
        return self._committed(state, result, expected_revision)

    def admit(self, expected_epoch=None):
        """Return epoch only after an exact-generation linearizable admission.

        A successful admission preceding a hold may still reach Nova later.
        This method neither drains nor cancels already admitted operations.
        """
        if expected_epoch is not None:
            expected_epoch = _uuid(expected_epoch, 'expected epoch')
        state = self.status()
        if state['blocked']:
            raise GuardDenied('Scheduled automation is held')
        if expected_epoch is not None and state['epoch'] != expected_epoch:
            raise GuardDenied('Automation epoch changed')
        ok, result = self._txn([self._compare(self._state_key, state['revision'])],
                                [{'request_range': {'key': self._state_key,
                                                    'serializable': False}}])
        if not ok:
            raise GuardConflict('Automation generation changed during admission')
        record = self._decode_range(result['responses'][0]['response_range'], self._state_key)
        if record is None or self._validate_state(*record) != state:
            raise GuardUnavailable('Inconsistent admission response')
        return state['epoch']
