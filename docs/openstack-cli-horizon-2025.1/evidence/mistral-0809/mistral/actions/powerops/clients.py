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

import re
import time
from types import SimpleNamespace

import eventlet
from keystoneauth1 import adapter as ks_adapter
from keystoneauth1.identity import v3
from keystoneauth1 import session as ks_session
from keystonemiddleware import auth_token as _auth_token  # noqa: F401
import openstack
from oslo_config import cfg

from mistral.actions.powerops import coordination
from mistral.actions.powerops import exceptions
from mistral.actions.powerops import live_migration


CONF = cfg.CONF

_INSTANCE_POLICIES = frozenset({
    'require_empty',
    'live_migrate',
    'stop',
})
_KNOWN_POWER_STATES = frozenset({'power on', 'power off'})
_PATH_RESOURCE_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]*$')


def _register_keystone_authtoken_options():
    options = (
        cfg.StrOpt('auth_url'),
        cfg.StrOpt('username'),
        cfg.StrOpt('password', secret=True),
        cfg.StrOpt('project_name'),
        cfg.StrOpt('user_domain_name'),
        cfg.StrOpt('project_domain_name'),
        cfg.StrOpt('user_domain_id'),
        cfg.StrOpt('project_domain_id'),
    )

    for option in options:
        try:
            CONF.register_opt(option, group='keystone_authtoken')
        except cfg.DuplicateOptError:
            pass


_register_keystone_authtoken_options()


def _required_auth_value(auth_conf, name):
    value = getattr(auth_conf, name, None)

    if not value:
        raise exceptions.PowerOpsConfigurationError(
            'PowerOps Keystone authentication is incomplete'
        )

    return value


def _domain_options(auth_conf):
    user_domain_id = getattr(auth_conf, 'user_domain_id', None)
    project_domain_id = getattr(auth_conf, 'project_domain_id', None)

    if user_domain_id or project_domain_id:
        if not user_domain_id or not project_domain_id:
            raise exceptions.PowerOpsConfigurationError(
                'PowerOps Keystone domain IDs must be configured as a pair'
            )

        return {
            'user_domain_id': user_domain_id,
            'project_domain_id': project_domain_id,
        }

    return {
        'user_domain_name': _required_auth_value(
            auth_conf, 'user_domain_name'
        ),
        'project_domain_name': _required_auth_value(
            auth_conf, 'project_domain_name'
        ),
    }


def connection_from_conf():
    auth_conf = CONF.keystone_authtoken
    auth_options = {
        'auth_url': _required_auth_value(auth_conf, 'auth_url'),
        'username': _required_auth_value(auth_conf, 'username'),
        'password': _required_auth_value(auth_conf, 'password'),
        'project_name': _required_auth_value(auth_conf, 'project_name'),
    }
    auth_options.update(_domain_options(auth_conf))
    auth = v3.Password(**auth_options)
    cafile = getattr(auth_conf, 'cafile', None)
    session = ks_session.Session(auth=auth, verify=cafile or True)

    return openstack.connection.Connection(
        session=session,
        region_name=CONF.powerops.region_name,
        interface=CONF.powerops.interface,
    )


def _compatible_node(node):
    return (
        node.provision_state == 'manageable'
        and node.network_interface == 'noop'
        and not node.last_error
    )


def _compatible_power(node, expected):
    return (
        node.power_state == expected
        and node.target_power_state in (None, expected)
        and not node.last_error
    )


def _noop_health_check():
    return None


def validate_resource_id(resource_id, description):
    if (
            not isinstance(resource_id, str)
            or not _PATH_RESOURCE_ID_RE.fullmatch(resource_id)):
        raise exceptions.HostResolutionError(
            '{} is not canonical'.format(description)
        )


