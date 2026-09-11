"""Privileged host entry points shared by Ansible and the local watchdog."""
import os
import base64
import json
import re
from pathlib import Path
import uuid

try:
    from ansible.module_utils.powerops_firewall_transaction import TransactionManager, TransactionError, _private, _read, _save
    from ansible.module_utils.powerops_firewall_firewalld import FirewalldAdapter, PATH, BUS, POLICY
    from ansible.module_utils.powerops_firewall_plan import rules_from_report
    from ansible.module_utils.powerops_firewall_probe import run_readonly
    from ansible.module_utils.powerops_firewall_boot import restore, read_policy_file
except ImportError:
    from powerops_firewall_transaction import TransactionManager, TransactionError, _private, _read, _save
    from powerops_firewall_firewalld import FirewalldAdapter, PATH, BUS, POLICY
    from powerops_firewall_plan import rules_from_report
    from powerops_firewall_probe import run_readonly
    from powerops_firewall_boot import restore, read_policy_file

ROOT = Path('/var/lib/kolla-host-firewall')
POLICY_FILE = Path('/etc/firewalld/policies/kolla-host-input.xml')


def _command(argv):
    result = run_readonly(argv, timeout=5, max_bytes=262144)
    if (result['rc'] != 0 or not result['available'] or result['timed_out'] or result['truncated']):
        raise TransactionError('HOST_PREREQUISITE_FAILED')
    return result['stdout'].strip()


def watchdog_ready():
    try:
        return (all(_command(['systemctl', 'is-active', unit]) == 'active' for unit in (
            'kolla-host-firewall-watchdog.timer', 'kolla-host-firewall-boot-recovery.service')) and
            _command(['systemctl', 'is-enabled', 'kolla-host-firewall-watchdog.timer']) == 'enabled' and
            'kolla-host-firewall-boot-recovery.service' in
            _command(['systemctl', 'show', 'firewalld.service', '--property=Requires', '--value']).split())
    except TransactionError:
        return False


def initial_reload_guard():
    # Reload is allowed only for a narrow, observed profile. External rules are
    # never flushed to "make room" for this addon. Existing prepared policies
    # do not reload and do not need this initialization-only restriction.
    data = json.loads(_command(['nft', '-j', 'list', 'tables']))
    for entry in data['nftables']:
        if 'metainfo' in entry:
            continue
        table = entry.get('table', {})
        if table.get('family') != 'inet' or table.get('name') != 'firewalld':
            raise TransactionError('INITIAL_RELOAD_FOREIGN_NFT_TABLES')
    for tool in ('iptables-save', 'ip6tables-save'):
        for line in _command([tool]).splitlines():
            if (not line or line.startswith('#') or line in ('*filter', 'COMMIT') or
                    re.fullmatch(r':(?:INPUT|FORWARD|OUTPUT) ACCEPT \[[0-9]+:[0-9]+\]', line)):
                continue
            raise TransactionError('INITIAL_RELOAD_FOREIGN_IPTABLES_RULES')
    for flag in ('--get-all-rules', '--get-all-passthroughs', '--get-all-chains'):
        if _command(['firewall-cmd', '--permanent', '--direct', flag]):
            raise TransactionError('INITIAL_RELOAD_PERMANENT_DIRECT_RULES')
    for args in (['firewall-cmd', '--get-ipsets'], ['firewall-cmd', '--permanent', '--get-ipsets']):
        if _command(args):
            raise TransactionError('INITIAL_RELOAD_IPSETS_NOT_QUALIFIED')


def execute(action, params, check_mode=False):
    if check_mode:
        return {'changed': False, 'simulation_only': True}
    if os.geteuid() != 0:
        raise TransactionError('ROOT_REQUIRED')
    if action == 'preflight':
        _command(['rpm', '-q', 'firewalld', 'python3-firewall'])
        if _command(['systemctl', 'is-enabled', 'firewalld.service']) != 'enabled':
            raise TransactionError('FIREWALLD_NOT_ENABLED')
        FirewalldAdapter('preflight').preflight()
        if (ROOT / 'current.json').exists():
            manager = TransactionManager(ROOT, None)
            with manager._lock():
                if manager._current()['state'] not in ('COMMITTED', 'ROLLED_BACK'):
                    raise TransactionError('TRANSACTION_ACTIVE')
        return {'changed': False, 'state': 'PREFLIGHT_OK'}
    if action == 'prepare':
        if params.get('allow_reload') is not True:
            raise TransactionError('INITIAL_RELOAD_APPROVAL_REQUIRED')
        execute('preflight', {})
        ROOT.mkdir(mode=0o700, exist_ok=True)
        _private(ROOT, directory=True)
        (ROOT / 'transactions').mkdir(mode=0o700, exist_ok=True)
        _private(ROOT / 'transactions', directory=True)
        manager = TransactionManager(ROOT, None, watchdog_ready=watchdog_ready)
        with manager._lock():
            current = manager._current()
            if current and current['state'] not in ('COMMITTED', 'ROLLED_BACK'):
                raise TransactionError('TRANSACTION_ACTIVE')
            owner_file = ROOT / 'owner.json'
            if not owner_file.exists():
                _save(owner_file, {'id': str(uuid.uuid4())})
            owner = _read(owner_file)['id']
            adapter = FirewalldAdapter(owner)
            if POLICY not in adapter.call(PATH, BUS + '.policy', 'getPolicies'):
                initial_reload_guard()
            return adapter.prepare(allow_reload=True)
    if action in ('recover-expired', 'recover-boot') and not (ROOT / 'current.json').exists():
        return {'changed': False, 'state': 'IDLE'}
    owner = _read(ROOT / 'owner.json')['id']
    if action == 'recover-boot':
        from firewall.core.io.policy import policy_reader
        return restore(ROOT, POLICY_FILE, owner,
                       lambda: policy_reader(POLICY_FILE.name, str(POLICY_FILE.parent)).export_config_dict(),
                       Path('/proc/sys/kernel/random/boot_id').read_text().strip())
    adapter = FirewalldAdapter(owner)
    manager = TransactionManager(ROOT, adapter, watchdog_ready=watchdog_ready)
    if action == 'inspect':
        adapter.forward_guard()
        return {'changed': False, 'snapshot': adapter.snapshot()}
    if action == 'begin':
        adapter.forward_guard()
        report = params['report']
        rules = rules_from_report(report)
        # Validate and canonicalise with the parser shipped with target firewalld.
        from firewall.core.rich import Rich_Rule
        rules = [str(Rich_Rule(rule_str=rule)) for rule in rules]
        plan = {'plan_id': params['plan_id'], 'host': report['host'],
                'ssh_port': report['ssh']['inventory_port'], 'rules': rules,
                'required_checks': params['required_checks'],
                'rollback_timeout': params['rollback_timeout'], 'expected': params['expected'],
                'boot_image': base64.b64encode(read_policy_file(POLICY_FILE)).decode()}
        return manager.begin(plan)
    if action == 'apply-runtime':
        return manager.apply_runtime(params['txid'])
    if action == 'verify':
        return manager.verify(params['txid'], params['nonce'], params['passed_checks'])
    if action == 'commit':
        return manager.commit(params['txid'])
    if action == 'rollback':
        return manager.rollback(params['txid'])
    if action == 'recover-expired':
        return manager.recover_expired()
    if action == 'status':
        return manager.status()
    raise TransactionError('UNKNOWN_FIREWALL_ACTION')
