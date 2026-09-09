SEGMENT_UUID = '11111111-1111-1111-1111-111111111111'
SECOND_SEGMENT_UUID = '55555555-5555-5555-5555-555555555555'
RETURN_SEGMENT_UUID = '77777777-7777-7777-7777-777777777777'
ACTION_SEGMENT_UUID = '14141414-1414-1414-1414-141414141414'
NODE_UUID = '22222222-2222-2222-2222-222222222222'
SECOND_NODE_UUID = '66666666-6666-6666-6666-666666666666'
RETURN_NODE_UUID = '88888888-8888-8888-8888-888888888888'
ACTION_NODE_UUID = '15151515-1515-1515-1515-151515151515'
FIRST_INSTANCE_UUID = '33333333-3333-3333-3333-333333333333'
SECOND_INSTANCE_UUID = '44444444-4444-4444-4444-444444444444'
INVENTORY_EXECUTION_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
STATUS_EXECUTION_UUID = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
PLANNED_EXECUTION_UUID = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
RETURN_EXECUTION_UUID = 'dddddddd-dddd-dddd-dddd-dddddddddddd'
TASK_UUID = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
SOURCE_EXECUTION_UUID = '99999999-9999-9999-9999-999999999999'
ERROR_EXECUTION_UUID = '12121212-1212-1212-1212-121212121212'
RETURN_STATUS_EXECUTION_UUID = '13131313-1313-1313-1313-131313131313'
ACTION_STATUS_EXECUTION_UUID = '16161616-1616-1616-1616-161616161616'

PRIMARY_HOST = 'compute-01'
RETURN_HOST = 'compute-03'
ACTION_HOST = 'compute-04'

HOST_ROWS = [{
    'region_name': 'RegionOne',
    'segment_uuid': SEGMENT_UUID,
    'host': PRIMARY_HOST,
    'ironic_node_uuid': NODE_UUID,
    'power_state': 'power on',
    'target_power_state': None,
    'nova_status': 'enabled',
    'nova_state': 'up',
    'masakari_maintenance': False,
    'instance_count': 2,
    'instances': [{
        'id': FIRST_INSTANCE_UUID,
        'name': 'demo-active',
        'project_id': '11111111111111111111111111111111',
        'status': 'ACTIVE',
    }, {
        'id': SECOND_INSTANCE_UUID,
        'name': 'demo-shutoff',
        'project_id': '22222222222222222222222222222222',
        'status': 'SHUTOFF',
    }],
    'operable': True,
    'blocking_reason': None,
}, {
    'region_name': 'RegionOne',
    'segment_uuid': SECOND_SEGMENT_UUID,
    'host': 'compute-02',
    'ironic_node_uuid': SECOND_NODE_UUID,
    'power_state': 'power on',
    'target_power_state': None,
    'nova_status': 'enabled',
    'nova_state': 'up',
    'masakari_maintenance': False,
    'instance_count': 0,
    'instances': [],
    'operable': False,
    'blocking_reason': 'ambiguous_masakari_host',
}, {
    'region_name': 'RegionOne',
    'segment_uuid': ACTION_SEGMENT_UUID,
    'host': ACTION_HOST,
    'ironic_node_uuid': ACTION_NODE_UUID,
    'power_state': 'power on',
    'target_power_state': None,
    'nova_status': 'enabled',
    'nova_state': 'up',
    'masakari_maintenance': False,
    'instance_count': 0,
    'instances': [],
    'operable': True,
    'blocking_reason': None,
}]

INVENTORY_EXECUTION = {
    'id': INVENTORY_EXECUTION_UUID,
    'workflow_name': 'power_ops.host_inventory',
    'state': 'SUCCESS',
    'state_info': None,
    'input': {},
    'output': {'result': HOST_ROWS},
    'created_at': '2026-09-03T09:00:00.000000',
}

STATUS_EXECUTION = {
    'id': STATUS_EXECUTION_UUID,
    'workflow_name': 'power_ops.host_power_status',
    'state': 'SUCCESS',
    'state_info': None,
    'input': {
        'host': PRIMARY_HOST,
        'segment_uuid': SEGMENT_UUID,
    },
    'output': {'result': {
        'host': PRIMARY_HOST,
        'ironic_node_uuid': NODE_UUID,
        'power_state': 'power on',
        'target_power_state': None,
        'ironic_last_error': None,
        'nova_enabled': True,
        'nova_state': 'up',
        'masakari_maintenance': False,
    }},
    'created_at': '2026-09-03T09:30:00.000000',
}

