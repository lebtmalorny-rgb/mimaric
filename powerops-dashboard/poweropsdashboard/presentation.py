from collections import abc
import dataclasses
import json
import math
import re
from types import MappingProxyType
import typing
import uuid

from django.conf import settings

from poweropsdashboard import constants
from poweropsdashboard import exceptions


_HOST_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
_FORBIDDEN_KEY_PARTS = (
    'token',
    'password',
    'secret',
    'bmc',
    'driver_info',
    'instance_info',
    'service_catalog',
)
_ROW_KEYS = frozenset({
    'region_name',
    'segment_uuid',
    'host',
    'ironic_node_uuid',
    'power_state',
    'target_power_state',
    'nova_status',
    'nova_state',
    'masakari_maintenance',
    'instance_count',
    'instances',
    'operable',
    'blocking_reason',
})
_INSTANCE_KEYS = frozenset({'id', 'name', 'project_id', 'status'})
_EXECUTION_STATES = frozenset({
    'IDLE', 'RUNNING', 'SUCCESS', 'ERROR', 'PAUSED', 'CANCELLED',
    'DELAYED', 'WAITING',
})
_TASK_STATES = _EXECUTION_STATES
_SAFE_RESULT_KEYS = frozenset({
    'host',
    'operation',
    'ironic_node_uuid',
    'power_state',
    'target_power_state',
    'nova_enabled',
    'nova_state',
    'masakari_maintenance',
    'stopped_instance_ids',
})
_SAFE_OPERATIONS = frozenset({
    'planned_power_off',
    'planned_reboot',
    'power_on_for_inspection',
    'return_to_service',
})
_FIXED_STATE_INFO = {
    'ERROR': (
        'Execution failed; verify host state before another operation.'
    ),
    'CANCELLED': 'Execution was cancelled.',
    'PAUSED': 'Execution is paused for operator inspection.',
}


@dataclasses.dataclass(frozen=True)
class InstanceRow:
    id: str
    name: str
    project_id: str
    status: str


@dataclasses.dataclass(frozen=True)
class HostRow:
    region_name: str
    segment_uuid: str
    host: str
    ironic_node_uuid: typing.Optional[str]
    power_state: typing.Optional[str]
    target_power_state: typing.Optional[str]
    nova_status: typing.Optional[str]
    nova_state: typing.Optional[str]
    masakari_maintenance: typing.Optional[bool]
    instance_count: int
    instances: typing.Tuple[InstanceRow, ...]
    operable: bool
    blocking_reason: typing.Optional[str]


@dataclasses.dataclass(frozen=True)
class ExecutionState:
    id: str
    workflow_name: str
    state: str
    state_info: typing.Optional[str]
    verification_required: bool
    output: typing.Mapping[str, object]


@dataclasses.dataclass(frozen=True)
class TaskState:
    id: str
    name: str
    task_type: typing.Optional[str]
    state: str


def _invalid():
    return exceptions.InvalidBackendData(
        'PowerOps backend data failed validation'
    )


def _resource_value(resource, name):
    if isinstance(resource, abc.Mapping):
        if name not in resource:
            raise _invalid()
        return resource[name]
    try:
        return getattr(resource, name)
    except (AttributeError, TypeError):
        raise _invalid() from None


def _reject_json_constant(value):
    raise ValueError(value)


def _mapping(value, empty_for_none=False):
    if empty_for_none and value in (None, ''):
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(
                value,
                parse_constant=_reject_json_constant,
            )
        except (TypeError, ValueError):
            raise _invalid() from None
    if not isinstance(value, abc.Mapping):
        raise _invalid()
    return dict(value)


