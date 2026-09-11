"""Fresh SSH and endpoint checks from the controller, outside Ansible multiplexing."""
import importlib.util
from pathlib import Path
from ansible.plugins.action import ActionBase

_spec = importlib.util.spec_from_file_location('_firewall_verify',
    Path(__file__).resolve().parents[1] / 'module_utils/powerops_firewall_verification.py')
_verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_verify)


class ActionModule(ActionBase):
    TRANSFERS_FILES = False
    _requires_connection = False

    def run(self, tmp=None, task_vars=None):
        result = super().run(tmp, task_vars)
        values = task_vars or {}
        def get(key, default=None):
            return self._templar.template(values.get(key, default),
                                          fail_on_undefined=True, disable_lookups=True)
        try:
            config = {'connection': get('ansible_connection', 'ssh'),
                      'host': get('ansible_host', values['inventory_hostname']),
                      'user': get('ansible_user', get('ansible_ssh_user', self._play_context.remote_user)),
                      'port': get('ansible_port', get('ansible_ssh_port', 22)),
                      'identity': get('ansible_private_key_file', get('ansible_ssh_private_key_file', '')),
                      'ssh_common_args': get('ansible_ssh_common_args', ''),
                      'ssh_extra_args': get('ansible_ssh_extra_args', ''),
                      'password': get('ansible_password', get('ansible_ssh_pass', ''))}
            checks = get('host_firewall_verification_checks', [])
            passed = _verify.verify(config, checks, ssh_only=self._task.args.get('ssh_only', False))
            return dict(result, changed=False, passed_checks=passed)
        except Exception:
            return dict(result, changed=False, failed=True,
                        msg='FIREWALL_CONNECTIVITY_CHECK_FAILED: fresh strict SSH or configured endpoint failed')
