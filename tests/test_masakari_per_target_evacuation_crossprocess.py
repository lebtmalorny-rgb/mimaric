"""Opt-in composed proof: real helpers/etcd; external Nova DB/virt are fakes."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from urllib.parse import urlsplit
import uuid

ENDPOINT = os.environ.get('EVAC_TEST_ENDPOINT')
HELPER = Path(__file__).parent / 'helpers/evacuation_service.py'


class ComposedHarnessDeliveryTests(unittest.TestCase):
    def test_composed_service_adapter_is_delivered(self):
        self.assertTrue(HELPER.is_file(), 'separate service adapter is missing')


@unittest.skipUnless(ENDPOINT, 'set EVAC_TEST_ENDPOINT to disposable loopback etcd')
class EvacuationCrossProcessTests(unittest.TestCase):
    def setUp(self):
        from powerops_evacuation_guard import Guard
        self.assertIn(urlsplit(ENDPOINT).hostname, ('127.0.0.1', 'localhost', '::1'))
        self.directory = tempfile.TemporaryDirectory(prefix='evac-composed-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.prefix = '/evac-composed/' + str(uuid.uuid4())
        self.env = dict(os.environ, EVAC_ENDPOINT=ENDPOINT, EVAC_PREFIX=self.prefix,
                        EVAC_DIRECTORY=str(self.root), PYTHONDONTWRITEBYTECODE='1')
        self.guard = Guard(ENDPOINT, prefix=self.prefix, cooldown=1.2)
        self.addCleanup(self.delete_namespace)
        self.guard.initialize('test', 'isolated composed proof')
        self.processes = []
        self.addCleanup(self.stop_processes)
        self.masakari = self.spawn('masakari', {})

    def delete_namespace(self):
        from powerops_evacuation_guard.etcd import b64, prefix_end
        start = self.prefix + '/'
        self.guard._etcd.request('deleterange', {'key': b64(start), 'range_end': b64(prefix_end(start))})

    def spawn(self, service, request):
        python = os.environ.get('EVAC_NOVA_PYTHON' if service == 'nova' else 'EVAC_MASAKARI_PYTHON')
        self.assertTrue(python, 'set both independent service interpreter paths')
        stderr = (self.root / (str(uuid.uuid4()) + '.stderr')).open('w+')
        process = subprocess.Popen([python, '-u', str(HELPER), service],
            env=dict(self.env, EVAC_REQUEST=json.dumps(request)), cwd='/tmp',
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, text=True)
        self.processes.append((process, stderr))
        return process

    def stop_processes(self):
        for process, stderr in self.processes:
            if process.poll() is None:
                process.terminate()
            try:
                process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=10)
            stderr.close()

    def masakari_call(self, **request):
        self.masakari.stdin.write(json.dumps(request) + '\n')
        self.masakari.stdin.flush()
        # Child writes a response file atomically; bounded wait avoids pipe hangs.
        path = self.root / 'masakari-response.json'
        self.wait_for(path.exists)
        result = json.loads(path.read_text())
        path.unlink()
        return result

    def wait_for(self, predicate, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.025)
        self.fail('bounded composed state wait expired\n' + self.diagnostics())

    def diagnostics(self):
        messages = []
        for child, stream in self.processes:
            stream.flush(); stream.seek(0)
            messages.append('pid=%s exit=%s\n%s' % (child.pid, child.poll(), stream.read()))
        return '\n'.join(messages)

    def reserve(self, target, mode='complete'):
        vm = str(uuid.uuid4())
        result = self.masakari_call(command='reserve', vm_uuid=vm)
        self.assertNotIn('error', result, self.diagnostics())
        result.update(vm_uuid=vm, migration_uuid=str(uuid.uuid4()),
                      target_uuid=target, target_host='compute-' + target[:8], mode=mode)
        return result

    def marker(self, request, suffix):
        return self.root / (request['migration_uuid'] + '.' + suffix)

    def wait_state(self, request, state):
        from powerops_evacuation_guard import GuardError
        def ready():
            try:
                return self.guard.get_operation(request['migration_uuid'])['state'] == state
            except GuardError:
                return False
        self.wait_for(ready)

    def confirmed(self, request):
        return self.masakari_call(command='confirmed', attempt_uuid=request['attempt_uuid'],
                                  target_host=request['target_host'])

    def finish_process(self, process):
        stdout, _ = process.communicate(timeout=30)
        if process.returncode:
            stderr = next(stream for child, stream in self.processes if child is process)
            stderr.flush(); stderr.seek(0)
            self.fail(stderr.read())
        return json.loads(stdout)

    def test_helpers_correlate_queue_complete_and_preserve_unknown_across_restart(self):
        a = self.reserve(str(uuid.uuid4()))
        pa = self.spawn('nova', a)
        self.wait_for(lambda: self.marker(a, 'admitted').exists())
        self.wait_state(a, 'RUNNING')
        self.assertFalse(self.confirmed(a)['confirmed'])
        b = self.reserve(a['target_uuid'])
        pb = self.spawn('nova', b)
        self.wait_state(b, 'WAITING')
        self.assertFalse(self.marker(b, 'admitted').exists())
        c = self.reserve(str(uuid.uuid4()))
        pc = self.spawn('nova', c)
        self.wait_for(lambda: self.marker(c, 'admitted').exists())
        self.assertEqual('RUNNING', self.guard.get_operation(a['migration_uuid'])['state'])
        d = self.reserve(str(uuid.uuid4()))
        pd = self.spawn('nova', d)
        self.wait_for(lambda: self.marker(d, 'admitted').exists())
        for request in (a, c, d):
            self.assertEqual('RUNNING', self.guard.get_operation(request['migration_uuid'])['state'])
        e = self.reserve(str(uuid.uuid4()))
        pe = self.spawn('nova', e)
        self.wait_state(e, 'WAITING')
        self.assertFalse(self.marker(e, 'admitted').exists())
        self.marker(c, 'release').touch()
        self.assertTrue(self.finish_process(pc)['executed'])
        self.assertTrue(self.confirmed(c)['confirmed'])
        self.wait_for(lambda: self.marker(e, 'admitted').exists())
        duplicate = self.finish_process(self.spawn('nova', a))
        self.assertFalse(duplicate['executed'])
        self.marker(a, 'release').touch()
        self.wait_state(a, 'COOLDOWN')
        self.assertFalse(self.confirmed(a)['confirmed'])
        self.assertFalse(self.marker(b, 'admitted').exists())
        self.assertTrue(self.finish_process(pa)['executed'])
        self.assertTrue(self.confirmed(a)['confirmed'])
        self.wait_for(lambda: self.marker(b, 'admitted').exists())
        for request, process in ((b, pb), (d, pd), (e, pe)):
            self.marker(request, 'release').touch()
            self.assertTrue(self.finish_process(process)['executed'])
            self.assertTrue(self.confirmed(request)['confirmed'])

        unknown = self.reserve(str(uuid.uuid4()), mode='unknown')
        result = self.finish_process(self.spawn('nova', unknown))
        self.assertEqual('RuntimeError', result['error'])
        self.wait_state(unknown, 'UNKNOWN')
        before = self.guard.get_operation(unknown['migration_uuid'])
        self.assertEqual('GuardDenied', self.confirmed(unknown)['error'])
        result = self.finish_process(self.spawn('nova', unknown))
        self.assertFalse(result['executed'])
        self.assertEqual(before, self.guard.get_operation(unknown['migration_uuid']))
        blocked = self.reserve(unknown['target_uuid'], mode='timeout')
        result = self.finish_process(self.spawn('nova', blocked))
        self.assertFalse(result['executed'])
        self.assertEqual('GuardDenied', result['error'])
        self.wait_state(blocked, 'DENIED')
        self.assertEqual(before, self.guard.get_operation(unknown['migration_uuid']))

        crashed = self.reserve(str(uuid.uuid4()))
        process = self.spawn('nova', crashed)
        self.wait_for(lambda: self.marker(crashed, 'admitted').exists())
        process.kill(); process.communicate(timeout=10)
        before = self.guard.get_operation(crashed['migration_uuid'])
        self.assertEqual('RUNNING', before['state'])
        result = self.finish_process(self.spawn('nova', crashed))
        self.assertFalse(result['executed'])
        self.assertEqual(before, self.guard.get_operation(crashed['migration_uuid']))
        self.assertFalse(self.confirmed(crashed)['confirmed'])


if __name__ == '__main__':
    unittest.main()
