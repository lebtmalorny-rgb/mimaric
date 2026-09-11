"""Durable, single-host firewall transactions. No Ansible or network imports.

The adapter owns exactly one policy. Every single-rule write is journalled
before execution, so a lost reply is distinguishable from foreign changes.
"""
from contextlib import contextmanager
import copy
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time
import uuid


class TransactionError(ValueError):
    pass


class Clock:
    @property
    def boot_id(self):
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip()

    def monotonic(self):
        return time.monotonic()


def _private(path, directory=False):
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise TransactionError('UNSAFE_STATE_PATH')


def _read(path):
    _private(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        data = stream.read(4194305)
    if len(data) > 4194304:
        raise TransactionError('STATE_TOO_LARGE')
    try:
        return json.loads(data)
    except (ValueError, TypeError):
        raise TransactionError('STATE_CORRUPT') from None


def _save(path, data):
    _private(path.parent, directory=True)
    if path.exists() or path.is_symlink():
        _private(path)
    encoded = json.dumps(data, sort_keys=True, allow_nan=False).encode()
    if len(encoded) > 4194304:
        raise TransactionError('STATE_TOO_LARGE')
    temporary = path.parent / ('.write-' + str(uuid.uuid4()))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        folder = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(folder)
        finally:
            os.close(folder)
    finally:
        if temporary.exists():
            temporary.unlink()


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value):
        raise TransactionError('INVALID_TRANSACTION_ID')
    return value


