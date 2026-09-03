import copy
import re
from types import SimpleNamespace
from unittest import mock

from django.core.exceptions import PermissionDenied
from django.test import override_settings
from django.test import SimpleTestCase

from poweropsdashboard import api
from poweropsdashboard import auth
from poweropsdashboard import constants
from poweropsdashboard.hosts import forms
from poweropsdashboard.hosts import views


SEGMENT_UUID = '11111111-1111-1111-1111-111111111111'
SOURCE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
RETURN_UUID = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
STATUS_UUID = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
TASK_UUID = 'dddddddd-dddd-dddd-dddd-dddddddddddd'
INSTANCE_UUID = '33333333-3333-3333-3333-333333333333'
SECOND_INSTANCE_UUID = '44444444-4444-4444-4444-444444444444'


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


def _source(**changes):
    source = {
        'id': SOURCE_UUID,
        'workflow_name': constants.PLANNED_POWER_OFF,
        'state': 'SUCCESS',
        'input': {
            'host': 'compute-03',
            'segment_uuid': SEGMENT_UUID,
            'instance_policy': 'stop',
            'allow_hard_off': False,
        },
        'output': {
            'result': {
                'host': 'compute-03',
                'operation': 'planned_power_off',
                'power_state': 'power off',
                'stopped_instance_ids': [INSTANCE_UUID],
                'nova_enabled': False,
                'masakari_maintenance': True,
            },
            'stopped_instance_ids': [INSTANCE_UUID],
        },
    }
    source.update(changes)
    return source


def _return_execution(**changes):
    execution = {
        'id': RETURN_UUID,
        'workflow_name': constants.POWER_ON_AND_RETURN,
        'state': 'PAUSED',
        'input': {
            'host': 'compute-03',
            'segment_uuid': SEGMENT_UUID,
            'stopped_instance_ids': [INSTANCE_UUID],
        },
        'output': {},
    }
    execution.update(changes)
    return execution


def _tasks(gate_name='operator_inspection_gate', gate_state='IDLE'):
    return [{
        'id': TASK_UUID,
        'name': gate_name,
        'type': 'ACTION',
        'state': gate_state,
    }]


def _status(**changes):
    result = {
        'host': 'compute-03',
        'ironic_node_uuid': '22222222-2222-2222-2222-222222222222',
        'power_state': 'power on',
        'target_power_state': None,
        'ironic_last_error': None,
        'nova_enabled': False,
        'nova_state': 'up',
        'masakari_maintenance': True,
    }
    result.update(changes)
    return {
        'id': STATUS_UUID,
        'workflow_name': constants.HOST_POWER_STATUS,
        'state': 'SUCCESS',
        'input': {
            'host': 'compute-03',
            'segment_uuid': SEGMENT_UUID,
        },
        'output': {'result': result},
    }


def _adapter():
    client = mock.Mock(spec=[
        'get_execution',
        'list_tasks',
        'start_host_status',
        'start_return',
        'resume_return',
    ])
    client.get_execution.side_effect = lambda execution_id: {
        SOURCE_UUID: copy.deepcopy(_source()),
        RETURN_UUID: copy.deepcopy(_return_execution()),
    }[execution_id]
    client.list_tasks.return_value = _tasks()
    client.start_host_status.return_value = _status()
    client.start_return.return_value = {'id': RETURN_UUID}
    client.resume_return.return_value = _return_execution(state='RUNNING')
    return client


def _token(response):
    match = re.search(
        r'name="submission_token"[^>]*value="([^"]+)"',
        response.content.decode('utf-8'),
    )
    if match is None:
        match = re.search(
            r'value="([^"]+)"[^>]*name="submission_token"',
            response.content.decode('utf-8'),
        )
    if match is None:
        raise AssertionError('submission token was not rendered')
    return match.group(1)


class ReturnAdapterTests(SimpleTestCase):

    def test_live_adapter_uses_only_closed_start_and_exact_resume(self):
        raw = mock.Mock()
        adapter = api.MistralPowerOpsClient(raw)
        payload = {
            'host': 'compute-03',
            'segment_uuid': SEGMENT_UUID,
            'stopped_instance_ids': [INSTANCE_UUID],
        }

        adapter.start_return(payload)
        adapter.resume_return(RETURN_UUID)

        raw.executions.create.assert_called_once_with(
            constants.POWER_ON_AND_RETURN,
            workflow_input=payload,
        )
        raw.executions.update.assert_called_once_with(
            RETURN_UUID,
            'RUNNING',
            env={'stale_domains_checked': True},
        )


