"""Optional offline integration against the exact user-provided 0809 archive."""
import hashlib
import json
import os
from pathlib import PurePosixPath
import shutil
import stat
import zipfile

from support import AnsibleFixture, ROOT


class Baseline0809Tests(AnsibleFixture):
    def test_overlay_on_verified_archive_and_original_files_unchanged(self):
        metadata = json.loads((ROOT.parents[2] / 'baselines/0809.json').read_text())
        expected = metadata['archives']['kolla-ansible']
        archive_path = next((p / expected['file'] for p in ROOT.parents
                             if (p / expected['file']).is_file()), None)
        if archive_path is None:
            self.skipTest('Place the declared 0809 zip in a parent workspace to enable baseline verification')
        self.assertEqual(expected['sha256'], hashlib.sha256(archive_path.read_bytes()).hexdigest())
        extracted = self.base / 'baseline'
        with zipfile.ZipFile(archive_path) as archive:
            links = []
            regular = []
            for item in archive.infolist():
                path = PurePosixPath(item.filename)
                self.assertFalse(path.is_absolute() or '..' in path.parts)
                if stat.S_ISLNK(item.external_attr >> 16):
                    target = archive.read(item).decode('utf-8')
                    destination = extracted / item.filename
                    self.assertFalse(PurePosixPath(target).is_absolute())
                    self.assertTrue((destination.parent / target).resolve().is_relative_to(extracted.resolve()))
                    links.append((destination, target))
                else:
                    regular.append(item)
            archive.extractall(extracted, members=regular)
            for destination, target in links:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.symlink_to(target)
        candidates = [p.parent.parent for p in extracted.rglob('site.yml') if p.parent.name == 'ansible']
        self.assertEqual(1, len(candidates))
        source = candidates[0]
        before = {p.relative_to(source): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in source.rglob('*') if p.is_file()}
        overlay_files = [p for p in (ROOT / 'ansible').rglob('*')
                         if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
        for path in overlay_files:
            self.assertFalse((source / 'ansible' / path.relative_to(ROOT / 'ansible')).exists(), path)
        # The temporary tree already has our overlay. Add the pristine source.
        shutil.copytree(source, self.tree, dirs_exist_ok=True, symlinks=True)
        self.env['PYTHONPATH'] = str(self.tree) + os.pathsep + self.env.get('PYTHONPATH', '')
        self.assert_success(self.run_play('host-firewall.yml', options=('--syntax-check',)))
        self.install_probe_fixture()
        self.env['POWEROPS_TEST_PROBE_MARKER'] = str(self.base / 'probe-called')
        result = self.run_play('host-firewall.yml', {
            'api_interface': 'ethapi', 'api_address_family': 'ipv4',
            'enable_mistral': True, 'enable_haproxy': True,
            'mistral_api_listen_port': 18989,
            'host_firewall_become': False,
        })
        self.assert_success(result)
        bundle = self.read_bundle()
        self.assertEqual(18989, bundle['reports']['node-a']['candidate_flows'][0]['port'])
        for relative, digest in before.items():
            self.assertEqual(digest, hashlib.sha256((self.tree / relative).read_bytes()).hexdigest(), str(relative))
