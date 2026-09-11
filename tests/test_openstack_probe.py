from pathlib import Path
import sys
import unittest
import importlib.util
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openstack_probe import Probe
from scenario_runner import Incomplete


class Response:
    def __init__(self, data, code=200): self.data, self.status_code = data, code
    def json(self): return self.data


class Session:
    def __init__(self, responses): self.responses = iter(responses); self.calls = []
    def request(self, url, method, **kwargs):
        self.calls.append((url, method, kwargs)); return next(self.responses)


class ProbeTests(unittest.TestCase):
    def probe(self, responses):
        session = Session(responses)
        return Probe(session, dict(compute='https://nova/v2.1/project', **{
            'instance-ha':'https://ha/v1', 'workflowv2':'https://mistral/v2', 'baremetal':'https://ironic/v1'})), session
    def test_pagination_continues_after_short_server_limited_page(self):
        probe, session = self.probe([Response({'migrations':[{'uuid':'a'}]}),
                                    Response({'migrations':[{'uuid':'b'}]}), Response({'migrations':[]})])
        self.assertEqual(['a','b'], [m['uuid'] for m in probe.pages('compute','/os-migrations','migrations','uuid')])
        self.assertEqual('a', session.calls[1][2]['params']['marker'])
        self.assertEqual('compute 2.59', session.calls[0][2]['headers']['OpenStack-API-Version'])
    def test_ignored_pagination_is_incomplete(self):
        probe, _ = self.probe([Response({'hosts':[{'uuid':'a'}]}), Response({'hosts':[{'uuid':'a'}]})])
        with self.assertRaises(Incomplete): probe.pages('instance-ha','/hosts','hosts','uuid')
    def test_mistral_json_strings_and_safe_output(self):
        probe, _ = self.probe([Response(dict(id='id', workflow_name='name', description='description', state='SUCCESS',
            input='{"host":"compute1"}', output='{"result":{"host":"compute1","secret":"hidden"}}',
            params='{"env":{"password":"hidden","stale_domains_checked":true}}'))])
        result = probe.execution('id')
        self.assertNotIn('hidden', str(result))
        self.assertIs(result['params']['env']['stale_domains_checked'], True)
    def test_no_automatic_http_retries_or_redirects_for_create(self):
        probe, session = self.probe([Response({}, 503)])
        with self.assertRaises(Incomplete): probe.create({'id':'id'})
        args = session.calls[0][2]
        self.assertEqual(0, args['connect_retries']); self.assertEqual(0, args['status_code_retries'])
        self.assertIs(args['allow_redirects'], False)
        self.assertIs(args['redirect'], False); self.assertIs(args['allow_reauth'], False)
        self.assertIs(args['log'], False)
        self.assertEqual(1, len(session.calls))
    def test_missing_task_state_is_not_treated_as_idle(self):
        probe, _ = self.probe([])
        with self.assertRaises(Incomplete): probe.server(dict(id='vm',status='ACTIVE',**{'OS-EXT-SRV-ATTR:host':'host'}))
    def test_only_execution_not_found_returns_none(self):
        probe, _ = self.probe([Response({},404),Response({},404)])
        self.assertIsNone(probe.execution('id'))
        with self.assertRaises(Incomplete): probe.get('baremetal','/nodes/missing')

    def test_error_workflow_output_is_not_parsed_as_success_result(self):
        probe, _ = self.probe([Response(dict(id='id',workflow_name='name',description='d',state='ERROR',
            input='{}',output='{"result":"failure with SECRET diagnostic"}'))])
        result = probe.execution('id')
        self.assertEqual('ERROR',result['state'])
        self.assertNotIn('SECRET',str(result))

    def test_auth_and_discovery_receive_timeout_before_first_endpoint_lookup(self):
        session = SimpleNamespace(timeout=None,get_project_id=lambda:'project',get_user_id=lambda:'user')
        def client(service, version):
            self.assertEqual(30,session.timeout)
            return SimpleNamespace(get_endpoint=lambda:'https://example.invalid/v' + version)
        connection = SimpleNamespace(session=session,config=SimpleNamespace(get_session_client=client))
        def connect(**kwargs):
            self.assertEqual(30,kwargs['api_timeout']); return connection
        with patch.dict(sys.modules,{'openstack':SimpleNamespace(connect=connect)}):
            _,identity = Probe.connect({})
        self.assertEqual('project',identity['project_id'])

    @unittest.skipUnless(importlib.util.find_spec('keystoneauth1'), 'SDK dependencies are not installed')
    def test_real_keystone_session_never_retries_or_follows_post_redirect(self):
        from keystoneauth1 import session, noauth
        from requests import Response as RealResponse
        for status in (302, 401, 503):
            with self.subTest(status=status):
                real = session.Session(auth=noauth.NoAuth())
                response = RealResponse()
                response.status_code = status
                response._content = b'{}'
                response.url = 'https://mistral.invalid/v2/executions'
                response.headers['Location'] = 'https://other.invalid/collect'
                probe = Probe(real, {'workflowv2':'https://mistral.invalid/v2'})
                with patch.object(real.session,'request',return_value=response) as request:
                    with self.assertRaises(Incomplete): probe.create({'id':'fixture'})
                    self.assertEqual(1,request.call_count)


if __name__ == '__main__': unittest.main()
