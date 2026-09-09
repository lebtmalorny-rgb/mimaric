from types import SimpleNamespace
from unittest import mock

from django.test import override_settings
from django.test import SimpleTestCase

from poweropsdashboard import api
from poweropsdashboard import exceptions


SEGMENT_UUID = '11111111-1111-1111-1111-111111111111'


def _request():
    return SimpleNamespace(user=SimpleNamespace(
        username='ops-user',
        project_id='project-id',
        services_region='RegionOne',
        token=SimpleNamespace(id='current-user-token'),
    ))


def _assert_secret_free(test, value):
    forbidden = (
        'token', 'password', 'secret', 'bmc', 'driver_info',
        'instance_info', 'service_catalog',
    )
    if isinstance(value, dict):
        for key, child in value.items():
            test.assertFalse(any(item in key.lower() for item in forbidden))
            _assert_secret_free(test, child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_secret_free(test, child)


@override_settings(POWEROPS_MOCK_MODE=True)
class MockPowerOpsClientTests(SimpleTestCase):

    @mock.patch.object(api.mistral_client, 'client')
    @mock.patch.object(api.base, 'url_for')
    def test_factory_does_not_discover_or_construct_live_client(
            self, url_for, client_factory):
        client = api.get_client(_request())

        self.assertIsInstance(client, api.MockPowerOpsClient)
        url_for.assert_not_called()
        client_factory.assert_not_called()

    def test_all_read_methods_return_independent_secret_free_copies(self):
        client = api.MockPowerOpsClient()
        first_inventory = client.start_inventory()
        first_status = client.start_host_status('compute-01', SEGMENT_UUID)
        first_execution = client.get_execution(first_status['id'])
        first_list = client.list_executions(all_projects=True)
        first_tasks = client.list_tasks(first_status['id'])

        first_inventory['state'] = 'CORRUPTED'
        first_status['output']['result']['host'] = 'corrupted-host'
        first_execution['state'] = 'CORRUPTED'
        first_list[0]['state'] = 'CORRUPTED'
        first_tasks[0]['state'] = 'CORRUPTED'

        second_inventory = client.start_inventory()
        second_status = client.start_host_status('compute-01', SEGMENT_UUID)
        second_execution = client.get_execution(second_status['id'])
        second_list = client.list_executions(all_projects=True)
        second_tasks = client.list_tasks(second_status['id'])

        self.assertEqual('SUCCESS', second_inventory['state'])
        self.assertEqual(
            'compute-01', second_status['output']['result']['host'])
        self.assertEqual('SUCCESS', second_execution['state'])
        self.assertNotEqual('CORRUPTED', second_list[0]['state'])
        self.assertEqual('SUCCESS', second_tasks[0]['state'])
        for value in (second_inventory, second_status, second_execution,
                      second_list, second_tasks):
            _assert_secret_free(self, value)

    def test_every_mock_mutation_method_fails_with_fixed_message(self):
        client = api.MockPowerOpsClient()
        methods = (
            lambda: client.start_planned('power_off', {}),
            lambda: client.start_return({}),
            lambda: client.resume_return(
                'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'),
        )

        for invoke in methods:
            with self.subTest(invoke=invoke):
                with self.assertRaisesRegex(
                        exceptions.MockMutationDisabled,
                        '^PowerOps mutations are disabled in mock mode$'):
                    invoke()
