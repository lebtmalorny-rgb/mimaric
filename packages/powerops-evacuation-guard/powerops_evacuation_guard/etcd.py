"""Strict, non-retrying etcd v3 JSON transport. Claims never use leases."""
import base64
import binascii
import json
import math
from urllib.parse import urlsplit

import requests


class GuardError(Exception):
    """No new evacuation side effect is authorized by this error."""


class GuardDenied(GuardError):
    """The operation is not authorized."""


class GuardBusy(GuardDenied):
    """No target or global capacity; a WAITING owner may poll again."""


class GuardDuplicate(GuardDenied):
    """A durable identity already exists; never execute it again."""


class GuardConflict(GuardDenied):
    """Ownership or observed revision changed."""


class GuardUnavailable(GuardDenied):
    """Backend data or outcome cannot be trusted."""


def text(value, name, maximum=255):
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise GuardDenied('Invalid ' + name)
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise GuardDenied('Invalid ' + name) from None
    return value


def number(value, name, minimum=0, strict=False):
    try:
        valid = (type(value) in (int, float) and math.isfinite(value)
                 and value >= minimum and not (strict and value == minimum))
    except OverflowError:
        valid = False
    if not valid:
        raise GuardDenied('Invalid ' + name)
    return float(value)


def integer(value, minimum=1, maximum=2**63-1):
    if (type(value) is int or isinstance(value, str) and len(value) <= len(str(maximum))
            and value.isascii() and value.isdecimal()):
        value = int(value)
        if minimum <= value <= maximum:
            return value
    raise GuardUnavailable('Invalid backend integer')


def b64(value):
    return base64.b64encode(value.encode('utf-8')).decode('ascii')


