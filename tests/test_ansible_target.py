import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ansible_target import Target
from scenario_runner import Incomplete


class TargetTests(unittest.TestCase):
    def test_transport_uses_private_no_log_play_and_no_shell(self):
        def process(argv, **kwargs):
            play_path = Path(argv[3])
            self.assertEqual(0o600, play_path.stat().st_mode & 0o777)
            play = json.loads(play_path.read_text())[0]
            self.assertIs(play['no_log'], True)
            self.assertIs(play['gather_facts'], False)
            self.assertNotIn('shell', kwargs)
            self.assertEqual('True', kwargs['env']['ANSIBLE_HOST_KEY_CHECKING'])
            extra = json.loads(Path(argv[-1][1:]).read_text())
            Path(extra['powerops_test_output']).write_text('{"interface":"ens3"}')
            return SimpleNamespace(returncode=0)
        target = Target(dict(inventory='/inventory', inventory_host='compute1', interface='ens3'), process)
        self.assertEqual('ens3', target.resolve_interface())

    def test_failed_ansible_output_is_not_exposed(self):
        target = Target(dict(inventory='/inventory', inventory_host='compute1', interface='ens3'),
                        lambda *a,**kw: SimpleNamespace(returncode=2,stdout='password=SECRET',stderr='SECRET'))
        with self.assertRaises(Incomplete) as context: target.resolve_interface()
        self.assertNotIn('SECRET', str(context.exception))

    @unittest.skipUnless(shutil.which('ansible-playbook'), 'Ansible is not installed')
    def test_real_ansible_resolves_globals_and_templates_locally(self):
        with tempfile.TemporaryDirectory(prefix='powerops-inventory-fixture-') as directory:
            root = Path(directory)
            (root/'inventory').write_text('[compute]\ncompute-fixture ansible_connection=local\n')
            (root/'globals.yml').write_text('test_nic_name: ens9\nnetwork_interface: "{{ test_nic_name }}"\n')
            task = dict(inventory=str(root/'inventory'),globals=str(root/'globals.yml'),
                        inventory_host='compute-fixture',interface_var='network_interface')
            self.assertEqual('ens9', Target(task).resolve_interface())

    @unittest.skipUnless(shutil.which('ansible-playbook'), 'Ansible is not installed')
    def test_real_ansible_rejects_a_group_matching_multiple_hosts(self):
        with tempfile.TemporaryDirectory(prefix='powerops-inventory-fixture-') as directory:
            root = Path(directory)
            (root/'inventory').write_text('[compute]\nfixture1 ansible_connection=local\nfixture2 ansible_connection=local\n')
            task = dict(inventory=str(root/'inventory'),inventory_host='compute',interface='ens3')
            with self.assertRaises(Incomplete): Target(task).resolve_interface()


if __name__ == '__main__': unittest.main()
