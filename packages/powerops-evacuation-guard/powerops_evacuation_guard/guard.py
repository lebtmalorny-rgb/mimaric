"""Durable per-target and global admission; no leases or automatic unknown release."""
import time
import uuid

from .etcd import (Etcd, GuardBusy, GuardConflict, GuardDenied, GuardDuplicate,
                   GuardUnavailable, number, prefix_end, text)

MAX_PARALLEL = 1024


def canonical(value, name):
    text(value, name, 36)
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except ValueError:
        raise GuardDenied('Invalid ' + name) from None
    return value


def valid_request_id(value):
    text(value, 'request ID', 40)
    if not value.startswith('req-'):
        raise GuardDenied('Invalid request ID')
    canonical(value[4:], 'request ID')
    return value


def bounded(value, name):
    if type(value) is not int or not 1 <= value <= MAX_PARALLEL:
        raise GuardDenied('Invalid ' + name)
    return value


def expected(value):
    if type(value) is not int or not 1 <= value <= 2**63-1:
        raise GuardDenied('Invalid expected revision')
    return value


def audit(actor, reason):
    return {'actor': text(actor, 'actor'), 'reason': text(reason, 'reason', 1024)}


class Guard:
    def __init__(self, endpoint, prefix='/powerops/evacuation/v1', timeout=5.0,
                 ca_file=None, cert_file=None, key_file=None, max_parallel=3, cooldown=5.0):
        text(prefix, 'prefix', 1024)
        if (not prefix.startswith('/') or prefix.endswith('/')
                or any(p in ('', '.', '..') for p in prefix[1:].split('/'))):
            raise GuardDenied('Invalid prefix')
        self.prefix = prefix
        self.max_parallel = bounded(max_parallel, 'max_parallel')
        self.cooldown = number(cooldown, 'cooldown')
        self._etcd = Etcd(endpoint, timeout, ca_file, cert_file, key_file)
        self._timers = {}

    def _key(self, kind, identity=None):
        paths = {'configuration':'metadata', 'intent':'records/intents',
                 'operation':'records/operations', 'request':'requests',
                 'vm':'claims/vms', 'target':'claims/targets', 'slot':'claims/slots'}
        return self.prefix + '/' + paths[kind] + (('/'+str(identity)) if identity is not None else '')

    def _validate(self, value, revision, kind, identity=None):
        base = {'schema', 'kind'}
        fields = {
            'configuration': {'max_parallel', 'cooldown', 'actor', 'reason'},
            'intent': {'attempt_uuid', 'vm_uuid', 'source_host', 'request_id', 'actor',
                       'state', 'migration_uuid', 'observation', 'reason', 'resolution'},
            'operation': {'migration_uuid', 'vm_uuid', 'source_host', 'target_uuid', 'target_host',
                          'owner_uuid', 'request_id', 'attempt_uuid', 'state', 'slot', 'reason',
                          'result', 'resolution', 'recovery'},
            'request': {'attempt_uuid', 'vm_uuid', 'source_host', 'request_id'},
            'vm': {'vm_uuid', 'attempt_uuid', 'migration_uuid'},
            'target': {'target_uuid', 'migration_uuid'},
            'slot': {'slot', 'migration_uuid'},
        }
        try:
            if (set(value) != base | fields[kind] or type(value['schema']) is not int
                    or value['schema'] != 1 or value['kind'] != kind):
                raise GuardDenied('Invalid schema')
            for k in ('vm_uuid', 'target_uuid', 'owner_uuid'):
                if k in value:
                    canonical(value[k], k)
            for k in ('attempt_uuid', 'migration_uuid'):
                if k in value and value[k] is not None:
                    canonical(value[k], k)
            for k in ('source_host', 'target_host', 'actor'):
                if k in value:
                    text(value[k], k)
            if value.get('request_id') is not None:
                valid_request_id(value['request_id'])
            if value.get('reason') is not None:
                text(value['reason'], 'reason', 1024)
            if value.get('resolution') is not None:
                r = value['resolution']
                if not isinstance(r, dict) or set(r) != {'actor', 'reason', 'nova_terminal', 'executors_quiesced'}:
                    raise GuardDenied('Invalid resolution')
                audit(r['actor'], r['reason'])
                self._proof_flags(r['nova_terminal'], r['executors_quiesced'])
            if value.get('recovery') is not None:
                recovery = value['recovery']
                if not isinstance(recovery, dict) or set(recovery) != {'actor', 'reason'}:
                    raise GuardDenied('Invalid recovery')
                audit(recovery['actor'], recovery['reason'])
            if kind == 'configuration':
                audit(value['actor'], value['reason'])
                bounded(value['max_parallel'], 'max_parallel')
                number(value['cooldown'], 'cooldown')
            elif kind == 'intent':
                canonical(value['attempt_uuid'], 'attempt_uuid')
                valid_request_id(value['request_id'])
                if (value['state'] not in ('SUBMITTING', 'BOUND', 'RESOLVED')
                        or value['observation'] not in ('PENDING', 'UNKNOWN')
                        or (value['state'] == 'RESOLVED') != (value['resolution'] is not None)
                        or (value['state'] == 'BOUND') != (value['migration_uuid'] is not None)):
                    raise GuardDenied('Invalid intent state')
            elif kind == 'operation':
                canonical(value['migration_uuid'], 'migration_uuid')
                if value['attempt_uuid'] is not None and value['request_id'] is None:
                    raise GuardDenied('Missing bound request ID')
                if value['result'] is not None and value['state'] not in ('COOLDOWN', 'DONE'):
                    raise GuardDenied('Premature completion proof')
                if value['resolution'] is not None and value['state'] not in ('DENIED', 'COOLDOWN', 'DONE'):
                    raise GuardDenied('Premature resolution proof')
                if value['recovery'] is not None and value['state'] not in ('COOLDOWN', 'DONE'):
                    raise GuardDenied('Premature recovery audit')
                if value['state'] not in ('WAITING', 'RUNNING', 'UNKNOWN', 'COOLDOWN', 'DONE', 'DENIED'):
                    raise GuardDenied('Invalid operation state')
                if value['state'] in ('WAITING', 'DENIED'):
                    if value['slot'] is not None:
                        raise GuardDenied('Invalid waiting slot')
                else:
                    bounded(value['slot'] + 1 if type(value['slot']) is int else None, 'slot')
                if value['result'] is not None:
                    self._completion_proof(value, value['result'])
                if value['state'] in ('COOLDOWN', 'DONE') and value['result'] is None and value['resolution'] is None:
                    raise GuardDenied('Missing terminal proof')
            elif kind == 'request':
                canonical(value['attempt_uuid'], 'attempt_uuid')
                valid_request_id(value['request_id'])
            elif kind == 'vm':
                if value['attempt_uuid'] is None and value['migration_uuid'] is None:
                    raise GuardDenied('Unowned VM claim')
            elif kind == 'target':
                canonical(value['migration_uuid'], 'migration_uuid')
            elif kind == 'slot':
                canonical(value['migration_uuid'], 'migration_uuid')
                bounded(value['slot']+1 if type(value['slot']) is int else None, 'slot')
            field = {'intent':'attempt_uuid', 'operation':'migration_uuid', 'request':'request_id',
                     'vm':'vm_uuid', 'target':'target_uuid', 'slot':'slot'}.get(kind)
            if field and identity is not None and str(value[field]) != str(identity):
                raise GuardDenied('Key identity mismatch')
        except (GuardDenied, TypeError, KeyError, ValueError, OverflowError):
            raise GuardUnavailable('Invalid stored ' + kind) from None
        return dict(value, revision=revision)

    def _read(self, kind, identity=None, required=True):
        item = self._etcd.read(self._key(kind, identity))
        if item is None:
            if required:
                raise GuardUnavailable('Missing ' + kind)
            return None
        return self._validate(*item, kind, identity)

    @staticmethod
    def _value(record):
        return {k:v for k, v in record.items() if k != 'revision'}

    def _compare(self, kind, identity, record):
        return self._etcd.compare(self._key(kind, identity), record['revision'] if record else 0)

    @staticmethod
    def _new(kind, **fields):
        return dict(schema=1, kind=kind, **fields)

    def _write(self, checks, puts, deletes=(), conflict=GuardConflict):
        ops = [self._etcd.put(key, self._value(value)) for key, value in puts]
        ops.extend(self._etcd.delete(key) for key in deletes)
        ok, revision = self._etcd.txn(checks, ops)
        if not ok:
            raise conflict('Guard transaction conflicted')
        return revision

    def configuration(self):
        return self._read('configuration')

    def _configuration(self):
        conf = self.configuration()
        if (conf['max_parallel'] != self.max_parallel or conf['cooldown'] != self.cooldown):
            raise GuardDenied('Local and shared configuration differ')
        return conf

    def _metadata_check(self):
        return self._compare('configuration', None, self._configuration())

    def initialize(self, actor, reason):
        value = self._new('configuration', max_parallel=self.max_parallel,
                          cooldown=self.cooldown, **audit(actor, reason))
        checks = [self._compare('configuration', None, None),
                  self._etcd.compare(self.prefix+'/', end=prefix_end(self.prefix+'/'))]
        rev = self._write(checks, [(self._key('configuration'), value)])
        return dict(value, revision=rev)

    def configure(self, expected_revision, max_parallel, cooldown, actor, reason):
        expected(expected_revision)
        value = self._new('configuration', max_parallel=bounded(max_parallel, 'max_parallel'),
                          cooldown=number(cooldown, 'cooldown'), **audit(actor, reason))
        conf = self.configuration()
        if conf['revision'] != expected_revision:
            raise GuardConflict('Configuration revision changed')
        claims = self.prefix + '/claims/'
        rev = self._write([self._compare('configuration', None, conf),
                           self._etcd.compare(claims, end=prefix_end(claims))],
                          [(self._key('configuration'), value)])
        return dict(value, revision=rev)

    def create_intent(self, attempt_uuid, vm_uuid, source_host, request_id, actor):
        attempt_uuid, vm_uuid = canonical(attempt_uuid, 'attempt_uuid'), canonical(vm_uuid, 'vm_uuid')
        request_id = valid_request_id(request_id)
        text(source_host, 'source_host')
        text(actor, 'actor')
        check = self._metadata_check()
        for kind, identity in (('intent', attempt_uuid), ('vm', vm_uuid), ('request', request_id)):
            if self._read(kind, identity, False):
                raise GuardDuplicate('Submission identity already reserved')
        intent = self._new('intent', attempt_uuid=attempt_uuid, vm_uuid=vm_uuid,
            source_host=source_host, request_id=request_id, actor=actor, state='SUBMITTING',
            migration_uuid=None, observation='PENDING', reason=None, resolution=None)
        index = self._new('request', attempt_uuid=attempt_uuid, vm_uuid=vm_uuid,
                          source_host=source_host, request_id=request_id)
        claim = self._new('vm', vm_uuid=vm_uuid, attempt_uuid=attempt_uuid, migration_uuid=None)
        rev = self._write([check] + [self._compare(k, i, None) for k,i in
            (('intent', attempt_uuid), ('vm', vm_uuid), ('request', request_id))],
            [(self._key('intent', attempt_uuid), intent), (self._key('request', request_id), index),
             (self._key('vm', vm_uuid), claim)], conflict=GuardDuplicate)
        return dict(intent, revision=rev)

    def get_intent(self, attempt_uuid):
        return self._read('intent', canonical(attempt_uuid, 'attempt_uuid'))

    def note_intent_unknown(self, attempt_uuid, reason):
        text(reason, 'reason', 1024)
        check = self._metadata_check()
        intent = self.get_intent(attempt_uuid)
        updated = dict(intent, observation='UNKNOWN', reason=reason)
        rev = self._write([check, self._compare('intent', attempt_uuid, intent)],
                          [(self._key('intent', attempt_uuid), updated)])
        return dict(updated, revision=rev)

    def register(self, migration_uuid, vm_uuid, source_host, target_uuid,
                 target_host, owner_uuid, request_id=None):
        for name, value in (('migration_uuid', migration_uuid), ('vm_uuid', vm_uuid),
                            ('target_uuid', target_uuid), ('owner_uuid', owner_uuid)):
            canonical(value, name)
        text(source_host, 'source_host')
        text(target_host, 'target_host')
        if request_id is not None:
            valid_request_id(request_id)
        checks = [self._metadata_check()]
        if self._read('operation', migration_uuid, False):
            raise GuardDuplicate('Migration already registered')
        checks.append(self._compare('operation', migration_uuid, None))
        claim = self._read('vm', vm_uuid, False)
        index = self._read('request', request_id, False) if request_id else None
        if request_id:
            checks.append(self._compare('request', request_id, index))
        intent, attempt, puts = None, None, []
        if index:
            attempt = index['attempt_uuid']
            intent = self.get_intent(attempt)
            if intent['state'] != 'SUBMITTING':
                raise GuardDuplicate('Intent already bound or resolved')
            if (any(index[k] != intent[k] for k in ('attempt_uuid', 'vm_uuid', 'source_host', 'request_id'))
                    or intent['vm_uuid'] != vm_uuid or intent['source_host'] != source_host
                    or claim is None or claim['attempt_uuid'] != attempt or claim['migration_uuid'] is not None):
                raise GuardDenied('Intent identity does not authorize binding')
            checks.append(self._compare('intent', attempt, intent))
            puts.append((self._key('intent', attempt), dict(intent, state='BOUND', migration_uuid=migration_uuid)))
        elif claim:
            raise GuardDenied('VM already claimed')
        checks.append(self._compare('vm', vm_uuid, claim))
        op = self._new('operation', migration_uuid=migration_uuid, vm_uuid=vm_uuid,
            source_host=source_host, target_uuid=target_uuid, target_host=target_host,
            owner_uuid=owner_uuid, request_id=request_id, attempt_uuid=attempt,
            state='WAITING', slot=None, reason=None, result=None, resolution=None, recovery=None)
        new_claim = self._new('vm', vm_uuid=vm_uuid, attempt_uuid=attempt, migration_uuid=migration_uuid)
        puts.extend([(self._key('operation', migration_uuid), op), (self._key('vm', vm_uuid), new_claim)])
        rev = self._write(checks, puts)
        return dict(op, revision=rev)

    def get_operation(self, migration_uuid):
        return self._read('operation', canonical(migration_uuid, 'migration_uuid'))

    def _owned(self, migration_uuid, owner_uuid, states):
        canonical(owner_uuid, 'owner_uuid')
        op = self.get_operation(migration_uuid)
        if op['owner_uuid'] != owner_uuid:
            raise GuardConflict('Operation owner changed')
        if op['state'] not in states:
            raise GuardDuplicate('Operation cannot execute this transition')
        return op

    def _claims(self, op, admitted=False):
        desired = [('vm', op['vm_uuid'], self._new('vm', vm_uuid=op['vm_uuid'],
                    attempt_uuid=op['attempt_uuid'], migration_uuid=op['migration_uuid']))]
        if admitted:
            desired.extend([
                ('target', op['target_uuid'], self._new('target', target_uuid=op['target_uuid'], migration_uuid=op['migration_uuid'])),
                ('slot', op['slot'], self._new('slot', slot=op['slot'], migration_uuid=op['migration_uuid']))])
        checks, keys = [], []
        for kind, identity, value in desired:
            stored = self._read(kind, identity)
            if self._value(stored) != value:
                raise GuardUnavailable('Inconsistent operation claim')
            checks.append(self._compare(kind, identity, stored))
            keys.append(self._key(kind, identity))
        return checks, keys

    def try_admit(self, migration_uuid, owner_uuid):
        checks = [self._metadata_check()]
        op = self._owned(migration_uuid, owner_uuid, ('WAITING',))
        checks.append(self._compare('operation', migration_uuid, op))
        claim_checks, _ = self._claims(op)
        checks.extend(claim_checks)
        if self._read('target', op['target_uuid'], False):
            raise GuardBusy('Target is occupied')
        slot = next((s for s in range(self.max_parallel) if self._read('slot', s, False) is None), None)
        if slot is None:
            raise GuardBusy('Global capacity is occupied')
        updated = dict(op, state='RUNNING', slot=slot)
        checks.extend([self._compare('target', op['target_uuid'], None), self._compare('slot', slot, None)])
        rev = self._write(checks, [(self._key('operation', migration_uuid), updated),
            (self._key('target', op['target_uuid']), self._new('target', target_uuid=op['target_uuid'], migration_uuid=migration_uuid)),
            (self._key('slot', slot), self._new('slot', slot=slot, migration_uuid=migration_uuid))], conflict=GuardBusy)
        return dict(updated, revision=rev)

    def deny_waiting(self, migration_uuid, owner_uuid, reason):
        text(reason, 'reason', 1024)
        checks = [self._metadata_check()]
        op = self._owned(migration_uuid, owner_uuid, ('WAITING',))
        claim_checks, keys = self._claims(op)
        updated = dict(op, state='DENIED', reason=reason)
        rev = self._write(checks + [self._compare('operation', migration_uuid, op)] + claim_checks,
                          [(self._key('operation', migration_uuid), updated)], keys)
        return dict(updated, revision=rev)

    def mark_unknown(self, migration_uuid, owner_uuid, reason):
        text(reason, 'reason', 1024)
        checks = [self._metadata_check()]
        op = self._owned(migration_uuid, owner_uuid, ('RUNNING', 'UNKNOWN'))
        claims, _ = self._claims(op, True)
        updated = dict(op, state='UNKNOWN', reason=reason)
        rev = self._write(checks + [self._compare('operation', migration_uuid, op)] + claims,
                          [(self._key('operation', migration_uuid), updated)])
        return dict(updated, revision=rev)

    @staticmethod
    def _completion_proof(op, result):
        if (not isinstance(result, dict) or set(result) != {'migration_status', 'vm_uuid', 'target_uuid', 'target_host', 'vm_state', 'task_state'}
                or result['migration_status'] != 'done' or result['vm_state'] not in ('active', 'stopped')
                or result['task_state'] is not None
                or any(result[k] != op[k] for k in ('vm_uuid', 'target_uuid', 'target_host'))):
            raise GuardDenied('Invalid Nova completion proof')

    def _cooldown(self, op, updated, checks):
        claims, _ = self._claims(op, True)
        rev = self._write(checks + [self._compare('operation', op['migration_uuid'], op)] + claims,
                          [(self._key('operation', op['migration_uuid']), updated)])
        self._timers[(op['migration_uuid'], rev)] = time.monotonic()
        return dict(updated, revision=rev)

    def complete(self, migration_uuid, owner_uuid, result):
        checks = [self._metadata_check()]
        op = self._owned(migration_uuid, owner_uuid, ('RUNNING',))
        self._completion_proof(op, result)
        return self._cooldown(op, dict(op, state='COOLDOWN', result=dict(result)), checks)

    def finish_cooldown(self, migration_uuid, owner_uuid):
        checks = [self._metadata_check()]
        op = self._owned(migration_uuid, owner_uuid, ('COOLDOWN',))
        timer = (migration_uuid, op['revision'])
        start = self._timers.get(timer)
        if start is None:
            raise GuardDenied('Cooldown requires exact-revision recovery after restart')
        while True:
            left = self.cooldown - (time.monotonic() - start)
            if left <= 0:
                break
            time.sleep(left)
        claims, keys = self._claims(op, True)
        updated = dict(op, state='DONE')
        rev = self._write(checks + [self._compare('operation', migration_uuid, op)] + claims,
                          [(self._key('operation', migration_uuid), updated)], keys)
        self._timers.pop(timer, None)
        return dict(updated, revision=rev)

    def recover_cooldown(self, migration_uuid, expected_revision, actor, reason):
        expected(expected_revision)
        audit(actor, reason)
        checks = [self._metadata_check()]
        op = self.get_operation(migration_uuid)
        if op['revision'] != expected_revision or op['state'] != 'COOLDOWN':
            raise GuardConflict('Cooldown revision or state changed')
        updated = dict(op, owner_uuid=str(uuid.uuid4()), reason=reason)
        # The actor/reason are retained with the recovery, without fabricating Nova proof.
        updated['recovery'] = audit(actor, reason)
        owned = self._cooldown(op, updated, checks)
        return self.finish_cooldown(migration_uuid, owned['owner_uuid'])

    @staticmethod
    def _proof_flags(nova_terminal, executors_quiesced):
        if nova_terminal is not True or executors_quiesced is not True:
            raise GuardDenied('Explicit terminal and quiescence acknowledgements required')

    def resolve(self, migration_uuid, expected_revision, actor, reason, nova_terminal, executors_quiesced):
        expected(expected_revision)
        self._proof_flags(nova_terminal, executors_quiesced)
        resolution = dict(audit(actor, reason), nova_terminal=True, executors_quiesced=True)
        checks = [self._metadata_check()]
        op = self.get_operation(migration_uuid)
        if op['revision'] != expected_revision or op['state'] not in ('WAITING', 'RUNNING', 'UNKNOWN'):
            raise GuardConflict('Operation revision or state changed')
        updated = dict(op, reason=reason, resolution=resolution, owner_uuid=str(uuid.uuid4()))
        if op['state'] == 'WAITING':
            claims, keys = self._claims(op)
            updated['state'] = 'DENIED'
            rev = self._write(checks + [self._compare('operation', migration_uuid, op)] + claims,
                              [(self._key('operation', migration_uuid), updated)], keys)
            return dict(updated, revision=rev)
        updated['state'] = 'COOLDOWN'
        owned = self._cooldown(op, updated, checks)
        return self.finish_cooldown(migration_uuid, owned['owner_uuid'])

    def resolve_intent(self, attempt_uuid, expected_revision, actor, reason, nova_terminal, executors_quiesced):
        expected(expected_revision)
        self._proof_flags(nova_terminal, executors_quiesced)
        resolution = dict(audit(actor, reason), nova_terminal=True, executors_quiesced=True)
        checks = [self._metadata_check()]
        intent = self.get_intent(attempt_uuid)
        if intent['revision'] != expected_revision or intent['state'] != 'SUBMITTING':
            raise GuardConflict('Intent revision or binding changed')
        index = self._read('request', intent['request_id'])
        if any(index[k] != intent[k] for k in ('attempt_uuid', 'vm_uuid', 'source_host', 'request_id')):
            raise GuardUnavailable('Inconsistent request index')
        claim = self._read('vm', intent['vm_uuid'])
        if claim['attempt_uuid'] != attempt_uuid or claim['migration_uuid'] is not None:
            raise GuardConflict('Intent VM already bound')
        updated = dict(intent, state='RESOLVED', reason=reason, resolution=resolution)
        rev = self._write(checks + [self._compare('intent', attempt_uuid, intent),
            self._compare('request', intent['request_id'], index), self._compare('vm', intent['vm_uuid'], claim)],
            [(self._key('intent', attempt_uuid), updated)], [self._key('vm', intent['vm_uuid'])])
        return dict(updated, revision=rev)

    def status(self, limit=100, cursor=None):
        bounded(limit, 'limit')
        configuration = self.configuration()
        prefix = self.prefix + '/records/'
        start = prefix
        if cursor is not None:
            text(cursor, 'cursor', 2048)
            if not cursor.startswith(prefix):
                raise GuardDenied('Invalid cursor namespace')
            start = cursor + '\0'
        rows, more, read_revision = self._etcd.range(start, prefix_end(prefix), limit)
        records = []
        for key, value, record_revision in rows:
            suffix = key[len(prefix):].split('/')
            if len(suffix) != 2 or suffix[0] not in ('intents', 'operations'):
                raise GuardUnavailable('Invalid status key')
            kind = 'intent' if suffix[0] == 'intents' else 'operation'
            records.append(self._validate(value, record_revision, kind, suffix[1]))
        return {'revision': read_revision, 'configuration': configuration, 'configuration_matches':
                configuration['max_parallel'] == self.max_parallel and configuration['cooldown'] == self.cooldown,
                'records': records, 'cursor': rows[-1][0] if more else None}