class TransactionManager:
    def __init__(self, root, adapter, clock=None, watchdog_ready=None):
        self.root = Path(root)
        self.adapter = adapter
        self.clock = clock or Clock()
        self.watchdog_ready = watchdog_ready or (lambda: False)

    @contextmanager
    def _lock(self, create=False):
        if create:
            self.root.mkdir(mode=0o700, exist_ok=True)
        if not self.root.exists():
            raise TransactionError('NOT_INITIALIZED')
        _private(self.root, directory=True)
        transactions = self.root / 'transactions'
        if create:
            transactions.mkdir(mode=0o700, exist_ok=True)
        _private(transactions, directory=True)
        fd = os.open(self.root / 'lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            _private(self.root / 'lock')
            until = time.monotonic() + 5
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= until:
                        raise TransactionError('TRANSACTION_BUSY') from None
                    time.sleep(0.05)
            yield
        finally:
            os.close(fd)

    def _current(self):
        pointer = self.root / 'current.json'
        if not pointer.exists() and not pointer.is_symlink():
            return None
        return _read(self.root / 'transactions' / (_id(_read(pointer)['id']) + '.json'))

    def _load(self, txid):
        record = self._current()
        if not record or record['id'] != _id(txid):
            raise TransactionError('STALE_TRANSACTION')
        return record

    def _store(self, record):
        _save(self.root / 'transactions' / (_id(record['id']) + '.json'), record)

    @staticmethod
    def _result(record, changed=False):
        return {key: record[key] for key in ('id', 'plan_id', 'state', 'nonce')} | {'changed': changed}

    def _deadline(self, record, reserve=0):
        if (record['boot_id'] != self.clock.boot_id or
                self.clock.monotonic() + reserve >= record['deadline']):
            raise TransactionError('TRANSACTION_EXPIRED')

    def _reconcile(self, record, rollback=False):
        actual = self.adapter.snapshot()
        expected = record['expected']
        pending = record.get('pending')
        known = [expected]
        if pending:
            known.append(pending)
        if rollback:
            # A daemon reload loads permanent into runtime, even in the middle
            # of persistence. Accept only this exact, journal-derived recovery
            # state; arbitrary changes to our rules are still not overwritten.
            for state in known[:]:
                reloaded = copy.deepcopy(state)
                reloaded['runtime'] = state['permanent'][:]
                known.append(reloaded)
        # Other policy changes stop forward progress. Recovery never writes
        # other policies, and must still undo our own restrictions afterwards.
        if not rollback and actual['foreign'] != expected['foreign']:
            raise TransactionError('FOREIGN_FIREWALL_DRIFT')
        if not any(all(actual[a] == state[a] for a in ('runtime', 'permanent')) for state in known):
            raise TransactionError('OWN_POLICY_DRIFT')
        record['expected'] = actual
        record['pending'] = None
        self._store(record)

    def _replace(self, record, area, rules, rollback=False):
        self._reconcile(record, rollback=rollback)
        target = sorted(set(rules))
        current = record['expected'][area]
        operations = [('add', r) for r in target if r not in current]
        # Remove the terminal deny first during rollback to an empty policy.
        operations += [('remove', r) for r in reversed(current) if r not in target]
        for operation, rule in operations:
            if not rollback:
                self._deadline(record, reserve=30)
            self._reconcile(record, rollback=rollback)
            after = copy.deepcopy(record['expected'])
            if operation == 'add':
                after[area].append(rule)
            else:
                after[area].remove(rule)
            after[area].sort()
            record['pending'] = after
            self._store(record)
            self.adapter.change(area, operation, rule)
            self._reconcile(record, rollback=rollback)
            if record['expected'][area] != after[area]:
                raise TransactionError('FIREWALL_READBACK_MISMATCH')
        if self.adapter.snapshot()[area] != target:
            raise TransactionError('FIREWALL_READBACK_MISMATCH')

    def begin(self, plan):
        port = plan.get('ssh_port')
        rules = plan.get('rules')
        checks = plan.get('required_checks')
        timeout = plan.get('rollback_timeout')
        if (type(port) is not int or not 1 <= port <= 65535 or
                type(timeout) is not int or not 60 <= timeout <= 900 or
                not isinstance(rules, list) or not rules or len(rules) > 4096 or
                not all(isinstance(r, str) and 0 < len(r) <= 2048 for r in rules) or
                f'rule priority="-30000" port port="{port}" protocol="tcp" accept' not in rules or
                not isinstance(checks, list) or 'ssh-fresh' not in checks or
                not all(isinstance(c, str) and re.fullmatch(r'[a-zA-Z0-9_.:-]{1,128}', c) for c in checks) or
                not re.fullmatch(r'[0-9a-f]{64}', str(plan.get('plan_id', '')))):
            raise TransactionError('INVALID_APPLY_PLAN')
        if not self.watchdog_ready():
            raise TransactionError('ROLLBACK_WATCHDOG_NOT_READY')
        snapshot = self.adapter.snapshot()
        if snapshot != plan.get('expected'):
            raise TransactionError('STALE_FIREWALL_PLAN')
        with self._lock(create=True):
            previous = self._current()
            if previous and previous['state'] not in ('COMMITTED', 'ROLLED_BACK'):
                raise TransactionError('TRANSACTION_ACTIVE')
            snapshot = self.adapter.snapshot()
            if snapshot != plan['expected']:
                raise TransactionError('STALE_FIREWALL_PLAN')
            rules = sorted(set(rules))
            if (previous and previous['state'] == 'COMMITTED' and
                    snapshot['runtime'] == snapshot['permanent'] == rules):
                return self._result(previous)
            record = {'id': str(uuid.uuid4()), 'plan_id': plan['plan_id'],
                      'host': plan['host'], 'state': 'ARMED', 'nonce': secrets.token_hex(24),
                      'boot_id': self.clock.boot_id, 'deadline': self.clock.monotonic() + timeout,
                      'before': snapshot, 'expected': copy.deepcopy(snapshot), 'pending': None,
                      'rules': rules, 'required_checks': sorted(set(checks)),
                      'boot_image': plan.get('boot_image')}
            self._store(record)
            _save(self.root / 'current.json', {'id': record['id']})
            return self._result(record, changed=True)

    def apply_runtime(self, txid):
        _id(txid)
        with self._lock():
            record = self._load(txid)
            if record['state'] != 'ARMED':
                raise TransactionError('INVALID_TRANSACTION_STATE')
            self._deadline(record, reserve=30)
            if not self.watchdog_ready():
                raise TransactionError('ROLLBACK_WATCHDOG_NOT_READY')
            self._replace(record, 'runtime', record['rules'])
            record['state'] = 'RUNTIME_APPLIED'
            self._store(record)
            return self._result(record, changed=True)

    def verify(self, txid, nonce, checks):
        _id(txid)
        with self._lock():
            record = self._load(txid)
            self._deadline(record, reserve=30)
            if (record['state'] != 'RUNTIME_APPLIED' or nonce != record['nonce'] or
                    not isinstance(checks, list) or sorted(checks) != record['required_checks']):
                raise TransactionError('VERIFICATION_INCOMPLETE')
            self._reconcile(record)
            record['state'] = 'VERIFIED'
            self._store(record)
            return self._result(record, changed=True)

    def commit(self, txid):
        _id(txid)
        with self._lock():
            record = self._load(txid)
            self._deadline(record, reserve=30)
            if record['state'] != 'VERIFIED':
                raise TransactionError('VERIFICATION_REQUIRED')
            if not self.watchdog_ready():
                raise TransactionError('ROLLBACK_WATCHDOG_NOT_READY')
            record['state'] = 'PERSISTING'
            self._store(record)
            self._replace(record, 'permanent', record['rules'])
            self._deadline(record)
            record['state'] = 'COMMITTED'
            self._store(record)
            return self._result(record, changed=True)

    def _rollback(self, record):
        if record['state'] == 'ROLLED_BACK':
            return self._result(record)
        self._reconcile(record, rollback=True)
        record['state'] = 'ROLLING_BACK'
        self._store(record)
        self._replace(record, 'runtime', record['before']['runtime'], rollback=True)
        self._replace(record, 'permanent', record['before']['permanent'], rollback=True)
        record['state'] = 'ROLLED_BACK'
        self._store(record)
        return self._result(record, changed=True)

    def rollback(self, txid):
        _id(txid)
        with self._lock():
            return self._rollback(self._load(txid))

    def recover_expired(self):
        if not self.root.exists():
            return {'changed': False, 'state': 'IDLE'}
        with self._lock():
            record = self._current()
            if not record or record['state'] in ('COMMITTED', 'ROLLED_BACK'):
                return {'changed': False, 'state': 'IDLE'}
            if record['boot_id'] == self.clock.boot_id and self.clock.monotonic() < record['deadline']:
                return self._result(record)
            return self._rollback(record)

    def status(self):
        if not self.root.exists():
            return {'changed': False, 'state': 'IDLE'}
        with self._lock():
            record = self._current()
            return self._result(record) if record else {'changed': False, 'state': 'IDLE'}
