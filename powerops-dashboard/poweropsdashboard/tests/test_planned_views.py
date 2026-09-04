import copy
import hashlib
import pathlib
import re
import subprocess
import threading
from types import SimpleNamespace
from unittest import mock

from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase
from horizon.utils import file_discovery

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
        authorized_tenants=[],
        available_services_regions=['RegionOne'],
        user_domain_name='Default',
        system_scoped=False,
        is_system_user=False,
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


def _inventory(rows=None, state='SUCCESS', execution_id=INVENTORY_UUID,
               workflow=constants.HOST_INVENTORY, workflow_input=None):
    return SimpleNamespace(
        id=execution_id,
        workflow_name=workflow,
        state=state,
        state_info=None,
        input={} if workflow_input is None else workflow_input,
        output={'result': [_row()] if rows is None else rows},
        created_at='2026-09-03T10:00:00',
    )


def _status(state='SUCCESS', execution_id=STATUS_UUID,
            workflow=constants.HOST_POWER_STATUS, workflow_input=None,
            **changes):
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
        id=execution_id,
        workflow_name=workflow,
        state=state,
        state_info=None,
        input=(
            {
                'host': 'compute-01',
                'segment_uuid': SEGMENT_UUID,
            }
            if workflow_input is None else workflow_input
        ),
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


class _Clock:

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class _Session(dict):
    modified = False


class ReadWorkflowPollingTests(SimpleTestCase):

    def _adapter(self):
        return mock.Mock(spec=[
            'start_inventory',
            'start_host_status',
            'get_execution',
            'list_executions',
        ])

    def test_running_inventory_and_status_are_polled_to_exact_success(self):
        adapter = self._adapter()
        adapter.start_inventory.return_value = _inventory(state='RUNNING')
        adapter.start_host_status.return_value = _status(state='RUNNING')
        adapter.get_execution.side_effect = [_inventory(), _status()]
        adapter.list_executions.return_value = []
        clock = _Clock()

        with mock.patch.object(
                submission, '_monotonic', clock.monotonic, create=True), \
                mock.patch.object(
                    submission, '_sleep', clock.sleep, create=True):
            row = submission.planned_preflight(
                adapter,
                auth.Authorization('powerops_operator', False),
                'compute-01',
                SEGMENT_UUID,
            )

        self.assertEqual('compute-01', row.host)
        adapter.start_inventory.assert_called_once_with()
        adapter.start_host_status.assert_called_once_with(
            'compute-01', SEGMENT_UUID)
        self.assertEqual([
            mock.call(INVENTORY_UUID),
            mock.call(STATUS_UUID),
        ], adapter.get_execution.call_args_list)

    def test_running_read_timeout_never_creates_inventory_twice(self):
        adapter = self._adapter()
        adapter.start_inventory.return_value = _inventory(state='RUNNING')
        adapter.get_execution.return_value = _inventory(state='RUNNING')
        clock = _Clock()

        with mock.patch.object(
                submission, '_READ_DEADLINE_SECONDS', 1.0, create=True), \
                mock.patch.object(
                    submission, '_READ_POLL_INTERVAL_SECONDS',
                    0.5,
                    create=True,
                ), mock.patch.object(
                    submission, '_monotonic', clock.monotonic, create=True), \
                mock.patch.object(
                    submission, '_sleep', clock.sleep, create=True):
            with self.assertRaises(submission.SubmissionConflict):
                submission.planned_preflight(
                    adapter,
                    auth.Authorization('powerops_operator', False),
                    'compute-01',
                    SEGMENT_UUID,
                )

        adapter.start_inventory.assert_called_once_with()
        adapter.start_host_status.assert_not_called()
        self.assertEqual(2, adapter.get_execution.call_count)

    def test_error_and_paused_reads_fail_without_a_second_create(self):
        for state in ('ERROR', 'CANCELLED', 'PAUSED'):
            with self.subTest(state=state):
                adapter = self._adapter()
                adapter.start_inventory.return_value = _inventory(state=state)

                with self.assertRaises(submission.SubmissionConflict):
                    submission.planned_preflight(
                        adapter,
                        auth.Authorization('powerops_operator', False),
                        'compute-01',
                        SEGMENT_UUID,
                    )

                adapter.start_inventory.assert_called_once_with()
                adapter.start_host_status.assert_not_called()
                adapter.get_execution.assert_not_called()

    def test_polled_response_identity_workflow_and_input_are_exact(self):
        mismatches = (
            _inventory(execution_id=(
                '99999999-9999-9999-9999-999999999999')),
            _inventory(workflow=constants.HOST_POWER_STATUS),
            _inventory(workflow_input={'host': 'forged'}),
        )

        for mismatch in mismatches:
            with self.subTest(mismatch=mismatch):
                adapter = self._adapter()
                adapter.start_inventory.return_value = _inventory(
                    state='RUNNING')
                adapter.get_execution.return_value = mismatch
                clock = _Clock()

                with mock.patch.object(
                        submission, '_monotonic',
                        clock.monotonic, create=True), mock.patch.object(
                            submission, '_sleep',
                            clock.sleep, create=True):
                    with self.assertRaises(submission.SubmissionConflict):
                        submission.planned_preflight(
                            adapter,
                            auth.Authorization('powerops_operator', False),
                            'compute-01',
                            SEGMENT_UUID,
                        )

                adapter.start_inventory.assert_called_once_with()
                adapter.start_host_status.assert_not_called()
                adapter.get_execution.assert_called_once_with(INVENTORY_UUID)

    def test_initial_read_requires_a_canonical_execution_uuid(self):
        adapter = self._adapter()
        adapter.start_inventory.return_value = _inventory(
            execution_id='not-a-uuid')

        with self.assertRaises(submission.SubmissionConflict):
            submission.planned_preflight(
                adapter,
                auth.Authorization('powerops_operator', False),
                'compute-01',
                SEGMENT_UUID,
            )

        adapter.start_inventory.assert_called_once_with()
        adapter.start_host_status.assert_not_called()
        adapter.get_execution.assert_not_called()


