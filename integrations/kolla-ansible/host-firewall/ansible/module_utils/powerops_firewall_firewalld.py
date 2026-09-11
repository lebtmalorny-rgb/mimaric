"""Version-scoped firewalld D-Bus adapter. Never flush or persist other rules."""
import hashlib
import json
import os
import stat
import time

BUS = 'org.fedoraproject.FirewallD1'
PATH = '/org/fedoraproject/FirewallD1'
POLICY = 'kolla-host-input'


class FirewalldError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


class FirewalldAdapter:
    def __init__(self, owner, timeout=5, transport=None):
        self.owner = owner
        self.timeout = timeout
        self._transport = transport
        self._until = None
        if transport is None:
            import dbus
            self.dbus = dbus
            self.bus = dbus.SystemBus()
            # Do not start firewalld via D-Bus activation.
            if not self.bus.name_has_owner(BUS):
                raise FirewalldError('FIREWALLD_NOT_RUNNING')
            self.bus_owner = self.bus.get_name_owner(BUS)

    def call(self, path, interface, method, *args):
        remaining = self.timeout
        if self._until is not None:
            remaining = min(remaining, self._until - time.monotonic())
            if remaining <= 0:
                raise FirewalldError('FIREWALL_SNAPSHOT_TIMEOUT')
        if self._transport:
            return self._transport(path, interface, method, *args)
        typed = []
        for value in args:
            if isinstance(value, dict):
                value = self.dbus.Dictionary({
                    k: self.dbus.Array(v, signature='s') if isinstance(v, list) else v
                    for k, v in value.items()}, signature='sv')
            typed.append(value)
        # A proxy to the well-known name can auto-activate an exited daemon.
        # Pin its unique owner: a mid-operation exit must fail, never start it.
        obj = self.bus.get_object(self.bus_owner, path, introspect=False)
        function = self.dbus.Interface(obj, interface).get_dbus_method(method)
        return function(*typed, timeout=remaining)

    def preflight(self):
        version = self.call(PATH, 'org.freedesktop.DBus.Properties', 'Get', BUS, 'version')
        state = self.call(PATH, 'org.freedesktop.DBus.Properties', 'Get', BUS, 'state')
        backend = self.call(PATH + '/config', 'org.freedesktop.DBus.Properties',
                            'Get', BUS + '.config', 'FirewallBackend')
        if version != '1.3.4' or backend != 'nftables' or state != 'RUNNING':
            raise FirewalldError('UNSUPPORTED_FIREWALL_PROFILE')
        if self.call(PATH, BUS, 'queryPanicMode'):
            raise FirewalldError('FIREWALL_PANIC_MODE')

    def _permanent_path(self, name=POLICY):
        return self.call(PATH + '/config', BUS + '.config', 'getPolicyByName', name)

    def _settings(self, area):
        if area == 'runtime':
            settings = dict(self.call(PATH, BUS + '.policy', 'getPolicySettings', POLICY))
        elif area == 'permanent':
            settings = dict(self.call(self._permanent_path(), BUS + '.config.policy', 'getSettings'))
        else:
            raise FirewalldError('INVALID_FIREWALL_AREA')
        required = {'description': 'kolla-host-firewall:' + self.owner,
                    'ingress_zones': ['ANY'], 'egress_zones': ['HOST'],
                    'target': 'CONTINUE', 'priority': -500}
        if any(settings.get(k) != v for k, v in required.items()):
            raise FirewalldError('POLICY_OWNERSHIP_CONFLICT')
        empty = {'ports', 'services', 'protocols', 'source_ports', 'forward_ports',
                 'icmp_blocks', 'masquerade', 'short', 'version'}
        if (any(v for k, v in settings.items() if k in empty) or
                set(settings) - set(required) - empty - {'rich_rules'}):
            raise FirewalldError('POLICY_SETTINGS_CONFLICT')
        return settings

    def _foreign(self):
        result = {'default_zone': str(self.call(PATH, BUS, 'getDefaultZone'))}
        for name in self.call(PATH, BUS + '.policy', 'getPolicies'):
            if name != POLICY:
                result['runtime-policy:' + name] = self.call(
                    PATH, BUS + '.policy', 'getPolicySettings', name)
        for name in self.call(PATH, BUS + '.zone', 'getZones'):
            result['runtime-zone:' + name] = self.call(PATH, BUS + '.zone', 'getZoneSettings2', name)
        for kind, method in (('Zone', 'getSettings2'), ('Policy', 'getSettings'),
                             ('Service', 'getSettings2'), ('IcmpType', 'getSettings'),
                             ('Helper', 'getSettings'), ('IPSet', 'getSettings')):
            for name in self.call(PATH + '/config', BUS + '.config', 'get' + kind + 'Names'):
                if kind == 'Policy' and name == POLICY:
                    continue
                path = self.call(PATH + '/config', BUS + '.config', 'get' + kind + 'ByName', name)
                result['permanent-' + kind + ':' + name] = self.call(
                    path, BUS + '.config.' + kind.lower(), method)
        result['direct-rules'] = self.call(PATH, BUS + '.direct', 'getAllRules')
        result['direct-passthroughs'] = self.call(PATH, BUS + '.direct', 'getAllPassthroughs')
        for name in self.call(PATH, BUS + '.ipset', 'getIPSets'):
            result['runtime-ipset:' + name] = self.call(PATH, BUS + '.ipset', 'getIPSetSettings', name)
        return result

    def snapshot(self):
        self._until = time.monotonic() + 20
        try:
            self.preflight()
            return {'runtime': sorted(self._settings('runtime').get('rich_rules', [])),
                    'permanent': sorted(self._settings('permanent').get('rich_rules', [])),
                    'foreign': digest(self._foreign())}
        finally:
            self._until = None

    @staticmethod
    def _check_priority(foreign):
        for key, settings in foreign.items():
            if not key.startswith(('runtime-policy:', 'permanent-Policy:')):
                continue
            if ('HOST' not in settings.get('egress_zones', []) or settings.get('priority', 0) > -500):
                continue
            # The stock IPv6 ICMP policy precedes us. Our compiler intentionally
            # allows IPv6 ICMP too. No other early policy is silently accepted.
            safe_icmp = (key.split(':', 1)[1] == 'allow-host-ipv6' and
                         settings.get('target') == 'CONTINUE' and
                         all('family="ipv6"' in rule and 'icmp-type name=' in rule and
                             rule.endswith(' accept') for rule in settings.get('rich_rules', [])) and
                         not any(settings.get(k) for k in ('services', 'ports', 'protocols',
                             'source_ports', 'forward_ports', 'masquerade', 'icmp_blocks')))
            if not safe_icmp:
                raise FirewalldError('EARLIER_HOST_POLICY_CONFLICT')

    def forward_guard(self):
        self._check_priority(self._foreign())

    def change(self, area, operation, rule):
        self.preflight()
        settings = self._settings(area)
        rules = list(settings.get('rich_rules', []))
        if operation == 'add' and rule not in rules:
            rules.append(rule)
        elif operation == 'remove' and rule in rules:
            rules.remove(rule)
        else:
            raise FirewalldError('UNEXPECTED_RULE_STATE')
        # Only one add/remove per write; transaction code journals this exact
        # intermediate state before calling us, then reads the result back.
        update = {'rich_rules': sorted(rules)}
        if area == 'runtime':
            self.call(PATH, BUS + '.policy', 'setPolicySettings', POLICY, update)
        else:
            self.call(self._permanent_path(), BUS + '.config.policy', 'update', update)
            if self._transport is None:
                # D-Bus returning success is not a durability barrier. Flush
                # the exact owned XML before the transaction can be committed.
                path = '/etc/firewalld/policies/kolla-host-input.xml'
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                        raise FirewalldError('UNSAFE_POLICY_FILE')
                    os.fsync(fd)
                finally:
                    os.close(fd)
                fd = os.open('/etc/firewalld/policies', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)

    def prepare(self, allow_reload=False):
        self.preflight()
        runtime = list(self.call(PATH, BUS + '.policy', 'getPolicies'))
        permanent = list(self.call(PATH + '/config', BUS + '.config', 'getPolicyNames'))
        if POLICY in runtime:
            # No adoption merely because a name happens to match.
            self.snapshot()
            return {'changed': False, 'state': 'PREPARED'}
        if not allow_reload:
            raise FirewalldError('INITIAL_RELOAD_APPROVAL_REQUIRED')
        foreign = self._foreign()
        self._check_priority(foreign)
        if POLICY in permanent and self._settings('permanent').get('rich_rules'):
            raise FirewalldError('INITIAL_POLICY_NOT_EMPTY')
        for key, settings in foreign.items():
            if key.startswith('runtime-zone:'):
                other = foreign.get('permanent-Zone:' + key.split(':', 1)[1])
                if settings != other:
                    raise FirewalldError('RUNTIME_PERMANENT_DRIFT')
            if key.startswith('runtime-policy:'):
                other = foreign.get('permanent-Policy:' + key.split(':', 1)[1])
                if settings != other:
                    raise FirewalldError('RUNTIME_PERMANENT_DRIFT')
        if foreign['direct-rules'] or foreign['direct-passthroughs']:
            raise FirewalldError('INITIAL_RELOAD_DIRECT_RULES_CONFLICT')
        settings = {'description': 'kolla-host-firewall:' + self.owner,
                    'ingress_zones': ['ANY'], 'egress_zones': ['HOST'],
                    'target': 'CONTINUE', 'priority': -500, 'rich_rules': []}
        if POLICY not in permanent:
            self.call(PATH + '/config', BUS + '.config', 'addPolicy', POLICY, settings)
        self.call(PATH, BUS, 'reload')
        after = self.snapshot()
        if after['runtime'] or after['permanent'] or after['foreign'] != digest(foreign):
            raise FirewalldError('INITIAL_RELOAD_READBACK_MISMATCH')
        return {'changed': True, 'state': 'PREPARED'}
