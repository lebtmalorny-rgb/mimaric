import copy
import dataclasses
import json
from types import SimpleNamespace
from unittest import mock

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.test import SimpleTestCase

from poweropsdashboard import auth
from poweropsdashboard import constants
from poweropsdashboard import exceptions
from poweropsdashboard.hosts import views
from poweropsdashboard import presentation


SEGMENT_UUID = '11111111-1111-1111-1111-111111111111'
SECOND_SEGMENT_UUID = '55555555-5555-5555-5555-555555555555'
NODE_UUID = '22222222-2222-2222-2222-222222222222'
SECOND_NODE_UUID = '66666666-6666-6666-6666-666666666666'
INSTANCE_UUID = '33333333-3333-3333-3333-333333333333'
INVENTORY_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
ACTIVE_UUID = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'


def _row(operable=True):
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
        'instance_count': 1,
        'instances': [{
            'id': INSTANCE_UUID,
            'name': 'vm-a',
            'project_id': 'project-a',
            'status': 'ACTIVE',
        }],
        'operable': operable,
        'blocking_reason': (
            None if operable else 'ironic_node_incompatible'
        ),
    }


def _execution(output, workflow=constants.HOST_INVENTORY,
               state='SUCCESS', execution_id=INVENTORY_UUID,
               workflow_input=None, created_at='2026-09-03T10:00:00'):
    return SimpleNamespace(
        id=execution_id,
        workflow_name=workflow,
        state=state,
        state_info=None,
        input={} if workflow_input is None else workflow_input,
        output=output,
        created_at=created_at,
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


class InventoryParserTests(SimpleTestCase):

    def test_exact_task5_shape_becomes_frozen_defensive_rows(self):
        output = {'result': [_row()]}
        execution = _execution(output)

        rows = presentation.parse_inventory_execution(execution)

        self.assertEqual(1, len(rows))
        self.assertIsInstance(rows[0], presentation.HostRow)
        self.assertEqual(INSTANCE_UUID, rows[0].instances[0].id)
        self.assertEqual('vm-a', rows[0].instances[0].name)
        self.assertEqual('project-a', rows[0].instances[0].project_id)
        self.assertEqual('ACTIVE', rows[0].instances[0].status)
        self.assertIsInstance(rows[0].instances, tuple)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            rows[0].host = 'changed'
        output['result'][0]['host'] = 'changed'
        self.assertEqual('compute-01', rows[0].host)
        self.assertEqual(
            'compute-01',
            presentation.parse_inventory_execution(_execution(json.dumps({
                'result': [_row()],
            })))[0].host,
        )

    def test_rejects_missing_extra_wrong_types_and_uuid_values(self):
        mutations = []

        missing = _row()
        missing.pop('host')
        mutations.append(missing)
        extra = _row()
        extra['unexpected'] = 'value'
        mutations.append(extra)
        non_list = _row()
        non_list['instances'] = ()
        mutations.append(non_list)
        wrong_segment = _row()
        wrong_segment['segment_uuid'] = 'not-a-uuid'
        mutations.append(wrong_segment)
        wrong_node = _row()
        wrong_node['ironic_node_uuid'] = 'not-a-uuid'
        mutations.append(wrong_node)
        wrong_instance = _row()
        wrong_instance['instances'][0]['id'] = 'not-a-uuid'
        mutations.append(wrong_instance)
        non_boolean = _row()
        non_boolean['operable'] = 1
        mutations.append(non_boolean)
        unknown_reason = _row(operable=False)
        unknown_reason['blocking_reason'] = 'raw_backend_failure'
        mutations.append(unknown_reason)

        for row in mutations:
            with self.subTest(row=row):
                with self.assertRaises(exceptions.InvalidBackendData):
                    presentation.parse_inventory_execution(
                        _execution({'result': [row]}))

    def test_accepts_task5_invalid_instance_row_with_omitted_record(self):
        degraded = _row(operable=False)
        degraded['blocking_reason'] = 'invalid_instance_data'
        degraded['instance_count'] = 2

        rows = presentation.parse_inventory_execution(
            _execution({'result': [degraded]}))

        self.assertEqual(2, rows[0].instance_count)
        self.assertEqual((INSTANCE_UUID,), tuple(
            instance.id for instance in rows[0].instances))
        self.assertFalse(rows[0].operable)
        self.assertEqual(
            'invalid_instance_data', rows[0].blocking_reason)

    def test_count_mismatch_is_allowed_only_for_exact_degraded_reason(self):
        too_small = _row(operable=False)
        too_small['blocking_reason'] = 'invalid_instance_data'
        too_small['instance_count'] = 0

        still_operable = _row()
        still_operable['instance_count'] = 2

        wrong_reason = _row(operable=False)
        wrong_reason['blocking_reason'] = 'missing_nova_service'
        wrong_reason['instance_count'] = 2

        for row in (too_small, still_operable, wrong_reason):
            with self.subTest(row=row):
                with self.assertRaises(exceptions.InvalidBackendData):
                    presentation.parse_inventory_execution(
                        _execution({'result': [row]}))

    def test_duplicate_host_rows_require_ambiguous_masakari_reason(self):
        first = _row(operable=False)
        first['blocking_reason'] = 'ambiguous_masakari_host'
        second = copy.deepcopy(first)
        second['segment_uuid'] = SECOND_SEGMENT_UUID

        rows = presentation.parse_inventory_execution(
            _execution({'result': [first, second]}))

        self.assertEqual(2, len(rows))
        self.assertEqual({'compute-01'}, {row.host for row in rows})
        self.assertEqual(
            {'ambiguous_masakari_host'},
            {row.blocking_reason for row in rows},
        )

        for invalid_reason, invalid_operable in (
                ('ambiguous_masakari_host', True),
                ('missing_nova_service', False)):
            invalid = copy.deepcopy(second)
            invalid['operable'] = invalid_operable
            invalid['blocking_reason'] = (
                None if invalid_operable else invalid_reason
            )
            with self.subTest(reason=invalid_reason,
                              operable=invalid_operable):
                with self.assertRaises(exceptions.InvalidBackendData):
                    presentation.parse_inventory_execution(
                        _execution({'result': [first, invalid]}))

    def test_cross_host_instance_requires_invalid_instance_reason(self):
        first = _row(operable=False)
        first['blocking_reason'] = 'invalid_instance_data'
        second = copy.deepcopy(first)
        second['host'] = 'compute-02'
        second['segment_uuid'] = SECOND_SEGMENT_UUID
        second['ironic_node_uuid'] = SECOND_NODE_UUID

        rows = presentation.parse_inventory_execution(
            _execution({'result': [first, second]}))

        self.assertEqual(2, len(rows))
        self.assertEqual(
            {'compute-01', 'compute-02'}, {row.host for row in rows})
        self.assertEqual(
            {'invalid_instance_data'},
            {row.blocking_reason for row in rows},
        )

        invalid = copy.deepcopy(second)
        invalid['blocking_reason'] = 'missing_nova_service'
        with self.assertRaises(exceptions.InvalidBackendData):
            presentation.parse_inventory_execution(
                _execution({'result': [first, invalid]}))

    def test_repeated_instance_on_duplicate_same_host_is_not_cross_host(self):
        first = _row(operable=False)
        first['blocking_reason'] = 'ambiguous_masakari_host'
        second = copy.deepcopy(first)

        rows = presentation.parse_inventory_execution(
            _execution({'result': [first, second]}))

        self.assertEqual(
            (INSTANCE_UUID, INSTANCE_UUID),
            tuple(row.instances[0].id for row in rows),
        )

    def test_rejects_forbidden_keys_at_every_inventory_depth(self):
        payloads = []
        for key in ('token', 'password', 'bmc_address', 'driver_info',
                    'instance_info', 'service_catalog'):
            row = _row()
            row['instances'][0][key] = 'must-not-render'
            payloads.append(row)

        for row in payloads:
            with self.subTest(row=row):
                with self.assertRaises(exceptions.InvalidBackendData):
                    presentation.parse_inventory_execution(
                        _execution({'result': [row]}))

    def test_region_mismatch_rejects_the_complete_snapshot(self):
        rows = [_row(), copy.deepcopy(_row())]
        rows[1]['host'] = 'compute-02'
        rows[1]['region_name'] = 'RegionTwo'

        with self.assertRaises(exceptions.InvalidBackendData):
            presentation.parse_inventory_execution(
                _execution({'result': rows}))


class InventoryViewTests(SimpleTestCase):

    @mock.patch.object(views.api, 'get_client')
    @mock.patch.object(views.auth, 'authorize_user',
                       side_effect=PermissionDenied)
    def test_index_authorizes_before_constructing_adapter(
            self, authorize, get_client):
        user = _user()
        request = RequestFactory().get('/powerops/')
        request.user = user

        with self.assertRaises(PermissionDenied):
            views.IndexView.as_view()(request)

        authorize.assert_called_once_with(user)
        get_client.assert_not_called()

    def test_inventory_requires_successful_exact_inventory_execution(self):
        decoys = (
            _execution({'result': [_row()]}, state='RUNNING'),
            _execution(
                {'result': [_row()]},
                workflow=constants.HOST_POWER_STATUS,
            ),
        )

        self.assertIsNone(
            presentation.latest_successful_inventory(decoys))

    def test_active_match_requires_exact_workflow_state_host_and_segment(self):
        valid = _execution(
            {},
            workflow=constants.PLANNED_POWER_OFF,
            state='RUNNING',
            execution_id=ACTIVE_UUID,
            workflow_input={
                'host': 'compute-01',
                'segment_uuid': SEGMENT_UUID,
                'instance_policy': 'require_empty',
                'allow_hard_off': False,
            },
        )
        decoys = (
            _execution(
                {}, workflow='power_ops.unapproved', state='RUNNING',
                execution_id='cccccccc-cccc-cccc-cccc-cccccccccccc',
                workflow_input={
                    'host': 'compute-01', 'segment_uuid': SEGMENT_UUID,
                },
            ),
            _execution(
                {}, workflow=constants.PLANNED_REBOOT, state='SUCCESS',
                execution_id='dddddddd-dddd-dddd-dddd-dddddddddddd',
                workflow_input={
                    'host': 'compute-01', 'segment_uuid': SEGMENT_UUID,
                    'instance_policy': 'require_empty',
                    'allow_hard_off': False,
                },
            ),
            _execution(
                {}, workflow=constants.HOST_POWER_STATUS, state='RUNNING',
                execution_id='eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
                workflow_input={
                    'host': 'compute-02', 'segment_uuid': SEGMENT_UUID,
                },
            ),
            _execution(
                {}, workflow=constants.HOST_POWER_STATUS, state='RUNNING',
                execution_id='ffffffff-ffff-ffff-ffff-ffffffffffff',
                workflow_input={
                    'host': 'compute-01',
                    'segment_uuid': (
                        '99999999-9999-9999-9999-999999999999'
                    ),
                },
            ),
        )

        active = presentation.match_active_executions((valid,) + decoys)

        self.assertEqual(
            ACTIVE_UUID, active[('compute-01', SEGMENT_UUID)].id)
        self.assertEqual(1, len(active))

    @mock.patch.object(views.api, 'get_client')
    @mock.patch.object(views.auth, 'authorize_user')
    def test_admin_and_operator_execution_listing_scope_is_exact(
            self, authorize, get_client):
        adapter = get_client.return_value
        adapter.list_executions.return_value = [
            _execution({'result': [_row()]})]
        user = _user()

        for authorization, expected in (
                (auth.Authorization('admin', True), True),
                (auth.Authorization('powerops_operator', False), False)):
            with self.subTest(authorization=authorization):
                authorize.return_value = authorization
                adapter.list_executions.reset_mock()
                with mock.patch(
                        'django.contrib.auth.middleware.auth.get_user',
                        return_value=user):
                    response = self.client.get('/powerops/')
                self.assertEqual(200, response.status_code)
                adapter.list_executions.assert_called_once_with(
                    all_projects=expected)

    @mock.patch.object(views.api, 'get_client')
    @mock.patch.object(views.auth, 'authorize_user',
                       return_value=auth.Authorization(
                           'powerops_operator', False))
    def test_non_operable_row_shows_fixed_reason_and_no_mutation_link(
            self, authorize, get_client):
        get_client.return_value.list_executions.return_value = [
            _execution({'result': [_row(operable=False)]})]
        with mock.patch('django.contrib.auth.middleware.auth.get_user',
                        return_value=_user()):
            response = self.client.get('/powerops/')
        content = response.content.decode('utf-8')

        self.assertIn('Ironic node is not safe for PowerOps', content)
        self.assertNotIn('/planned/', content)
        self.assertNotIn('/return/', content)

    @mock.patch.object(views.api, 'get_client')
    @mock.patch.object(views.auth, 'authorize_user',
                       return_value=auth.Authorization(
                           'powerops_operator', False))
    def test_refresh_starts_only_closed_read_inventory_workflow(
            self, authorize, get_client):
        adapter = mock.Mock(spec=[
            'start_inventory',
            'start_host_status',
            'start_planned',
            'start_return',
            'resume_return',
        ])
        adapter.start_inventory.return_value = {
            'id': INVENTORY_UUID,
        }
        get_client.return_value = adapter

        with mock.patch('django.contrib.auth.middleware.auth.get_user',
                        return_value=_user()):
            response = self.client.get('/powerops/refresh/')

        self.assertEqual(302, response.status_code)
        self.assertIn(INVENTORY_UUID, response['Location'])
        adapter.start_inventory.assert_called_once_with()
        adapter.start_host_status.assert_not_called()
        adapter.start_planned.assert_not_called()
        adapter.start_return.assert_not_called()
        adapter.resume_return.assert_not_called()
