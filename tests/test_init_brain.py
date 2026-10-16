import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]


class InitializeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()

    def invoke(self, target):
        return subprocess.run([sys.executable, str(SOURCE / 'scripts/init_brain.py'), '--target', str(target)], text=True, capture_output=True)

    def test_fresh_brain_is_empty_clean_local_and_skill_installable(self):
        target = self.base / 'my-brain'
        output = self.invoke(target)
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertEqual(json.loads(output.stdout)['projects'], 0)
        registry = json.loads((target / 'system/project-registry.json').read_text())
        self.assertEqual(registry['projects'], [])
        self.assertFalse(list((target / 'sessions').rglob('*.md')))
        for args in (['remote'], ['status', '--porcelain']):
            self.assertEqual(subprocess.check_output(['git', '-C', str(target), *args], text=True).strip(), '')
        self.assertEqual(subprocess.check_output(['git', '-C', str(target), 'config', '--get', 'core.hooksPath'], text=True).strip(), '.githooks')
        check = subprocess.run([sys.executable, str(target / 'scripts/brain.py'), 'check'], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stdout)
        install = self.base / 'skill'
        output = subprocess.run([sys.executable, str(target / 'scripts/install_sync_skill.py'), '--target', str(install)], capture_output=True, text=True)
        self.assertEqual(output.returncode, 0, output.stderr)
        config = json.loads((install / 'config.json').read_text())
        self.assertEqual(config['personal'], str(target))
        self.assertIsNone(config['work'])
        route = subprocess.run([sys.executable, str(install / 'scripts/route.py'), '--scope', 'personal'], capture_output=True, text=True)
        self.assertEqual(route.returncode, 0, route.stderr)
        self.assertEqual(json.loads(route.stdout)['candidates'], [])

    def test_existing_target_is_never_replaced(self):
        target = self.base / 'existing'
        target.mkdir()
        (target / 'sentinel.txt').write_text('preserve')
        result = self.invoke(target)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(target.iterdir()), [target / 'sentinel.txt'])
        self.assertEqual((target / 'sentinel.txt').read_text(), 'preserve')

    def test_symlink_and_nested_public_targets_are_rejected(self):
        real = self.base / 'real'
        real.mkdir()
        linked = self.base / 'link'
        linked.symlink_to(real, target_is_directory=True)
        self.assertNotEqual(self.invoke(linked / 'new').returncode, 0)
        self.assertFalse((real / 'new').exists())
        nested = SOURCE / 'private-test-must-not-exist'
        self.assertNotEqual(self.invoke(nested).returncode, 0)
        self.assertFalse(nested.exists())


if __name__ == '__main__':
    unittest.main()
