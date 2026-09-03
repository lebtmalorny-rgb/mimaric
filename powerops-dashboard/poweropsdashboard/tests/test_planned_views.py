import copy
import hashlib
import re
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from poweropsdashboard import api
from poweropsdashboard import auth
from poweropsdashboard import constants
from poweropsdashboard.hosts import views
from poweropsdashboard import submission


SEGMENT_UUID = '11111111-1111-1111-1111-111111111111'
NODE_UUID = '22222222-2222-2222-2222-222222222222'
INSTANCE_UUID = '33333333-3333-3333-3333-333333333333'
SECOND_INSTANCE_UUID = '44444444-4444-4444-4444-444444444444'
INVENTORY_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
STATUS_UUID = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
PLANNED_UUID = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
ACTIVE_UUID = 'dddddddd-dddd-dddd-dddd-dddddddddddd'


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


def _row():
    return {
        'region_name': 'RegionOne',
        'segment_uuid': SEGMENT_UUID,
        'host': 'compute-01',
        'ironic_node_uuid': NODE_UUID,
        'power_state': 'power on',
        'target_power_state': None,
        'nova_status': 'enabled',
        'nova_state': 'up',
        'masakari_maintenance': False,
        'instance_count': 2,
        'instances': [{
            'id': INSTANCE_UUID,
            'name': 'vm-a',
            'project_id': 'project-a',
            'status': 'ACTIVE',
        }, {
            'id': SECOND_INSTANCE_UUID,
            'name': 'vm-b',
            'project_id': 'project-b',
            'status': 'SHUTOFF',
        }],
        'operable': True,
        'blocking_reason': None,
    }


def _inventory(rows=None):
    return SimpleNamespace(
        id=INVENTORY_UUID,
        workflow_name=constants.HOST_INVENTORY,
        state='SUCCESS',
        state_info=None,
        input={},
        output={'result': [_row()] if rows is None else rows},
        created_at='2026-09-03T10:00:00',
    )


def _status(**changes):
    result = {
        'host': 'compute-01',
        'ironic_node_uuid': NODE_UUID,
        'power_state': 'power on',
        'target_power_state': None,
        'ironic_last_error': None,
        'nova_enabled': True,
        'nova_state': 'up',
        'masakari_maintenance': False,
    }
    result.update(changes)
    return SimpleNamespace(
        id=STATUS_UUID,
        workflow_name=constants.HOST_POWER_STATUS,
        state='SUCCESS',
        state_info=None,
        input={
            'host': 'compute-01',
            'segment_uuid': SEGMENT_UUID,
        },
        output={'result': result},
        created_at='2026-09-03T10:01:00',
    )


def _planned(state='RUNNING'):
    return SimpleNamespace(
        id=ACTIVE_UUID,
        workflow_name=constants.PLANNED_POWER_OFF,
        state=state,
        state_info=None,
        input={
            'host': 'compute-01',
            'segment_uuid': SEGMENT_UUID,
            'instance_policy': 'require_empty',
            'allow_hard_off': False,
        },
        output={},
        created_at='2026-09-03T10:02:00',
    )


def _url(operation='power_off'):
    return '/powerops/planned/{}/{}/compute-01/'.format(
        operation, SEGMENT_UUID)


def _token_from(response):
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


def _post(token, **overrides):
    result = {
        'typed_host': 'compute-01',
        'instance_policy': 'require_empty',
        'submission_token': token,
    }
    result.update(overrides)
    return result


