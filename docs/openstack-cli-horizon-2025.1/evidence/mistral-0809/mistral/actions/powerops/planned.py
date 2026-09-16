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
from mistral.actions.powerops import clients  # noqa: F401
from mistral.actions.powerops import coordination  # noqa: F401
from mistral.actions.powerops import exceptions


CONF = cfg.CONF


class _PlannedPowerAction(base.PowerOpsAction):
    def _validate_inputs(self):
        super(_PlannedPowerAction, self)._validate_inputs()

        if (
                not isinstance(self.instance_policy, str)
                or self.instance_policy not in clients._INSTANCE_POLICIES):
            raise exceptions.InstancePolicyError(
                'unsupported planned instance policy'
            )

        if type(self.allow_hard_off) is not bool:
            raise exceptions.PowerStateError(
                'allow_hard_off must be a boolean'
            )


class PlannedPowerOffAction(_PlannedPowerAction):
    """Safely quiesce and power off one exact compute host."""

    def __init__(self, host, segment_uuid, instance_policy='require_empty',
                 allow_hard_off=False):
        super(PlannedPowerOffAction, self).__init__()

        self.host = host
        self.segment_uuid = segment_uuid
        self.instance_policy = instance_policy
        self.allow_hard_off = allow_hard_off

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
            stopped = cloud.apply_instance_policy(
                self.host, self.instance_policy
            )
            cloud.assert_host_safe_for_power_off(
                self.host, self.instance_policy, stopped
            )
            node = cloud.power_off(self.host, self.allow_hard_off)
            result = {
                'host': self.host,
                'operation': 'planned_power_off',
                'power_state': node.power_state,
                'stopped_instance_ids': stopped,
                'nova_enabled': False,
                'masakari_maintenance': True,
            }

            return result

        return self._run_locked(
            context, 'planned_power_off', operation
        )


class PlannedRebootAction(_PlannedPowerAction):
    """Safely power-cycle and return one exact compute host to service."""

    def __init__(self, host, segment_uuid, instance_policy='require_empty',
                 allow_hard_off=False):
        super(PlannedRebootAction, self).__init__()

        self.host = host
        self.segment_uuid = segment_uuid
        self.instance_policy = instance_policy
        self.allow_hard_off = allow_hard_off

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
            stopped = cloud.apply_instance_policy(
                self.host, self.instance_policy
            )
            cloud.assert_host_safe_for_power_off(
                self.host, self.instance_policy, stopped
            )
            cloud.power_off(self.host, self.allow_hard_off)
            cloud.power_on(self.host)
            cloud.wait_nova_service(
                self.host, enabled=False, up=True
            )
            cloud.start_instances(self.host, stopped)
            cloud.enable_nova(self.host)
            cloud.set_masakari_maintenance(
                self.segment_uuid, self.host, False
            )
            result = {
                'host': self.host,
                'operation': 'planned_reboot',
                'power_state': 'power on',
                'stopped_instance_ids': stopped,
                'nova_enabled': True,
                'masakari_maintenance': False,
            }

            return result

        return self._run_locked(context, 'planned_reboot', operation)