RETURN_STATUS_EXECUTION = {
    'id': RETURN_STATUS_EXECUTION_UUID,
    'workflow_name': 'power_ops.host_power_status',
    'state': 'SUCCESS',
    'state_info': None,
    'input': {
        'host': RETURN_HOST,
        'segment_uuid': RETURN_SEGMENT_UUID,
    },
    'output': {'result': {
        'host': RETURN_HOST,
        'ironic_node_uuid': RETURN_NODE_UUID,
        'power_state': 'power on',
        'target_power_state': None,
        'ironic_last_error': None,
        'nova_enabled': False,
        'nova_state': 'up',
        'masakari_maintenance': True,
    }},
    'created_at': '2026-09-03T10:25:00.000000',
}

ACTION_STATUS_EXECUTION = {
    'id': ACTION_STATUS_EXECUTION_UUID,
    'workflow_name': 'power_ops.host_power_status',
    'state': 'SUCCESS',
    'state_info': None,
    'input': {
        'host': ACTION_HOST,
        'segment_uuid': ACTION_SEGMENT_UUID,
    },
    'output': {'result': {
        'host': ACTION_HOST,
        'ironic_node_uuid': ACTION_NODE_UUID,
        'power_state': 'power on',
        'target_power_state': None,
        'ironic_last_error': None,
        'nova_enabled': True,
        'nova_state': 'up',
        'masakari_maintenance': False,
    }},
    'created_at': '2026-09-03T10:26:00.000000',
}

PLANNED_EXECUTION = {
    'id': PLANNED_EXECUTION_UUID,
    'workflow_name': 'power_ops.planned_power_off',
    'state': 'RUNNING',
    'state_info': None,
    'input': {
        'host': PRIMARY_HOST,
        'segment_uuid': SEGMENT_UUID,
        'instance_policy': 'require_empty',
        'allow_hard_off': False,
    },
    'output': {},
    'created_at': '2026-09-03T10:00:00.000000',
}

RETURN_EXECUTION = {
    'id': RETURN_EXECUTION_UUID,
    'workflow_name': 'power_ops.power_on_and_return',
    'state': 'PAUSED',
    'state_info': None,
    'input': {
        'host': RETURN_HOST,
        'segment_uuid': RETURN_SEGMENT_UUID,
        'stopped_instance_ids': [FIRST_INSTANCE_UUID],
    },
    'output': {},
    'created_at': '2026-09-03T10:30:00.000000',
}

SOURCE_EXECUTION = {
    'id': SOURCE_EXECUTION_UUID,
    'workflow_name': 'power_ops.planned_power_off',
    'state': 'SUCCESS',
    'state_info': None,
    'input': {
        'host': RETURN_HOST,
        'segment_uuid': RETURN_SEGMENT_UUID,
        'instance_policy': 'stop',
        'allow_hard_off': False,
    },
    'output': {
        'result': {
            'host': RETURN_HOST,
            'operation': 'planned_power_off',
            'power_state': 'power off',
            'stopped_instance_ids': [FIRST_INSTANCE_UUID],
            'nova_enabled': False,
            'masakari_maintenance': True,
        },
        'stopped_instance_ids': [FIRST_INSTANCE_UUID],
    },
    'created_at': '2026-09-03T10:20:00.000000',
}

ERROR_EXECUTION = {
    'id': ERROR_EXECUTION_UUID,
    'workflow_name': 'power_ops.planned_reboot',
    'state': 'ERROR',
    'state_info': None,
    'input': {
        'host': 'compute-02',
        'segment_uuid': SECOND_SEGMENT_UUID,
        'instance_policy': 'require_empty',
        'allow_hard_off': False,
    },
    'output': {},
    'verification_required': True,
    'created_at': '2026-09-03T10:40:00.000000',
}

EXECUTIONS = [
    ERROR_EXECUTION,
    RETURN_EXECUTION,
    PLANNED_EXECUTION,
    SOURCE_EXECUTION,
    ACTION_STATUS_EXECUTION,
    RETURN_STATUS_EXECUTION,
    STATUS_EXECUTION,
    INVENTORY_EXECUTION,
]

TASKS = {
    STATUS_EXECUTION_UUID: [{
        'id': TASK_UUID,
        'name': 'status',
        'type': 'ACTION',
        'state': 'SUCCESS',
    }],
    PLANNED_EXECUTION_UUID: [{
        'id': TASK_UUID,
        'name': 'power_off',
        'type': 'ACTION',
        'state': 'RUNNING',
    }],
    RETURN_EXECUTION_UUID: [{
        'id': TASK_UUID,
        'name': 'operator_inspection_gate',
        'type': 'ACTION',
        'state': 'IDLE',
    }],
}
