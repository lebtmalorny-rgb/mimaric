import hashlib
import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / 'tools' / 'watcher_automation_hold_delivery.py'


def load_tool():
    spec = importlib.util.spec_from_file_location('watcher_hold_delivery', TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(directory, *args):
    return subprocess.check_output(
        ['git', '-C', str(directory), *args], text=True).strip()


class WatcherAutomationHoldDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = pathlib.Path(self.directory.name)

    def make_manifest(self, artifact, **component):
        manifest = {
            'schema': 1,
            'package': {
                'path': artifact.name,
                'sha256': sha256(artifact),
            },
            'components': {'sample': component},
        }
        path = self.root / 'manifest.json'
        path.write_text(json.dumps(manifest))
        return path

    def test_verify_rejects_changed_artifact(self):
        tool = load_tool()
        artifact = self.root / 'guard.whl'
        artifact.write_bytes(b'wheel')
        manifest = self.make_manifest(
            artifact,
            base_tree='0' * 40,
            final_tree='1' * 40,
            patches=[],
            excluded_paths=[],
        )
        artifact.write_bytes(b'changed')

        with self.assertRaisesRegex(tool.DeliveryError, 'SHA256 mismatch'):
            tool.verify_manifest(manifest)

    def test_verify_includes_component_prerequisites(self):
        tool = load_tool()
        artifact = self.root / 'guard.whl'
        prerequisite = self.root / 'prerequisite.patch'
        artifact.write_bytes(b'wheel')
        prerequisite.write_bytes(b'original')
        manifest = self.make_manifest(
            artifact,
            base_tree='0' * 40,
            final_tree='1' * 40,
            prerequisites=[{
                'path': prerequisite.name,
                'sha256': sha256(prerequisite),
            }],
            patches=[],
            excluded_paths=[],
        )
        prerequisite.write_bytes(b'changed')

        with self.assertRaisesRegex(tool.DeliveryError, 'SHA256 mismatch'):
            tool.verify_manifest(manifest)

    def test_replay_matches_tree_without_storing_excluded_secret_blob(self):
        tool = load_tool()
        source = self.root / 'source'
        source.mkdir()
        subprocess.run(['git', 'init', '-q', str(source)], check=True)
        subprocess.run(['git', '-C', str(source), 'config', 'user.email', 'test@example.invalid'], check=True)
        subprocess.run(['git', '-C', str(source), 'config', 'user.name', 'Test'], check=True)
        (source / 'kept').write_text('before\n')
        (source / 'excluded').write_text('private\n')
        subprocess.run(['git', '-C', str(source), 'add', 'kept'], check=True)
        subprocess.run(['git', '-C', str(source), 'commit', '-qm', 'base'], check=True)
        base_tree = git(source, 'rev-parse', 'HEAD^{tree}')
        (source / 'kept').write_text('after\n')
        subprocess.run(['git', '-C', str(source), 'add', 'kept'], check=True)
        subprocess.run(['git', '-C', str(source), 'commit', '-qm', 'final'], check=True)
        final_tree = git(source, 'rev-parse', 'HEAD^{tree}')
        patch = self.root / 'change.patch'
        patch.write_bytes(subprocess.check_output(
            ['git', '-C', str(source), 'diff', 'HEAD^', 'HEAD', '--binary']))
        artifact = self.root / 'guard.whl'
        artifact.write_bytes(b'wheel')
        manifest = self.make_manifest(
            artifact,
            base_tree=base_tree,
            final_tree=final_tree,
            patches=[{'path': patch.name, 'sha256': sha256(patch)}],
            excluded_paths=['excluded'],
        )
        subprocess.run(['git', '-C', str(source), 'checkout', '-q', 'HEAD^'], check=True)
        output = self.root / 'replayed'

        result = tool.replay_component(manifest, 'sample', source, output)

        self.assertEqual(final_tree, result['final_tree'])
        self.assertEqual('after\n', (output / 'kept').read_text())
        self.assertEqual('private\n', (output / 'excluded').read_text())
        secret = b'private\n'
        blob = hashlib.sha1(
            b'blob ' + str(len(secret)).encode() + b'\0' + secret,
            usedforsecurity=False,
        ).hexdigest()
        retained = subprocess.run(
            ['git', '-C', str(output), 'cat-file', '-e', blob + '^{blob}'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertNotEqual(0, retained.returncode)

    def test_replay_checks_dependent_patches_in_order(self):
        tool = load_tool()
        source = self.root / 'source'
        source.mkdir()
        subprocess.run(['git', 'init', '-q', str(source)], check=True)
        subprocess.run(['git', '-C', str(source), 'config', 'user.email', 'test@example.invalid'], check=True)
        subprocess.run(['git', '-C', str(source), 'config', 'user.name', 'Test'], check=True)
        tracked = source / 'tracked'
        tracked.write_text('base\n')
        subprocess.run(['git', '-C', str(source), 'add', 'tracked'], check=True)
        subprocess.run(['git', '-C', str(source), 'commit', '-qm', 'base'], check=True)
        base_commit = git(source, 'rev-parse', 'HEAD')
        base_tree = git(source, 'rev-parse', 'HEAD^{tree}')
        patches = []
        for index, value in enumerate(('first\n', 'second\n'), start=1):
            tracked.write_text(value)
            subprocess.run(['git', '-C', str(source), 'commit', '-qam', f'change {index}'], check=True)
            patch = self.root / f'change-{index}.patch'
            patch.write_bytes(subprocess.check_output(
                ['git', '-C', str(source), 'diff', 'HEAD^', 'HEAD', '--binary']))
            patches.append({'path': patch.name, 'sha256': sha256(patch)})
        final_tree = git(source, 'rev-parse', 'HEAD^{tree}')
        artifact = self.root / 'guard.whl'
        artifact.write_bytes(b'wheel')
        manifest = self.make_manifest(
            artifact,
            base_tree=base_tree,
            final_tree=final_tree,
            patches=patches,
            excluded_paths=[],
        )
        subprocess.run(['git', '-C', str(source), 'checkout', '-q', base_commit], check=True)

        result = tool.replay_component(
            manifest, 'sample', source, self.root / 'replayed')

        self.assertEqual(final_tree, result['final_tree'])

    def test_replay_refuses_wrong_base_without_touching_output(self):
        tool = load_tool()
        source = self.root / 'source'
        source.mkdir()
        (source / 'file').write_text('unexpected\n')
        artifact = self.root / 'guard.whl'
        artifact.write_bytes(b'wheel')
        manifest = self.make_manifest(
            artifact,
            base_tree='0' * 40,
            final_tree='1' * 40,
            patches=[],
            excluded_paths=[],
        )
        output = self.root / 'replayed'

        with self.assertRaisesRegex(tool.DeliveryError, 'base tree mismatch'):
            tool.replay_component(manifest, 'sample', source, output)

        self.assertFalse(output.exists())

    def test_replay_refuses_patch_that_changes_excluded_file(self):
        tool = load_tool()
        source = self.root / 'source'
        source.mkdir()
        subprocess.run(['git', 'init', '-q', str(source)], check=True)
        subprocess.run(['git', '-C', str(source), 'config', 'user.email', 'test@example.invalid'], check=True)
        subprocess.run(['git', '-C', str(source), 'config', 'user.name', 'Test'], check=True)
        (source / 'kept').write_text('before\n')
        (source / 'excluded').write_text('private-before\n')
        subprocess.run(['git', '-C', str(source), 'add', 'kept', 'excluded'], check=True)
        subprocess.run(['git', '-C', str(source), 'commit', '-qm', 'base'], check=True)
        base_commit = git(source, 'rev-parse', 'HEAD')
        base_tree = tool._snapshot_tree(source, ['excluded'])
        (source / 'kept').write_text('after\n')
        (source / 'excluded').write_text('private-after\n')
        subprocess.run(['git', '-C', str(source), 'commit', '-qam', 'change'], check=True)
        final_tree = tool._snapshot_tree(source, ['excluded'])
        patch = self.root / 'change.patch'
        patch.write_bytes(subprocess.check_output(
            ['git', '-C', str(source), 'diff', 'HEAD^', 'HEAD', '--binary']))
        artifact = self.root / 'guard.whl'
        artifact.write_bytes(b'wheel')
        manifest = self.make_manifest(
            artifact,
            base_tree=base_tree,
            final_tree=final_tree,
            patches=[{'path': patch.name, 'sha256': sha256(patch)}],
            excluded_paths=['excluded'],
        )
        subprocess.run(['git', '-C', str(source), 'checkout', '-q', base_commit], check=True)
        output = self.root / 'replayed'

        with self.assertRaisesRegex(tool.DeliveryError, 'excluded path changed'):
            tool.replay_component(manifest, 'sample', source, output)

        self.assertFalse(output.exists())

    def test_shared_package_uses_current_spdx_metadata(self):
        import tomllib

        project = tomllib.loads(
            (ROOT / 'packages' / 'powerops-watcher-guard' / 'pyproject.toml').read_text())
        self.assertEqual('Apache-2.0', project['project']['license'])
        self.assertIn('setuptools>=77', project['build-system']['requires'])


if __name__ == '__main__':
    unittest.main()
