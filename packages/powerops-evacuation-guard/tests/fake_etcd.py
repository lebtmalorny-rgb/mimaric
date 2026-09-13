"""Transactional gateway double; same tests also run against actual etcd."""
import base64
import copy
import threading


def raw(value):
    return base64.b64decode(value)


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
        self.after_txn = None

    def header(self):
        return {'revision': str(self.revision)}

    def keys(self, req):
        lo = raw(req['key'])
        hi = raw(req['range_end']) if 'range_end' in req else None
        return sorted(k for k in self.data if (lo <= k < hi if hi else k == lo))

    def range(self, req):
        keys = self.keys(req)
        limited = keys[:int(req.get('limit', len(keys)))]
        return {'header': self.header(), 'kvs': [self.data[k] for k in limited],
                'count': str(len(keys)), 'more': len(limited) < len(keys)}

    def txn(self, req):
        if self.before_txn:
            call, self.before_txn = self.before_txn, None
            call()
        ok = True
        for cmp in req['compare']:
            field = {'MOD': 'mod_revision', 'VERSION': 'version'}[cmp['target']]
            values = [self.data[k] for k in self.keys(cmp)] or [{}]
            ok &= all(int(v.get(field, 0)) == int(cmp[field]) for v in values)
        ops = req['success' if ok else 'failure']
        if ops:
            self.revision += 1
        out = []
        for op in ops:
            if 'request_put' in op:
                p = op['request_put']
                assert not p.get('lease')
                key = raw(p['key'])
                old = self.data.get(key, {})
                self.data[key] = dict(key=p['key'], value=p['value'],
                    mod_revision=str(self.revision),
                    create_revision=old.get('create_revision', str(self.revision)),
                    version=str(int(old.get('version', 0)) + 1))
                out.append({'response_put': {'header': self.header()}})
            else:
                p = op['request_delete_range']
                keys = self.keys(p)
                for k in keys:
                    del self.data[k]
                out.append({'response_delete_range': {'header': self.header(),
                                                     'deleted': str(len(keys))}})
        body = {'header': self.header(), 'responses': out}
        if ok:
            body['succeeded'] = True
        if self.after_txn:
            call, self.after_txn = self.after_txn, None
            call()
        return body

    def post(self, url, **kwargs):
        with self.lock:
            if url.endswith('/range'):
                return Response(self.range(kwargs['json']))
            assert url.endswith('/txn')
            return Response(self.txn(kwargs['json']))
