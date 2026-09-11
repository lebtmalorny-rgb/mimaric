"""Validate diagnostic evidence before compiling any restrictive host policy."""
import hashlib
import ipaddress
import json


class PlanError(ValueError):
    pass


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def report_digest(bundle):
    # Only explicit stable fields; timestamp and raw counters are observations,
    # not policy inputs. Runtime/permanent are rechecked by the remote adapter.
    return canonical_digest({'selected_hosts': sorted(bundle['selected_hosts']),
                             'catalog_digest': bundle.get('catalog_digest'),
                             'reports': {host: {key: report.get(key) for key in (
                                 'host', 'ssh', 'candidate_flows', 'blockers', 'enabled_flags', 'conditions')}
                                 for host, report in sorted(bundle['reports'].items())}})


def rules_from_report(report):
    blockers = report.get('blockers')
    if (not isinstance(blockers, list) or any(
            b.get('code') not in ('SSH_ACCESS_NOT_VERIFIED', 'APPLY_REQUIRES_VERIFICATION') for b in blockers)):
        raise PlanError('REPORT_HAS_BLOCKERS')
    port = report.get('ssh', {}).get('inventory_port')
    if type(port) is not int or not 1 <= port <= 65535:
        raise PlanError('SSH_PORT_UNRESOLVED')
    rules = [f'rule priority="-30000" port port="{port}" protocol="tcp" accept',
             'rule family="ipv4" priority="-29000" protocol value="icmp" accept',
             'rule family="ipv6" priority="-29000" protocol value="ipv6-icmp" accept']
    flows = report.get('candidate_flows')
    if not isinstance(flows, list):
        raise PlanError('INVALID_FLOW_LIST')
    for flow in flows:
        try:
            destination = ipaddress.ip_address(flow['destination'])
            sources = flow['sources']
            number = flow['port']
            protocol = flow['protocol']
            if (type(number) is not int or not 1 <= number <= 65535 or
                    protocol not in ('tcp', 'udp') or not isinstance(sources, list) or not sources):
                raise ValueError()
            for source in sources:
                address = ipaddress.ip_address(source['address'])
                if (address.version != destination.version or address.is_unspecified or
                        address.is_multicast or address.is_loopback or address.is_link_local or
                        destination.is_unspecified or destination.is_multicast or
                        destination.is_loopback or destination.is_link_local):
                    raise ValueError()
                prefix = 32 if address.version == 4 else 128
                rules.append(f'rule family="ipv{address.version}" priority="-20000" '
                             f'source address="{address}/{prefix}" '
                             f'destination address="{destination}/{prefix}" '
                             f'port port="{number}" protocol="{protocol}" accept')
        except (KeyError, ValueError, TypeError):
            raise PlanError('INVALID_FLOW') from None
    return sorted(set(rules)) + ['rule priority="30000" drop']
