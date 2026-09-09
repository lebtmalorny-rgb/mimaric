import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'docs/evidence/horizon-powerops-baselines.json'


class HorizonBackendBaselinesTest(unittest.TestCase):
    def test_exact_existing_baselines_and_patch_counts(self):
        data = json.loads(MANIFEST.read_text(encoding='utf-8'))
        self.assertEqual(
            '0fd34dd6a6d90525dbf806f35577c5ee1d7e9444',
            data['masakari']['commit'],
        )
        self.assertEqual(10, data['masakari']['published_patches'])
        self.assertEqual(
            '3b2eab29e9dc71a5ba250d989155eb69a9bd8e48',
            data['mistral']['commit'],
        )
        self.assertEqual(10, data['mistral']['published_patches'])
        self.assertEqual(
            '693174dd0aac1da22870b31e4a2481c4e749916a',
            data['mistral_lib']['commit'],
        )
        self.assertEqual(
            '703b06c9fa5771c758f703b424d63fb04192567a',
            data['kolla_ansible']['commit'],
        )
        self.assertEqual(6, data['kolla_ansible']['published_patches'])
        self.assertEqual(
            'd14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c',
            data['kolla']['commit'],
        )
        self.assertEqual('stable/2025.1', data['horizon']['branch'])
        self.assertRegex(data['horizon']['commit'], r'^[0-9a-f]{40}$')


if __name__ == '__main__':
    unittest.main()
