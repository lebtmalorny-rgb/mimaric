from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stand_test


class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'inventory').write_text('[compute]\ncompute1\n')
        self.task = dict(scenario='planned',host='compute1',inventory='inventory',interface='ens3',
            node_uuid='11111111-1111-4111-8111-111111111111',segment_uuid='22222222-2222-4222-8222-222222222222',
            ha_host_uuid='33333333-3333-4333-8333-333333333333',
            server_ids=['44444444-4444-4444-8444-444444444444'],destination_hosts=['compute2'],libvirt={'backend':'host'})
        self.path = self.root/'task.json'; self.path.write_text(json.dumps(self.task))
    def test_plan_and_unarmed_run_are_local_only(self):
        for action in ('plan','run'):
            stream = io.StringIO()
            with patch.object(stand_test.Probe,'connect',side_effect=AssertionError('API')), \
                 patch.object(stand_test.Target,'play',side_effect=AssertionError('Ansible')), redirect_stdout(stream):
                code = stand_test.main([action,'--task',str(self.path),'--run-id','test1'])
            self.assertEqual(0, code)
            self.assertEqual('PLAN',json.loads(stream.getvalue())['status'])
    def test_interface_duration_overrides_are_validated(self):
        args = stand_test.parser().parse_args(['plan','--task',str(self.path),'--run-id','test1',
                                               '--interface','eno2','--duration','301'])
        task = stand_test.load_task(self.path,args)
        self.assertEqual(('eno2',301),(task['interface'],task['duration']))
    def test_password_argument_in_task_is_rejected(self):
        self.task['password'] = 'SECRET'; self.path.write_text(json.dumps(self.task))
        args = stand_test.parser().parse_args(['plan','--task',str(self.path),'--run-id','test1'])
        with self.assertRaises(ValueError) as context: stand_test.load_task(self.path,args)
        self.assertNotIn('SECRET',str(context.exception))
    def test_status_only_reads_saved_report(self):
        state = self.root/'state'; state.mkdir()
        (state/'test1.json').write_text('{"status":"PASS","evidence":{}}')
        with redirect_stdout(io.StringIO()), patch.object(stand_test.Probe,'connect',side_effect=AssertionError('API')):
            self.assertEqual(0,stand_test.main(['status','--run-id','test1','--state-dir',str(state)]))

    def test_failed_preflight_does_not_hold_source_but_unknown_mutation_does(self):
        identity = dict(user_id='user1',endpoints={'baremetal':'https://ironic/v1'})
        saved = dict(status='FAIL',operations={},binding=dict(task=self.task,identity=identity))
        self.assertFalse(stand_test.holds_source(saved,self.task,identity))
        saved['operations'] = {'off': {'id':'unknown'}}
        self.assertTrue(stand_test.holds_source(saved,self.task,identity))
        self.assertTrue(stand_test.holds_source(saved,self.task,dict(identity,user_id='different-user')))


if __name__ == '__main__': unittest.main()
