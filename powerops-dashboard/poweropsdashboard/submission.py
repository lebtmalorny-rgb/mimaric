from collections import abc
import hashlib
import hmac
import json
import secrets

from poweropsdashboard import constants
from poweropsdashboard import presentation


SESSION_DIGEST_KEY = 'powerops_submission_digest'
SESSION_EXECUTION_KEY = 'powerops_last_execution_id'

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


def _has_active_mutation(executions, host_row):
    for execution in executions:
        try:
            workflow_name = _resource_value(execution, 'workflow_name')
        except SubmissionConflict:
            continue
        if workflow_name not in _MUTATION_WORKFLOWS:
            continue
        try:
            state = _resource_value(execution, 'state')
        except SubmissionConflict:
            raise SubmissionConflict(
                'Active PowerOps mutation data is ambiguous') from None
        if state in constants.TERMINAL_STATES:
            continue

        active = presentation.match_active_executions((execution,))
        if len(active) != 1:
            raise SubmissionConflict(
                'Active PowerOps mutation data is ambiguous')
        if (host_row.host, host_row.segment_uuid) in active:
            return True
    return False


def planned_preflight(client, authorization, host, segment_uuid):
    try:
        inventory_execution = client.start_inventory()
        host_row = _select_host(inventory_execution, host, segment_uuid)
        status_execution = client.start_host_status(
            host_row.host, host_row.segment_uuid)
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
