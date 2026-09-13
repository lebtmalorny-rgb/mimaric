"""Small etcd JSON-gateway double; real etcd validates its protocol assumptions."""
import base64
import copy
import threading


def b64(value):
    return base64.b64encode(value.encode()).decode()


class Response:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self, **kwargs):
        return copy.deepcopy(self.body)


class Etcd:
    def __init__(self):
        self.data = {}
        self.revision = 1
        self.lock = threading.RLock()
        self.before_txn = None
        self.requests = []

    def header(self):
        return {'revision': str(self.revision), 'cluster_id': '1',
                'member_id': '1', 'raft_term': '1'}

    def range(self, request):
        assert request.get('serializable', False) is False
        key = request['key']
        result = {'header': self.header()}
        if key in self.data:
            result.update(kvs=[copy.deepcopy(self.data[key])], count='1')
        return result

    def put(self, key, value):
        old = self.data.get(key)
        self.data[key] = {'key': key, 'value': value,
                          'mod_revision': str(self.revision),
                          'create_revision': (old['create_revision'] if old
                                              else str(self.revision)),
                          'version': str(int(old['version']) + 1 if old else 1)}

    def txn(self, request):
        if self.before_txn:
            callback, self.before_txn = self.before_txn, None
            callback()
        ok = True
        for compare in request['compare']:
            kv = self.data.get(compare['key'], {})
            field = {'MOD': 'mod_revision', 'VERSION': 'version'}[compare['target']]
            assert compare['result'] == 'EQUAL'
            ok &= int(kv.get(field, 0)) == int(compare[field])
        ops = request['success' if ok else 'failure']
        if any('request_put' in op for op in ops):
            self.revision += 1
        responses = []
        for op in ops:
            if 'request_put' in op:
                put = op['request_put']
                assert not put.get('lease'), 'Guard keys must never expire'
                self.put(put['key'], put['value'])
                responses.append({'response_put': {'header': self.header()}})
            else:
                responses.append({'response_range': self.range(op['request_range'])})
        # Gateway protobuf JSON may omit false/default fields.
        result = {'header': self.header(), 'responses': responses}
        if ok:
            result['succeeded'] = True
        return result

    def post(self, url, **kwargs):
        with self.lock:
            self.requests.append((url, copy.deepcopy(kwargs)))
            if url.endswith('/v3/kv/range'):
                return Response(self.range(kwargs['json']))
            assert url.endswith('/v3/kv/txn')
            return Response(self.txn(kwargs['json']))
