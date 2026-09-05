"""Offline regression probes for the three additional PowerOps fixes.

Run only with the local Mistral test virtualenv. No real HTTP or power actions.
Assertions require safe behavior. This is not live infrastructure acceptance.
"""

from types import SimpleNamespace
from unittest import mock

from verify_sdk_contracts import SDKContractAudit

from mistral.actions.powerops import base
from mistral.actions.powerops import clients
from mistral.actions.powerops import planned
from mistral import config
from mistral.services import powerops
from mistral.tests.unit.actions.powerops import fakes


config.CONF.set_override('enabled', True, group='powerops')
config.CONF.set_override('allowed_project_names', ['operations'],
                         group='powerops')
config.CONF.set_override('allowed_user_names', ['powerops-operator'],
                         group='powerops')

admin = SimpleNamespace(roles=['admin'], project_name='admin', user_name='admin')
assert powerops.authorize(admin) == 'admin'
base.PowerOpsAction()._authorize(SimpleNamespace(security=admin))
print('VERIFIED: admin outside operator allowlists passes API and action')

member = SimpleNamespace(roles=['member'], project_name='operations',
                         user_name='powerops-operator')
try:
    powerops.authorize(member, allow_hard_off=True)
except Exception as error:
    assert type(error).__name__ == 'NotAllowedException'
else:
    raise AssertionError('Expected API authorization denial')
action = planned.PlannedPowerOffAction('compute-01', 'segment-1',
                                       allow_hard_off=True)
try:
    action._authorize(SimpleNamespace(security=member))
except clients.exceptions.PowerOpsUnauthorized:
    print('VERIFIED: allowlisted member rejected by action and API '
          '(no power action executed)')
else:
    raise AssertionError('Expected action authorization denial')

audit = SDKContractAudit('test_stop_manifest_and_restart')
try:
    audit.setUp()
    audit.server['OS-EXT-SRV-ATTR:host'] = audit.other_host
    audit.server['status'] = 'SHUTOFF'
    try:
        audit.cloud.start_instances(audit.host, [audit.server_id])
    except clients.exceptions.InstanceManifestError:
        pass
    else:
        raise AssertionError('Foreign restart manifest was accepted')
    assert audit.server['status'] == 'SHUTOFF'
    assert audit.server['OS-EXT-SRV-ATTR:host'] == audit.other_host
    print('VERIFIED: restart manifest rejects VM from another compute host '
          '(real SDK, intercepted HTTP)')
finally:
    audit.doCleanups()

host = fakes.masakari_host('host-1', 'compute-01', on_maintenance=False)
service = fakes.service('service-1', 'compute-01', status='enabled')
data = fakes.cloud(
    ironic_nodes=[fakes.node('node-1', 'compute-01')],
    nova_services=[service], masakari_hosts=[host],
)
cloud = clients.CloudClients(data.connection, ha_adapter=data.ha_adapter,
                             sleep=lambda _seconds: None)
original_get = data.ha_adapter.get.side_effect


def fail_readback(path):
    if host.on_maintenance:
        raise RuntimeError('simulated read-back failure after applied PUT')
    return original_get(path)


data.ha_adapter.get.side_effect = fail_readback
coordinator = fakes.recording_coordinator([])
coordinator.assert_healthy = lambda: None
with mock.patch.object(base.coordination, 'OperationCoordinator',
                       return_value=coordinator), \
        mock.patch.object(clients, 'connection_from_conf',
                          return_value=data.connection), \
        mock.patch.object(clients, 'CloudClients', return_value=cloud):
    action = planned.PlannedPowerOffAction('compute-01', 'segment-1')
    try:
        action.run(fakes.action_context('offline-execution'))
    except RuntimeError as error:
        assert 'read-back' in str(error)
    else:
        raise AssertionError('Expected simulated read-back error')

assert host.on_maintenance is True
assert service.status == 'disabled'
assert data.connection.compute.disable_service.call_count == 1
assert data.connection.baremetal.set_node_power_state.call_count == 0
print('VERIFIED: maintenance applied, read-back failed, Nova disabled; '
      'no power mutation')
