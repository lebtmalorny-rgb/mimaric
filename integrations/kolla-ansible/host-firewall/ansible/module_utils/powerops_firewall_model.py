"""Report-only network model. This module never generates executable rules."""
import ipaddress
import re


def strict_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        value = value.strip().lower()
        if value in ('yes', 'true', 'on', '1'):
            return True
        if value in ('no', 'false', 'off', '0'):
            return False
    raise ValueError('Invalid boolean')


def valid_port(value):
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]{1,5}', str(value)):
        raise ValueError('Invalid port')
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError('Invalid port')
    return port


def build_report(host, model, catalog, observation):
    """Build a deterministic report from an already projected, non-secret model."""
    blockers = []

    def block(code, subject=''):
        entry = {'code': code, 'subject': subject}
        if entry not in blockers:
            blockers.append(entry)

    block('APPLY_NOT_IMPLEMENTED')
    block('SSH_ACCESS_NOT_VERIFIED')
    flags = {}
    for name, value in sorted(model.get('enabled_flags', {}).items()):
        try:
            flags[name] = strict_bool(value)
        except ValueError:
            flags[name] = None
            block('INVALID_ENABLE_FLAG', name)
    for name in sorted(set(model.get('unresolved_names', []))):
        block('UNRESOLVED_VARIABLE', name)
    try:
        ssh_port = valid_port(model.get('ssh_port'))
    except ValueError:
        ssh_port = None
        block('SSH_PORT_UNRESOLVED')

    services = catalog.get('services', {}) if isinstance(catalog, dict) else {}
    if not isinstance(catalog, dict) or catalog.get('schema_version') != 1 or not isinstance(services, dict):
        block('INVALID_CATALOG')
        services = {}
    known = {s.get('enable_flag') for s in services.values() if isinstance(s, dict)}
    for name, value in flags.items():
        if value is True and name not in known:
            block('UNKNOWN_ENABLED_FLAG', name)

    groups = model.get('groups', {})
    addresses = model.get('network_addresses', {})

    def group_members(name):
        members = groups.get(name)
        if not isinstance(members, list) or not members:
            block('MISSING_GROUP', name)
            return []
        return sorted(set(members))

    def address(node, network):
        value = addresses.get(node, {}).get(network)
        if value is None:
            block('MISSING_ADDRESS', node + ':' + network)
            return None
        try:
            if not isinstance(value, str) or '%' in value:
                raise ValueError('Ambiguous address')
            parsed = ipaddress.ip_address(value)
            if parsed.is_unspecified or parsed.is_multicast or parsed.is_loopback or parsed.is_link_local:
                raise ValueError('Not an interhost address')
            return parsed
        except ValueError:
            block('INVALID_ADDRESS', node + ':' + network)
            return None

    candidates = []
    for service, spec in sorted(services.items()):
        if not isinstance(spec, dict) or not isinstance(spec.get('flows'), list):
            block('INVALID_CATALOG', service)
            continue
        flag = spec.get('enable_flag')
        if flag not in flags:
            block('MISSING_ENABLE_FLAG', flag or service)
        if flags.get(flag) is not True:
            continue
        # No catalog entry in this delivery can declare complete service coverage.
        block('PARTIAL_SERVICE_COVERAGE', service)
        requirements = spec.get('required_flags', [])
        for required in requirements:
            if required not in flags:
                block('MISSING_ENABLE_FLAG', required)
        if any(flags.get(required) is not True for required in requirements):
            continue
        for flow in spec['flows']:
            required = ('id', 'protocol', 'port_var', 'destination_group', 'network')
            if not isinstance(flow, dict) or not all(isinstance(flow.get(k), str) for k in required):
                block('INVALID_CATALOG', service)
                continue
            if flow['protocol'] not in ('tcp', 'udp'):
                block('INVALID_CATALOG', service)
                continue
            destinations = group_members(flow['destination_group'])
            if host not in destinations:
                continue
            source_groups = flow.get('source_groups')
            if not isinstance(source_groups, list) or not source_groups:
                block('SOURCE_POLICY_REQUIRED', flow['id'])
                continue
            try:
                port = valid_port(model.get('ports', {}).get(flow['port_var']))
            except ValueError:
                block('INVALID_PORT', flow['port_var'])
                continue
            destination = address(host, flow['network'])
            peers = [group_members(g) for g in source_groups]
            if destination is None or not all(peers):
                continue
            sources = []
            complete = True
            for node in sorted({n for members in peers for n in members}):
                source = address(node, flow['network'])
                if source is None:
                    complete = False
                elif source.version != destination.version:
                    block('ADDRESS_FAMILY_MISMATCH', flow['id'])
                    complete = False
                else:
                    sources.append({'host': node, 'address': str(source)})
            if complete and sources:
                candidates.append({
                    'id': flow['id'], 'service': service, 'protocol': flow['protocol'],
                    'port': port, 'network': flow['network'], 'destination': str(destination),
                    'sources': sources, 'evidence': spec.get('source_evidence', ''),
                })

    safe_observation = {'timestamp': observation.get('timestamp'), 'commands': {}}
    fields = ('argv', 'rc', 'stdout', 'stderr', 'available', 'truncated', 'timed_out')
    commands = observation.get('commands', {})
    if not commands:
        block('OBSERVATION_MISSING')
    for name, result in sorted(commands.items()):
        safe_observation['commands'][name] = {k: result.get(k) for k in fields}
        if not result.get('available'):
            block('PROBE_UNAVAILABLE', name)
        if result.get('timed_out'):
            block('PROBE_TIMEOUT', name)
        if result.get('truncated'):
            block('PROBE_TRUNCATED', name)
        if result.get('rc') != 0:
            block('PROBE_FAILED', name)
    return {
        'schema_version': 1, 'host': host, 'enabled_flags': flags,
        'candidate_flows': sorted(candidates, key=lambda f: (f['service'], f['id'])),
        'blockers': sorted(blockers, key=lambda b: (b['code'], b['subject'])),
        'observations': safe_observation, 'apply_ready': False,
        'ssh': {'inventory_port': ssh_port, 'access_verified': False},
    }
