"""Bounded REST calls using the operator's OpenStack SDK authentication session.

No BMC credentials are fetched. Only allowlisted response fields reach journals.
"""
from urllib.parse import urlsplit, urlunsplit, quote

from scenario_runner import Incomplete, obj


def fields(data, names):
    try:
        return {name: data[name] for name in names.split()}
    except (KeyError, TypeError):
        raise Incomplete('required API field is absent; check policy and API version') from None


def optional(data, names):
    return {key: data[key] for key in names.split() if key in data}


class Probe:
    def __init__(self, session, endpoints):
        self.session, self.endpoints = session, endpoints

    @classmethod
    def connect(cls, task):
        try:
            import openstack
            kwargs = {k: task[k] for k in ('cloud', 'region_name') if task.get(k)}
            conn = openstack.connect(api_timeout=30, **kwargs)
            conn.session.timeout = 30  # Includes Keystone authentication/discovery.
            endpoints = {}
            for service, version in [('compute','2'), ('instance-ha','1'), ('baremetal','1'), ('workflowv2','2')]:
                adapter = conn.config.get_session_client(service, version=version)
                url = adapter.get_endpoint()
                parsed = urlsplit(url)
                if parsed.scheme not in ('https', 'http') or parsed.username or parsed.query or parsed.fragment:
                    raise ValueError('unsupported endpoint')
                path = parsed.path.rstrip('/')
                if service != 'compute' and not path.endswith('/v' + version):
                    path += '/v' + version
                endpoints[service] = urlunsplit((parsed.scheme, parsed.netloc, path, '', ''))
            session = conn.session
            identity = dict(project_id=session.get_project_id(), user_id=session.get_user_id(), endpoints=endpoints)
            if not identity['project_id'] or not identity['user_id']:
                raise ValueError('a project-scoped operator identity is required')
            return cls(session, endpoints), identity
        except ImportError:
            raise Incomplete('install requirements.txt in the Python 3.11 environment') from None
        except Exception:
            raise Incomplete('OpenStack authentication/service discovery failed; check clouds.yaml/OS_* locally') from None

    def request(self, service, path, method='GET', body=None, params=None, missing=False):
        versions = {'compute':'compute 2.59', 'instance-ha':'instance-ha 1.3'}
        headers = {'Accept':'application/json'}
        if service in versions:
            headers['OpenStack-API-Version'] = versions[service]
        if service == 'baremetal':
            headers['X-OpenStack-Ironic-API-Version'] = '1.52'
        try:
            response = self.session.request(self.endpoints[service] + path, method,
                json=body, params=params, headers=headers, timeout=30, raise_exc=False,
                connect_retries=0, status_code_retries=0, redirect=False, allow_redirects=False,
                allow_reauth=False, log=False)
            if missing and response.status_code == 404:
                return None
            if not 200 <= response.status_code < 300:
                raise Incomplete(f'{service} {method}: HTTP {response.status_code}; request outcome may be unknown')
            return response.json()
        except Incomplete:
            raise
        except Exception:
            # SDK/HTTP exceptions may include tokens, credentials or response bodies.
            raise Incomplete(f'{service} {method}: no valid API reply; request outcome may be unknown') from None

    def get(self, service, path, **params):
        return self.request(service, path, params=params)

    def pages(self, service, path, collection, marker_key, **filters):
        result, seen, marker = [], set(), None
        for _ in range(1000):
            query = dict(filters, limit=100)
            if marker is not None:
                query['marker'] = marker
            page = self.get(service, path, **query)[collection]
            if not isinstance(page, list):
                raise Incomplete('API collection is not a list')
            if not page:
                return result
            for item in page:
                key = item[marker_key]
                if key in seen:
                    raise Incomplete('API pagination repeated an item; complete enumeration cannot be proven')
                seen.add(key)
                result.append(item)
            marker = page[-1][marker_key]
        raise Incomplete('API pagination bound exceeded')

    @staticmethod
    def server(data):
        required = fields(data, 'id status OS-EXT-SRV-ATTR:host OS-EXT-STS:task_state')
        return dict(id=required['id'], status=required['status'], host=required['OS-EXT-SRV-ATTR:host'],
                    task_state=required['OS-EXT-STS:task_state'])

    def service(self, host):
        items = self.get('compute', '/os-services', host=host, binary='nova-compute')['services']
        if len(items) != 1:
            raise Incomplete('Nova service lookup is not unique')
        return fields(items[0], 'id host binary status state')

    def snapshot(self, task):
        node = fields(self.get('baremetal', '/nodes/' + quote(task['node_uuid'])),
                      'uuid name power_state target_power_state last_error maintenance')
        host = fields(self.get('instance-ha', f"/segments/{quote(task['segment_uuid'])}/hosts/{quote(task['ha_host_uuid'])}")['host'],
                      'uuid name failover_segment_id on_maintenance')
        source = [self.server(item) for item in self.pages('compute', '/servers/detail', 'servers', 'id',
                    all_tenants=1, host=task['host'])]
        if any(s['host'] != task['host'] for s in source):
            raise Incomplete('Nova ignored the compute host filter')
        migrations = [fields(m, 'uuid instance_uuid source_compute dest_compute migration_type status')
                      for m in self.pages('compute', '/os-migrations', 'migrations', 'uuid', host=task['host'])]
        if any(m['source_compute'] != task['host'] and m['dest_compute'] != task['host'] for m in migrations):
            raise Incomplete('Nova ignored the migration host filter')
        return dict(node=node, service=self.service(task['host']), ha_host=host,
            source_ids=[s['id'] for s in source], migrations=migrations,
            servers=[self.server(self.get('compute', '/servers/' + quote(ident))['server']) for ident in task['server_ids']],
            destinations=[self.service(h) for h in task['destination_hosts']])

    def notifications(self, task):
        return [fields(n, 'notification_uuid source_host_uuid type status payload') for n in self.pages(
            'instance-ha', '/notifications', 'notifications', 'notification_uuid', source_host_uuid=task['ha_host_uuid'])]

    def notification(self, ident):
        data = self.get('instance-ha', '/notifications/' + quote(ident))['notification']
        result = fields(data, 'notification_uuid source_host_uuid type status payload')
        result['recovery_workflow_details'] = data.get('recovery_workflow_details', [])
        return result

    def vmoves(self, ident):
        path = '/notifications/' + quote(ident) + '/vmoves'
        result = []
        for item in self.pages('instance-ha', path, 'vmoves', 'uuid'):
            move = self.get('instance-ha', path + '/' + quote(item['uuid']))['vmove']
            result.append(fields(move, 'uuid notification_uuid instance_uuid source_host dest_host type status start_time end_time'))
        return result

    def execution(self, ident):
        data = self.request('workflowv2', '/executions/' + quote(ident), missing=True)
        if data is None:
            return None
        result = fields(data, 'id workflow_name description state input')
        result['input'] = obj(result['input'])
        if result['state'] in ('ERROR', 'CANCELLED'):
            # Failed workflows put a human error string in output.result. The
            # state is sufficient evidence; do not parse or persist that string.
            result.update(output={}, params={})
            return result
        output = obj(data.get('output') or {})
        result['output'] = optional(output, 'stopped_instance_ids')
        if 'result' in output:
            result['output']['result'] = optional(obj(output['result']),
                'host operation power_state stopped_instance_ids nova_enabled masakari_maintenance')
        env = obj(obj(data.get('params') or {}).get('env') or {})
        result['params'] = dict(env=optional(env, 'stale_domains_checked'))
        return result

    def tasks(self, ident):
        return [fields(t, 'id name state workflow_execution_id') for t in self.pages(
            'workflowv2', '/tasks', 'tasks', 'id', workflow_execution_id=ident)]

    def create(self, body):
        self.request('workflowv2', '/executions', 'POST', body=body)

    def resume(self, ident, body):
        self.request('workflowv2', '/executions/' + quote(ident), 'PUT', body=body)
