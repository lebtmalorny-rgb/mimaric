import ast
import pathlib
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.test import override_settings
from django.test import SimpleTestCase

from poweropsdashboard import api
from poweropsdashboard import constants
from poweropsdashboard import exceptions


SEGMENT_UUID = '11111111-1111-1111-1111-111111111111'


def _request(region='RegionOne'):
    user = SimpleNamespace(
        username='ops-user',
        project_id='project-id',
        services_region=region,
        token=SimpleNamespace(id='current-user-token'),
    )
    return SimpleNamespace(user=user)


class MistralPowerOpsClientTests(SimpleTestCase):

    @mock.patch.object(api.mistral_client, 'client')
    @mock.patch.object(api.base, 'url_for',
                       return_value='https://mistral.example/v2')
    def test_constructs_client_with_current_user_token_and_fixed_service(
            self, url_for, client_factory):
        request = _request()

        result = api.get_client(request)

        self.assertIsInstance(result, api.MistralPowerOpsClient)
        url_for.assert_called_once_with(
            request,
            'workflowv2',
            endpoint_type=settings.OPENSTACK_ENDPOINT_TYPE,
            region='RegionOne',
        )
        client_factory.assert_called_once_with(
            username=request.user.username,
            auth_token=request.user.token.id,
            project_id=request.user.project_id,
            mistral_url='https://mistral.example/v2',
            endpoint_type=settings.OPENSTACK_ENDPOINT_TYPE,
            service_type='workflowv2',
            enforce_raw_definition=False,
        )

    @mock.patch.object(api.mistral_client, 'client')
    @mock.patch.object(api.base, 'url_for')
    def test_rejects_region_mismatch_before_endpoint_discovery(
            self, url_for, client_factory):
        with self.assertRaises(exceptions.RegionMismatch):
            api.get_client(_request(region='RegionTwo'))

        url_for.assert_not_called()
        client_factory.assert_not_called()

    def test_read_methods_use_only_closed_workflow_and_get_calls(self):
        raw = mock.Mock()
        adapter = api.MistralPowerOpsClient(raw)

        adapter.start_inventory()
        adapter.start_host_status('compute-01', SEGMENT_UUID)
        adapter.get_execution('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        adapter.list_tasks('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')

        self.assertEqual(
            [mock.call(constants.HOST_INVENTORY),
             mock.call(
                 constants.HOST_POWER_STATUS,
                 workflow_input={
                     'host': 'compute-01',
                     'segment_uuid': SEGMENT_UUID,
                 },
             )],
            raw.executions.create.call_args_list,
        )
        raw.executions.get.assert_called_once_with(
            'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        raw.tasks.list.assert_called_once_with(
            workflow_execution_id=(
                'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
            ),
        )

    def test_execution_listing_scopes_operator_and_sorts_newest_first(self):
        newest = SimpleNamespace(created_at='2026-09-03T11:00:00')
        oldest = SimpleNamespace(created_at='2026-09-03T09:00:00')
        raw = mock.Mock()
        raw.executions.list.return_value = [oldest, newest]
        adapter = api.MistralPowerOpsClient(raw)

        self.assertEqual([newest, oldest], adapter.list_executions(False))
        raw.executions.list.assert_called_once_with()

        raw.executions.list.reset_mock()
        self.assertEqual([newest, oldest], adapter.list_executions(True))
        raw.executions.list.assert_called_once_with(all_projects=True)

    def test_plugin_has_no_direct_infrastructure_client_import(self):
        package = pathlib.Path(__file__).parents[1]
        forbidden = {
            'baremetal',
            'ironic',
            'novaclient',
            'nova',
            'masakariclient',
            'masakari',
            'ironicclient',
            'openstack',
            'redfish',
            'sushy',
        }
        imported = set()

        for path in package.rglob('*.py'):
            if 'tests' in path.parts or 'test' in path.parts:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split('.')[0]
                                    for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split('.')[0])

        self.assertFalse(forbidden.intersection(imported))


@override_settings(POWEROPS_MOCK_MODE=True)
class RegionGateInMockModeTests(SimpleTestCase):

    @mock.patch.object(api.base, 'url_for')
    def test_mock_mode_still_enforces_configured_region(self, url_for):
        with self.assertRaises(exceptions.RegionMismatch):
            api.get_client(_request(region='RegionTwo'))

        url_for.assert_not_called()
