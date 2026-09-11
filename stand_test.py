#!/usr/bin/env python3.11
"""Python 3.11 PowerOps stand acceptance runner: one scenario per durable run."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import uuid

from ansible_target import Target
from openstack_probe import Probe
from remote_fault import ID_PATTERN, locked, validate
from scenario_runner import Failed, Incomplete, Journal, Runner


def load_task(path, args):
    task = json.loads(path.read_text())
    allowed = {'scenario','host','inventory_host','inventory','globals','vault_password_file',
               'interface','interface_var','duration','server_ids','destination_hosts','node_uuid',
               'segment_uuid','ha_host_uuid','timeout','poll_interval','cloud','region_name',
               'libvirt','become','remote_python'}
    if not isinstance(task, dict) or set(task) - allowed:
        raise ValueError('unknown task fields; credentials belong in clouds.yaml/Ansible inventory/Vault')
    for key in ('host','inventory','globals','interface','duration'):
        value = getattr(args, key, None)
        if value is not None:
            task[key] = str(Path(value).expanduser().resolve()) if key in ('inventory','globals') else value
    if getattr(args, 'interface', None):
        task.pop('interface_var', None)
    if task.get('scenario') not in ('emergency','planned'):
        raise ValueError('scenario must be emergency or planned')
    task.setdefault('duration', 300)
    task.setdefault('timeout', 1800)
    task.setdefault('poll_interval', 5)
    task.setdefault('inventory_host', task.get('host'))
    task.setdefault('become', True)
    task.setdefault('remote_python', 'python3.11')
    for key in ('host','inventory_host'):
        if not isinstance(task.get(key), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,252}', task[key]):
            raise ValueError(f'{key} must be one explicit host name')
    if type(task['become']) is not bool or not re.fullmatch(r'[A-Za-z0-9/][A-Za-z0-9_./-]*', task['remote_python']):
        raise ValueError('invalid become/remote_python')
    for key in ('node_uuid','segment_uuid','ha_host_uuid'):
        task[key] = str(uuid.UUID(task[key]))
    servers = task['server_ids']
    if not isinstance(servers, list) or not servers or len(set(servers)) != len(servers):
        raise ValueError('server_ids must explicitly list unique existing test VMs')
    task['server_ids'] = sorted(str(uuid.UUID(item)) for item in servers)
    hosts = task['destination_hosts']
    if (not isinstance(hosts, list) or not hosts or len(set(hosts)) != len(hosts) or task['host'] in hosts
            or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,252}', host) for host in hosts)):
        raise ValueError('destination_hosts must list other explicit compute hosts')
    task['destination_hosts'] = sorted(hosts)
    if bool(task.get('interface')) == bool(task.get('interface_var')):
        raise ValueError('specify exactly one of interface or interface_var')
    if task.get('interface_var') and task['interface_var'] not in ('network_interface','tunnel_interface','storage_interface'):
        raise ValueError('interface_var must be network_interface, tunnel_interface or storage_interface')
    validate(dict(run_id=args.run_id, interface=task.get('interface','placeholder'), duration=task['duration']))
    if type(task['timeout']) is not int or not 30 <= task['timeout'] <= 14400:
        raise ValueError('timeout must be 30..14400 seconds per stage')
    if type(task['poll_interval']) is not int or not 1 <= task['poll_interval'] <= 30:
        raise ValueError('poll_interval must be 1..30 seconds')
    libvirt = task['libvirt']
    if not isinstance(libvirt, dict) or set(libvirt) - {'backend','container'} or libvirt.get('backend') not in ('host','docker','podman'):
        raise ValueError('libvirt.backend must be host, docker or podman')
    if libvirt['backend'] != 'host' and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', libvirt.get('container','')):
        raise ValueError('an explicit libvirt container name is required')
    digests = {}
    for key in ('inventory','globals','vault_password_file'):
        if key not in task:
            if key == 'inventory':
                raise ValueError('inventory is required')
            continue
        value = Path(task[key]).expanduser()
        value = (path.parent / value).resolve() if not value.is_absolute() else value.resolve()
        if not value.is_file():
            raise ValueError(f'{key} must be an existing file')
        task[key] = str(value)
        if key != 'vault_password_file':
            digests[key] = hashlib.sha256(value.read_bytes()).hexdigest()
    task['input_sha256'] = digests
    return task


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('plan','preflight','run','status','report'))
    p.add_argument('--task', type=Path, help='JSON task; paths inside it are relative to this file')
    p.add_argument('--run-id', required=True)
    p.add_argument('--state-dir', type=Path, default=Path('artifacts/stand-tests'))
    p.add_argument('--execute', action='store_true', help='allow real outage, migrations, power operations and automatic operator confirmation')
    p.add_argument('--host', help='Nova compute host; inventory_host in task may select a different inventory alias')
    p.add_argument('--inventory')
    p.add_argument('--globals')
    p.add_argument('--interface')
    p.add_argument('--duration', type=int, help='fault duration in seconds; default 300')
    return p


def holds_source(saved, task, identity):
    binding = saved['binding']
    return (bool(saved['operations']) and saved['status'] != 'PASS'
            and binding['task']['host'] == task['host']
            and binding['identity']['endpoints']['baremetal'] == identity['endpoints']['baremetal'])


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if not re.fullmatch(ID_PATTERN, args.run_id):
        p.error('invalid run-id')
    try:
        path = args.state_dir / (args.run_id + '.json')
        if args.action in ('status','report'):
            data = json.loads(path.read_text())
        else:
            if args.task is None:
                p.error('--task is required')
            task = load_task(args.task.resolve(), args)
            if args.action == 'plan' or (args.action == 'run' and not args.execute):
                print(json.dumps(dict(status='PLAN', task=task, automatic_operator_confirmation=True,
                    note='No Ansible/API calls. run --execute performs real operations.'), indent=2, ensure_ascii=False))
                return 0
            with locked(args.state_dir):
                target = Target(task)
                task['interface'] = target.resolve_interface()
                validate(dict(run_id=args.run_id, interface=task['interface'], duration=task['duration']))
                cloud, identity = Probe.connect(task)
                # All invocations sharing this state-dir are serialized. Failed or
                # incomplete runs continue to hold their source for reconciliation.
                for other in args.state_dir.glob('*.json'):
                    if other == path:
                        continue
                    saved = json.loads(other.read_text())
                    if holds_source(saved, task, identity):
                        raise Failed('another unfinished run owns this source; reconcile its run-id first')
                journal = Journal(path, task, args.run_id, identity)
                runner = Runner(task, cloud, target, journal)
                if args.action == 'preflight':
                    if journal.data['operations']:
                        raise Failed('preflight cannot overwrite a run that already has mutation intents')
                    runner.preflight()
                    journal.data['status'] = 'PREFLIGHT'
                    journal.save()
                    data = journal.data
                else:
                    data = runner.run()
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0 if data['status'] in ('PASS','PREFLIGHT') else (3 if data['status'] == 'INCOMPLETE' else 2)
    except (Failed, Incomplete, OSError, ValueError, KeyError, TypeError) as exc:
        message = str(exc) if isinstance(exc, (Failed, Incomplete, ValueError)) else 'invalid configuration, journal or inaccessible local file'
        print(json.dumps(dict(status='INCOMPLETE', error=message), ensure_ascii=False))
        return 3


if __name__ == '__main__':
    if sys.version_info < (3, 11):
        raise SystemExit('Python 3.11+ is required')
    raise SystemExit(main())
