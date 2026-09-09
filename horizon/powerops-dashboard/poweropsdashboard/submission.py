from collections import abc
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid

from django.core.cache import cache

from poweropsdashboard import constants
from poweropsdashboard import presentation


SESSION_DIGEST_KEY = 'powerops_submission_digest'
SESSION_EXECUTION_KEY = 'powerops_last_execution_id'

_READ_DEADLINE_SECONDS = 30.0
_READ_POLL_INTERVAL_SECONDS = 0.5
_SUBMISSION_CLAIM_TTL_SECONDS = 300
_monotonic = time.monotonic
_sleep = time.sleep

_PLANNED_OPERATIONS = frozenset({'power_off', 'reboot'})
_MUTATION_WORKFLOWS = frozenset({
    constants.PLANNED_POWER_OFF,
    constants.PLANNED_REBOOT,
    constants.POWER_ON_AND_RETURN,
})
_STATUS_RESULT_KEYS = frozenset({
    'host',
    'ironic_node_uuid',
    'power_state',
    'target_power_state',
    'ironic_last_error',
    'nova_enabled',
    'nova_state',
    'masakari_maintenance',
})
_POLLABLE_READ_STATES = frozenset({
    'IDLE', 'RUNNING', 'DELAYED', 'WAITING',
})
_EXECUTION_STATES = _POLLABLE_READ_STATES | frozenset({
    'SUCCESS', 'ERROR', 'PAUSED', 'CANCELLED',
})
_HOST_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')


class SubmissionConflict(Exception):
    pass


class InvalidSubmission(Exception):
    pass


def _validate_target(operation, host):
    if operation not in _PLANNED_OPERATIONS:
        raise InvalidSubmission('Unsupported planned operation')
    if not isinstance(host, str) or not host:
        raise InvalidSubmission('Invalid planned operation target')


def _submission_digest(token, operation, host):
    value = '\0'.join((token, operation, host)).encode('utf-8')
    return hashlib.sha256(value).hexdigest()


def issue_submission_token(request, operation, host):
    _validate_target(operation, host)
    token = secrets.token_urlsafe(32)
    request.session[SESSION_DIGEST_KEY] = _submission_digest(
        token, operation, host)
    request.session.modified = True
    return token


def consume_submission_token(request, token, operation, host):
    _validate_target(operation, host)
    if not isinstance(token, str) or not token:
        raise SubmissionConflict('Submission token is missing')

    stored = request.session.get(SESSION_DIGEST_KEY)
    candidate = _submission_digest(token, operation, host)
    if (not isinstance(stored, str)
            or len(stored) != 64
            or not hmac.compare_digest(stored, candidate)):
        raise SubmissionConflict('Submission token is invalid or consumed')

    claim_key = 'powerops-submission-{}'.format(stored)
    try:
        claimed = cache.add(
            claim_key,
            True,
            timeout=_SUBMISSION_CLAIM_TTL_SECONDS,
        )
    except Exception:
        raise SubmissionConflict(
            'Submission token could not be claimed') from None
    if claimed is not True:
        raise SubmissionConflict('Submission token is already claimed')

    del request.session[SESSION_DIGEST_KEY]
    request.session.modified = True


def _resource_value(resource, name):
    if isinstance(resource, abc.Mapping):
        if name not in resource:
            raise SubmissionConflict('Required preflight data is missing')
        return resource[name]
    try:
        return getattr(resource, name)
    except (AttributeError, TypeError):
        raise SubmissionConflict(
            'Required preflight data is missing') from None