class ReturnFormTests(SimpleTestCase):

    def test_start_form_has_no_manifest_and_rejects_forged_fields(self):
        valid = forms.StartReturnForm(data={'submission_token': 'one'})
        forged = forms.StartReturnForm(data={
            'submission_token': 'one',
            'stopped_instance_ids': INSTANCE_UUID,
        })

        self.assertEqual({'submission_token'}, set(valid.fields))
        self.assertTrue(valid.is_valid())
        self.assertFalse(forged.is_valid())

    def test_resume_form_accepts_only_checkbox_and_submission_token(self):
        valid = forms.ResumeReturnForm(data={
            'submission_token': 'one',
            'stale_domains_checked': 'on',
        })
        forged = forms.ResumeReturnForm(data={
            'submission_token': 'one',
            'stale_domains_checked': 'on',
            'env': 'forged',
        })

        self.assertEqual(
            {'submission_token', 'stale_domains_checked'},
            set(valid.fields),
        )
        self.assertTrue(valid.is_valid())
        self.assertIs(True, valid.cleaned_data['stale_domains_checked'])
        self.assertFalse(forged.is_valid())


class StartReturnViewTests(SimpleTestCase):

    @mock.patch.object(views.api, 'get_client')
    @mock.patch.object(
        views.auth,
        'authorize_user',
        return_value=auth.Authorization('powerops_operator', False),
    )
    def test_post_uses_fresh_server_manifest_copy_only(
            self, authorize, get_client):
        client = _adapter()
        source = _source()
        client.get_execution.side_effect = lambda execution_id: source
        received = []

        def start_return(payload):
            received.append(payload)
            payload['stopped_instance_ids'].append(SECOND_INSTANCE_UUID)
            return {'id': RETURN_UUID}

        client.start_return.side_effect = start_return
        get_client.return_value = client

        with mock.patch(
                'django.contrib.auth.middleware.auth.get_user',
                return_value=_user()):
            response = self.client.get(
                '/powerops/return/start/{}/'.format(SOURCE_UUID))
            token = _token(response)
            response = self.client.post(
                '/powerops/return/start/{}/'.format(SOURCE_UUID),
                {'submission_token': token},
            )

        self.assertEqual(302, response.status_code)
        self.assertEqual([{
            'host': 'compute-03',
            'segment_uuid': SEGMENT_UUID,
            'stopped_instance_ids': [
                INSTANCE_UUID,
                SECOND_INSTANCE_UUID,
            ],
        }], received)
        self.assertEqual(
            [INSTANCE_UUID],
            source['output']['stopped_instance_ids'],
        )
        self.assertEqual(
            [INSTANCE_UUID],
            source['output']['result']['stopped_instance_ids'],
        )

    @mock.patch.object(views.api, 'get_client')
    @mock.patch.object(
        views.auth,
        'authorize_user',
        return_value=auth.Authorization('powerops_operator', False),
    )
    def test_unknown_or_repeated_browser_keys_reject_before_mutation(
            self, authorize, get_client):
        client = _adapter()
        get_client.return_value = client

        with mock.patch(
                'django.contrib.auth.middleware.auth.get_user',
                return_value=_user()):
            response = self.client.get(
                '/powerops/return/start/{}/'.format(SOURCE_UUID))
            token = _token(response)
            response = self.client.post(
                '/powerops/return/start/{}/'.format(SOURCE_UUID),
                {
                    'submission_token': token,
                    'stopped_instance_ids': [
                        INSTANCE_UUID, SECOND_INSTANCE_UUID],
                },
            )

        self.assertEqual(422, response.status_code)
        client.start_return.assert_not_called()

    @mock.patch.object(views.api, 'get_client')
    @mock.patch.object(
        views.auth,
        'authorize_user',
        return_value=auth.Authorization('powerops_operator', False),
    )
    def test_source_requires_exact_successful_planned_power_off_and_manifest(
            self, authorize, get_client):
        invalid = []
        invalid.append(_source(workflow_name=constants.PLANNED_REBOOT))
        invalid.append(_source(state='ERROR'))
        bad_input = _source()
        bad_input['input']['extra'] = 'forged'
        invalid.append(bad_input)
        bad_result_type = _source()
        bad_result_type['output']['result']['nova_enabled'] = 0
        invalid.append(bad_result_type)
        for manifest in (
                None,
                [INSTANCE_UUID, INSTANCE_UUID],
                [1],
                ['not-a-uuid']):
            bad = _source()
            if manifest is None:
                bad['output'].pop('stopped_instance_ids')
            else:
                bad['output']['stopped_instance_ids'] = manifest
                bad['output']['result']['stopped_instance_ids'] = manifest
            invalid.append(bad)

        with mock.patch(
                'django.contrib.auth.middleware.auth.get_user',
                return_value=_user()):
            for source in invalid:
                with self.subTest(source=source):
                    client = _adapter()
                    client.get_execution.return_value = source
                    client.get_execution.side_effect = None
                    get_client.return_value = client
                    response = self.client.get(
                        '/powerops/return/start/{}/'.format(SOURCE_UUID))
                    self.assertEqual(422, response.status_code)
                    client.start_return.assert_not_called()

    @override_settings(POWEROPS_ALLOWED_USER_NAMES=[])
    @mock.patch.object(views.api, 'get_client')
    def test_authorization_is_rechecked_after_allowlist_removal(
            self, get_client):
        get_client.return_value = _adapter()

        with mock.patch(
                'django.contrib.auth.middleware.auth.get_user',
                return_value=_user()):
            response = self.client.get(
                '/powerops/return/start/{}/'.format(SOURCE_UUID))

        self.assertEqual(403, response.status_code)
        get_client.assert_not_called()