def unique(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ValueError('Duplicate field')
        result[k] = v
    return result


def prefix_end(prefix):
    # Guard prefixes and key suffixes end in ASCII '/'.
    return prefix[:-1] + chr(ord(prefix[-1]) + 1)


class Etcd:
    def __init__(self, endpoint, timeout=5.0, ca_file=None, cert_file=None, key_file=None):
        text(endpoint, 'endpoint', 2048)
        try:
            p = urlsplit(endpoint)
            if (p.scheme not in ('http', 'https') or not p.hostname
                    or p.username is not None or p.password is not None
                    or '?' in endpoint or '#' in endpoint or p.netloc.endswith(':')
                    or p.path not in ('', '/')
                    or any(c.isspace() for c in endpoint) or p.port == 0):
                raise ValueError
        except ValueError:
            raise GuardDenied('Invalid endpoint') from None
        self.endpoint = endpoint.rstrip('/')
        self.timeout = number(timeout, 'timeout', strict=True)
        for name, value in (('ca_file', ca_file), ('cert_file', cert_file), ('key_file', key_file)):
            if value is not None:
                text(value, name, 4096)
        if bool(cert_file) != bool(key_file):
            raise GuardDenied('Client certificate and key must be paired')
        self.verify = ca_file if ca_file else True
        self.cert = (cert_file, key_file) if cert_file else None

    @staticmethod
    def revision(response):
        if not isinstance(response, dict) or not isinstance(response.get('header'), dict):
            raise GuardUnavailable('Missing backend revision')
        return integer(response['header'].get('revision'))

    def request(self, path, body):
        try:
            r = requests.post(self.endpoint + '/v3/kv/' + path, json=body,
                              timeout=self.timeout, verify=self.verify, cert=self.cert,
                              allow_redirects=False)
            if r.status_code != 200:
                raise GuardUnavailable('Backend request failed')
            result = r.json(object_pairs_hook=unique)
            if not isinstance(result, dict) or 'error' in result:
                raise GuardUnavailable('Invalid backend response')
            self.revision(result)
            return result
        except (requests.RequestException, ValueError, OSError, RecursionError):
            raise GuardUnavailable('Backend request unavailable') from None

    def range(self, key, end=None, limit=None):
        request = {'key': b64(key), 'serializable': False}
        if end is not None:
            request['range_end'] = b64(end)
        if limit is not None:
            request['limit'] = str(limit)
        result = self.request('range', request)
        revision = self.revision(result)
        kvs = result.get('kvs', [])
        more = result.get('more', False)
        count = integer(result.get('count', '0'), 0)
        if (not isinstance(kvs, list) or type(more) is not bool or count < len(kvs)
                or limit is not None and len(kvs) > limit
                or not more and count != len(kvs)
                or more and (limit is None or len(kvs) != limit or count <= len(kvs))):
            raise GuardUnavailable('Invalid backend range')
        records, last = [], None
        for kv in kvs:
            try:
                decoded_key = base64.b64decode(kv['key'], validate=True).decode('utf-8')
                value = json.loads(base64.b64decode(kv['value'], validate=True), object_pairs_hook=unique)
                mod = integer(kv['mod_revision'])
                create = integer(kv['create_revision'])
                integer(kv['version'])
                if (integer(kv.get('lease', '0'), 0) != 0 or create > mod or mod > revision
                        or not isinstance(value, dict) or not (key <= decoded_key < end if end else decoded_key == key)
                        or last is not None and decoded_key <= last):
                    raise ValueError
            except (KeyError, TypeError, ValueError, binascii.Error, UnicodeError, RecursionError):
                raise GuardUnavailable('Invalid backend record') from None
            records.append((decoded_key, value, mod))
            last = decoded_key
        if end is None and (len(records) > 1 or more):
            raise GuardUnavailable('Invalid exact range')
        return records, more, revision

    def read(self, key):
        records, _, _ = self.range(key)
        return (records[0][1], records[0][2]) if records else None

    @staticmethod
    def compare(key, revision=0, end=None):
        result = {'key': b64(key), 'result': 'EQUAL',
                  'target': 'MOD' if revision else 'VERSION',
                  'mod_revision' if revision else 'version': str(revision)}
        if end is not None:
            result['range_end'] = b64(end)
        return result

    @staticmethod
    def put(key, value):
        return {'request_put': {'key': b64(key), 'value': b64(json.dumps(
            value, sort_keys=True, separators=(',', ':'), allow_nan=False))}}

    @staticmethod
    def delete(key):
        return {'request_delete_range': {'key': b64(key)}}

    def txn(self, compare, success):
        result = self.request('txn', {'compare': compare, 'success': success, 'failure': []})
        succeeded = result.get('succeeded', False)
        responses = result.get('responses', [])
        expected = success if succeeded else []
        if (type(succeeded) is not bool or not isinstance(responses, list)
                or len(responses) != len(expected)):
            raise GuardUnavailable('Invalid backend transaction outcome')
        revision = self.revision(result)
        for request, response in zip(expected, responses):
            kind = next(iter(request)).replace('request_', 'response_')
            if (not isinstance(response, dict) or set(response) != {kind}
                    or not isinstance(response[kind], dict)):
                raise GuardUnavailable('Invalid backend transaction operation')
            payload = response[kind]
            allowed = {'header', 'deleted'} if kind == 'response_delete_range' else {'header'}
            if set(payload) - allowed:
                raise GuardUnavailable('Unexpected backend transaction payload')
            if 'header' in payload:
                header = payload['header']
                if (not isinstance(header, dict)
                        or set(header) - {'revision', 'cluster_id', 'member_id', 'raft_term'}):
                    raise GuardUnavailable('Invalid transaction operation header')
                # Protobuf may omit the header or its default fields. Validate
                # fields that are supplied without requiring cluster/member/term.
                if 'revision' in header and integer(header['revision']) != revision:
                    raise GuardUnavailable('Inconsistent transaction operation revision')
                for field in ('cluster_id', 'member_id', 'raft_term'):
                    if field in header:
                        integer(header[field], 0, 2**64-1)
            if kind == 'response_delete_range' and integer(payload.get('deleted', '0'), 0) != 1:
                raise GuardUnavailable('Inconsistent claim deletion')
        if succeeded and revision <= max((int(c.get('mod_revision', 0)) for c in compare), default=0):
            raise GuardUnavailable('Invalid committed revision')
        return succeeded, revision
