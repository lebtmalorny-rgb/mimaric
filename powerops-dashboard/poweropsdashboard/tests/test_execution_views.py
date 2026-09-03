import dataclasses
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from poweropsdashboard import auth
from poweropsdashboard import constants
from poweropsdashboard import exceptions
from poweropsdashboard.hosts import views
from poweropsdashboard import presentation


EXECUTION_UUID = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
TASK_UUID = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
SEGMENT_UUID = '11111111-1111-1111-1111-111111111111'


def _execution(state='RUNNING', output=None, state_info=None):
    return SimpleNamespace(
        id=EXECUTION_UUID,
        workflow_name=constants.PLANNED_POWER_OFF,
        state=state,
        state_info=state_info,
        input={
            'host': 'compute-01',
            'segment_uuid': SEGMENT_UUID,
            'instance_policy': 'require_empty',
            'allow_hard_off': False,
        },
        output={} if output is None else output,
        created_at='2026-09-03T10:00:00',
    )


def _task():
    return SimpleNamespace(
        id=TASK_UUID,
        name='power_off',
        type='ACTION',
        state='SUCCESS',
        state_info='raw task exception must not be displayed',
    )


def _user():
    return SimpleNamespace(
        roles=[{'name': 'powerops_operator'}],
        project_name='ops-project',
        username='ops-user',
        project_id='project-id',
        services_region='RegionOne',
        token=SimpleNamespace(id='current-user-token'),
        is_authenticated=True,
        has_perms=lambda permissions: True,
    )


class ExecutionParserTests(SimpleTestCase):

    def test_execution_state_is_frozen_and_output_is_allowlisted(self):
        raw = _execution(
            state='ERROR',
            state_info='Traceback token=must-not-render',
            output={
                'result': {
                    'host': 'compute-01',
                    'operation': 'planned_power_off',
                    'power_state': 'power off',
                    'nova_enabled': False,
                    'masakari_maintenance': True,
                    'ignored_backend_field': 'not displayed',
                },
                'stopped_instance_ids': [],
            },
        )

        state = presentation.parse_execution_state(raw)

        self.assertIsInstance(state, presentation.ExecutionState)
        self.assertTrue(state.verification_required)
        self.assertEqual(
            'Execution failed; verify host state before another operation.',
            state.state_info,
        )
        self.assertNotIn('ignored_backend_field', state.output['result'])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            state.state = 'SUCCESS'
        with self.assertRaises(TypeError):
            state.output['new'] = 'value'

    def test_execution_output_rejects_secret_keys_and_raw_objects(self):
        payloads = (
            {'result': {'token': 'secret'}},
            {'result': {'password_hint': 'secret'}},
            {'result': {'safe': object()}},
        )

        for output in payloads:
            with self.subTest(output=output):
                with self.assertRaises(exceptions.InvalidBackendData):
                    presentation.parse_execution_state(
                        _execution(output=output))


class ExecutionViewTests(SimpleTestCase):

    @mock.patch.object(views.api, 'get_client')
    @mock.patch.object(views.auth, 'authorize_user',
                       return_value=auth.Authorization(
                           'powerops_operator', False))
    def test_each_poll_uses_only_execution_and_task_reads(
            self, authorize, get_client):
        adapter = mock.Mock(spec=[
            'get_execution',
            'list_tasks',
            'start_inventory',
            'start_host_status',
            'start_planned',
            'start_return',
            'resume_return',
        ])
        adapter.get_execution.return_value = _execution()
        adapter.list_tasks.return_value = [_task()]
        get_client.return_value = adapter

        for _index in range(2):
            with mock.patch(
                    'django.contrib.auth.middleware.auth.get_user',
                    return_value=_user()):
                response = self.client.get(
                    '/powerops/executions/{}/'.format(EXECUTION_UUID))
            self.assertEqual(200, response.status_code)
            self.assertIn(
                constants.PLANNED_POWER_OFF,
                response.content.decode('utf-8'),
            )

        self.assertEqual(2, adapter.get_execution.call_count)
        self.assertEqual(2, adapter.list_tasks.call_count)
        adapter.start_inventory.assert_not_called()
        adapter.start_host_status.assert_not_called()
        adapter.start_planned.assert_not_called()
        adapter.start_return.assert_not_called()
        adapter.resume_return.assert_not_called()

    @mock.patch.object(views.api, 'get_client')
    @mock.patch.object(views.auth, 'authorize_user',
                       return_value=auth.Authorization('admin', True))
    def test_execution_page_never_renders_raw_state_information(
            self, authorize, get_client):
        get_client.return_value.get_execution.return_value = _execution(
            state='ERROR',
            state_info='Traceback password=must-not-render',
        )
        get_client.return_value.list_tasks.return_value = [_task()]
        with mock.patch('django.contrib.auth.middleware.auth.get_user',
                        return_value=_user()):
            response = self.client.get(
                '/powerops/executions/{}/'.format(EXECUTION_UUID))
        content = response.content.decode('utf-8')

        self.assertEqual(200, response.status_code)
        self.assertIn('verification required', content.lower())
        self.assertIn(EXECUTION_UUID, content)
        self.assertIn('power_off', content)
        self.assertIn('ACTION', content)
        self.assertNotIn('Traceback', content)
        self.assertNotIn('must-not-render', content)
