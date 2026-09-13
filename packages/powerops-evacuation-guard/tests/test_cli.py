import json
import pytest
import requests


def test_cli_commands_share_durable_configuration_and_emit_json(backend, tmp_path, capsys):
    if backend is None:
        pytest.skip('Offline CLI with HTTP boundary double; process proof is separate')
    from powerops_evacuation_guard.cli import main
    cfg = tmp_path / 'guard.conf'
    cfg.write_text('[powerops_evacuation_guard]\nendpoint=http://fake:2379\nprefix=/cli-test\n')
    args = ['--config-file', str(cfg)]
    assert main(args + ['initialize', '--actor', 'op', '--reason', 'commission']) == 0
    initial = json.loads(capsys.readouterr().out)
    assert initial['max_parallel'] == 3
    assert main(args + ['status', '--limit', '10']) == 0
    status = json.loads(capsys.readouterr().out)
    assert status['configuration']['revision'] == initial['revision']
    assert main(args + ['configure', '--expected-revision', str(initial['revision']),
                        '--max-parallel', '4', '--cooldown', '7', '--actor', 'op', '--reason', 'change']) == 0
    assert json.loads(capsys.readouterr().out)['max_parallel'] == 4


def test_cli_sanitizes_transport_config_and_argument_errors(tmp_path, monkeypatch, capsys):
    from powerops_evacuation_guard.cli import main
    cfg = tmp_path / 'guard.conf'
    cfg.write_text('[powerops_evacuation_guard]\nendpoint=http://fake:2379\n')
    def fail(*args, **kwargs):
        raise requests.ConnectionError('https://user:secret@host private-response')
    monkeypatch.setattr('requests.post', fail)
    assert main(['--config-file', str(cfg), 'status']) != 0
    err = capsys.readouterr().err
    assert 'secret' not in err and 'private-response' not in err and 'Traceback' not in err
    cfg.write_text('[powerops_evacuation_guard]\ntimeout=secret-value\n')
    assert main(['--config-file', str(cfg), 'status']) != 0
    assert 'secret-value' not in capsys.readouterr().err
    assert main(['--secret-argument']) != 0
    assert 'secret-argument' not in capsys.readouterr().err


def test_cli_resolution_requires_explicit_terminal_and_quiescence_flags(capsys):
    from powerops_evacuation_guard.cli import main
    assert main(['resolve-operation', '00000000-0000-0000-0000-000000000001',
                 '--actor', 'op', '--reason', 'checked', '--expected-revision', '3']) != 0
    assert 'Traceback' not in capsys.readouterr().err


def test_real_cli_initialize_and_status_in_distinct_processes(tmp_path):
    import os
    import subprocess
    import sys
    import uuid
    endpoint = os.environ.get('POWEROPS_EVACUATION_TEST_ENDPOINT')
    if not endpoint:
        pytest.skip('Requires actual etcd shared between processes')
    cfg = tmp_path / 'guard.conf'
    cfg.write_text('[powerops_evacuation_guard]\nendpoint='+endpoint+'\nprefix=/cli-process-test/'+str(uuid.uuid4())+'\n')
    command = [sys.executable, '-m', 'powerops_evacuation_guard.cli', '--config-file', str(cfg)]
    initialized = subprocess.run(command+['initialize', '--actor', 'test', '--reason', 'process proof'], capture_output=True, text=True, check=True)
    status = subprocess.run(command+['status'], capture_output=True, text=True, check=True)
    assert json.loads(status.stdout)['configuration'] == json.loads(initialized.stdout)
    assert json.loads(status.stdout)['records'] == []
