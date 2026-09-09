HOST_INVENTORY = 'power_ops.host_inventory'
HOST_POWER_STATUS = 'power_ops.host_power_status'
PLANNED_POWER_OFF = 'power_ops.planned_power_off'
PLANNED_REBOOT = 'power_ops.planned_reboot'
POWER_ON_AND_RETURN = 'power_ops.power_on_and_return'

POWEROPS_WORKFLOWS = frozenset({
    HOST_INVENTORY,
    HOST_POWER_STATUS,
    PLANNED_POWER_OFF,
    PLANNED_REBOOT,
    POWER_ON_AND_RETURN,
})
INSTANCE_POLICIES = ('require_empty', 'live_migrate', 'stop')
TERMINAL_STATES = frozenset({'SUCCESS', 'ERROR', 'CANCELLED'})

BLOCKING_REASONS = frozenset({
    'ambiguous_masakari_host',
    'missing_nova_service',
    'ambiguous_nova_service',
    'missing_ironic_node',
    'ambiguous_ironic_node',
    'ironic_node_incompatible',
    'invalid_instance_data',
})

BLOCKING_REASON_MESSAGES = {
    'ambiguous_masakari_host': 'Masakari host mapping is ambiguous',
    'missing_nova_service': 'Nova compute service was not found',
    'ambiguous_nova_service': 'Nova compute service mapping is ambiguous',
    'missing_ironic_node': 'Ironic node was not found',
    'ambiguous_ironic_node': 'Ironic node mapping is ambiguous',
    'ironic_node_incompatible': 'Ironic node is not safe for PowerOps',
    'invalid_instance_data': 'Instance inventory is incomplete',
}
