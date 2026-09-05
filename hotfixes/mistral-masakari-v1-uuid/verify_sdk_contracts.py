# Copyright 2026 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Offline audit of PowerOps calls through real openstacksdk proxies.

Run with the Mistral test virtualenv. All HTTP is intercepted by requests-mock;
this script never connects to OpenStack or issues real power operations.
"""

import unittest

from keystoneauth1 import fixture
from keystoneauth1.identity import v3
from keystoneauth1 import session
from openstack import connection
import requests_mock

from mistral.actions.powerops import clients
from mistral.actions.powerops import exceptions
from mistral import config


config.parse_args(args=[], default_config_files=[])
config.CONF.set_override('instance_interval', 0, group='powerops')


class SDKContractAudit(unittest.TestCase):
    host = 'compute-01.example'
    other_host = 'compute-02.example'
    service_id = '00000000-0000-0000-0000-000000000001'
    server_id = '00000000-0000-0000-0000-000000000002'
    node_id = '00000000-0000-0000-0000-000000000003'

    def setUp(self):
        self.http = requests_mock.Mocker(real_http=False)
        self.http.start()
        self.addCleanup(self.http.stop)
        token = fixture.V3Token()
        for service_type, name, endpoint in (
            ('compute', 'nova', 'http://nova.example/v2.1'),
            ('baremetal', 'ironic', 'http://ironic.example/v1'),
        ):
            service = token.add_service(service_type, name)
            service.add_endpoint('internal', endpoint, region='RegionOne')
        self.http.post(
            'http://identity.example/v3/auth/tokens', json=token,
            headers={'X-Subject-Token': 'offline-test-token'},
        )
        for endpoint, version_id, minimum, maximum in (
            ('http://nova.example/v2.1', 'v2.1', '2.1', '2.96'),
            ('http://ironic.example/v1', 'v1', '1.1', '1.95'),
        ):
            version = {
                'id': version_id, 'status': 'CURRENT',
                'min_version': minimum, 'version': maximum,
                'links': [{'rel': 'self', 'href': endpoint + '/'}],
            }
            self.http.get(endpoint, json={'version': version})

        auth = v3.Password(
            auth_url='http://identity.example/v3', username='mistral',
            password='offline-test-password', project_name='service',
            user_domain_name='Default', project_domain_name='Default',
        )
        self.cloud = clients.CloudClients(
            connection.Connection(
                session=session.Session(auth=auth),
                region_name='RegionOne', interface='internal',
            ),
            sleep=lambda _seconds: None,
        )
        self.service = {
            'id': self.service_id, 'binary': 'nova-compute', 'host': self.host,
            'status': 'enabled', 'state': 'up', 'disabled_reason': None,
        }
        self.server = {
            'id': self.server_id, 'status': 'ACTIVE',
            'OS-EXT-SRV-ATTR:host': self.host,
            'OS-EXT-SRV-ATTR:hypervisor_hostname': self.host,
        }
        self.node = {
            'uuid': self.node_id, 'name': self.host, 'power_state': 'power on',
            'target_power_state': None, 'last_error': None,
            'provision_state': 'manageable', 'network_interface': 'noop',
        }
        self.events = []
        self.http.get(
            'http://nova.example/v2.1/os-services',
            json=lambda request, context: {'services': [self.service]},
        )
        self.http.put(
            'http://nova.example/v2.1/os-services/' + self.service_id,
            json=self._update_service,
        )
        self.http.get(
            'http://nova.example/v2.1/servers/detail',
            json=self._servers,
        )
        self.http.get(
            'http://nova.example/v2.1/servers/' + self.server_id,
            json=lambda request, context: {'server': self.server},
        )
        self.http.post(
            'http://nova.example/v2.1/servers/' + self.server_id + '/action',
            json=self._server_action,
        )
        self.http.get(
            'http://ironic.example/v1/nodes/detail',
            json=lambda request, context: {'nodes': [self.node]},
        )
        self.http.get(
            'http://ironic.example/v1/nodes/' + self.node_id,
            json=lambda request, context: self.node,
        )
        self.http.put(
            'http://ironic.example/v1/nodes/' + self.node_id + '/states/power',
            json=self._power,
        )

    def _update_service(self, request, context):
        self.assertEqual('compute 2.69',
                         request.headers['OpenStack-API-Version'])
        self.events.append(request.json())
        self.service.update(request.json())
        return {'service': self.service}

    def _servers(self, request, context):
        self.assertEqual(['true'], request.qs['all_tenants'])
        host = request.qs.get('host')
        found = (not host or
                 host == [self.server['OS-EXT-SRV-ATTR:host']])
        return {'servers': [self.server] if found else []}

    def _server_action(self, request, context):
        body = request.json()
        self.events.append(body)
        if 'os-stop' in body:
            self.server['status'] = 'SHUTOFF'
        elif 'os-start' in body:
            self.server['status'] = 'ACTIVE'
        elif 'os-migrateLive' in body:
            self.assertEqual('compute 2.30',
                             request.headers['OpenStack-API-Version'])
            self.server['OS-EXT-SRV-ATTR:host'] = self.other_host
        else:
            self.fail('Unexpected Nova action: ' + repr(body))
        context.status_code = 202
        return None

    def _power(self, request, context):
        body = request.json()
        self.events.append(body)
        if body['target'] == 'soft power off':
            service_type, version = request.headers[
                'OpenStack-API-Version'].split()
            self.assertEqual('baremetal', service_type)
            # 1.27 is the minimum, not an exact pin: SDK may negotiate higher.
            self.assertGreaterEqual(tuple(map(int, version.split('.'))),
                                    (1, 27))
        self.node['power_state'] = (
            'power on' if body['target'] == 'power on' else 'power off'
        )
        context.status_code = 202
        return None

    def test_nova_disable_and_enable(self):
        self.cloud.disable_nova(self.host, 'PowerOps planned operation')
        self.assertEqual('disabled', self.service['status'])
        self.cloud.enable_nova(self.host)
        self.assertEqual('enabled', self.service['status'])
        self.assertEqual([
            {'status': 'disabled',
             'disabled_reason': 'PowerOps planned operation'},
            {'status': 'enabled'},
        ], self.events)

    def test_stop_manifest_and_restart(self):
        manifest = self.cloud.apply_instance_policy(self.host, 'stop')
        self.assertEqual([self.server_id], manifest)
        self.cloud.assert_host_safe_for_power_off(self.host, 'stop', manifest)
        self.cloud.start_instances(self.host, manifest)
        self.assertEqual('ACTIVE', self.server['status'])
        self.assertEqual([{'os-stop': None}, {'os-start': None}], self.events)

    def test_live_migration_and_source_empty_guard(self):
        self.assertEqual([], self.cloud.apply_instance_policy(
            self.host, 'live_migrate'))
        self.cloud.assert_host_safe_for_power_off(
            self.host, 'live_migrate', [])
        self.assertEqual([{'os-migrateLive': {
            'host': None, 'block_migration': 'auto',
        }}], self.events)

    def test_restart_rejects_foreign_host_without_sending_start(self):
        self.server['OS-EXT-SRV-ATTR:host'] = self.other_host
        self.server['status'] = 'SHUTOFF'
        with self.assertRaises(exceptions.InstanceManifestError):
            self.cloud.start_instances(self.host, [self.server_id])

        self.assertEqual('SHUTOFF', self.server['status'])
        self.assertFalse(any(
            request.method == 'POST' and '/servers/' in request.url
            for request in self.http.request_history
        ))

    def test_require_empty_rejects_populated_host(self):
        with self.assertRaises(clients.exceptions.InstancePolicyError):
            self.cloud.apply_instance_policy(self.host, 'require_empty')
        self.assertEqual([], self.events)

    def test_ironic_soft_off_and_power_on(self):
        off = self.cloud.power_off(self.host, allow_hard_off=False)
        self.assertEqual('power off', off.power_state)
        on = self.cloud.power_on(self.host)
        self.assertEqual('power on', on.power_state)
        self.assertEqual([
            {'target': 'soft power off'}, {'target': 'power on'},
        ], self.events)


if __name__ == '__main__':
    unittest.main(verbosity=2)
