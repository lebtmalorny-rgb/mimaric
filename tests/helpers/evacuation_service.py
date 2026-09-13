"""Composed-test adapter. Real helpers/Guard; synthetic Nova DB and rebuild.

Never run against a cloud. The parent supplies a disposable loopback namespace.
MacOS lacks Linux capability symbols: imports are shimmed, calls fail loudly.
"""
import sys
import eventlet
eventlet.monkey_patch()

import json
import os
from pathlib import Path
import time
import traceback
from types import SimpleNamespace
from unittest import mock

SERVICE = sys.argv[1]
DIRECTORY = Path(os.environ['EVAC_DIRECTORY'])
REQUEST = json.loads(os.environ['EVAC_REQUEST'])


def configure(conf):
    conf(args=[], default_config_files=[])
    for name, value in dict(enabled=True, endpoint=os.environ['EVAC_ENDPOINT'],
                            prefix=os.environ['EVAC_PREFIX'], cooldown=1.2,
                            poll_interval=.025, admission_timeout=(.4 if REQUEST.get('mode') == 'timeout' else 20)).items():
        conf.set_override(name, value, group='powerops_evacuation_guard')


def masakari():
    from masakari import conf, context
    from masakari.powerops.evacuation import Attempt
    configure(conf.CONF)
    attempts = {}
    for line in sys.stdin:
        request = json.loads(line)
        try:
            if request['command'] == 'reserve':
                attempt = Attempt(context.RequestContext(),
                    SimpleNamespace(instance_uuid=request['vm_uuid'], source_host='source'),
                    lambda: True, lambda: None)
                attempt.reserve()
                attempt.submitted = True
                attempts[attempt.uuid] = attempt
                output = dict(attempt_uuid=attempt.uuid, request_id=attempt.context.global_request_id)
            else:
                output = dict(confirmed=attempts[request['attempt_uuid']].confirmed(
                    request['target_host'], 'active'))
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            output = dict(error=type(error).__name__)
        temporary = DIRECTORY / 'masakari-response.tmp'
        temporary.write_text(json.dumps(output))
        temporary.rename(DIRECTORY / 'masakari-response.json')


def nova():
    if sys.platform == 'darwin':
        import cffi
        original = cffi.FFI.dlopen
        class LinuxSymbols:
            def __init__(self, library):
                self.library = library
            def __getattr__(self, name):
                if name in {'prctl', 'capget', 'capset'}:
                    def unavailable(*args, **kwargs):
                        raise AssertionError('Linux syscall called in macOS test: ' + name)
                    return unavailable
                return getattr(self.library, name)
        def dlopen(ffi, name, *args, **kwargs):
            library = original(ffi, name, *args, **kwargs)
            return LinuxSymbols(library) if name is None else library
        with mock.patch.object(cffi.FFI, 'dlopen', dlopen):
            import oslo_privsep.capabilities
    from nova import context, objects
    from nova.compute import powerops_evacuation as helper
    objects.register_all()
    configure(helper.CONF)
    r = REQUEST
    # Model complete fields consumed at the production helper DB boundary.
    class Record(SimpleNamespace):
        def obj_attr_is_set(self, name):
            return hasattr(self, name)
    node = Record(uuid=r['target_uuid'], host=r['target_host'],
                  hypervisor_hostname='node-' + r['target_uuid'], id=17)
    migration = Record(uuid=r['migration_uuid'], instance_uuid=r['vm_uuid'],
        migration_type='evacuation', source_compute='source', source_node='source-node',
        dest_compute=None, dest_node=None, dest_compute_id=None, status='accepted')
    instance = Record(uuid=r['vm_uuid'], host='source', node='source-node',
                      task_state='rebuilding', vm_state='active', compute_id=1)
    executed = False
    @helper.guard_rebuild
    def rebuild(**kwargs):
        nonlocal executed
        executed = True
        (DIRECTORY / (r['migration_uuid'] + '.admitted')).touch()
        if r['mode'] == 'unknown':
            raise RuntimeError('synthetic external rebuild failure')
        release = DIRECTORY / (r['migration_uuid'] + '.release')
        deadline = time.monotonic() + 60
        while not release.exists():
            if time.monotonic() >= deadline:
                raise RuntimeError('test barrier timeout')
            time.sleep(.025)
        migration.status = 'done'
        migration.dest_compute = node.host
        migration.dest_node = node.hypervisor_hostname
        migration.dest_compute_id = node.id
        instance.host = node.host
        instance.node = node.hypervisor_hostname
        instance.compute_id = node.id
        instance.task_state = None
        return 'synthetic rebuild completed normally'
    ctx = context.RequestContext(global_request_id=r['request_id'])
    # Only external object lookups and rebuild body are fake, never helper,
    # Guard configuration, clocks, claims, proof checks, or ownership methods.
    with mock.patch.object(objects.ComputeNode, 'get_by_host_and_nodename', return_value=node), \
         mock.patch.object(objects.Migration, 'get_by_uuid', return_value=migration), \
         mock.patch.object(objects.Instance, 'get_by_uuid', return_value=instance):
        try:
            rebuild(SimpleNamespace(host=node.host), ctx, instance, None, None,
                    [], None, {}, [], True, False, False, migration,
                    node.hypervisor_hostname, {}, None, [], None, None)
            output = dict(executed=executed)
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            output = dict(executed=executed, error=type(error).__name__)
    print(json.dumps(output))


if SERVICE == 'masakari':
    masakari()
elif SERVICE == 'nova':
    nova()
else:
    raise ValueError('Unknown service')
