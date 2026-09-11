#!/usr/bin/python
"""Ansible adapter; real operations are shared with the independent watchdog."""
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.powerops_firewall_runtime import execute


def main():
    module = AnsibleModule(argument_spec={
        'action': {'type': 'str', 'required': True, 'choices': [
            'preflight', 'prepare', 'inspect', 'begin', 'apply-runtime',
            'verify', 'commit', 'rollback', 'status']},
        'allow_reload': {'type': 'bool', 'default': False},
        'txid': {'type': 'str', 'default': ''},
        'nonce': {'type': 'str', 'default': '', 'no_log': True},
        'plan_id': {'type': 'str', 'default': ''},
        'report': {'type': 'dict', 'default': {}},
        'expected': {'type': 'dict', 'default': {}},
        'required_checks': {'type': 'list', 'elements': 'str', 'default': []},
        'passed_checks': {'type': 'list', 'elements': 'str', 'default': []},
        'rollback_timeout': {'type': 'int', 'default': 300},
    }, supports_check_mode=True)
    try:
        result = execute(module.params['action'], module.params, module.check_mode)
    except Exception as exc:
        import re
        code = str(exc)
        if not re.fullmatch(r'[A-Z_]+', code):
            code = 'FIREWALL_OPERATION_FAILED'
        module.fail_json(msg=code, changed=module.params['action'] not in ('preflight', 'inspect', 'status'),
                         recovery='Do not disable the local rollback watchdog; inspect its journal.')
    if module.params['action'] != 'begin':
        result.pop('nonce', None)
    module.exit_json(**result)


if __name__ == '__main__':
    main()
