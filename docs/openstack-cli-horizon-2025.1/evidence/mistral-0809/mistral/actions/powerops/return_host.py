# Copyright 2026 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_config import cfg

from mistral.actions.powerops import base
# Keep dependency patch points local to the public composite action module.
from mistral.actions.powerops import clients
from mistral.actions.powerops import coordination  # noqa: F401
from mistral.actions.powerops import exceptions


CONF = cfg.CONF


class HostPowerStatusAction(base.PowerOpsAction):
    """Return one exact point-in-time host PowerOps observation."""

    def __init__(self, host, segment_uuid):
        super(HostPowerStatusAction, self).__init__()

        self.host = host
        self.segment_uuid = segment_uuid

    def run(self, context):
        if not CONF.powerops.enabled:
            raise exceptions.PowerOpsDisabled()

        self._authorize(context)
        self._validate_inputs()
        cloud = clients.CloudClients(clients.connection_from_conf())
        node = cloud.ironic_node(self.host)
        service = cloud.nova_service(self.host)
        service_status = getattr(service, 'status', None)

        if service_status not in ('enabled', 'disabled'):
            raise exceptions.HostResolutionError(
                'Nova compute service has an invalid administrative status'
            )

        masakari_host = cloud.masakari_host(
            self.segment_uuid, self.host
        )

        return {
            'host': self.host,
            'ironic_node_uuid': node.id,
            'power_state': node.power_state,
            'target_power_state': node.target_power_state,
            'ironic_last_error': node.last_error,
            'nova_enabled': service_status == 'enabled',
            'nova_state': service.state,
            'masakari_maintenance': masakari_host.on_maintenance,
        }


class PowerOnForInspectionAction(base.PowerOpsAction):
    """Power on one host while retaining its out-of-service state."""

    def __init__(self, host, segment_uuid):
        super(PowerOnForInspectionAction, self).__init__()

        self.host = host
        self.segment_uuid = segment_uuid

    def run(self, context):
        def operation(cloud):
            cloud.resolve_host_set(self.segment_uuid, self.host)
            # A failed maintenance call may already have changed the host.
            self._fail_safe_required = True
            cloud.set_masakari_maintenance(
                self.segment_uuid, self.host, True
            )
            cloud.disable_nova(
                self.host, CONF.powerops.nova_disable_reason
            )
            node = cloud.power_on(self.host)
            cloud.wait_nova_service(
                self.host, enabled=False, up=True
            )

            return {
                'host': self.host,
                'operation': 'power_on_for_inspection',
                'power_state': node.power_state,
                'stopped_instance_ids': [],
                'nova_enabled': False,
                'masakari_maintenance': True,
            }

        return self._run_locked(
            context, 'power_on_for_inspection', operation
        )


class ReturnToServiceAction(base.PowerOpsAction):
    """Return an inspected host and its explicit VM manifest to service."""

    def __init__(self, host, segment_uuid, stopped_instance_ids,
                 stale_domains_checked=False):
        super(ReturnToServiceAction, self).__init__()

        self.host = host
        self.segment_uuid = segment_uuid
        self.stopped_instance_ids = stopped_instance_ids
        self.stale_domains_checked = stale_domains_checked

    def _validate_inputs(self):
        super(ReturnToServiceAction, self)._validate_inputs()

        if self.stale_domains_checked is not True:
            raise exceptions.OperatorGateRequired(
                'resume with env stale_domains_checked=true after host '
                'inspection'
            )

        clients.CloudClients._validate_stopped_manifest(
            self.stopped_instance_ids
        )

    def run(self, context):
        def operation(cloud):
            cloud.resolve_host_set(self.segment_uuid, self.host)
            self._fail_safe_required = True
            cloud.require_stable_power_on(self.host)
            cloud.wait_nova_service(
                self.host, enabled=False, up=True
            )
            cloud.require_masakari_maintenance(
                self.segment_uuid, self.host, expected=True
            )
            cloud.start_instances(self.host, self.stopped_instance_ids)
            cloud.enable_nova(self.host)
            cloud.set_masakari_maintenance(
                self.segment_uuid, self.host, False
            )

            return {
                'host': self.host,
                'operation': 'return_to_service',
                'power_state': 'power on',
                'stopped_instance_ids': sorted(
                    self.stopped_instance_ids
                ),
                'nova_enabled': True,
                'masakari_maintenance': False,
            }

        return self._run_locked(context, 'return_to_service', operation)