class SubmissionTokenConcurrencyTests(SimpleTestCase):

    class AtomicCache:

        def __init__(self, parties=2):
            self.barrier = threading.Barrier(parties)
            self.lock = threading.Lock()
            self.values = {}
            self.calls = []

        def add(self, key, value, timeout=None):
            self.barrier.wait(timeout=2)
            with self.lock:
                self.calls.append((key, value, timeout))
                if key in self.values:
                    return False
                self.values[key] = value
                return True

    def _issued_session(self):
        session = _Session()
        request = SimpleNamespace(session=session)
        with mock.patch.object(
                submission.secrets, 'token_urlsafe',
                return_value='visible-concurrent-token'):
            token = submission.issue_submission_token(
                request, 'power_off', 'compute-01')
        return token, session

    def test_parallel_session_copies_have_exactly_one_atomic_winner(self):
        token, issued = self._issued_session()
        cache = self.AtomicCache()
        requests = (
            SimpleNamespace(session=_Session(issued)),
            SimpleNamespace(session=_Session(issued)),
        )
        results = []

        def consume(request):
            try:
                submission.consume_submission_token(
                    request, token, 'power_off', 'compute-01')
            except submission.SubmissionConflict:
                results.append('conflict')
            else:
                results.append('consumed')

        with mock.patch.object(submission, 'cache', cache, create=True):
            threads = tuple(
                threading.Thread(target=consume, args=(request,))
                for request in requests
            )
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)

        self.assertEqual(['conflict', 'consumed'], sorted(results))
        self.assertEqual(2, len(cache.calls))
        self.assertTrue(all(call[1] is True for call in cache.calls))
        self.assertTrue(all(call[2] == 300 for call in cache.calls))
        for key, value, _timeout in cache.calls:
            self.assertNotIn(token, str((key, value)))
            self.assertNotIn('power_off', str((key, value)))
            self.assertNotIn('compute-01', str((key, value)))

    def test_cache_false_none_or_error_rejects_without_consuming_digest(self):
        behaviors = (False, None, RuntimeError('cache unavailable'))

        for behavior in behaviors:
            with self.subTest(behavior=behavior):
                token, session = self._issued_session()
                fake_cache = mock.Mock()
                if isinstance(behavior, Exception):
                    fake_cache.add.side_effect = behavior
                else:
                    fake_cache.add.return_value = behavior

                with mock.patch.object(
                        submission, 'cache', fake_cache, create=True):
                    with self.assertRaises(submission.SubmissionConflict):
                        submission.consume_submission_token(
                            SimpleNamespace(session=session),
                            token,
                            'power_off',
                            'compute-01',
                        )

                self.assertIn(submission.SESSION_DIGEST_KEY, session)