def _scan_json(value):
    if isinstance(value, abc.Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise _invalid()
            lowered = key.lower()
            if any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
                raise _invalid()
            _scan_json(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _scan_json(child)
    elif value is not None:
        if type(value) not in (str, int, float, bool):
            raise _invalid()
        if type(value) is float and not math.isfinite(value):
            raise _invalid()


def _string(value):
    if not isinstance(value, str) or not value:
        raise _invalid()
    return value


def _uuid(value, optional=False):
    if optional and value is None:
        return None
    value = _string(value)
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        raise _invalid() from None
    if str(parsed) != value.lower() or len(value) != 36:
        raise _invalid()
    return value


def _host(value):
    value = _string(value)
    if not _HOST_RE.fullmatch(value):
        raise _invalid()
    return value


def _choice(value, choices, optional=False):
    if optional and value is None:
        return None
    if value not in choices:
        raise _invalid()
    return value


def _boolean(value, optional=False):
    if optional and value is None:
        return None
    if type(value) is not bool:
        raise _invalid()
    return value


def _uuid_list(value):
    if not isinstance(value, list):
        raise _invalid()
    result = tuple(_uuid(item) for item in value)
    if len(set(result)) != len(result):
        raise _invalid()
    return result


def _parse_instance(value):
    if not isinstance(value, dict) or set(value) != _INSTANCE_KEYS:
        raise _invalid()
    return InstanceRow(
        id=_uuid(value['id']),
        name=_string(value['name']),
        project_id=_string(value['project_id']),
        status=_string(value['status']),
    )


def _parse_row(value):
    if not isinstance(value, dict) or set(value) != _ROW_KEYS:
        raise _invalid()
    if not isinstance(value['instances'], list):
        raise _invalid()
    if (type(value['instance_count']) is not int
            or value['instance_count'] < 0):
        raise _invalid()

    instances = tuple(_parse_instance(item)
                      for item in value['instances'])
    if value['instance_count'] != len(instances):
        raise _invalid()
    if len({item.id for item in instances}) != len(instances):
        raise _invalid()

    operable = _boolean(value['operable'])
    blocking_reason = value['blocking_reason']
    if operable:
        if blocking_reason is not None:
            raise _invalid()
    elif blocking_reason not in constants.BLOCKING_REASONS:
        raise _invalid()

    region_name = _string(value['region_name'])
    if region_name != settings.POWEROPS_REGION_NAME:
        raise _invalid()

    return HostRow(
        region_name=settings.POWEROPS_REGION_NAME,
        segment_uuid=_uuid(value['segment_uuid']),
        host=_host(value['host']),
        ironic_node_uuid=_uuid(value['ironic_node_uuid'], optional=True),
        power_state=_choice(
            value['power_state'], {'power on', 'power off'}, optional=True),
        target_power_state=_choice(
            value['target_power_state'],
            {'power on', 'power off'},
            optional=True,
        ),
        nova_status=_choice(
            value['nova_status'], {'enabled', 'disabled'}, optional=True),
        nova_state=_choice(
            value['nova_state'], {'up', 'down'}, optional=True),
        masakari_maintenance=_boolean(
            value['masakari_maintenance'], optional=True),
        instance_count=value['instance_count'],
        instances=instances,
        operable=operable,
        blocking_reason=blocking_reason,
    )


def parse_inventory_execution(execution):
    if _resource_value(execution, 'workflow_name') != constants.HOST_INVENTORY:
        raise _invalid()
    if _resource_value(execution, 'state') != 'SUCCESS':
        raise _invalid()

    output = _mapping(_resource_value(execution, 'output'))
    _scan_json(output)
    if set(output) != {'result'} or not isinstance(output['result'], list):
        raise _invalid()

    rows = tuple(_parse_row(item) for item in output['result'])
    targets = {(row.host, row.segment_uuid) for row in rows}
    if len(targets) != len(rows):
        raise _invalid()
    return rows


def latest_successful_inventory(executions):
    for execution in executions:
        try:
            workflow_name = _resource_value(execution, 'workflow_name')
            state = _resource_value(execution, 'state')
        except exceptions.InvalidBackendData:
            continue
        if workflow_name == constants.HOST_INVENTORY and state == 'SUCCESS':
            return parse_inventory_execution(execution)
    return None


def _safe_result(value):
    if not isinstance(value, abc.Mapping):
        return MappingProxyType({})
    result = {}
    for key in _SAFE_RESULT_KEYS.intersection(value):
        raw = value[key]
        if key == 'host':
            result[key] = _host(raw)
        elif key == 'operation':
            result[key] = _choice(raw, _SAFE_OPERATIONS)
        elif key == 'ironic_node_uuid':
            result[key] = _uuid(raw, optional=True)
        elif key in ('power_state', 'target_power_state'):
            result[key] = _choice(
                raw, {'power on', 'power off'}, optional=True)
        elif key in ('nova_enabled', 'masakari_maintenance'):
            result[key] = _boolean(raw, optional=True)
        elif key == 'nova_state':
            result[key] = _choice(raw, {'up', 'down'}, optional=True)
        elif key == 'stopped_instance_ids':
            result[key] = _uuid_list(raw)
    return MappingProxyType(result)


def _safe_execution_output(execution, workflow_name):
    raw_output = _mapping(
        _resource_value(execution, 'output'), empty_for_none=True)
    _scan_json(raw_output)

    if workflow_name == constants.HOST_INVENTORY:
        rows = parse_inventory_execution(execution)
        return MappingProxyType({'host_count': len(rows)})

    result = {}
    if 'result' in raw_output:
        result['result'] = _safe_result(raw_output['result'])
    if 'stopped_instance_ids' in raw_output:
        result['stopped_instance_ids'] = _uuid_list(
            raw_output['stopped_instance_ids'])
    return MappingProxyType(result)


def parse_execution_state(execution):
    execution_id = _uuid(_resource_value(execution, 'id'))
    workflow_name = _choice(
        _resource_value(execution, 'workflow_name'),
        constants.POWEROPS_WORKFLOWS,
    )
    state = _choice(
        _resource_value(execution, 'state'), _EXECUTION_STATES)
    return ExecutionState(
        id=execution_id,
        workflow_name=workflow_name,
        state=state,
        state_info=_FIXED_STATE_INFO.get(state),
        verification_required=state == 'ERROR',
        output=_safe_execution_output(execution, workflow_name),
    )


def parse_tasks(tasks):
    result = []
    for task in tasks:
        task_type = _resource_value(task, 'type')
        if task_type is not None:
            task_type = _string(task_type)
        result.append(TaskState(
            id=_uuid(_resource_value(task, 'id')),
            name=_string(_resource_value(task, 'name')),
            task_type=task_type,
            state=_choice(_resource_value(task, 'state'), _TASK_STATES),
        ))
    return tuple(result)


def _execution_target(execution, workflow_name):
    if workflow_name == constants.HOST_INVENTORY:
        return None
    workflow_input = _mapping(_resource_value(execution, 'input'))
    _scan_json(workflow_input)
    allowed = {'host', 'segment_uuid'}
    if workflow_name in {
            constants.PLANNED_POWER_OFF, constants.PLANNED_REBOOT}:
        allowed.update({'instance_policy', 'allow_hard_off'})
    elif workflow_name == constants.POWER_ON_AND_RETURN:
        allowed.add('stopped_instance_ids')
    if not {'host', 'segment_uuid'}.issubset(workflow_input):
        raise _invalid()
    if not set(workflow_input).issubset(allowed):
        raise _invalid()
    if 'instance_policy' in workflow_input:
        _choice(workflow_input['instance_policy'], constants.INSTANCE_POLICIES)
    if 'allow_hard_off' in workflow_input:
        _boolean(workflow_input['allow_hard_off'])
    if 'stopped_instance_ids' in workflow_input:
        _uuid_list(workflow_input['stopped_instance_ids'])
    return (
        _host(workflow_input['host']),
        _uuid(workflow_input['segment_uuid']),
    )


def match_active_executions(executions):
    result = {}
    for execution in executions:
        try:
            workflow_name = _choice(
                _resource_value(execution, 'workflow_name'),
                constants.POWEROPS_WORKFLOWS,
            )
            state = _choice(
                _resource_value(execution, 'state'), _EXECUTION_STATES)
            if state in constants.TERMINAL_STATES:
                continue
            target = _execution_target(execution, workflow_name)
            if target is None or target in result:
                continue
            result[target] = parse_execution_state(execution)
        except exceptions.InvalidBackendData:
            continue
    return MappingProxyType(result)


def execution_id(execution):
    return _uuid(_resource_value(execution, 'id'))
