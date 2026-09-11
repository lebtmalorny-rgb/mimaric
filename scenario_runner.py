"""Durable acceptance scenarios. Ports perform real API/Ansible operations."""
from datetime import datetime
import json
import time
import uuid

from remote_fault import atomic_write


class Failed(Exception):
    """Observed violation of the acceptance contract."""


class Incomplete(Exception):
    """Missing evidence or ambiguous outcome; never a successful test."""


def require(condition, message):
    if not condition:
        raise Failed(message)


def obj(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise Incomplete('API field is not a JSON object') from None
    if not isinstance(value, dict):
        raise Incomplete('API field is not a JSON object')
    return value


def timestamp(value):
    try:
        # Masakari uses UTC, including its offset-free legacy timestamps.
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            from datetime import timezone
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (AttributeError, TypeError, ValueError):
        raise Incomplete('missing or invalid recovery timestamp') from None


class Journal:
    """Caller holds an exclusive runner lock. Intents survive process failure."""
    def __init__(self, path, task, run_id, identity):
        self.path = path
        binding = dict(task=task, run_id=run_id, identity=identity)
        if path.exists():
            require(not path.is_symlink(), 'symlink journal')
            self.data = json.loads(path.read_text())
            require(self.data['binding'] == binding, 'run-id belongs to another task or cloud identity')
        else:
            self.data = dict(schema=1, binding=binding, status='NEW', operations={}, evidence={}, deadlines={})
            self.save()

    def save(self):
        atomic_write(self.path, json.dumps(self.data, indent=2, sort_keys=True) + '\n')


class Runner:
    def __init__(self, task, cloud, target, journal, clock=time):
        self.task, self.cloud, self.target = task, cloud, target
        self.journal, self.clock = journal, clock
        self.data = journal.data
        self.evidence = self.data['evidence']
        self.run_id = self.data['binding']['run_id']

    def record(self, key, value):
        self.evidence[key] = value
        self.journal.save()
        return value

    def poll(self, key, read, accept):
        deadlines = self.data['deadlines']
        if key not in deadlines:
            deadlines[key] = self.clock.time() + self.task['timeout']
            self.journal.save()
        monotonic_deadline = self.clock.monotonic() + max(0, deadlines[key] - self.clock.time())
        while True:
            if self.clock.time() >= deadlines[key] or self.clock.monotonic() >= monotonic_deadline:
                raise Incomplete(f'timeout waiting for {key}; deadline is retained for this run-id')
            value = read()
            if self.clock.time() > deadlines[key] or self.clock.monotonic() > monotonic_deadline:
                raise Incomplete(f'timeout while reading {key}')
            if accept(value):
                return value
            remaining = min(deadlines[key] - self.clock.time(), monotonic_deadline - self.clock.monotonic())
            if remaining <= 0:
                raise Incomplete(f'timeout waiting for {key}; deadline is retained for this run-id')
            self.clock.sleep(min(self.task['poll_interval'], remaining))

    def check_host(self, snap, power, enabled, maintenance, nova_state=None):
        node, service, host = snap['node'], snap['service'], snap['ha_host']
        require(node['uuid'] == self.task['node_uuid'] and node['name'] == self.task['host'], 'Ironic host binding changed')
        require(node['power_state'] == power and node['target_power_state'] is None and not node['last_error'],
                'Ironic power state is not settled or has an error')
        require(node['maintenance'] is False, 'Ironic node is in maintenance')
        require(service['host'] == self.task['host'] and service['binary'] == 'nova-compute', 'Nova host binding changed')
        require(service['status'] == ('enabled' if enabled else 'disabled'), 'unexpected Nova enabled status')
        if nova_state:
            require(service['state'] == nova_state, 'unexpected Nova service state')
        require(host['uuid'] == self.task['ha_host_uuid'] and host['name'] == self.task['host']
                and host['failover_segment_id'] == self.task['segment_uuid'], 'Masakari host binding changed')
        require(host['on_maintenance'] is maintenance, 'unexpected Masakari maintenance status')
        if 'baseline' in self.evidence:
            require(service['id'] == self.evidence['baseline']['snapshot']['service']['id'], 'Nova service ID changed')

    def check_vms(self, snap, moved):
        expected = set(self.task['server_ids'])
        require(len(snap['servers']) == len(expected) and {s['id'] for s in snap['servers']} == expected,
                'VM manifest is incomplete')
        for server in snap['servers']:
            require(server['status'] == 'ACTIVE' and server['task_state'] is None, 'VM is not ACTIVE/idle')
            require(server['host'] in (self.task['destination_hosts'] if moved else [self.task['host']]),
                    'VM is on an unexpected compute host')
        require(set(snap['source_ids']) == (set() if moved else expected), 'source VM manifest is not the expected set')
        if moved and 'movement' in self.evidence:
            previous = {s['id']: s['host'] for s in self.evidence['movement']['snapshot']['servers']}
            require(all(previous[s['id']] == s['host'] for s in snap['servers']), 'VM placement changed during host return')

    def preflight(self, persist=True):
        snap = self.cloud.snapshot(self.task)
        self.check_host(snap, 'power on', True, False, 'up')
        self.check_vms(snap, False)
        require({d['host'] for d in snap['destinations']} == set(self.task['destination_hosts']) and
                all(d['status'] == 'enabled' and d['state'] == 'up' for d in snap['destinations']),
                'destination compute services must be enabled/up')
        terminal = {'completed', 'confirmed', 'reverted', 'error', 'failed', 'cancelled', 'canceled'}
        if self.task['scenario'] == 'emergency':
            terminal.add('done')
        require(all(m['status'] in terminal
                    for m in snap['migrations']), 'source has an in-flight migration')
        notifications = self.cloud.notifications(self.task)
        require(all(n['status'] in ('finished', 'failed', 'ignored') for n in notifications), 'source has a pending HA notification')
        target = self.target.inspect()
        require(target['interface'] == self.task['interface'] and target['up'] is True, 'fault interface must be UP')
        require(set(target['domains']) == set(self.task['server_ids']), 'libvirt domains differ from the test VM manifest')
        require(bool(target['machine_id']) and bool(target['mac']), 'target identity is missing')
        baseline = dict(snapshot=snap, target=target,
            notification_ids=[n['notification_uuid'] for n in notifications], taken_at=self.clock.time())
        return self.record('baseline', baseline) if persist else baseline

    def workflow(self, key, name, inputs):
        operations = self.data['operations']
        if key not in operations:
            if key == 'off':
                self.fresh_preflight()
            if key == 'return':
                snap = self.cloud.snapshot(self.task)
                self.check_host(snap, 'power off', False, True,
                                'down' if self.task['scenario'] == 'emergency' else None)
                self.check_vms(snap, True)
            body = dict(id=str(uuid.uuid4()), workflow_name=name, input=inputs,
                        description=f'powerops-stand:{self.run_id}:{key}')
            operations[key] = body
            self.journal.save()  # No POST may precede its durable, client-assigned ID.
            try:
                self.cloud.create(body)
            except Incomplete:
                pass  # GET this ID; never create a second execution after uncertainty.
        body = operations[key]
        require(body['workflow_name'] == name and body['input'] == inputs, 'saved operation contract differs')
        return body

    def execution(self, body):
        result = self.cloud.execution(body['id'])
        if result is None:
            return None
        require(result['id'] == body['id'] and result['workflow_name'] == body['workflow_name'] and
                obj(result['input']) == body['input'] and result['description'] == body['description'],
                'Mistral execution does not match the saved intent')
        if result['state'] in ('ERROR', 'CANCELLED'):
            raise Failed(f"Mistral execution {body['id']} is {result['state']}")
        return result

    def wait_workflow(self, key, body, state):
        def accept(result):
            if result is None:
                return False
            if state == 'PAUSED' and result['state'] == 'SUCCESS':
                raise Failed('return workflow completed without the observed operator gate')
            if state == 'SUCCESS' and result['state'] == 'PAUSED' and key == 'off':
                raise Failed('planned power-off unexpectedly paused')
            return result['state'] == state
        return self.poll(key, lambda: self.execution(body), accept)

    def check_output(self, execution, operation):
        output = obj(execution['output'])
        result = obj(output['result'])
        returning = operation == 'return_to_service'
        require(result['host'] == self.task['host'] and result['operation'] == operation and
                result['power_state'] == ('power on' if returning else 'power off') and
                result['nova_enabled'] is returning and result['masakari_maintenance'] is (not returning) and
                result['stopped_instance_ids'] == [], 'workflow result violates the live-migration/return contract')
        if not returning:
            require(output['stopped_instance_ids'] == [], 'planned workflow stopped VMs instead of migrating')
        return output

    def planned(self):
        body = self.workflow('off', 'power_ops.planned_power_off', dict(host=self.task['host'],
            segment_uuid=self.task['segment_uuid'], instance_policy='live_migrate', allow_hard_off=False))
        execution = self.wait_workflow('off', body, 'SUCCESS')
        self.check_output(execution, 'planned_power_off')
        snap = self.cloud.snapshot(self.task)
        self.check_host(snap, 'power off', False, True)
        self.check_vms(snap, True)
        old = {m['uuid'] for m in self.evidence['baseline']['snapshot']['migrations']}
        migrations = [m for m in snap['migrations'] if m['uuid'] not in old]
        require({m['instance_uuid'] for m in migrations} == set(self.task['server_ids']), 'new migration manifest differs')
        for server in snap['servers']:
            matches = [m for m in migrations if m['instance_uuid'] == server['id']]
            require(len(matches) == 1, 'expected exactly one new migration per VM')
            move = matches[0]
            require(move['migration_type'] == 'live-migration' and move['status'] == 'completed' and
                    move['source_compute'] == self.task['host'] and move['dest_compute'] == server['host'],
                    'live migration did not complete at the observed VM destination')
        return self.record('movement', dict(snapshot=snap, execution=execution, migrations=migrations))

    def emergency(self):
        if 'fault' not in self.data['operations']:
            self.fresh_preflight()
            self.data['operations']['fault'] = dict(run_id=self.run_id, nonce=uuid.uuid4().hex, submitted_at=self.clock.time())
            self.journal.save()
            try:
                submitted = self.record('fault_submission', self.target.fault(
                    'start', self.run_id, nonce=self.data['operations']['fault']['nonce']))
                require(submitted.get('new_submission') is True, 'remote fault run-id already exists or submission is not confirmed')
            except Incomplete:
                pass  # Loss of this very interface may sever SSH before the reply.
        old = set(self.evidence['baseline']['notification_ids'])
        def new_notification():
            items = [n for n in self.cloud.notifications(self.task) if n['notification_uuid'] not in old]
            require(len(items) <= 1, 'multiple new notifications: HA event attribution is ambiguous')
            if not items:
                return None
            item = items[0]
            require(item['source_host_uuid'] == self.task['ha_host_uuid'] and item['type'] == 'COMPUTE_HOST'
                    and obj(item['payload']).get('event') == 'STOPPED', 'new notification is not the requested host failure')
            return item
        if 'notification_id' not in self.evidence:
            notification = self.poll('notification_created', new_notification, lambda n: n is not None)
            self.record('notification_id', notification['notification_uuid'])
        ident = self.evidence['notification_id']
        def finished(item):
            require(item['notification_uuid'] == ident and item['source_host_uuid'] == self.task['ha_host_uuid'],
                    'notification binding changed')
            require(item['status'] not in ('failed', 'ignored'), 'Masakari recovery failed or was ignored')
            return item['status'] == 'finished'
        notification = self.poll('evacuation', lambda: self.cloud.notification(ident), finished)
        moves = self.cloud.vmoves(ident)
        snap = self.cloud.snapshot(self.task)
        self.check_host(snap, 'power off', False, True, 'down')
        self.check_vms(snap, True)
        require(len(moves) == len(self.task['server_ids']) and
                {m['instance_uuid'] for m in moves} == set(self.task['server_ids']), 'VMove manifest differs from test VMs')
        hosts = {s['id']: s['host'] for s in snap['servers']}
        for move in moves:
            require(move['notification_uuid'] == ident and move['source_host'] == self.task['host'] and
                    move['dest_host'] == hosts[move['instance_uuid']] and move['type'] == 'evacuation' and
                    move['status'] == 'succeeded', 'VMove did not succeed for this notification and VM destination')
        details = notification.get('recovery_workflow_details', [])
        fence = [d for d in details if d['name'] == 'IronicFenceTask' and d['state'] == 'SUCCESS']
        if len(fence) != 1:
            raise Incomplete('timestamped IronicFenceTask SUCCESS evidence is required (Masakari persistence + hotfix)')
        progress = fence[0].get('progress_details', [])
        off = [timestamp(p.get('timestamp')) for p in progress
               if p.get('message', '').startswith(f"Ironic confirmed power off for host {self.task['host']!r};")]
        down = [timestamp(p.get('timestamp')) for p in progress
                if p.get('message', '').startswith(f"Nova confirmed disabled/down for fenced host {self.task['host']!r};")]
        if len(off) != 1 or len(down) != 1:
            raise Incomplete('fencing and Nova-down confirmation timestamps are missing or ambiguous')
        require(off[0] <= down[0] and all(down[0] <= timestamp(m['start_time']) <= timestamp(m['end_time']) for m in moves),
                'evacuation began before confirmed fencing/Nova-down')
        # If DOWN's reply was lost, conservatively hold the already fenced host
        # off for another duration; do not assume clocks on separate hosts agree.
        return self.record('movement', dict(snapshot=snap, notification=notification, vmoves=moves,
                                          hold_duration=self.task['duration']))

    def fresh_preflight(self):
        original = self.evidence['baseline']
        # Revalidate immediately before a never-submitted first mutation, also
        # after a process restart. Preserve the original run's ownership evidence.
        fresh = self.preflight(persist=False)
        require(fresh['target'] == original['target'] and fresh['snapshot'] == original['snapshot'] and
                fresh['notification_ids'] == original['notification_ids'], 'preflight changed before first mutation')

    def check_inspection(self, snap, inspection):
        self.check_host(snap, 'power on', False, True, 'up')
        self.check_vms(snap, True)
        self.check_target(inspection)

    def check_target(self, inspection):
        initial = self.evidence['baseline']['target']
        require(inspection['machine_id'] == initial['machine_id'] and
                inspection['interface'] == initial['interface'] and inspection['mac'] == initial['mac'],
                'source machine or interface identity changed')
        require(bool(inspection['boot_id']) and inspection['boot_id'] != initial['boot_id'],
                'source did not complete a new boot after the observed power-off')
        require(inspection['up'] is True and set(initial['addresses']) <= set(inspection['addresses']),
                'source interface/address configuration has not returned')
        require(inspection['domains'] == [], 'stale libvirt domains remain on source; automatic confirmation refused')

    def return_host(self):
        if 'return' not in self.data['operations']:
            # A fresh full hold after process restart is conservative. Only the
            # durable return intent proves that an earlier hold already finished.
            duration = self.evidence['movement'].get('hold_duration', 0)
            started = self.clock.monotonic()
            hold_until = started + duration
            while self.clock.monotonic() < hold_until:
                self.clock.sleep(min(30, hold_until - self.clock.monotonic()))
            self.record('power_off_hold', dict(requested_seconds=duration,
                elapsed_seconds=self.clock.monotonic() - started, completed_at=self.clock.time()))
        body = self.workflow('return', 'power_ops.power_on_and_return', dict(host=self.task['host'],
            segment_uuid=self.task['segment_uuid'], stopped_instance_ids=[]))
        if 'resume' not in self.data['operations']:
            execution = self.wait_workflow('inspection_gate', body, 'PAUSED')
            tasks = self.cloud.tasks(body['id'])
            require(all(t['workflow_execution_id'] == body['id'] for t in tasks), 'task belongs to another workflow')
            require(len([t for t in tasks if t['name'] == 'power_on_for_inspection' and t['state'] == 'SUCCESS']) == 1
                    and len([t for t in tasks if t['name'] == 'operator_inspection_gate' and t['state'] == 'IDLE']) == 1
                    and not any(t['name'] == 'return_to_service' for t in tasks), 'unexpected operator gate task states')
            snap = self.cloud.snapshot(self.task)
            inspection = self.target.inspect()
            self.check_inspection(snap, inspection)
            if self.task['scenario'] == 'emergency':
                nonce = self.data['operations']['fault']['nonce']
                fault = self.target.fault('reconcile', self.run_id, nonce=nonce)
                require(fault['request'] == dict(run_id=self.run_id, interface=self.task['interface'], duration=self.task['duration'], nonce=nonce)
                        and fault.get('down_confirmed_at') is not None, 'actual interface DOWN was not confirmed by the fault worker')
                require(fault['phase'] == 'RESTORED' and not fault.get('observation_error'), 'fault journal/interface is not reconciled')
                require(fault['result'] in ('COMPLETED', 'INTERRUPTED_BY_REBOOT'),
                        'interface fault ended early for a reason other than fencing/reboot')
                baseline = self.evidence['baseline']['target']
                require(fault['identity']['boot_id'] == baseline['boot_id'] and
                        fault['identity']['ifname'] == baseline['interface'] and fault['identity']['address'] == baseline['mac'],
                        'fault journal does not belong to the preflight boot/interface')
                self.record('fault_final', fault)
            # Fresh control-plane read immediately before attestation.
            self.check_inspection(self.cloud.snapshot(self.task), inspection)
            require(self.execution(body)['state'] == 'PAUSED', 'operator gate changed during inspection')
            self.record('inspection', dict(snapshot=snap, target=inspection, tasks=tasks,
                                          execution_id=body['id'], confirmed_at=self.clock.time()))
            resume = dict(state='RUNNING', params={'env': {'stale_domains_checked': True}})
            self.data['operations']['resume'] = dict(execution_id=body['id'], body=resume)
            self.journal.save()
            try:
                self.cloud.resume(body['id'], resume)
            except Incomplete:
                pass  # Never replay PUT. The same execution is observed below.
        final = self.wait_workflow('return_complete', body, 'SUCCESS')
        self.check_output(final, 'return_to_service')
        self.record('return_execution', final)
        snap = self.cloud.snapshot(self.task)
        self.check_host(snap, 'power on', True, False, 'up')
        self.check_vms(snap, True)
        inspection = self.target.inspect()
        self.check_target(inspection)
        self.record('final', dict(snapshot=snap, target=inspection, checked_at=self.clock.time()))

    def run(self):
        if self.data['status'] in ('PASS', 'FAIL'):
            return self.data  # Historical result. A new run requires a new explicit VM placement.
        self.data['status'] = 'RUNNING'
        self.data.pop('error', None)
        self.journal.save()
        try:
            if 'baseline' not in self.evidence:
                self.preflight()
            if 'movement' not in self.evidence:
                (self.emergency if self.task['scenario'] == 'emergency' else self.planned)()
            self.return_host()
            self.data['status'] = 'PASS'
        except Failed as exc:
            self.data.update(status='FAIL', error=str(exc))
        except Incomplete as exc:
            self.data.update(status='INCOMPLETE', error=str(exc))
        except (KeyError, TypeError, ValueError):
            self.data.update(status='INCOMPLETE', error='required API/target field missing or invalid')
        self.journal.save()
        return self.data