class PlannedPolicyJavascriptTests(SimpleTestCase):

    def test_external_asset_is_registered_once_after_discovery(self):
        static_root = pathlib.Path(__file__).parents[1] / 'static'
        horizon_config = {}

        file_discovery.populate_horizon_config(
            horizon_config, str(static_root))

        self.assertEqual(
            1,
            horizon_config['js_files'].count(
                'poweropsdashboard/js/powerops.js'),
        )

    def test_javascript_accepts_only_fixed_policies_and_updates_outputs(self):
        javascript = pathlib.Path(__file__).parents[1] / (
            'static/poweropsdashboard/js/powerops.js')
        probe = r"""
const assert = require('assert');
const initialize = require(process.argv[1]);
let changeHandler = null;
let listenerCount = 0;
const select = {
  value: 'require_empty',
  addEventListener: function(name, handler) {
    assert.strictEqual(name, 'change');
    changeHandler = handler;
    listenerCount += 1;
  }
};
const submit = {disabled: true};
const selected = [{textContent: ''}, {textContent: ''}];
const current = {textContent: ''};
const texts = {
  require_empty: 'Require empty fixed text',
  live_migrate: 'Live migrate fixed text',
  stop: 'Stop fixed text'
};
const definitions = Object.keys(texts).map(function(policy) {
  return {
    textContent: texts[policy],
    getAttribute: function() { return policy; }
  };
});
const document = {
  querySelector: function(selector) {
    return {
      '[data-powerops-policy-select]': select,
      '[data-powerops-submit]': submit,
      '[data-powerops-policy-result]': current
    }[selector] || null;
  },
  querySelectorAll: function(selector) {
    if (selector === '[data-powerops-selected-policy]') return selected;
    if (selector === '[data-powerops-policy-consequence]') return definitions;
    return [];
  }
};
initialize(document);
initialize(document);
assert.strictEqual(listenerCount, 1);
assert.strictEqual(submit.disabled, false);
assert.deepStrictEqual(selected.map(x => x.textContent),
                       ['require_empty', 'require_empty']);
assert.strictEqual(current.textContent, texts.require_empty);
['live_migrate', 'stop'].forEach(function(policy) {
  submit.disabled = true;
  select.value = policy;
  changeHandler();
  assert.strictEqual(submit.disabled, false);
  assert.deepStrictEqual(selected.map(x => x.textContent), [policy, policy]);
  assert.strictEqual(current.textContent, texts[policy]);
});
select.value = 'user_workflow';
changeHandler();
assert.strictEqual(submit.disabled, true);
assert.strictEqual(current.textContent, '');
"""

        result = subprocess.run(
            ['node', '-e', probe, str(javascript)],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)


