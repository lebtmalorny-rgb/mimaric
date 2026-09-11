"""Controller-only projection. Never template or serialize all task/host vars."""
from datetime import datetime, timezone
import importlib.util
import ipaddress
import json
from pathlib import Path
import re

from ansible.plugins.action import ActionBase

# An action runs on the controller, where custom module_utils are not installed
# as a Python package. Load our adjacent, fixed path, not a user-provided path.
_spec = importlib.util.spec_from_file_location(
    '_powerops_firewall_report_model',
    Path(__file__).resolve().parents[1] / 'module_utils/powerops_firewall_model.py')
_model = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_model)
_plan_spec = importlib.util.spec_from_file_location('_firewall_report_plan',
    Path(__file__).resolve().parents[1] / 'module_utils/powerops_firewall_plan.py')
_plan = importlib.util.module_from_spec(_plan_spec)
_plan_spec.loader.exec_module(_plan)


class ActionModule(ActionBase):
    TRANSFERS_FILES = False
    _requires_connection = False

    def run(self, tmp=None, task_vars=None):
        result = super().run(tmp, task_vars)
        result['changed'] = False
        task_vars = task_vars or {}
        stage = self._task.args.get('stage', 'project')
        if stage not in ('project', 'aggregate'):
            return dict(result, failed=True, msg='Unknown report stage')
        catalog = task_vars.get('host_firewall_catalog', {})
        try:
            # Task selection may skip both assertions. Never aggregate a report
            # that could be mistaken for successful handling of an apply request.
            mode = self._templar.template(task_vars.get('host_firewall_mode', 'report'),
                                          fail_on_undefined=True, disable_lookups=True)
            if mode != 'report' and not (mode == 'apply' and
                    task_vars.get('host_firewall_admission', {}).get('operation') == 'apply'):
                return dict(result, failed=True, msg='Report or admitted apply request required')
            if stage == 'project':
                result['model'] = self.project(task_vars, catalog)
            else:
                result['bundle'] = self.aggregate(task_vars, catalog)
                result['bundle']['catalog_digest'] = _plan.canonical_digest(catalog)
                result['bundle']['plan_id'] = _plan.report_digest(result['bundle'])
        except Exception:
            # Exception text from templating can include passwords or expressions.
            return dict(result, failed=True, msg='Report model failed; check input schema and selected variables')
        return result

    def project(self, values, catalog):
        unresolved = []

        def resolve(name, default=None):
            if name not in values:
                if default is None:
                    unresolved.append(name)
                return default
            try:
                return self._templar.template(values[name], fail_on_undefined=True,
                                              disable_lookups=True)
            except Exception:
                unresolved.append(name)
                return None

        flags = {}
        for key in sorted(k for k in values if re.fullmatch(r'enable_[a-zA-Z0-9_]+', k)):
            try:
                flags[key] = _model.strict_bool(resolve(key))
            except ValueError:
                flags[key] = None
        ports = {}
        conditions = {}
        for service in catalog.get('services', {}).values():
            if flags.get(service['enable_flag']) is True:
                for flow in service['flows']:
                    key = flow['port_var']
                    ports[key] = resolve(key)
                    for condition in flow.get('required_conditions', []):
                        try:
                            conditions[condition] = _model.strict_bool(resolve(condition))
                        except ValueError:
                            conditions[condition] = None

        host = values['inventory_hostname']
        groups = {key: list(members) for key, members in values.get('groups', {}).items()}
        observation = values.get('host_firewall_observation', {}).get('snapshot', {})
        interface = resolve('api_interface')
        family = resolve('api_address_family')
        override = None
        raw = values.get('api_interface_address')
        explicit_override = 'api_interface_address' in values and not (
            isinstance(raw, str) and re.fullmatch(r"\{\{\s*(['\"])api\1\s*\|\s*kolla_address\s*\}\}", raw)
        )
        if explicit_override:
            override = resolve('api_interface_address')
        vips = [resolve(name, '') for name in
                ('kolla_internal_vip_address', 'kolla_external_vip_address')]
        # None from an explicit setting is a failed/null override, not permission
        # to select a different address automatically.
        address = None if explicit_override and override is None else self.observed_address(
            observation, interface, family, override, vips)
        if address is None:
            unresolved.append('api_interface_address')
        ssh_key = 'ansible_port' if 'ansible_port' in values else 'ansible_ssh_port'
        return {
            'enabled_flags': flags, 'groups': groups, 'ports': ports,
            'conditions': conditions,
            'network_addresses': {host: {'api': address}},
            'ssh_port': resolve(ssh_key), 'unresolved_names': sorted(set(unresolved)),
        }

    @staticmethod
    def observed_address(observation, interface, family, override, vips):
        """Only accept an unambiguous fresh address, or an observed explicit override."""
        command = observation.get('commands', {}).get('addresses', {})
        if (command.get('rc') != 0 or not command.get('available') or
                command.get('timed_out') or command.get('truncated')):
            return None
        if family not in ('ipv4', 'ipv6'):
            return None
        try:
            rows = json.loads(command['stdout'])
            candidates = set()
            excluded = {str(ipaddress.ip_address(vip)) for vip in vips if vip}
            for row in rows:
                if row.get('ifname') != interface:
                    continue
                for info in row.get('addr_info', []):
                    if info.get('family') != ('inet' if family == 'ipv4' else 'inet6'):
                        continue
                    if info.get('scope') != 'global' or any(info.get(k) for k in ('tentative', 'dadfailed', 'deprecated')):
                        continue
                    ip = ipaddress.ip_address(info['local'])
                    if not (ip.is_unspecified or ip.is_multicast or ip.is_loopback or ip.is_link_local) and str(ip) not in excluded:
                        candidates.add(str(ip))
            if override is not None:
                normalized = str(ipaddress.ip_address(override))
                return normalized if normalized in candidates else None
            return next(iter(candidates)) if len(candidates) == 1 else None
        except (ValueError, TypeError, KeyError, AttributeError):
            return None

    def aggregate(self, values, catalog):
        selected = sorted(set(self._task.args['hosts']))
        hostvars = values['hostvars']
        projections = {}
        addresses = {}
        for host in selected:
            projected = hostvars[host].get('host_firewall_projection', {}).get('model', {})
            projections[host] = dict(projected)
            addresses.update(projected.get('network_addresses', {}))
        reports = {}
        complete = True
        for host in selected:
            projection = projections[host]
            projection['network_addresses'] = addresses
            probe = hostvars[host].get('host_firewall_observation', {})
            if probe.get('unreachable'):
                status = 'unreachable'
            elif probe.get('failed'):
                status = 'failed'
            elif 'snapshot' in probe:
                status = 'ok'
            else:
                status = 'not_collected'
            report = _model.build_report(host, projection, catalog, probe.get('snapshot', {}))
            report['collection_status'] = status
            if not projections[host].get('enabled_flags'):
                report['blockers'].append({'code': 'PROJECTION_INCOMPLETE', 'subject': host})
            complete = complete and status == 'ok' and not any(
                b['code'].startswith(('PROBE_', 'OBSERVATION_')) for b in report['blockers'])
            reports[host] = report
        inventory = sorted(values.get('groups', {}).get('all', []))
        return {
            'schema_version': 1, 'mode': 'report', 'apply_ready': False,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'selected_hosts': selected, 'not_selected_hosts': sorted(set(inventory) - set(selected)),
            'collection_complete': bool(selected) and complete, 'reports': reports,
        }
