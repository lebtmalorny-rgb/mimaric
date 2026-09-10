#!/usr/bin/python
"""Ansible boundary for read-only host firewall observations."""
import platform

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.powerops_firewall_probe import collect_snapshot

DOCUMENTATION = r'''
---
module: powerops_firewall_probe
short_description: Collect bounded read-only host network observations
description: Does not install packages, change rules, reload or start services.
options:
  timeout:
    type: int
    default: 10
    description: Maximum seconds per command, from 1 to 120.
  max_bytes:
    type: int
    default: 262144
    description: Maximum captured bytes per stream, at most 4194304.
author: PowerOps maintainers
'''
EXAMPLES = r'''
- powerops_firewall_probe:
    timeout: 10
    max_bytes: 262144
'''
RETURN = r'''
snapshot:
  description: Timestamp and command results, including failures and truncation.
  type: dict
  returned: success
'''


def main():
    module = AnsibleModule(argument_spec={
        'timeout': {'type': 'int', 'default': 10},
        'max_bytes': {'type': 'int', 'default': 262144},
    }, supports_check_mode=True)
    if platform.system() != 'Linux':
        module.fail_json(msg='Host firewall probe requires Linux', changed=False)
    try:
        snapshot = collect_snapshot(**module.params)
    except ValueError as exc:
        module.fail_json(msg=str(exc), changed=False)
    module.exit_json(changed=False, snapshot=snapshot)


if __name__ == '__main__':
    main()
