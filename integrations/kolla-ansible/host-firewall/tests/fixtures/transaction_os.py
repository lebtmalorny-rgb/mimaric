"""Test-only OS substitute; the real transaction manager and compiler are used."""
import json
import os
from pathlib import Path
import time
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.powerops_firewall_transaction import TransactionManager
from ansible.module_utils.powerops_firewall_plan import rules_from_report


class Clock:
    boot_id = 'test-boot'
    monotonic = staticmethod(time.monotonic)


class Firewall:
    def __init__(self, path):
        self.path = path
        if not path.exists():
            path.write_text(json.dumps({'runtime': [], 'permanent': [], 'foreign': 'unchanged'}))

    def snapshot(self):
        return json.loads(self.path.read_text())

    def change(self, area, operation, rule):
        state = self.snapshot()
        if operation == 'add':
            state[area].append(rule)
        else:
            state[area].remove(rule)
        state[area].sort()
        self.path.write_text(json.dumps(state))


def main():
    module = AnsibleModule(argument_spec={
        'action': {'type': 'str', 'required': True}, 'txid': {'type': 'str', 'default': ''},
        'nonce': {'type': 'str', 'default': '', 'no_log': True},
        'plan_id': {'type': 'str', 'default': ''}, 'report': {'type': 'dict', 'default': {}},
        'expected': {'type': 'dict', 'default': {}},
        'required_checks': {'type': 'list', 'elements': 'str', 'default': []},
        'passed_checks': {'type': 'list', 'elements': 'str', 'default': []},
        'rollback_timeout': {'type': 'int', 'default': 300},
    }, supports_check_mode=True)
    p = module.params
    marker = Path(os.environ['POWEROPS_TEST_MUTATION_MARKER'])
    marker.parent.mkdir(exist_ok=True)
    with marker.open('a') as stream:
        stream.write(json.dumps({'action': p['action']}) + '\n')
    firewall = Firewall(marker.parent / 'firewall.json')
    manager = TransactionManager(marker.parent / 'transaction', firewall, Clock(), lambda: True)
    try:
        if p['action'] == 'inspect':
            result = {'changed': False, 'snapshot': firewall.snapshot()}
        elif p['action'] == 'begin':
            result = manager.begin({'plan_id': p['plan_id'], 'host': p['report']['host'],
                'ssh_port': p['report']['ssh']['inventory_port'], 'rules': rules_from_report(p['report']),
                'required_checks': p['required_checks'], 'rollback_timeout': p['rollback_timeout'],
                'expected': p['expected']})
        elif p['action'] == 'verify':
            result = manager.verify(p['txid'], p['nonce'], p['passed_checks'])
        else:
            result = getattr(manager, p['action'].replace('-', '_'))(p['txid'])
        module.exit_json(**result)
    except Exception as exc:
        module.fail_json(msg=str(exc), changed=False)


main()