class ResumeReturnViewTests(SimpleTestCase):

    @mock.patch.object(views.api, 'get_client')
    @mock.patch.object(
        views.auth,
        'authorize_user',
        return_value=auth.Authorization('powerops_operator', False),
    )
    def test_resume_rechecks_all_predicates_and_uses_fixed_server_env(
            self, authorize, get_client):
        client = _adapter()
        get_client.return_value = client

        with mock.patch(
                'django.contrib.auth.middleware.auth.get_user',
                return_value=_user()):
            response = self.client.get(
                '/powerops/return/resume/{}/'.format(RETURN_UUID))
            token = _token(response)
            response = self.client.post(
                '/powerops/return/resume/{}/'.format(RETURN_UUID),
                {
                    'submission_token': token,
                    'stale_domains_checked': 'on',
                },
            )

        self.assertEqual(302, response.status_code)
        client.resume_return.assert_called_once_with(RETURN_UUID)
        self.assertEqual(2, client.start_host_status.call_count)

    @mock.patch.object(views.api, 'get_client')
    @mock.patch.object(
        views.auth,
        'authorize_user',
        return_value=auth.Authorization('powerops_operator', False),
    )
    def test_each_false_resume_predicate_rejects_before_mutation(
            self, authorize, get_client):
        cases = []
        cases.append(('workflow', _return_execution(
            workflow_name=constants.PLANNED_REBOOT), _tasks(), _status()))
        cases.append(('state', _return_execution(state='RUNNING'),
                      _tasks(), _status()))
        cases.append(('gate', _return_execution(), _tasks('wrong_gate'),
                      _status()))
        cases.append(('power', _return_execution(), _tasks(),
                      _status(power_state='power off')))
        cases.append(('nova enabled', _return_execution(), _tasks(),
                      _status(nova_enabled=True)))
        cases.append(('nova down', _return_execution(), _tasks(),
                      _status(nova_state='down')))
        cases.append(('maintenance', _return_execution(), _tasks(),
                      _status(masakari_maintenance=False)))
        cases.append(('ironic UUID', _return_execution(), _tasks(),
                      _status(ironic_node_uuid='not-a-uuid')))
        cases.append(('restart started', _return_execution(), _tasks() + [{
            'id': 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
            'name': 'return_to_service',
            'type': 'ACTION',
            'state': 'RUNNING',
        }], _status()))

        with mock.patch(
                'django.contrib.auth.middleware.auth.get_user',
                return_value=_user()):
            for name, execution, tasks, status in cases:
                with self.subTest(name=name):
                    client = _adapter()
                    client.get_execution.return_value = execution
                    client.get_execution.side_effect = None
                    client.list_tasks.return_value = tasks
                    client.start_host_status.return_value = status
                    get_client.return_value = client
                    response = self.client.get(
                        '/powerops/return/resume/{}/'.format(RETURN_UUID))
                    self.assertEqual(409, response.status_code)
                    client.resume_return.assert_not_called()

    @mock.patch.object(views.api, 'get_client')
    @mock.patch.object(
        views.auth,
        'authorize_user',
        return_value=auth.Authorization('powerops_operator', False),
    )
    def test_resume_rejects_browser_env_identity_and_manifest(
            self, authorize, get_client):
        client = _adapter()
        get_client.return_value = client

        with mock.patch(
                'django.contrib.auth.middleware.auth.get_user',
                return_value=_user()):
            response = self.client.get(
                '/powerops/return/resume/{}/'.format(RETURN_UUID))
            token = _token(response)
            response = self.client.post(
                '/powerops/return/resume/{}/'.format(RETURN_UUID),
                {
                    'submission_token': token,
                    'stale_domains_checked': 'on',
                    'env': '{}',
                    'host': 'compute-evil',
                    'roles': 'admin',
                    'stopped_instance_ids': INSTANCE_UUID,
                },
            )

        self.assertEqual(422, response.status_code)
        client.resume_return.assert_not_called()

    @mock.patch.object(views.api, 'get_client')
    @mock.patch.object(
        views.auth,
        'authorize_user',
        side_effect=(
            auth.Authorization('powerops_operator', False),
            PermissionDenied,
        ),
    )
    def test_resume_reauthorizes_every_request(
            self, authorize, get_client):
        get_client.return_value = _adapter()

        with mock.patch(
                'django.contrib.auth.middleware.auth.get_user',
                return_value=_user()):
            response = self.client.get(
                '/powerops/return/resume/{}/'.format(RETURN_UUID))
            token = _token(response)
            response = self.client.post(
                '/powerops/return/resume/{}/'.format(RETURN_UUID),
                {
                    'submission_token': token,
                    'stale_domains_checked': 'on',
                },
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual(2, authorize.call_count)
        get_client.return_value.resume_return.assert_not_called()