class PlannedOperationViewTests(SimpleTestCase):

    def setUp(self):
        self.authorization = auth.Authorization(
            'powerops_operator', False)
        self.adapter = mock.Mock(spec=[
            'start_inventory',
            'start_host_status',
            'get_execution',
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
            'openstack_auth.utils.get_user',
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
                'require_empty', 'all projects',
                'The host must already have no instances',
                'Every eligible instance is live-migrated',
                'Every instance is stopped and recorded'):
            self.assertIn(expected, content)
        self.assertRegex(
            content,
            r'<button[^>]*data-powerops-submit[^>]*disabled',
        )

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
        events = []
        consume_submission_token = submission.consume_submission_token

        def consume(*args, **kwargs):
            consume_submission_token(*args, **kwargs)
            events.append('consumed')

        def inspect_consumed():
            events.append('preflight')
            return _inventory()

        self.adapter.start_inventory.side_effect = inspect_consumed
        self.adapter.start_host_status.return_value = _status()
        self.adapter.list_executions.return_value = []
        self.adapter.start_planned.return_value = {'id': PLANNED_UUID}

        with mock.patch.object(
                submission,
                'consume_submission_token',
                side_effect=consume):
            response = self.client.post(_url(), _post(token))

        self.assertEqual(302, response.status_code)
        self.assertEqual(['consumed', 'preflight'], events[:2])
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
        missing_input = _planned()
        del missing_input.input
        missing_state = _planned()
        del missing_state.state
        missing_workflow = _planned()
        del missing_workflow.workflow_name
        non_string_workflow = _planned()
        non_string_workflow.workflow_name = None
        malformed_terminal = _planned(state='SUCCESS')
        malformed_terminal.input = {'host': 'compute-01'}
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
            ('missing mutation input', _inventory(), _status(),
             [missing_input]),
            ('state-less active mutation', _inventory(), _status(),
             [missing_state]),
            ('missing workflow name', _inventory(), _status(),
             [missing_workflow]),
            ('non-string workflow name', _inventory(), _status(),
             [non_string_workflow]),
            ('malformed terminal mutation', _inventory(), _status(),
             [malformed_terminal]),
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

    def test_valid_terminal_mutation_does_not_block_preflight(self):
        self.adapter.list_executions.return_value = [
            _planned(state='SUCCESS')]

        response = self.client.get(_url())

        self.assertEqual(200, response.status_code)
        self.adapter.start_planned.assert_not_called()

    def test_valid_non_powerops_workflow_name_can_be_ignored(self):
        self.adapter.list_executions.return_value = [SimpleNamespace(
            workflow_name='other_service.unrelated_workflow')]

        response = self.client.get(_url())

        self.assertEqual(200, response.status_code)
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
        self.assertIn(
            'Обязательный сервис временно недоступен.',
            response.content.decode('utf-8'),
        )
        self.assertEqual(1, self.adapter.start_planned.call_count)

        self.adapter.start_planned.side_effect = AssertionError(
            'GET must not retry the mutation')
        following = self.client.get(_url())

        self.assertEqual(200, following.status_code)
        self.assertEqual(1, self.adapter.start_planned.call_count)
        self.assertGreaterEqual(self.adapter.list_executions.call_count, 3)

    def test_planned_mutation_errors_use_fixed_shared_classification(self):
        conflict = RuntimeError('password=must-not-render')
        conflict.error_code = 409
        cases = (
            (
                PermissionDenied('token=must-not-render'),
                403,
                'Недостаточно прав для операции PowerOps.',
            ),
            (
                conflict,
                409,
                'Хост занят или его состояние изменилось.',
            ),
            (
                submission.InvalidSubmission('token=must-not-render'),
                422,
                'Параметры операции не прошли проверку.',
            ),
        )

        for error, status_code, public_message in cases:
            with self.subTest(status_code=status_code):
                self._set_valid_reads()
                self.adapter.start_planned.reset_mock()
                self.adapter.start_planned.side_effect = error
                token = _token_from(self.client.get(_url()))

                response = self.client.post(_url(), _post(token))

                self.assertEqual(status_code, response.status_code)
                self.assertEqual(
                    public_message, response.content.decode('utf-8'))
                self.assertNotIn(
                    'must-not-render', response.content.decode('utf-8'))
                self.assertEqual(1, self.adapter.start_planned.call_count)

    def test_unknown_planned_mutation_error_requires_verification(self):
        token = _token_from(self.client.get(_url()))
        self.adapter.start_planned.side_effect = RuntimeError(
            'password=must-not-render')

        response = self.client.post(_url(), _post(token))

        content = response.content.decode('utf-8')
        self.assertEqual(503, response.status_code)
        self.assertIn('Обязательный сервис временно недоступен.', content)
        self.assertIn('Verification required', content)
        self.assertNotIn('must-not-render', content)
        self.assertEqual(1, self.adapter.start_planned.call_count)

    def test_malformed_planned_response_is_uncertain_logged_and_not_retried(
            self):
        token = _token_from(self.client.get(_url()))
        self.adapter.start_planned.return_value = {
            'id': 'bmc_address=must-not-be-logged',
        }

        with mock.patch.object(views.LOG, 'error') as log_error:
            response = self.client.post(_url(), _post(token))

        content = response.content.decode('utf-8')
        self.assertEqual(503, response.status_code)
        self.assertIn('Обязательный сервис временно недоступен.', content)
        self.assertIn('Verification required', content)
        self.assertEqual(1, self.adapter.start_planned.call_count)
        log_error.assert_called_once_with(
            'PowerOps mutation response is uncertain '
            '[request_id=%s, exception_type=%s]',
            'unavailable',
            'InvalidBackendData',
        )
        self.assertNotIn('bmc_address', str(log_error.call_args))

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
