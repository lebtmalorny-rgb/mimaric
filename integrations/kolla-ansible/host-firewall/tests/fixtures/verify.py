"""Test-only fresh SSH/endpoint boundary substitute."""
import os
from pathlib import Path
from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):
    _requires_connection = False
    def run(self, tmp=None, task_vars=None):
        marker = Path(os.environ['POWEROPS_TEST_MUTATION_MARKER']).parent / 'checks'
        count = int(marker.read_text()) + 1 if marker.exists() else 1
        marker.write_text(str(count))
        if os.environ.get('POWEROPS_TEST_VERIFY_FAIL') == str(count):
            return {'failed': True, 'changed': False, 'msg': 'Injected new SSH connection failure'}
        return {'changed': False, 'passed_checks': ['ssh-fresh', 'api']}
