from collections import abc
import copy

from django.conf import settings

from mistralclient.api import client as mistral_client
from openstack_dashboard.api import base

from poweropsdashboard import constants
from poweropsdashboard import exceptions
from poweropsdashboard import mock_data


def _resource_value(resource, name, default=None):
    if isinstance(resource, abc.Mapping):
        return resource.get(name, default)
    return getattr(resource, name, default)


class MistralPowerOpsClient:

    def __init__(self, client):
        self._client = client

    def start_inventory(self):
        return self._client.executions.create(constants.HOST_INVENTORY)

    def start_host_status(self, host, segment_uuid):
        return self._client.executions.create(
            constants.HOST_POWER_STATUS,
            workflow_input={
                'host': host,
                'segment_uuid': segment_uuid,
            },
        )

    def start_planned(self, operation, payload):
        workflow = {
            'power_off': constants.PLANNED_POWER_OFF,
            'reboot': constants.PLANNED_REBOOT,
        }[operation]
        return self._client.executions.create(
            workflow,
            workflow_input=dict(payload),
        )

    def start_return(self, payload):
        return self._client.executions.create(
            constants.POWER_ON_AND_RETURN,
            workflow_input=dict(payload),
        )

    def resume_return(self, execution_id):
        return self._client.executions.update(
            execution_id,
            'RUNNING',
            env={'stale_domains_checked': True},
        )

    def get_execution(self, execution_id):
        return self._client.executions.get(execution_id)

    def list_executions(self, all_projects=False):
        if type(all_projects) is not bool:
            raise TypeError('all_projects must be a boolean')

        if all_projects:
            executions = self._client.executions.list(all_projects=True)
        else:
            executions = self._client.executions.list()

        return sorted(
            executions,
            key=lambda item: _resource_value(item, 'created_at', ''),
            reverse=True,
        )

    def list_tasks(self, execution_id):
        return self._client.tasks.list(
            workflow_execution_id=execution_id,
        )


class MockPowerOpsClient:

    def start_inventory(self):
        return copy.deepcopy(mock_data.INVENTORY_EXECUTION)

    def start_host_status(self, host, segment_uuid):
        for execution in (
                mock_data.STATUS_EXECUTION,
                mock_data.RETURN_STATUS_EXECUTION,
                mock_data.ACTION_STATUS_EXECUTION):
            expected_input = execution['input']
            if (host == expected_input['host']
                    and segment_uuid == expected_input['segment_uuid']):
                return copy.deepcopy(execution)
        raise exceptions.InvalidBackendData(
            'Mock host status fixture is unavailable'
        )

    def get_execution(self, execution_id):
        for execution in mock_data.EXECUTIONS:
            if execution['id'] == execution_id:
                return copy.deepcopy(execution)
        raise exceptions.InvalidBackendData(
            'Mock execution fixture is unavailable'
        )

    def list_executions(self, all_projects=False):
        if type(all_projects) is not bool:
            raise TypeError('all_projects must be a boolean')
        return copy.deepcopy(mock_data.EXECUTIONS)

    def list_tasks(self, execution_id):
        return copy.deepcopy(mock_data.TASKS.get(execution_id, []))

    @staticmethod
    def _mutation_disabled():
        raise exceptions.MockMutationDisabled(
            'PowerOps mutations are disabled in mock mode'
        )

    def start_planned(self, operation, payload):
        self._mutation_disabled()

    def start_return(self, payload):
        self._mutation_disabled()

    def resume_return(self, execution_id):
        self._mutation_disabled()


def get_client(request):
    configured_region = settings.POWEROPS_REGION_NAME
    if request.user.services_region != configured_region:
        raise exceptions.RegionMismatch(
            'The selected region is not configured for PowerOps'
        )

    if settings.POWEROPS_MOCK_MODE:
        return MockPowerOpsClient()

    endpoint = base.url_for(
        request,
        'workflowv2',
        endpoint_type=settings.OPENSTACK_ENDPOINT_TYPE,
        region=configured_region,
    )
    client = mistral_client.client(
        username=request.user.username,
        auth_token=request.user.token.id,
        project_id=request.user.project_id,
        mistral_url=endpoint,
        endpoint_type=settings.OPENSTACK_ENDPOINT_TYPE,
        service_type='workflowv2',
        enforce_raw_definition=False,
    )
    return MistralPowerOpsClient(client)
