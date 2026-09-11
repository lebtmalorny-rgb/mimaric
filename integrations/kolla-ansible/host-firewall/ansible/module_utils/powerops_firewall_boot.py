"""Restore the exact owned permanent XML before firewalld starts on a new boot."""
import base64
import copy
import os
import stat
import tempfile

try:
    from ansible.module_utils.powerops_firewall_transaction import TransactionManager, TransactionError
except ImportError:
    from powerops_firewall_transaction import TransactionManager, TransactionError


def read_policy_file(path):
    for target, directory in ((path.parent, True), (path, False)):
        info = target.lstat()
        if (info.st_uid != os.geteuid() or info.st_mode & 0o022 or
                not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
            raise TransactionError('UNSAFE_POLICY_FILE')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        data = stream.read(1048577)
    if len(data) > 1048576:
        raise TransactionError('POLICY_FILE_TOO_LARGE')
    return data


def restore(root, path, owner, read_settings, boot_id):
    manager = TransactionManager(root, None)
    if not (root / 'current.json').exists():
        return {'changed': False, 'state': 'IDLE'}
    with manager._lock():
        record = manager._current()
        if record['state'] in ('COMMITTED', 'ROLLED_BACK') or record['boot_id'] == boot_id:
            return {'changed': False, 'state': 'IDLE'}
        read_policy_file(path)
        required = {'description': 'kolla-host-firewall:' + owner, 'target': 'CONTINUE',
                    'priority': -500, 'ingress_zones': ['ANY'], 'egress_zones': ['HOST']}
        try:
            settings = read_settings()
        except Exception:
            # firewalld 1.3.4 writes XML with truncate+write. A private durable
            # WAL entry for a permanent write is the ownership evidence if that
            # exact file is torn. No such write intent => no automatic overwrite.
            pending = record.get('pending')
            if (record['state'] not in ('PERSISTING', 'ROLLING_BACK') or not pending or
                    pending['runtime'] != record['expected']['runtime'] or
                    pending['permanent'] == record['expected']['permanent']):
                raise TransactionError('BOOT_XML_CORRUPT_WITHOUT_WRITE_INTENT') from None
            settings = dict(required, rich_rules=record['expected']['permanent'])
        if any(settings.get(k) != value for k, value in required.items()):
            raise TransactionError('BOOT_POLICY_OWNERSHIP_CONFLICT')
        extra = {key: value for key, value in settings.items()
                 if key not in set(required) | {'rich_rules'} and value}
        if extra:
            raise TransactionError('BOOT_POLICY_SETTINGS_CONFLICT')
        known = [record['before']['permanent'], record['expected']['permanent']]
        if record.get('pending'):
            known.append(record['pending']['permanent'])
        if sorted(settings.get('rich_rules', [])) not in known:
            raise TransactionError('BOOT_POLICY_DRIFT')
        original = base64.b64decode(record['boot_image'], validate=True)
        if not original or len(original) > 1048576:
            raise TransactionError('BOOT_IMAGE_INVALID')
        # Current/pending/before remain durable until the atomic restore is on
        # disk. A second crash can repeat this operation without losing evidence.
        fd, temporary = tempfile.mkstemp(prefix='.kolla-restore-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(original)
                os.fchmod(stream.fileno(), 0o644)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        record['expected'] = copy.deepcopy(record['before'])
        # firewalld will initially load restored permanent, not old runtime.
        record['expected']['runtime'] = record['before']['permanent'][:]
        record['pending'] = None
        record['state'] = 'BOOT_RESTORED'
        manager._store(record)
        return {'changed': True, 'state': 'BOOT_RESTORED'}