class PlannedOperationViewTests(SimpleTestCase):

    def setUp(self):
        self.authorization = auth.Authorization(
            'powerops_operator', False)
        self.adapter = mock.Mock(spec=[
            'start_inventory',
            'start_host_status',
            'list_executions',
            'start_planned',
        ])
        self.adapter.start_inventory.return_value = _inventory()
        self.adapter.start_host_status.return_value = _status()
        self.adapter.list_executions.return_value = []
        self.adapter.start_planned.return_value = {'id': PLANNED_UUID}
        self.auth_patch = mock.patch.object(
            views.auth, 'authorize_user', return_value=self.authorization)
        self.client_patch = mock.patch.object(
            views.api, 'get_client', return_value=self.adapter)
        self.user_patch = mock.patch(
            'django.contrib.auth.middleware.auth.get_user',
            return_value=_user(),
        )
        self.auth_patch.start()
        self.client_patch.start()
        self.user_patch.start()
        self.addCleanup(self.auth_patch.stop)
        self.addCleanup(self.client_patch.stop)
        self.addCleanup(self.user_patch.stop)

    def _set_valid_reads(self):
        self.adapter.start_inventory.side_effect = None
        self.adapter.start_inventory.return_value = _inventory()
        self.adapter.start_host_status.side_effect = None
        self.adapter.start_host_status.return_value = _status()
        self.adapter.list_executions.return_value = []

    def test_get_runs_fresh_preflight_and_renders_all_project_impact(self):
        with mock.patch.object(
                submission.secrets, 'token_urlsafe',
                return_value='visible-one-use-token') as token_urlsafe:
            response = self.client.get(_url())
        content = response.content.decode('utf-8')

        self.assertEqual(200, response.status_code)
        self.adapter.start_inventory.assert_called_once_with()
        self.adapter.start_host_status.assert_called_once_with(
            'compute-01', SEGMENT_UUID)
        self.adapter.list_executions.assert_called_once_with(
            all_projects=False)
        token_urlsafe.assert_called_once_with(32)
        for expected in (
                INSTANCE_UUID, 'vm-a', 'project-a', 'ACTIVE',
                SECOND_INSTANCE_UUID, 'vm-b', 'project-b', 'SHUTOFF',
                'require_empty', 'all projects'):
            self.assertIn(expected, content)

        session = self.client.session
        self.assertNotIn('visible-one-use-token', tuple(session.values()))
        self.assertEqual(
            hashlib.sha256(
                b'visible-one-use-token\x00power_off\x00compute-01'
            ).hexdigest(),
            session[submission.SESSION_DIGEST_KEY],
        )

    def test_post_repeats_preflight_and_uses_only_server_derived_target(self):
        response = self.client.get(_url('reboot'))
        token = _token_from(response)
        self.adapter.reset_mock()
        self.adapter.start_inventory.return_value = _inventory()
        self.adapter.start_host_status.return_value = _status()
        self.adapter.list_executions.return_value = []
        self.adapter.start_planned.return_value = {'id': PLANNED_UUID}

        response = self.client.post(
            _url('reboot'),
            _post(token, instance_policy='stop'),
        )

        self.assertEqual(302, response.status_code)
        self.assertIn(PLANNED_UUID, response['Location'])
        self.adapter.start_inventory.assert_called_once_with()
        self.adapter.start_host_status.assert_called_once_with(
            'compute-01', SEGMENT_UUID)
        self.adapter.start_planned.assert_called_once_with('reboot', {
            'host': 'compute-01',
            'segment_uuid': SEGMENT_UUID,
            'instance_policy': 'stop',
            'allow_hard_off': False,
        })
        session = self.client.session
        self.assertNotIn(submission.SESSION_DIGEST_KEY, session)
        self.assertEqual(
            PLANNED_UUID, session[submission.SESSION_EXECUTION_KEY])
        self.assertNotIn('current-user-token', tuple(session.values()))
        self.assertNotIn('stop', tuple(session.values()))

    def test_replayed_token_causes_at_most_one_planned_adapter_call(self):
        token = _token_from(self.client.get(_url()))
        first = self.client.post(_url(), _post(token))
        second = self.client.post(_url(), _post(token))

        self.assertEqual(302, first.status_code)
        self.assertEqual(409, second.status_code)
        self.adapter.start_planned.assert_called_once()

    def test_token_is_consumed_before_any_mistral_preflight_or_mutation(self):
        token = _token_from(self.client.get(_url()))
        self.adapter.reset_mock()

        def inspect_consumed():
            self.assertNotIn(
                submission.SESSION_DIGEST_KEY, self.client.session)
            return _inventory()

        self.adapter.start_inventory.side_effect = inspect_consumed
        self.adapter.start_host_status.return_value = _status()
        self.adapter.list_executions.return_value = []
        self.adapter.start_planned.return_value = {'id': PLANNED_UUID}

        response = self.client.post(_url(), _post(token))

        self.assertEqual(302, response.status_code)
        self.adapter.start_planned.assert_called_once()

    def test_form_forgery_returns_422_before_planned_start(self):
        token = _token_from(self.client.get(_url()))

        response = self.client.post(
            _url(), _post(token, host='forged-host'))

        self.assertEqual(422, response.status_code)
        self.adapter.start_planned.assert_not_called()

    def test_read_failures_and_non_operable_rows_fail_closed(self):
        cases = []
        inventory_failure = mock.Mock(side_effect=RuntimeError('unavailable'))
        cases.append(('inventory failure', inventory_failure, _status(), []))
        status_failure = mock.Mock(return_value=_inventory())
        cases.append((
            'status failure', status_failure,
            RuntimeError('unavailable'), []))
        blocked = _row()
        blocked['operable'] = False
        blocked['blocking_reason'] = 'ironic_node_incompatible'
        cases.append((
            'non-operable', mock.Mock(return_value=_inventory([blocked])),
            _status(), []))

        for name, inventory_behavior, status_result, executions in cases:
            with self.subTest(name=name):
                self._set_valid_reads()
                token = _token_from(self.client.get(_url()))
                self.adapter.reset_mock()
                if inventory_behavior.side_effect is not None:
                    self.adapter.start_inventory.side_effect = (
                        inventory_behavior.side_effect)
                else:
                    self.adapter.start_inventory.return_value = (
                        inventory_behavior.return_value)
                self.adapter.start_host_status.side_effect = None
                if isinstance(status_result, Exception):
                    self.adapter.start_host_status.side_effect = status_result
                else:
                    self.adapter.start_host_status.return_value = status_result
                self.adapter.list_executions.return_value = executions

                response = self.client.post(_url(), _post(token))

                self.assertEqual(409, response.status_code)
                self.adapter.start_planned.assert_not_called()

    def test_get_conflict_never_renders_a_submission_form(self):
        self.adapter.start_host_status.return_value = _status(
            power_state='power off')

        response = self.client.get(_url())

        self.assertEqual(409, response.status_code)
        self.assertNotIn(
            'submission_token', response.content.decode('utf-8'))
        self.adapter.start_planned.assert_not_called()

    def test_state_change_ambiguity_and_active_mutation_fail_closed(self):
        duplicate = _row()
        duplicate['operable'] = False
        duplicate['blocking_reason'] = 'ambiguous_masakari_host'
        duplicate_two = copy.deepcopy(duplicate)
        malformed_active = _planned()
        malformed_active.input = {'host': 'compute-01'}
        missing_state = _planned()
        del missing_state.state
        incomplete = _row()
        incomplete['nova_status'] = None
        states = (
            ('state changed', _inventory(), _status(power_state='power off'),
             []),
            ('wrong status type', _inventory(), _status(nova_enabled=1),
             []),
            ('incomplete operable row', _inventory([incomplete]),
             _status(nova_enabled=False), []),
            ('ambiguous', _inventory([duplicate, duplicate_two]), _status(),
             []),
            ('active mutation', _inventory(), _status(), [_planned()]),
            ('ambiguous active mutation', _inventory(), _status(),
             [malformed_active]),
            ('state-less active mutation', _inventory(), _status(),
             [missing_state]),
        )

        for name, inventory, status, executions in states:
            with self.subTest(name=name):
                self._set_valid_reads()
                token = _token_from(self.client.get(_url()))
                self.adapter.reset_mock()
                self.adapter.start_inventory.side_effect = None
                self.adapter.start_inventory.return_value = inventory
                self.adapter.start_host_status.side_effect = None
                self.adapter.start_host_status.return_value = status
                self.adapter.list_executions.return_value = executions
                self.adapter.start_planned.reset_mock()

                response = self.client.post(_url(), _post(token))

                self.assertEqual(409, response.status_code)
                self.adapter.start_planned.assert_not_called()

    def test_admin_preflight_uses_all_projects_execution_scope(self):
        self.authorization = auth.Authorization('admin', True)
        views.auth.authorize_user.return_value = self.authorization

        response = self.client.get(_url())

        self.assertEqual(200, response.status_code)
        self.adapter.list_executions.assert_called_once_with(
            all_projects=True)

    def test_timeout_requires_verification_and_get_never_retries(self):
        token = _token_from(self.client.get(_url()))
        self.adapter.start_planned.side_effect = TimeoutError()

        response = self.client.post(_url(), _post(token))

        self.assertEqual(503, response.status_code)
        self.assertIn(
            'verification required', response.content.decode('utf-8').lower())
        self.assertEqual(1, self.adapter.start_planned.call_count)

        self.adapter.start_planned.side_effect = AssertionError(
            'GET must not retry the mutation')
        following = self.client.get(_url())

        self.assertEqual(200, following.status_code)
        self.assertEqual(1, self.adapter.start_planned.call_count)
        self.assertGreaterEqual(self.adapter.list_executions.call_count, 3)

    def test_operation_route_is_closed(self):
        response = self.client.get(_url('shutdown'))

        self.assertEqual(404, response.status_code)
        self.adapter.start_inventory.assert_not_called()
        self.adapter.start_planned.assert_not_called()


class PlannedOperationAdapterTests(SimpleTestCase):

    def test_adapter_maps_only_closed_operations_to_fixed_workflows(self):
        raw = mock.Mock()
        adapter = api.MistralPowerOpsClient(raw)
        payload = {
            'host': 'compute-01',
            'segment_uuid': SEGMENT_UUID,
            'instance_policy': 'stop',
            'allow_hard_off': False,
        }

        adapter.start_planned('power_off', payload)
        adapter.start_planned('reboot', payload)

        self.assertEqual([
            mock.call(
                constants.PLANNED_POWER_OFF,
                workflow_input=dict(payload),
            ),
            mock.call(
                constants.PLANNED_REBOOT,
                workflow_input=dict(payload),
            ),
        ], raw.executions.create.call_args_list)

        with self.assertRaises(KeyError):
            adapter.start_planned('user.workflow', payload)
        self.assertEqual(2, raw.executions.create.call_count)
