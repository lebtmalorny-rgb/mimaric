"""Real CLI command discovery/parser checks: no cloud or credentials required."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'files' / 'collect.py'

PARSE = '''
import socket, sys
from types import SimpleNamespace
from openstackclient.shell import OpenStackShell
def refuse_network(*args, **kwargs):
    raise AssertionError('Parser test must not access a network')
socket.socket.connect = refuse_network
socket.create_connection = refuse_network
app = OpenStackShell()
app.options, remaining = app.parser.parse_known_args(sys.argv[1:])
app.cloud = SimpleNamespace(config={'ha_api_version': '1.3', 'baremetal_api_version': '1.95',
                                    'compute_api_version': '2', 'identity_api_version': '3',
                                    'image_api_version': '2', 'network_api_version': '2',
                                    'volume_api_version': '3', 'workflow_api_version': '2'})
app._load_plugins()
app._load_commands()
factory, name, arguments = app.command_manager.find_command(remaining)
command = factory(app, None)
command.get_parser(name).parse_args(arguments)
print('PARSED: ' + name)
'''


@unittest.skipUnless(os.environ.get('POWEROPS_REAL_OPENSTACK'), 'explicit real OpenStack executable')
class RealCliTests(unittest.TestCase):
    def test_every_emitted_api_command_is_accepted_by_real_cli_parser(self):
        spec = importlib.util.spec_from_file_location('collector_real_cli_test', SCRIPT)
        collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(collector)
        cfg = collector.validate_config({
            'notification_id': 'a1e7d8e9-cb63-4c7f-9dd1-52e0a0cea0af',
            'segment_id': 'b045da78-bc53-435a-937e-f12d41a217b1',
            'node_id': 'edebd181-6865-4134-8657-0e318efd4336',
            'compute_hosts': ['ultra1-2.ultra1.test.pvs.un.sbt'],
            'server_ids': ['85387b2a-32fe-48b2-be94-df20701d2659'],
        })
        jobs = collector.api_jobs(cfg) + collector.api_jobs(dict(cfg, notification_id=''))[:1]
        jobs.append(('vmove_detail', ['openstack', 'notification', 'vmove', 'show',
                     cfg['notification_id'], 'de084e2d-2324-48a5-8fde-31a2b7aa1bab', '-f', 'json']))
        # Capture the actual dynamically emitted discovery/detail commands too.
        # Fixtures replace only subprocess output, not the collector's command builder.
        from test_incident_collection import IncidentTests
        discovery = IncidentTests()
        discovery.setUp()
        discovery.collect(dict(discovery.cfg, segment_id=''))
        jobs.extend(('discovered_' + str(i), argv) for i, argv in enumerate(discovery.calls)
                    if argv[1:] != ['--version'])
        jobs = list({tuple(argv): (name, argv) for name, argv in jobs}.values())
        with tempfile.TemporaryDirectory(prefix='powerops-cli-parser-') as temp:
            cloud = Path(temp) / 'clouds.yaml'
            cloud.write_text(json.dumps({'clouds': {}}))
            env = {k: v for k, v in os.environ.items() if not k.startswith('OS_')}
            env['OS_CLIENT_CONFIG_FILE'] = str(cloud)
            for name, argv in jobs:
                with self.subTest(command=name):
                    python = str(Path(os.environ['POWEROPS_REAL_OPENSTACK']).with_name('python'))
                    result = subprocess.run([python, '-c', PARSE] + argv[1:],
                                            cwd=temp, env=env, text=True, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stdout)
                    self.assertIn('PARSED:', result.stdout)
