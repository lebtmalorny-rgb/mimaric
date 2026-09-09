"""Offline delivery checks; no cloud commands, imports or external source trees."""
import ast
import hashlib
import json
from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOCS = (
    'OVERVIEW', 'DIAGNOSTICS', 'CONFIGURATION', 'AUTHENTICATION',
    'IRONIC-ENROLLMENT', 'CONSUL', 'TROUBLESHOOTING-COMMANDS',
)


class RepositoryTests(unittest.TestCase):
    def test_current_payload_checksums_and_exact_coverage(self):
        entries = {}
        for line in (ROOT / 'SHA256SUMS').read_text().splitlines():
            digest, name = line.split(None, 1)
            self.assertNotIn(name, entries)
            entries[name] = digest
            self.assertEqual(digest, hashlib.sha256((ROOT / name).read_bytes()).hexdigest())
        expected = {str(p.relative_to(ROOT)) for p in (ROOT / 'hotfixes').rglob('*.patch')}
        expected.update(str(p.relative_to(ROOT)) for p in (ROOT / 'tools/diagnostics').glob('*.yml'))
        self.assertEqual(expected, set(entries))
        self.assertEqual(3, len(entries))

    def test_0809_baseline_and_horizon_boundary_are_explicit(self):
        data = json.loads((ROOT / 'baselines/0809.json').read_text())
        self.assertEqual('0809', data['baseline'])
        self.assertEqual({'mistral', 'masakari', 'kolla-ansible'}, set(data['archives']))
        for value in data['archives'].values():
            self.assertTrue(value['file'].endswith('_0809.zip'))
            self.assertRegex(value['sha256'], r'^[a-f0-9]{64}$')
        patch = data['additional_patch']
        self.assertEqual(patch['sha256'], hashlib.sha256((ROOT / patch['file']).read_bytes()).hexdigest())
        self.assertEqual('not_verified', data['horizon']['compatible_with_0809'])
        self.assertEqual({'planned-return-v2', 'planned-return-kit-delivery'}, set(data['retired']))

    def test_seven_documents_and_incident_evidence_are_present(self):
        for name in DOCS:
            self.assertTrue((ROOT / 'docs' / ('POWEROPS-' + name + '.md')).is_file())
        for name in ('AUDIT-2026-09-09-planned-off-live-migration.md',
                     'INCIDENT-2026-09-07-planned-off-live-migration.md'):
            self.assertTrue((ROOT / 'docs' / name).is_file())

    def test_superseded_root_files_are_absent(self):
        for name in ('boofer', 'image.png', 'image2.png', 'INSTALL.md', 'DELIVERY.md',
                     'OPERATIONS.md', 'ansible', 'patches', 'docs/superpowers',
                     'tools/diagnostics/collect.yml', 'planned-return-v2',
                     'hotfixes/repair-0509', 'hotfixes/planned-live-migration-wait'):
            self.assertFalse((ROOT / name).exists(), name)

    def test_horizon_original_files_are_preserved(self):
        entries = (ROOT / 'baselines/horizon-files.sha256').read_text().splitlines()
        self.assertGreater(len(entries), 100)
        for line in entries:
            digest, name = line.split(None, 1)
            self.assertTrue(name.startswith('horizon/'))
            self.assertEqual(digest, hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), name)

    def test_new_and_current_markdown_links_resolve(self):
        documents = [ROOT / 'README.md', ROOT / 'horizon/README.md',
                     ROOT / 'tools/diagnostics/README.md']
        documents.extend((ROOT / 'docs').glob('*.md'))
        documents.extend((ROOT / 'hotfixes').rglob('README.md'))
        for path in documents:
            text = path.read_text()
            outside_code = re.sub(r'```.*?```', '', text, flags=re.S)
            for link in re.findall(r'(?<!!)\[[^\]]+\]\(([^)]+)\)', outside_code):
                link = link.strip('<>')
                parsed = urlsplit(link)
                if parsed.scheme or not parsed.path:
                    continue
                self.assertTrue((path.parent / unquote(parsed.path)).exists(), (path, link))
            self.assertTrue(text.endswith('\n'), str(path))
            self.assertFalse(any(line.rstrip() != line for line in text.splitlines()), str(path))
            self.assertEqual(0, len(re.findall(r'^```', text, re.M)) % 2, str(path))

    def test_python_sources_compile(self):
        for folder in ('tests', 'tools/diagnostics'):
            for path in (ROOT / folder).rglob('*.py'):
                ast.parse(path.read_text(), filename=str(path))


if __name__ == '__main__':
    unittest.main()
