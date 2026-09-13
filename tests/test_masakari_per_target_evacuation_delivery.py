"""Offline incremental delivery checks; optional exact clean archive replay."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from test_watcher_automation_hold_delivery import load_tool, sha256

ROOT = Path(__file__).resolve().parents[1]
DELIVERY = ROOT / 'hotfixes/masakari-per-target-evacuation'
MANIFEST = DELIVERY / 'manifest.json'
PARENT = '1d3bd3255b3678347414578fd89dbd6f05430b19'
TREES = {
    'nova': '85d45af66afefeb0317eb42d1d235d28dc61dc90',
    'masakari': '568c7daa3e71c85beb22be44252d90c310a98acf',
    'kolla-ansible': 'f888c531b3d80f1ce2e6b2098933e7a098fb99aa',
}


class EvacuationDeliveryTests(unittest.TestCase):
    def test_complete_incremental_delivery_and_predecessor_lineage(self):
        self.assertTrue(MANIFEST.is_file(), 'reviewed queue delivery is missing')
        data, entries = load_tool().verify_manifest(MANIFEST)
        old = ROOT / 'hotfixes/watcher-automation-hold/manifest.json'
        predecessor, _ = load_tool().verify_manifest(old)
        self.assertEqual(sha256(old), data['dependency']['manifest_sha256'])
        self.assertEqual(set(TREES), set(data['components']))
        # Wheel + Nova + Masakari + three ordered Kolla patches.
        self.assertEqual(6, len(entries))
        for name, tree in TREES.items():
            component = data['components'][name]
            self.assertEqual(tree, component['final_tree'])
            self.assertEqual([], component['prerequisites'])
            if name != 'nova':
                self.assertEqual(predecessor['components'][name]['final_tree'], component['base_tree'])
            for patch in component['patches']:
                self.assertNotIn('..', Path(patch['path']).parts)
        self.assertEqual(3, len(data['components']['kolla-ansible']['patches']))

    def test_watcher_payload_and_source_bytes_unchanged(self):
        names = subprocess.check_output([
            'git', '-C', str(ROOT), 'ls-tree', '-r', '--name-only', PARENT,
            '--', 'hotfixes/watcher-automation-hold', 'packages/powerops-watcher-guard',
        ], text=True).splitlines()
        self.assertTrue(names)
        for name in names:
            original = subprocess.check_output(['git', '-C', str(ROOT), 'show', PARENT + ':' + name])
            self.assertEqual(original, (ROOT / name).read_bytes(), name)

    def test_wheel_contains_exact_reviewed_core_and_cli(self):
        self.assertTrue(MANIFEST.exists(), 'reviewed wheel delivery is missing')
        data = json.loads(MANIFEST.read_text())
        with zipfile.ZipFile(DELIVERY / data['package']['path']) as wheel:
            for path in (ROOT / 'packages/powerops-evacuation-guard/powerops_evacuation_guard').glob('*.py'):
                self.assertEqual(path.read_bytes(), wheel.read('powerops_evacuation_guard/' + path.name))
            metadata = wheel.read('powerops_evacuation_guard-0.1.0.dist-info/METADATA').decode()
            self.assertIn('Requires-Python: >=3.11', metadata)
            self.assertIn('powerops-evacuation-guard = powerops_evacuation_guard.cli:main',
                          wheel.read('powerops_evacuation_guard-0.1.0.dist-info/entry_points.txt').decode())

    def test_new_manifest_rejects_wrong_base_and_existing_output(self):
        self.assertTrue(MANIFEST.exists(), 'reviewed replay delivery is missing')
        tool = load_tool()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source'
            source.mkdir()
            (source / 'wrong').write_text('wrong baseline\n')
            output = Path(directory) / 'output'
            with self.assertRaisesRegex(tool.DeliveryError, 'base tree mismatch'):
                tool.replay_component(MANIFEST, 'nova', source, output)
            self.assertFalse(output.exists())
            output.mkdir()
            marker = output / 'retain'
            marker.write_text('retain\n')
            with self.assertRaisesRegex(tool.DeliveryError, 'output already exists'):
                tool.replay_component(MANIFEST, 'nova', source, output)
            self.assertEqual('retain\n', marker.read_text())

    @unittest.skipUnless(os.environ.get('EVAC_CLEAN_REPLAY_BASES'), 'set clean archive baseline mapping')
    def test_exact_clean_replay_and_required_symlinks(self):
        bases = json.loads(Path(os.environ['EVAC_CLEAN_REPLAY_BASES']).read_text())
        data = json.loads(MANIFEST.read_text())
        with tempfile.TemporaryDirectory(prefix='evac-delivery-replay-') as directory:
            for name, tree in TREES.items():
                source = Path(bases['kolla' if name == 'kolla-ansible' else name]['path'])
                self.assertFalse((source / 'etc/kolla/passwords.yml').exists())
                output = Path(directory) / name
                result = load_tool().replay_component(MANIFEST, name, source, output)
                self.assertEqual(tree, result['final_tree'])
                for link in data['components'][name].get('required_symlinks', []):
                    self.assertTrue((output / link).is_symlink())
                for patch in data['components'][name]['patches']:
                    for line in (DELIVERY / patch['path']).read_text().splitlines():
                        if line.startswith('+++ b/') and line.endswith('.py'):
                            path = output / line[6:]
                            compile(path.read_text(), str(path), 'exec')


if __name__ == '__main__':
    unittest.main()
