"""Use Ansible's own inventory, variable and Vault resolution; never dump vars."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from link_fault import BOOTSTRAP
from scenario_runner import Incomplete


INSPECT = r'''
import json, pathlib, subprocess, sys
request = json.load(sys.stdin)
def command(argv):
    return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=15).stdout
interface = request['interface']
link, = json.loads(command(['ip', '-j', 'address', 'show', 'dev', interface]))
backend = request['libvirt']['backend']
argv = [] if backend == 'host' else [backend, 'exec', request['libvirt']['container']]
domains = command(argv + ['virsh', '-c', 'qemu:///system', 'list', '--all', '--uuid']).split()
print(json.dumps(dict(
    machine_id=pathlib.Path('/etc/machine-id').read_text().strip(),
    boot_id=pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
    interface=link['ifname'], mac=link['address'], up='UP' in link['flags'],
    addresses=sorted(a['local'] + '/' + str(a['prefixlen']) for a in link.get('addr_info', [])
                     if a.get('scope') != 'link'), domains=sorted(domains))))
'''


class Target:
    def __init__(self, task, process=subprocess.run):
        self.task, self.process = task, process

    def play(self, tasks):
        with tempfile.TemporaryDirectory(prefix='powerops-ansible-') as directory:
            directory = Path(directory)
            output = directory / 'result.json'
            assertions = dict(name='Require exactly the explicitly selected inventory host',
                **{'ansible.builtin.assert': {'that': [
                    'ansible_play_hosts_all | length == 1',
                    'inventory_hostname == powerops_test_host']}})
            playbook = [dict(name='PowerOps stand target operation', hosts=self.task['inventory_host'],
                gather_facts=False, any_errors_fatal=True, no_log=True, tasks=[assertions] + tasks)]
            play_path = directory / 'play.json'
            vars_path = directory / 'vars.json'
            # Temp dir 0700, inputs 0600; secrets stay inside Ansible/Vault.
            for path, data in [(play_path, playbook), (vars_path, dict(
                    powerops_test_host=self.task['inventory_host'], powerops_test_output=str(output)))]:
                path.touch(mode=0o600)
                path.write_text(json.dumps(data))
            argv = ['ansible-playbook', '-i', self.task['inventory'], str(play_path)]
            if self.task.get('globals'):
                argv += ['-e', '@' + self.task['globals']]
            argv += ['-e', '@' + str(vars_path)]
            if self.task.get('vault_password_file'):
                argv += ['--vault-password-file', self.task['vault_password_file']]
            environment = dict(os.environ, ANSIBLE_HOST_KEY_CHECKING='True', ANSIBLE_LOG_PATH=os.devnull,
                ANSIBLE_STDOUT_CALLBACK='default', ANSIBLE_RETRY_FILES_ENABLED='False',
                ANSIBLE_LOCAL_TEMP=str(directory / 'ansible-tmp'))
            try:
                result = self.process(argv, env=environment, capture_output=True, text=True, timeout=120, check=False)
                if result.returncode or not output.exists():
                    raise Incomplete('Ansible did not return a confirmed result; inspect target with the same run-id')
                return json.loads(output.read_text())
            except (OSError, subprocess.SubprocessError, ValueError):
                raise Incomplete('Ansible transport failed; remote outcome may be unknown') from None

    @staticmethod
    def receipt(content):
        return dict(name='Save allowlisted result locally', delegate_to='localhost', become=False,
                    vars=dict(ansible_connection='local', ansible_python_interpreter=sys.executable,
                              ansible_remote_tmp='{{ powerops_test_output | dirname }}/module-tmp'),
                    **{'ansible.builtin.copy': {'content': content, 'dest': '{{ powerops_test_output }}', 'mode':'0600'}})

    def resolve_interface(self):
        if self.task.get('interface'):
            expression = json.dumps(self.task['interface'])
        else:
            # Config validator only permits known, simple variable names.
            expression = self.task['interface_var']
        result = self.play([self.receipt("{{ {'interface': " + expression + "} | to_json }}")])
        return result['interface']

    def command(self, source, request):
        task = dict(name='Run bounded PowerOps target operation', become=self.task.get('become', True),
                    register='powerops_test_command', **{'ansible.builtin.command': {
                        'argv':[self.task.get('remote_python', 'python3.11'), '-c', source],
                        'stdin':json.dumps(request), 'stdin_add_newline':False}})
        return self.play([task, self.receipt('{{ powerops_test_command.stdout }}')])

    def inspect(self):
        return self.command(INSPECT, dict(interface=self.task['interface'], libvirt=self.task['libvirt']))

    def fault(self, action, run_id, nonce):
        source = Path(__file__).with_name('remote_fault.py').read_text()
        result = self.command(BOOTSTRAP, dict(source=source, request=dict(action=action,
            fault=dict(run_id=run_id, interface=self.task['interface'], duration=self.task['duration'], nonce=nonce))))
        if result.get('phase') == 'ERROR':
            raise Incomplete('fault worker rejected the request; reconcile the same run-id on the target')
        return result
