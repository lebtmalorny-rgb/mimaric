"""Unit checks for the offline image-check orchestration; no Docker calls."""

import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

import verify_images


class ImageCheckTest(unittest.TestCase):
    def setUp(self):
        self.argv = ['verify_images.py', '--engine', 'docker',
                     '--api-image', 'local/api:test',
                     '--engine-image', 'local/engine:test',
                     '--executor-image', 'local/executor:test']

    def test_pins_three_local_ids_and_never_starts_service_entrypoint(self):
        with mock.patch.object(sys, 'argv', self.argv), mock.patch.object(
                verify_images.subprocess, 'run',
                return_value=SimpleNamespace(stdout='sha256:localid\n')) as run:
            self.assertEqual(0, verify_images.main())
        calls = [call.args[0] for call in run.call_args_list]
        checks = [args for args in calls if args[1] == 'run']
        self.assertEqual(3, len(checks))
        for args in checks:
            for flag in ('--pull=never', '--network=none', '--read-only'):
                self.assertIn(flag, args)
            index = args.index('--entrypoint')
            self.assertEqual('/var/lib/kolla/venv/bin/python', args[index + 1])
            self.assertEqual('sha256:localid', args[index + 2])
        names = [args[args.index('--name') + 1] for args in checks]
        self.assertEqual(3, len(set(names)))
        self.assertEqual(names, [args[-1] for args in calls if args[1] == 'rm'])

    def test_timeout_removes_only_the_named_disposable_container(self):
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            if args[1] == 'run':
                raise subprocess.TimeoutExpired(args, kwargs['timeout'])
            return SimpleNamespace(stdout='sha256:localid\n')

        with mock.patch.object(sys, 'argv', self.argv), mock.patch.object(
                verify_images.subprocess, 'run', side_effect=run):
            with self.assertRaises(subprocess.TimeoutExpired):
                verify_images.main()
        self.assertEqual(3, len(calls))
        name = calls[1][calls[1].index('--name') + 1]
        self.assertEqual(['docker', 'rm', '-f', name], calls[2])

    def test_unknown_local_image_does_not_pull_or_run_anything(self):
        with mock.patch.object(sys, 'argv', self.argv), mock.patch.object(
                verify_images.subprocess, 'run',
                side_effect=subprocess.CalledProcessError(1, 'inspect')) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                verify_images.main()
        run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