def _mapping(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            raise SubmissionConflict(
                'Required preflight data is malformed') from None
    if not isinstance(value, abc.Mapping):
        raise SubmissionConflict('Required preflight data is malformed')
    return dict(value)


def _canonical_uuid(value):
    if not isinstance(value, str) or len(value) != 36:
        raise SubmissionConflict('Execution identifier is malformed')
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        raise SubmissionConflict('Execution identifier is malformed') from None
    if str(parsed) != value:
        raise SubmissionConflict('Execution identifier is malformed')
    return value


def _read_envelope(execution, expected_workflow, expected_input,
                   expected_id=None):
    execution_id = _canonical_uuid(_resource_value(execution, 'id'))
    if expected_id is not None and execution_id != expected_id:
        raise SubmissionConflict('Read execution identity changed')

    workflow_name = _resource_value(execution, 'workflow_name')
    if (not isinstance(workflow_name, str)
            or workflow_name != expected_workflow):
        raise SubmissionConflict('Read execution workflow changed')

    workflow_input = _mapping(_resource_value(execution, 'input'))
    if workflow_input != expected_input:
        raise SubmissionConflict('Read execution target changed')

    state = _resource_value(execution, 'state')
    if not isinstance(state, str) or state not in _EXECUTION_STATES:
        raise SubmissionConflict('Read execution state is invalid')
    if state not in _POLLABLE_READ_STATES and state != 'SUCCESS':
        raise SubmissionConflict('Read execution did not succeed')
    return execution_id, state


def _wait_for_read(client, execution, expected_workflow, expected_input):
    execution_id, state = _read_envelope(
        execution, expected_workflow, expected_input)
    if state == 'SUCCESS':
        return execution

    deadline = _monotonic() + _READ_DEADLINE_SECONDS
    while True:
        remaining = deadline - _monotonic()
        if remaining <= 0:
            raise SubmissionConflict('Read execution timed out')
        _sleep(min(_READ_POLL_INTERVAL_SECONDS, remaining))
        execution = client.get_execution(execution_id)
        _polled_id, state = _read_envelope(
            execution,
            expected_workflow,
            expected_input,
            expected_id=execution_id,
        )
        if state == 'SUCCESS':
            return execution


def _select_host(inventory_execution, host, segment_uuid):
    try:
        rows = presentation.parse_inventory_execution(inventory_execution)
    except Exception:
        raise SubmissionConflict(
            'Fresh PowerOps inventory failed validation') from None

    matches = tuple(
        row for row in rows
        if row.host == host and row.segment_uuid == segment_uuid
    )
    if len(matches) != 1:
        raise SubmissionConflict('Host mapping is missing or ambiguous')
    if not matches[0].operable:
        raise SubmissionConflict('Host is not operable')
    required_state = (
        matches[0].ironic_node_uuid,
        matches[0].power_state,
        matches[0].nova_status,
        matches[0].nova_state,
        matches[0].masakari_maintenance,
    )
    if any(value is None for value in required_state):
        raise SubmissionConflict('Operable host state is incomplete')
    return matches[0]


def _validate_status(status_execution, host_row):
    try:
        if (_resource_value(status_execution, 'workflow_name')
                != constants.HOST_POWER_STATUS):
            raise SubmissionConflict('Unexpected preflight workflow')
        if _resource_value(status_execution, 'state') != 'SUCCESS':
            raise SubmissionConflict('Host status preflight did not finish')

        workflow_input = _mapping(
            _resource_value(status_execution, 'input'))
        if workflow_input != {
                'host': host_row.host,
                'segment_uuid': host_row.segment_uuid}:
            raise SubmissionConflict('Host status target changed')

        output = _mapping(_resource_value(status_execution, 'output'))
        if set(output) != {'result'}:
            raise SubmissionConflict('Host status output is malformed')
        result = _mapping(output['result'])
        if set(result) != _STATUS_RESULT_KEYS:
            raise SubmissionConflict('Host status result is malformed')
        if (type(result['nova_enabled']) is not bool
                or type(result['masakari_maintenance']) is not bool):
            raise SubmissionConflict('Host status types are malformed')
    except SubmissionConflict:
        raise
    except Exception:
        raise SubmissionConflict(
            'Host status preflight failed validation') from None

    expected = {
        'host': host_row.host,
        'ironic_node_uuid': host_row.ironic_node_uuid,
        'power_state': host_row.power_state,
        'target_power_state': host_row.target_power_state,
        'ironic_last_error': None,
        'nova_enabled': host_row.nova_status == 'enabled',
        'nova_state': host_row.nova_state,
        'masakari_maintenance': host_row.masakari_maintenance,
    }
    if result != expected:
        raise SubmissionConflict('Host state changed during preflight')


def _mutation_target(execution, workflow_name):
    workflow_input = _mapping(_resource_value(execution, 'input'))
    if workflow_name in {
            constants.PLANNED_POWER_OFF, constants.PLANNED_REBOOT}:
        if set(workflow_input) != {
                'host', 'segment_uuid', 'instance_policy',
                'allow_hard_off'}:
            raise SubmissionConflict('Mutation input is malformed')
        if (workflow_input['instance_policy']
                not in constants.INSTANCE_POLICIES):
            raise SubmissionConflict('Mutation policy is malformed')
        if type(workflow_input['allow_hard_off']) is not bool:
            raise SubmissionConflict('Mutation hard-off input is malformed')
    else:
        if set(workflow_input) != {
                'host', 'segment_uuid', 'stopped_instance_ids'}:
            raise SubmissionConflict('Mutation input is malformed')
        stopped_instance_ids = workflow_input['stopped_instance_ids']
        if not isinstance(stopped_instance_ids, list):
            raise SubmissionConflict('Mutation manifest is malformed')
        parsed_ids = tuple(
            _canonical_uuid(instance_id)
            for instance_id in stopped_instance_ids
        )
        if len(set(parsed_ids)) != len(parsed_ids):
            raise SubmissionConflict('Mutation manifest is malformed')

    host = workflow_input['host']
    if not isinstance(host, str) or not _HOST_RE.fullmatch(host):
        raise SubmissionConflict('Mutation host is malformed')
    segment_uuid = _canonical_uuid(workflow_input['segment_uuid'])
    return host, segment_uuid


def _has_active_mutation(executions, host_row):
    for execution in executions:
        try:
            workflow_name = _resource_value(execution, 'workflow_name')
        except SubmissionConflict:
            raise SubmissionConflict(
                'Execution workflow name is missing') from None
        if not isinstance(workflow_name, str):
            raise SubmissionConflict('Execution workflow name is malformed')
        if workflow_name not in _MUTATION_WORKFLOWS:
            continue
        try:
            state = _resource_value(execution, 'state')
        except SubmissionConflict:
            raise SubmissionConflict(
                'Active PowerOps mutation data is ambiguous') from None
        if not isinstance(state, str) or state not in _EXECUTION_STATES:
            raise SubmissionConflict(
                'Active PowerOps mutation data is ambiguous')
        target = _mutation_target(execution, workflow_name)
        if state in constants.TERMINAL_STATES:
            continue
        if target == (host_row.host, host_row.segment_uuid):
            return True
    return False


def planned_preflight(client, authorization, host, segment_uuid):
    try:
        inventory_execution = client.start_inventory()
        inventory_execution = _wait_for_read(
            client,
            inventory_execution,
            constants.HOST_INVENTORY,
            {},
        )
        host_row = _select_host(inventory_execution, host, segment_uuid)
        status_execution = client.start_host_status(
            host_row.host, host_row.segment_uuid)
        status_execution = _wait_for_read(
            client,
            status_execution,
            constants.HOST_POWER_STATUS,
            {
                'host': host_row.host,
                'segment_uuid': host_row.segment_uuid,
            },
        )
        _validate_status(status_execution, host_row)
        executions = client.list_executions(
            all_projects=authorization.is_admin)
        if _has_active_mutation(executions, host_row):
            raise SubmissionConflict('Another PowerOps mutation is active')
    except SubmissionConflict:
        raise
    except Exception:
        raise SubmissionConflict('PowerOps preflight failed') from None
    return host_row
