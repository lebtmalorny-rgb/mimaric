"""Report-only network model. This module never generates executable rules."""
import ipaddress
import re


# Kept explicit on the controller; the contract test compares this set with the
# remote collector, so adding a measurement cannot silently bypass completeness.
EXPECTED_COMMANDS = frozenset((
    'firewalld_package', 'firewalld_python_package', 'firewalld_version', 'firewalld_service',
    'addresses', 'routes_v4', 'routes_v6', 'ss', 'firewalld_state',
    'firewalld_active_zones', 'firewalld_runtime_zones', 'firewalld_permanent_zones',
    'firewalld_runtime_policies', 'firewalld_permanent_policies', 'nft',
    'iptables', 'ip6tables', 'services', 'bridge_netfilter',
))


def complete_result(result):
    """An error may be evidence, but missing/truncated output is not."""
    return (isinstance(result, dict) and result.get('available') is True
            and result.get('timed_out') is False and result.get('truncated') is False
            and type(result.get('rc')) is int
            and isinstance(result.get('stdout'), str) and isinstance(result.get('stderr'), str))


def installed_rpm(result, name):
    """Query the installed RPM database, never a repository or package search."""
    unknown = {'installed': None, 'versions': []}
    if not complete_result(result) or result['stderr'].strip():
        return unknown
    output = result['stdout'].strip()
    # LC_ALL=C is fixed in the probe. Any other rc=1 (e.g. rpmdb failure)
    # remains unknown, not a false assertion that the package is absent.
    if result['rc'] == 1 and output == 'package %s is not installed' % name:
        return {'installed': False, 'versions': []}
    if result['rc'] != 0 or not output:
        return unknown
    versions = []
    for line in output.splitlines():
        fields = line.split('\t')
        if (len(fields) != 4 or fields[0] != name or
                not all(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+~^:-]*', f) for f in fields[1:])):
            return unknown
        versions.append(dict(zip(('version', 'release', 'arch'), fields[1:])))
    return {'installed': True, 'versions': versions}


def firewalld_prerequisites(commands, block):
    """Report observed prerequisites; this is not an authorization to apply."""
    packages = {}
    for name, key in (('firewalld', 'firewalld_package'),
                      ('python3-firewall', 'firewalld_python_package')):
        packages[name] = installed_rpm(commands.get(key), name)
        installed = packages[name]['installed']
        if installed is not True:
            block('FIREWALLD_PACKAGE_MISSING' if installed is False else 'FIREWALLD_PACKAGE_UNKNOWN', name)

    version = None
    result = commands.get('firewalld_version')
    if complete_result(result) and result['rc'] == 0 and not result['stderr'].strip():
        value = result['stdout'].strip()
        if re.fullmatch(r'[0-9]+(?:\.[0-9]+)+(?:[-+][A-Za-z0-9._-]+)?', value):
            version = value
    if version is None:
        block('FIREWALLD_VERSION_UNKNOWN')

    service = dict.fromkeys(('load_state', 'active_state', 'sub_state', 'unit_file_state',
                             'running', 'enabled', 'masked'))
    result = commands.get('firewalld_service')
    if complete_result(result) and result['rc'] == 0 and not result['stderr'].strip():
        pairs = [line.split('=', 1) for line in result['stdout'].splitlines() if line]
        fields = ('Id', 'LoadState', 'ActiveState', 'SubState', 'UnitFileState')
        if (len(pairs) == len(fields) and all(len(p) == 2 for p in pairs)
                and {p[0] for p in pairs} == set(fields)):
            values = dict(pairs)
            if (values['Id'] == 'firewalld.service'
                    and all(re.fullmatch(r'[a-z][a-z-]*', values[f]) for f in fields[1:4])
                    and re.fullmatch(r'[a-z-]*', values['UnitFileState'])):
                service.update(zip(('load_state', 'active_state', 'sub_state', 'unit_file_state'),
                                   (values[f] for f in fields[1:])))
                service['running'] = values['ActiveState'] == 'active' and values['SubState'] == 'running'
                service['enabled'] = values['UnitFileState'] == 'enabled'
                service['masked'] = (values['LoadState'] == 'masked' or
                                     values['UnitFileState'] in ('masked', 'masked-runtime'))
    if service['load_state'] is None:
        block('FIREWALLD_SERVICE_UNKNOWN')
    else:
        if service['load_state'] != 'loaded':
            block('FIREWALLD_NOT_LOADED')
        if not service['running']:
            block('FIREWALLD_NOT_RUNNING')
        if not service['enabled']:
            block('FIREWALLD_NOT_ENABLED')
        if service['masked']:
            block('FIREWALLD_MASKED')

    api = {}
    for name in ('state', 'runtime_policies', 'permanent_policies'):
        result = commands.get('firewalld_' + name)
        usable = None
        if complete_result(result):
            if result['rc'] != 0:
                usable = False
            elif not result['stderr'].strip() and (name != 'state' or result['stdout'].strip() == 'running'):
                usable = True
        api[name] = usable
        if usable is not True:
            block('FIREWALLD_API_UNAVAILABLE' if usable is False else 'FIREWALLD_API_UNKNOWN', name)
    return {'packages': packages, 'cli_version': version, 'service': service, 'api': api}


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
            conditions_met = True
            for condition in flow.get('required_conditions', []):
                try:
                    enabled = strict_bool(model.get('conditions', {}).get(condition))
                except ValueError:
                    enabled = False
                    block('UNRESOLVED_FLOW_CONDITION', condition)
                conditions_met = conditions_met and enabled
            if not conditions_met:
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
    for name in sorted(EXPECTED_COMMANDS - commands.keys()):
        block('PROBE_MISSING', name)
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
    firewalld = firewalld_prerequisites(commands, block)
    return {
        'schema_version': 1, 'host': host, 'enabled_flags': flags,
        'conditions': model.get('conditions', {}),
        'candidate_flows': sorted(candidates, key=lambda f: (f['service'], f['id'])),
        'blockers': sorted(blockers, key=lambda b: (b['code'], b['subject'])),
        'observations': safe_observation, 'apply_ready': False,
        'firewalld': firewalld,
        'ssh': {'inventory_port': ssh_port, 'access_verified': False},
    }
