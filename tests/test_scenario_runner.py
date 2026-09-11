import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scenario_runner import Runner, Journal, Failed, Incomplete


TASK = dict(scenario='planned', host='compute-1', interface='eno1', duration=300,
            server_ids=['vm1'], destination_hosts=['compute-2'], node_uuid='node1',
            segment_uuid='segment1', ha_host_uuid='ha1', timeout=20, poll_interval=1)


class Clock:
    def __init__(self): self.now = 1000; self.wall_shift = 0
    def time(self): return self.now + self.wall_shift
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now += seconds


class Cloud:
    def __init__(self, task):
        self.task = task
        self.phase = 'initial'
        self.executions = {}
        self.creates = []
        self.resumes = []
        self.bad_vm = False
        self.missing_fence = False
        self.lost_create = False
        self.lost_resume = False
    def snapshot(self, task):
        initial = self.phase == 'initial'
        returned = self.phase == 'returned'
        on = initial or self.phase in ('inspection', 'returned')
        return dict(node=dict(uuid='node1', name='compute-1', power_state='power on' if on else 'power off',
                              target_power_state=None, last_error=None, maintenance=False),
                    service=dict(id='svc1', host='compute-1', binary='nova-compute',
                                 status='enabled' if initial or returned else 'disabled', state='up' if on else 'down'),
                    ha_host=dict(uuid='ha1', name='compute-1', failover_segment_id='segment1',
                                 on_maintenance=not (initial or returned)),
                    servers=[dict(id='vm1', host='compute-1' if initial else 'compute-2',
                                  status='ERROR' if self.bad_vm else 'ACTIVE', task_state=None)],
                    source_ids=['vm1'] if initial else [],
                    destinations=[dict(host='compute-2', status='enabled', state='up')],
                    migrations=[] if initial else [dict(uuid='mig1', instance_uuid='vm1', source_compute='compute-1',
                          dest_compute='compute-2', migration_type='live-migration', status='completed')])
    def notifications(self, task):
        return [] if self.phase == 'initial' else [dict(notification_uuid='notification1', source_host_uuid='ha1',
            type='COMPUTE_HOST', status='finished', payload={'event': 'STOPPED'})]
    def notification(self, ident):
        return dict(notification_uuid=ident, source_host_uuid='ha1', type='COMPUTE_HOST', status='finished',
                    payload={'event': 'STOPPED'}, recovery_workflow_details=[] if self.missing_fence else [
                    dict(name='IronicFenceTask', state='SUCCESS', progress_details=[
                        dict(timestamp='2026-09-11T00:00:01Z', message="Ironic confirmed power off for host 'compute-1'; waiting up to 60s for Nova disabled/down"),
                        dict(timestamp='2026-09-11T00:00:02Z', message="Nova confirmed disabled/down for fenced host 'compute-1'; host recovery may proceed")])])
    def vmoves(self, ident):
        return [dict(uuid='move1', notification_uuid=ident, instance_uuid='vm1', source_host='compute-1',
                     dest_host='compute-2', type='evacuation', status='succeeded',
                     start_time='2026-09-11T00:00:03Z', end_time='2026-09-11T00:00:04Z')]
    def execution(self, ident): return copy.deepcopy(self.executions.get(ident))
    def create(self, body):
        self.creates.append(copy.deepcopy(body))
        result = copy.deepcopy(body)
        if body['workflow_name'].endswith('planned_power_off'):
            self.phase = 'off'
            result.update(state='SUCCESS', output={'result':dict(host='compute-1', operation='planned_power_off',
                  power_state='power off', stopped_instance_ids=[], nova_enabled=False, masakari_maintenance=True),
                  'stopped_instance_ids':[]})
        else:
            self.phase = 'inspection'
            result.update(state='PAUSED', output={})
        self.executions[body['id']] = result
        if self.lost_create:
            self.lost_create = False
            raise Incomplete('lost POST response')
        return result
    def tasks(self, ident):
        return [dict(name='power_on_for_inspection', state='SUCCESS', workflow_execution_id=ident),
                dict(name='operator_inspection_gate', state='IDLE', workflow_execution_id=ident)]
    def resume(self, ident, body):
        self.resumes.append((ident, body))
        self.phase = 'returned'
        self.executions[ident].update(state='SUCCESS', params=body['params'], output={'result':dict(
            host='compute-1', operation='return_to_service', power_state='power on', stopped_instance_ids=[],
            nova_enabled=True, masakari_maintenance=False)})
        if self.lost_resume: raise Incomplete('lost PUT response')