class CloudClients:
    def __init__(self, connection, ha_adapter=None, sleep=time.sleep,
                 monotonic=time.monotonic, health_check=None):
        self.connection = connection
        self.sleep = sleep
        self.monotonic = monotonic
        self.health_check = health_check or _noop_health_check
        self.ha_adapter = ha_adapter
        self._live_migrations = {}

        if self.ha_adapter is None:
            self.ha_adapter = ks_adapter.Adapter(
                session=connection.session,
                service_type='ha',
                version='1',
                interface=CONF.powerops.interface,
                region_name=CONF.powerops.region_name,
            )

    @staticmethod
    def _validate_host(host):
        coordination.host_lock_name(host)

    @staticmethod
    def _validate_resource_id(resource_id, description):
        validate_resource_id(resource_id, description)

    def _deadline(self, timeout):
        return self.monotonic() + timeout

    def _remaining(self, deadline, description):
        remaining = deadline - self.monotonic()

        if remaining <= 0:
            raise exceptions.PowerOpsTimeout(description)

        return remaining

    def _call_with_deadline(self, call, deadline, description):
        try:
            remaining = self._remaining(deadline, description)
        except exceptions.PowerOpsTimeout as exc:
            raise exceptions.PowerOpsCallTimeout(description) from exc

        session = self.connection.session
        had_timeout = hasattr(session, 'timeout')
        previous_timeout = getattr(session, 'timeout', None)
        session.timeout = remaining

        try:
            with eventlet.Timeout(remaining):
                return call()
        except eventlet.Timeout as exc:
            raise exceptions.PowerOpsCallTimeout(description) from exc
        finally:
            if had_timeout:
                session.timeout = previous_timeout
            else:
                del session.timeout

    def _mutation(self, call, deadline, description):
        self.health_check()
        return self._call_with_deadline(call, deadline, description)

    def _wait_until(self, probe, accept, timeout, description,
                    deadline=None, observations=None):
        deadline = deadline if deadline is not None else self._deadline(
            timeout
        )
        observations = (
            CONF.powerops.stable_observations
            if observations is None else observations
        )
        consecutive = 0

        while self.monotonic() < deadline:
            self.health_check()
            value = probe()
            consecutive = consecutive + 1 if accept(value) else 0

            if consecutive >= observations:
                self.health_check()
                return value

            remaining = self._remaining(deadline, description)
            self.sleep(min(CONF.powerops.poll_interval, remaining))

        raise exceptions.PowerOpsTimeout(description)

    def ironic_node(self, host, _deadline=None):
        self._validate_host(host)
        deadline = _deadline or self._deadline(CONF.powerops.power_timeout)
        nodes = self._call_with_deadline(
            lambda: list(self.connection.baremetal.nodes(details=True)),
            deadline,
            'timed out listing Ironic nodes',
        )
        matches = [node for node in nodes if node.name == host]

        if len(matches) != 1 or not _compatible_node(matches[0]):
            raise exceptions.HostResolutionError(
                'host must resolve to one compatible Ironic node'
            )

        return matches[0]

    def nova_service(self, host, _deadline=None):
        self._validate_host(host)
        deadline = _deadline or self._deadline(CONF.powerops.service_timeout)
        services = self._call_with_deadline(
            lambda: list(self.connection.compute.services(
                host=host, binary='nova-compute'
            )),
            deadline,
            'timed out listing Nova compute services',
        )
        matches = [
            service for service in services
            if service.binary == 'nova-compute' and service.host == host
        ]

        if len(matches) != 1:
            raise exceptions.HostResolutionError(
                'host must resolve to one Nova compute service'
            )

        if matches[0].status not in ('enabled', 'disabled'):
            raise exceptions.HostResolutionError(
                'Nova compute service has an invalid administrative status'
            )

        return matches[0]

    @classmethod
    def _masakari_identifier(cls, item, description):
        # REST resources expose a numeric database id alongside their UUID.
        # Only the UUID identifies a resource in Masakari API paths.
        value = item.get('uuid')
        cls._validate_resource_id(value, description)
        return value

    @classmethod
    def _masakari_resource(cls, item):
        if not isinstance(item, dict):
            raise exceptions.HostResolutionError(
                'Masakari host entry must be a mapping'
            )

        host_id = cls._masakari_identifier(
            item, 'Masakari host UUID'
        )
        name = item.get('name')
        on_maintenance = item.get('on_maintenance')

        if (
                not isinstance(name, str)
                or not coordination.HOST_RE.fullmatch(name)):
            raise exceptions.HostResolutionError(
                'Masakari host name is not canonical'
            )

        if not isinstance(on_maintenance, bool):
            raise exceptions.HostResolutionError(
                'Masakari maintenance state must be Boolean'
            )

        return SimpleNamespace(
            id=host_id,
            name=name,
            on_maintenance=on_maintenance,
        )

    def masakari_host(self, segment_uuid, host, _deadline=None):
        self._validate_resource_id(segment_uuid, 'Masakari segment UUID')
        self._validate_host(host)
        deadline = _deadline or self._deadline(CONF.powerops.service_timeout)
        segment_url = '/segments/{}'.format(segment_uuid)
        hosts_url = '/segments/{}/hosts'.format(segment_uuid)
        segment_body = self._call_with_deadline(
            lambda: self.ha_adapter.get(segment_url).json(),
            deadline,
            'timed out resolving the Masakari segment',
        )

        if not isinstance(segment_body, dict):
            raise exceptions.HostResolutionError(
                'Masakari segment response must be a mapping'
            )

        segment = segment_body.get('segment')

        if not isinstance(segment, dict):
            raise exceptions.HostResolutionError(
                'Masakari segment must be a mapping'
            )

        segment_id = self._masakari_identifier(
            segment, 'Masakari segment UUID'
        )

        if segment_id != segment_uuid:
            raise exceptions.HostResolutionError(
                'Masakari segment response does not match the requested UUID'
            )

        body = self._call_with_deadline(
            lambda: self.ha_adapter.get(hosts_url).json(),
            deadline,
            'timed out listing Masakari hosts',
        )

        if not isinstance(body, dict):
            raise exceptions.HostResolutionError(
                'Masakari hosts response must be a mapping'
            )

        host_entries = body.get('hosts')

        if not isinstance(host_entries, list):
            raise exceptions.HostResolutionError(
                'Masakari hosts response must contain a hosts list'
            )

        hosts = [
            self._masakari_resource(item)
            for item in host_entries
        ]
        matches = [item for item in hosts if item.name == host]

        if len(matches) != 1:
            raise exceptions.HostResolutionError(
                'host must resolve to one Masakari segment host'
            )

        return matches[0]

    def resolve_host_set(self, segment_uuid, host):
        deadline = self._deadline(CONF.powerops.service_timeout)
        node = self.ironic_node(host, _deadline=deadline)
        service = self.nova_service(host, _deadline=deadline)
        masakari = self.masakari_host(
            segment_uuid, host, _deadline=deadline
        )
        self.health_check()

        return node, service, masakari

    def instances_on_host(self, host, _deadline=None):
        self._validate_host(host)
        deadline = _deadline or self._deadline(
            CONF.powerops.vm_action_timeout
        )
        servers = self._call_with_deadline(
            lambda: list(self.connection.compute.servers(
                details=True, all_projects=True, compute_host=host
            )),
            deadline,
            'timed out listing Nova instances',
        )

        if any(getattr(server, 'compute_host', None) != host
               for server in servers):
            raise exceptions.HostResolutionError(
                'Nova returned an instance outside the requested compute host'
            )

        return sorted(servers, key=lambda server: server.id)

    def _server_by_id(self, server_id, deadline):
        return self._call_with_deadline(
            lambda: self.connection.compute.get_server(server_id),
            deadline,
            'timed out reading Nova instance {}'.format(server_id),
        )

    @staticmethod
    def _validate_stop_observation(server):
        if server.status not in ('ACTIVE', 'SHUTOFF'):
            raise exceptions.InstancePolicyError(
                'instance entered an unsafe stop state'
            )

        return server.status == 'SHUTOFF'

    def _pace_instances(self):
        if CONF.powerops.instance_interval:
            self.sleep(CONF.powerops.instance_interval)

        self.health_check()

    def apply_instance_policy(self, host, policy):
        if policy not in _INSTANCE_POLICIES:
            raise exceptions.InstancePolicyError(
                'unsupported planned instance policy'
            )

        if policy == 'live_migrate':
            self._live_migrations.pop(host, None)
            live_migration.require_uncached(self)
        servers = self.instances_on_host(host)

        if policy == 'require_empty':
            if servers:
                raise exceptions.InstancePolicyError(
                    'host is not empty'
                )

            self.health_check()
            return []

        if policy == 'stop':
            if any(server.status not in ('ACTIVE', 'SHUTOFF')
                   for server in servers):
                raise exceptions.InstancePolicyError(
                    'stop policy found an unsupported instance state'
                )

            stopped = []

            for server in servers:
                if server.status == 'SHUTOFF':
                    continue

                deadline = self._deadline(CONF.powerops.vm_action_timeout)
                wait_description = (
                    'timed out waiting for Nova instance {}'.format(
                        server.id
                    )
                )
                self._mutation(
                    lambda server=server: self.connection.compute.stop_server(
                        server
                    ),
                    deadline,
                    'timed out stopping Nova instance {}'.format(server.id),
                )
                self._wait_until(
                    lambda server_id=server.id:
                        self._server_by_id(server_id, deadline),
                    self._validate_stop_observation,
                    CONF.powerops.vm_action_timeout,
                    wait_description,
                    deadline=deadline,
                    observations=1,
                )
                stopped.append(server.id)
                self._pace_instances()

            self.health_check()
            return stopped

        if any(server.status != 'ACTIVE' for server in servers):
            raise exceptions.InstancePolicyError(
                'live migration requires ACTIVE instances'
            )

        completed = []
        for server in servers:
            migration = live_migration.LiveMigrationWaiter(
                self, server.id, host)
            migration.run()
            completed.append(migration)
            self._pace_instances()

        self.health_check()
        self._live_migrations[host] = completed
        return []

    @staticmethod
    def _validate_restart_host(server, host, server_id):
        if (getattr(server, 'id', None) != server_id
                or getattr(server, 'compute_host', None) != host):
            raise exceptions.InstanceManifestError(
                'restart manifest instance does not belong to the target host'
            )

        return server.status == 'ACTIVE'

    def start_instances(self, host, instance_ids):
        self._validate_host(host)
        self._validate_stopped_manifest(instance_ids)

        lookup_deadline = self._deadline(CONF.powerops.vm_action_timeout)
        servers = self._call_with_deadline(
            lambda: list(self.connection.compute.servers(
                details=True, all_projects=True
            )),
            lookup_deadline,
            'timed out resolving the instance restart manifest',
        )
        by_id = {server.id: server for server in servers}

        if any(server_id not in by_id for server_id in instance_ids):
            raise exceptions.InstanceManifestError(
                'restart manifest contains an unknown instance UUID'
            )

        selected = [by_id[server_id] for server_id in sorted(instance_ids)]

        for server in selected:
            self._validate_restart_host(server, host, server.id)

        if any(server.status not in ('ACTIVE', 'SHUTOFF')
               for server in selected):
            raise exceptions.InstanceManifestError(
                'restart manifest contains an instance in an unsafe state'
            )

        for server in selected:
            deadline = self._deadline(CONF.powerops.vm_action_timeout)
            current = self._server_by_id(server.id, deadline)
            self._validate_restart_host(current, host, server.id)

            if current.status not in ('ACTIVE', 'SHUTOFF'):
                raise exceptions.InstanceManifestError(
                    'restart manifest instance entered an unsafe state'
                )

            server = current

            if server.status == 'ACTIVE':
                continue

            self._mutation(
                lambda server=server:
                    self.connection.compute.start_server(server),
                deadline,
                'timed out starting Nova instance {}'.format(server.id),
            )
            self._wait_until(
                lambda server_id=server.id:
                    self._server_by_id(server_id, deadline),
                lambda current, server_id=server.id:
                    self._validate_restart_host(current, host, server_id),
                CONF.powerops.vm_action_timeout,
                'timed out waiting for Nova instance {}'.format(server.id),
                deadline=deadline,
                observations=1,
            )
            self._pace_instances()

        self.health_check()

    @staticmethod
    def _validate_power_observation(node, host, expected):
        if node.name != host or not _compatible_node(node):
            raise exceptions.HostResolutionError(
                'Ironic node changed or became incompatible'
            )

        if node.power_state not in _KNOWN_POWER_STATES:
            raise exceptions.PowerStateError(
                'Ironic returned an unknown power state'
            )

        if node.target_power_state not in (None, expected):
            raise exceptions.PowerStateError(
                'Ironic target power state conflicts with the transition'
            )

        return _compatible_power(node, expected)

    def _refresh_ironic_node(self, node_id, host, expected, deadline):
        node = self._call_with_deadline(
            lambda: self.connection.baremetal.get_node(node_id),
            deadline,
            'timed out reading the Ironic power state',
        )
        self._validate_power_observation(node, host, expected)

        return node

    def _transition_power(self, host, expected, target, timeout,
                          force_mutation=False):
        deadline = self._deadline(timeout)
        node = self.ironic_node(host, _deadline=deadline)
        compatible = self._validate_power_observation(
            node, host, expected
        )

        if (
                not compatible
                and (node.target_power_state is None or force_mutation)):
            self._mutation(
                lambda: self.connection.baremetal.set_node_power_state(
                    node, target
                ),
                deadline,
                'timed out requesting Ironic {}'.format(expected),
            )

        result = self._wait_until(
            lambda: self._refresh_ironic_node(
                node.id, host, expected, deadline
            ),
            lambda current: _compatible_power(current, expected),
            timeout,
            'timed out waiting for stable Ironic {}'.format(expected),
            deadline=deadline,
        )
        self.health_check()

        return result

    def power_off(self, host, allow_hard_off):
        try:
            return self._transition_power(
                host,
                'power off',
                'soft power off',
                CONF.powerops.graceful_shutdown_timeout,
            )
        except exceptions.PowerOpsCallTimeout:
            raise
        except exceptions.PowerOpsTimeout:
            if allow_hard_off is not True:
                raise

        return self._transition_power(
            host,
            'power off',
            'power off',
            CONF.powerops.power_timeout,
            force_mutation=True,
        )

    def power_on(self, host):
        return self._transition_power(
            host,
            'power on',
            'power on',
            CONF.powerops.power_timeout,
        )

    def power_status(self, host):
        node = self.ironic_node(host)
        self._validate_power_observation(node, host, node.power_state)
        self.health_check()

        return node.power_state

    def require_stable_power_on(self, host):
        deadline = self._deadline(CONF.powerops.power_timeout)
        node = self.ironic_node(host, _deadline=deadline)
        self._validate_power_observation(node, host, 'power on')

        return self._wait_until(
            lambda: self._refresh_ironic_node(
                node.id, host, 'power on', deadline
            ),
            lambda current: _compatible_power(current, 'power on'),
            CONF.powerops.power_timeout,
            'timed out waiting for stable Ironic power on',
            deadline=deadline,
        )

    @staticmethod
    def _service_matches(service, enabled, up):
        enabled_matches = (service.status == 'enabled') is enabled
        up_matches = up is None or (service.state == 'up') is up

        return enabled_matches and up_matches

    def _wait_nova_service(self, host, enabled, up, deadline):
        return self._wait_until(
            lambda: self.nova_service(host, _deadline=deadline),
            lambda service: self._service_matches(service, enabled, up),
            CONF.powerops.service_timeout,
            'timed out waiting for the Nova compute service',
            deadline=deadline,
        )

    def wait_nova_service(self, host, enabled, up):
        deadline = self._deadline(CONF.powerops.service_timeout)
        return self._wait_nova_service(host, enabled, up, deadline)

    def disable_nova(self, host, reason):
        deadline = self._deadline(CONF.powerops.service_timeout)
        service = self.nova_service(host, _deadline=deadline)

        if service.status == 'enabled':
            self._mutation(
                lambda: self.connection.compute.disable_service(
                    service, host=service.host, binary=service.binary,
                    disabled_reason=reason
                ),
                deadline,
                'timed out disabling the Nova compute service',
            )

        result = self._wait_nova_service(
            host, enabled=False, up=None, deadline=deadline
        )
        self.health_check()

        return result

    def enable_nova(self, host):
        deadline = self._deadline(CONF.powerops.service_timeout)
        service = self.nova_service(host, _deadline=deadline)

        if service.status == 'disabled':
            self._mutation(
                lambda: self.connection.compute.enable_service(
                    service, host=service.host, binary=service.binary
                ),
                deadline,
                'timed out enabling the Nova compute service',
            )

        result = self._wait_nova_service(
            host, enabled=True, up=True, deadline=deadline
        )
        self.health_check()

        return result

    def _wait_masakari_maintenance(
            self, segment_uuid, host, expected, deadline):
        return self._wait_until(
            lambda: self.masakari_host(
                segment_uuid, host, _deadline=deadline
            ),
            lambda item: item.on_maintenance is expected,
            CONF.powerops.service_timeout,
            'timed out waiting for Masakari host maintenance',
            deadline=deadline,
        )

    def require_masakari_maintenance(self, segment_uuid, host, expected):
        deadline = self._deadline(CONF.powerops.service_timeout)
        return self._wait_masakari_maintenance(
            segment_uuid, host, expected, deadline
        )

    def set_masakari_maintenance(self, segment_uuid, host, expected):
        if not isinstance(expected, bool):
            raise exceptions.HostResolutionError(
                'Masakari maintenance state must be Boolean'
            )

        deadline = self._deadline(CONF.powerops.service_timeout)
        item = self.masakari_host(
            segment_uuid, host, _deadline=deadline
        )

        if item.on_maintenance is not expected:
            host_url = '/segments/{}/hosts/{}'.format(
                segment_uuid, item.id
            )
            body = {'host': {'on_maintenance': expected}}
            self._mutation(
                lambda: self.ha_adapter.put(host_url, json=body),
                deadline,
                'timed out updating Masakari host maintenance',
            )

        result = self._wait_masakari_maintenance(
            segment_uuid, host, expected, deadline
        )
        self.health_check()

        return result

    @staticmethod
    def _validate_stopped_manifest(stopped_instance_ids):
        if not isinstance(stopped_instance_ids, list):
            raise exceptions.InstanceManifestError(
                'stopped instance manifest must be a list'
            )

        if any(
                not isinstance(server_id, str)
                or not _PATH_RESOURCE_ID_RE.fullmatch(server_id)
                for server_id in stopped_instance_ids):
            raise exceptions.InstanceManifestError(
                'stopped manifest contains a noncanonical instance UUID'
            )

        if len(set(stopped_instance_ids)) != len(stopped_instance_ids):
            raise exceptions.InstanceManifestError(
                'duplicate instance UUID in stopped manifest'
            )

    def assert_host_safe_for_power_off(
            self, host, policy, stopped_instance_ids):
        if policy not in _INSTANCE_POLICIES:
            raise exceptions.InstancePolicyError(
                'unsupported planned instance policy'
            )

        self._validate_stopped_manifest(stopped_instance_ids)
        if policy == 'live_migrate':
            if host not in self._live_migrations:
                raise exceptions.InstancePolicyError(
                    'no completed planned migration pass for source ' + host)
            deadline = self._deadline(CONF.powerops.vm_action_timeout)
            live_migration.assert_no_inflight(self, host, deadline)
            for migration in self._live_migrations[host]:
                migration.revalidate(deadline)

        # Keep this Nova placement read last; it is not a domain inventory.
        servers = self.instances_on_host(host)

        if policy in ('require_empty', 'live_migrate'):
            if stopped_instance_ids:
                raise exceptions.InstanceManifestError(
                    'non-stop policy returned a stopped instance manifest'
                )

            if servers:
                raise exceptions.InstancePolicyError(
                    'instances remain on the source host'
                )

            self.health_check()
            return

        if any(server.status != 'SHUTOFF' for server in servers):
            raise exceptions.InstancePolicyError(
                'stop policy left a non-SHUTOFF source instance'
            )

        by_id = {server.id: server for server in servers}

        if len(by_id) != len(servers):
            raise exceptions.InstanceManifestError(
                'source instance response contains duplicate UUIDs'
            )

        if any(server_id not in by_id
               for server_id in stopped_instance_ids):
            raise exceptions.InstanceManifestError(
                'stopped manifest UUID is not on the source host'
            )

        self.health_check()
