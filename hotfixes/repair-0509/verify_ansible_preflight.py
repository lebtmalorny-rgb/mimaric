#!/usr/bin/env python3
"""Exercise the supplied Kolla PowerOps gates with local Ansible only.

Usage: python review_ansible_preflight_0509.py KOLLA_ANSIBLE_ROOT

Requires PyYAML and ansible-playbook in this Python environment. Source files
are read only. Generated inventory, sanitized task copies, events and logs go
to a new temporary directory. No source deployment, container, API, database,
or reconciliation command is executed. Only guard/import/loop/delegation/
async semantics are retained from the supplied tasks; poll is reduced to 1s.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import yaml


HOSTS = ['controller-1', 'controller-2', 'controller-3']
CONTAINERS = ['mistral_api', 'mistral_engine', 'mistral_executor']


def emit(arguments):
    event_file, kind, host, container, fail_host = arguments
    event = {'kind': kind, 'host': host, 'container': container,
             'failed': kind == 'CHECK' and host == fail_host}
    fd = os.open(event_file, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(fd, (json.dumps(event) + '\n').encode())
    finally:
        os.close(fd)
    return int(event['failed'])


def marker(event_file, kind, host, container='', fail_host=''):
    return {'argv': [sys.executable, str(Path(__file__).resolve()), '--emit',
                     str(event_file), kind, host, container, fail_host]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kolla_root', type=Path)
    args = parser.parse_args()
    root = args.kolla_root.resolve()
    task_dir = root / 'ansible/roles/mistral/tasks'
    source_paths = [task_dir / 'deploy.yml', task_dir / 'powerops.yml']
    deploy, phase = [yaml.safe_load(path.read_text()) for path in source_paths]
    guard = copy.deepcopy(next(task for task in deploy if task.get('name') ==
                               'Verify selected Mistral hosts completed deploy'))
    phase_import = copy.deepcopy(next(task for task in deploy if
                                      task.get('import_tasks') == 'powerops.yml'))
    check = copy.deepcopy(next(task for task in phase if task.get('name') ==
                               'Verify PowerOps Mistral action entry points'))
    populate = copy.deepcopy(next(task for task in phase if task.get('name') ==
                                  'Populate Mistral action definitions'))
    assert check['run_once'] is True and check['any_errors_fatal'] is True
    assert check['delegate_to'] == '{{ item.1 }}'
    assert 'mistral.cmd.powerops_check' in check['ansible.builtin.command']
    assert 'populate' in populate['ansible.builtin.command']
    output = Path(tempfile.mkdtemp(prefix='powerops-0509-ansible-probe-', dir='/tmp'))
    print(json.dumps({'output': str(output)}), flush=True)
    config_path = output / 'ansible.cfg'
    config_path.write_text('[defaults]\nhost_key_checking = False\n')
    inventory = {'all': {'children': {group: {'hosts': {host: {} for host in HOSTS}}
                  for group in ['mistral-api', 'mistral-engine', 'mistral-executor']}}}
    inventory_path = output / 'inventory.yml'
    inventory_path.write_text(yaml.safe_dump(inventory, sort_keys=False))
    ansible = Path(sys.executable).parent / 'ansible-playbook'
    scenarios = [
        ('healthy-serial0', 0, None, '', False),
        ('healthy-serial1', 1, None, '', False),
        ('third-check-fails-serial0', 0, None, HOSTS[-1], False),
        ('third-check-fails-serial1', 1, None, HOSTS[-1], False),
        ('limit-one-still-checks-nine', 1, HOSTS[1], '', False),
        ('limit-one-third-check-fails', 1, HOSTS[1], HOSTS[-1], False),
        ('last-selected-deploy-fails-serial0', 0, None, '', True),
        ('last-selected-deploy-fails-serial1', 1, None, '', True),
    ]
    results = []
    for name, serial, limit, fail_host, deploy_fail in scenarios:
        case_dir = output / name
        case_dir.mkdir()
        events_path = case_dir / 'events.jsonl'
        case_check = copy.deepcopy(check)
        case_check['become'] = False
        case_check['poll'] = 1
        case_check['ansible.builtin.command'] = marker(
            events_path, 'CHECK', '{{ item.1 }}', '{{ item.0.container }}', fail_host)
        case_populate = copy.deepcopy(populate)
        case_populate['become'] = False
        case_populate['ansible.builtin.command'] = marker(events_path, 'POPULATE',
                                                        '{{ inventory_hostname }}')
        phase_path = case_dir / 'powerops.yml'
        phase_path.write_text(yaml.safe_dump([case_check, case_populate], sort_keys=False))
        case_import = copy.deepcopy(phase_import)
        case_import['import_tasks'] = str(phase_path)
        play = {
            'name': name, 'hosts': 'all', 'gather_facts': False,
            'connection': 'local', 'serial': serial,
            'vars': {'enable_powerops': True, 'probe_deploy_fail': deploy_fail,
                     'ansible_remote_tmp': str(case_dir / 'remote'),
                     'ansible_async_dir': str(case_dir / 'async'),
                     'ansible_python_interpreter': sys.executable},
            'tasks': [
                {'name': 'Inject selected host deployment failure',
                 'ansible.builtin.fail': {'msg': 'safe local deployment failure'},
                 'when': ["probe_deploy_fail | bool", "inventory_hostname == 'controller-3'"]},
                {'name': 'Record completed local deployment',
                 'ansible.builtin.command': marker(events_path, 'DEPLOY', '{{ inventory_hostname }}'),
                 'changed_when': False},
                guard, case_import,
            ],
        }
        play_path = case_dir / 'play.yml'
        play_path.write_text(yaml.safe_dump([play], sort_keys=False))
        env = dict(os.environ, ANSIBLE_CONFIG=str(config_path),
                   ANSIBLE_LOCAL_TEMP=str(case_dir / 'local'),
                   ANSIBLE_LOG_PATH=str(case_dir / 'ansible.log'),
                   ANSIBLE_NOCOLOR='1', PYTHONDONTWRITEBYTECODE='1')
        command = [str(ansible), '-i', str(inventory_path), str(play_path)]
        if limit:
            command.extend(['--limit', limit])
        completed = subprocess.run(command, text=True, capture_output=True,
                                   env=env, timeout=180)
        log = completed.stdout + completed.stderr
        (case_dir / 'console.log').write_text(log)
        events = [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else []
        checked = [event for event in events if event['kind'] == 'CHECK']
        populated = [event for event in events if event['kind'] == 'POPULATE']
        selected = [limit] if limit else HOSTS
        should_succeed = not (fail_host or deploy_fail)
        assertions = {
            'return_code': completed.returncode == (0 if should_succeed else 2),
            'population_count': len(populated) == (1 if should_succeed else 0),
        }
        if not deploy_fail:
            assertions['all_nine_replicas'] = {(e['host'], e['container']) for e in checked} == {
                (host, container) for host in HOSTS for container in CONTAINERS}
            assertions['exactly_nine_checks'] = len(checked) == 9
            first_check = next((i for i, e in enumerate(events) if e['kind'] == 'CHECK'), len(events))
            assertions['selected_deploys_before_checks'] = {
                e['host'] for e in events[:first_check] if e['kind'] == 'DEPLOY'} == set(selected)
        if should_succeed:
            assertions['checks_before_population'] = bool(events) and all(
                e['kind'] == 'CHECK' for e in events[-10:-1]) and events[-1]['kind'] == 'POPULATE'
        if deploy_fail:
            assertions['no_check_after_partial_deploy'] = not checked
            if serial == 0:
                assertions['guard_failed'] = 'Some selected Mistral hosts failed or became unreachable.' in log
        result = {'scenario': name, 'result': 'ok' if all(assertions.values()) else 'failed',
                  'rc': completed.returncode, 'checks': len(checked),
                  'populations': len(populated), 'assertions': assertions}
        results.append(result)
        print(json.dumps(result, sort_keys=True), flush=True)
    report = {'result': 'ok' if all(r['result'] == 'ok' for r in results) else 'failed',
              'source_sha256': {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in source_paths},
              'output': str(output), 'scenarios': results}
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'result': report['result'], 'report': str(output / 'report.json')}))
    return int(report['result'] != 'ok')


if __name__ == '__main__':
    sys.exit(emit(sys.argv[2:]) if sys.argv[1:2] == ['--emit'] else main())