class Target:
    def __init__(self, cloud): self.cloud = cloud; self.stale = False; self.fault_calls = []
    def inspect(self):
        return dict(machine_id='machine1', boot_id='boot1' if self.cloud.phase == 'initial' else 'boot2', interface='eno1', mac='aa:bb', up=True,
                    addresses=['192.0.2.1/24'], domains=['vm1'] if self.cloud.phase == 'initial' or self.stale else [])
    def fault(self, action, run_id, nonce):
        self.fault_calls.append(action)
        if action == 'start': self.cloud.phase = 'off'
        return dict(phase='RESTORED', result='COMPLETED', down_confirmed_at=1000,
                    new_submission=True, identity=dict(boot_id='boot1',ifname='eno1',address='aa:bb'),
                    request=dict(run_id=run_id, interface='eno1', duration=300, nonce=nonce))


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.task = copy.deepcopy(TASK)
        self.cloud = Cloud(self.task); self.target = Target(self.cloud); self.clock = Clock()
    def runner(self):
        journal = Journal(Path(self.temp.name) / 'run.json', self.task, 'test1', {'project': 'p1'})
        return Runner(self.task, self.cloud, self.target, journal, self.clock)
    def test_planned_migrates_powers_off_returns_and_auto_confirms(self):
        report = self.runner().run()
        self.assertEqual('PASS', report['status'])
        self.assertEqual(2, len(self.cloud.creates))
        ident, body = self.cloud.resumes[0]
        self.assertEqual(self.cloud.creates[1]['id'], ident)
        self.assertIs(body['params']['env']['stale_domains_checked'], True)
        self.assertIn('inspection', report['evidence'])
    def test_emergency_observes_notification_fencing_and_vmove(self):
        self.task['scenario'] = 'emergency'
        self.assertEqual('PASS', self.runner().run()['status'])
        self.assertEqual(['start', 'reconcile'], self.target.fault_calls)
        self.assertGreaterEqual(self.clock.time(), 1300)
        self.assertEqual(1, len(self.cloud.creates))
    def test_stale_domains_prevent_confirmation(self):
        self.target.stale = True
        self.assertEqual('FAIL', self.runner().run()['status'])
        self.assertEqual([], self.cloud.resumes)
    def test_bad_vm_prevents_first_mutation(self):
        self.cloud.bad_vm = True
        self.assertEqual('FAIL', self.runner().run()['status'])
        self.assertEqual([], self.cloud.creates)

    def test_planned_rejects_legacy_done_migration_before_workflow_changes_host(self):
        original = self.cloud.snapshot
        def old_done(task):
            result = original(task)
            result['migrations'] = [dict(uuid='old', status='done')]
            return result
        self.cloud.snapshot = old_done
        self.assertEqual('FAIL', self.runner().run()['status'])
        self.assertEqual([], self.cloud.creates)
    def test_missing_fencing_proof_never_passes_or_returns(self):
        self.task['scenario'] = 'emergency'; self.cloud.missing_fence = True
        self.assertEqual('INCOMPLETE', self.runner().run()['status'])
        self.assertEqual([], self.cloud.creates)
    def test_lost_create_response_reconciles_exact_id_without_second_post(self):
        self.cloud.lost_create = True
        self.assertEqual('PASS', self.runner().run()['status'])
        self.assertEqual(2, len(self.cloud.creates))
    def test_lost_resume_response_does_not_replay_put(self):
        self.cloud.lost_resume = True
        self.assertEqual('PASS', self.runner().run()['status'])
        self.assertEqual(1, len(self.cloud.resumes))
    def test_repeat_completed_run_does_not_repeat_mutations(self):
        self.runner().run(); self.runner().run()
        self.assertEqual(2, len(self.cloud.creates)); self.assertEqual(1, len(self.cloud.resumes))
    def test_changed_task_or_identity_is_rejected(self):
        self.runner()
        self.task['duration'] = 301
        with self.assertRaises(Failed): self.runner()
    def test_no_post_replay_after_journalled_intent_without_response(self):
        runner = self.runner()
        runner.journal.data['operations']['off'] = dict(id='unknown-id', workflow_name='power_ops.planned_power_off',
            input={'host':'compute-1','segment_uuid':'segment1','instance_policy':'live_migrate','allow_hard_off':False},
            description='powerops-stand:test1:off')
        runner.journal.save()
        self.assertEqual('INCOMPLETE', runner.run()['status'])
        self.assertEqual([], self.cloud.creates)

    def test_restart_rechecks_foreign_vm_before_first_mutation(self):
        runner = self.runner(); runner.preflight()
        original = self.cloud.snapshot
        def changed(task):
            result = original(task); result['source_ids'].append('foreign-vm'); return result
        self.cloud.snapshot = changed
        self.assertEqual('FAIL', self.runner().run()['status'])
        self.assertEqual([], self.cloud.creates)
        self.assertEqual(['vm1'], self.runner().evidence['baseline']['snapshot']['source_ids'])

    def test_restart_rechecks_host_before_new_return_workflow(self):
        runner = self.runner(); runner.preflight(); runner.planned()
        self.cloud.phase = 'initial'
        self.assertEqual('FAIL', self.runner().run()['status'])
        self.assertEqual(1, len(self.cloud.creates))

    def test_remote_clock_skew_cannot_shorten_outage_hold(self):
        self.task['scenario'] = 'emergency'
        original = self.target.fault
        def skew(action, run_id, nonce):
            result = original(action, run_id, nonce); result['down_confirmed_at'] = 0; return result
        self.target.fault = skew
        self.assertEqual('PASS', self.runner().run()['status'])
        self.assertGreaterEqual(self.clock.time(), 1300)

    def test_final_network_drift_cannot_pass(self):
        original = self.target.inspect
        def changed():
            result = original()
            if self.cloud.phase == 'returned': result.update(addresses=[], mac='different')
            return result
        self.target.inspect = changed
        self.assertEqual('FAIL', self.runner().run()['status'])

    def test_poll_does_not_accept_response_after_deadline(self):
        runner = self.runner()
        def slow(): self.clock.sleep(21); return True
        with self.assertRaises(Incomplete): runner.poll('slow', slow, bool)
        with self.assertRaises(Incomplete): runner.poll('slow', lambda: True, bool)

    def test_evacuation_before_fence_is_failure(self):
        self.task['scenario'] = 'emergency'
        original = self.cloud.vmoves
        def early(ident):
            result = original(ident); result[0]['start_time'] = '2026-09-11T00:00:00Z'; return result
        self.cloud.vmoves = early
        self.assertEqual('FAIL', self.runner().run()['status'])
        self.assertEqual([], self.cloud.creates)

    def test_vmove_from_different_notification_is_failure(self):
        self.task['scenario'] = 'emergency'
        original = self.cloud.vmoves
        def wrong(ident):
            result = original(ident); result[0]['notification_uuid'] = 'foreign'; return result
        self.cloud.vmoves = wrong
        self.assertEqual('FAIL', self.runner().run()['status'])

    def test_failed_live_migration_cannot_pass(self):
        original = self.cloud.snapshot
        def failed(task):
            result = original(task)
            if result['migrations']: result['migrations'][0]['status'] = 'failed'
            return result
        self.cloud.snapshot = failed
        self.assertEqual('FAIL', self.runner().run()['status'])
        self.assertEqual([], self.cloud.resumes)

    def test_notification_binding_is_persisted_before_wait(self):
        self.task['scenario'] = 'emergency'
        original = self.cloud.notification
        def lost(ident): raise Incomplete('lost GET')
        self.cloud.notification = lost
        self.assertEqual('INCOMPLETE', self.runner().run()['status'])
        self.assertEqual('notification1', self.runner().evidence['notification_id'])
        self.cloud.notification = original
        self.cloud.notifications = lambda task: []
        self.assertEqual('PASS', self.runner().run()['status'])

    def test_unknown_resume_left_paused_is_not_replayed(self):
        def lost(ident, body):
            self.cloud.resumes.append((ident,body)); raise Incomplete('lost PUT before apply')
        self.cloud.resume = lost
        self.assertEqual('INCOMPLETE', self.runner().run()['status'])
        self.assertEqual('INCOMPLETE', self.runner().run()['status'])
        self.assertEqual(1, len(self.cloud.resumes))

    def test_missing_actual_down_evidence_blocks_auto_confirmation(self):
        self.task['scenario'] = 'emergency'
        original = self.target.fault
        def no_down(action, ident, nonce):
            result = original(action,ident,nonce); result.pop('down_confirmed_at'); return result
        self.target.fault = no_down
        self.assertEqual('FAIL', self.runner().run()['status'])
        self.assertEqual([], self.cloud.resumes)

    def test_existing_remote_run_id_is_not_reused_as_a_new_outage(self):
        self.task['scenario'] = 'emergency'
        original = self.target.fault
        def existing(action, ident, nonce):
            result = original(action,ident,nonce); result['new_submission'] = False; return result
        self.target.fault = existing
        self.assertEqual('FAIL', self.runner().run()['status'])
        self.assertEqual([], self.cloud.creates)

    def test_early_interface_restore_cannot_pass_as_fencing(self):
        self.task['scenario'] = 'emergency'
        original = self.target.fault
        def early(action, ident, nonce):
            result = original(action,ident,nonce); result['result'] = 'INTERRUPTED'; return result
        self.target.fault = early
        self.assertEqual('FAIL', self.runner().run()['status'])
        self.assertEqual([], self.cloud.resumes)

    def test_journal_from_another_boot_cannot_authorize_return(self):
        self.task['scenario'] = 'emergency'
        original = self.target.fault
        def old(action, ident, nonce):
            result = original(action,ident,nonce); result['identity']['boot_id'] = 'older-boot'; return result
        self.target.fault = old
        self.assertEqual('FAIL', self.runner().run()['status'])
        self.assertEqual([], self.cloud.resumes)

    def test_lost_reply_cannot_attribute_old_same_boot_fault_to_current_run(self):
        self.task['scenario'] = 'emergency'
        original = self.target.fault
        def old_after_lost_reply(action, ident, nonce):
            if action == 'start':
                self.cloud.phase = 'off'  # Independent external event, no new DOWN.
                raise Incomplete('lost existing run reply')
            result = original(action,ident,nonce)
            result['request']['nonce'] = '0' * 32
            return result
        self.target.fault = old_after_lost_reply
        self.assertEqual('FAIL', self.runner().run()['status'])
        self.assertEqual([], self.cloud.resumes)

    def test_forward_wall_clock_step_cannot_shorten_power_off_hold(self):
        self.task['scenario'] = 'emergency'
        original = self.clock.sleep
        def step(seconds):
            original(seconds); self.clock.wall_shift += 600
        self.clock.sleep = step
        report = self.runner().run()
        self.assertEqual('PASS',report['status'])
        self.assertGreaterEqual(self.clock.monotonic(),1300)
        self.assertGreaterEqual(report['evidence']['power_off_hold']['elapsed_seconds'],300)

    def test_restart_before_return_repeats_full_conservative_hold(self):
        self.task['scenario'] = 'emergency'
        runner = self.runner(); runner.preflight(); runner.emergency()
        self.clock.sleep(100)
        before = self.clock.monotonic()
        self.assertEqual('PASS',self.runner().run()['status'])
        self.assertGreaterEqual(self.clock.monotonic() - before,300)


if __name__ == '__main__': unittest.main()
