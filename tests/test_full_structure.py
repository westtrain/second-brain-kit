import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SOURCE / 'automation'), str(SOURCE / 'scripts')]
import providers
import install_schedule
import run as automation_run


class PairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.pair = self.base / 'brains'
        result = subprocess.run([sys.executable, str(SOURCE / 'scripts/init_brain.py'), '--pair', '--target', str(self.pair)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_independent_scopes_and_empty_registries(self):
        config = json.loads((self.pair / 'config.json').read_text())
        for scope in ('personal', 'work'):
            root = self.pair / scope
            self.assertEqual(config[scope], str(root))
            self.assertEqual(json.loads((root / 'system/scope.json').read_text())['scope'], scope)
            self.assertEqual(json.loads((root / 'system/project-registry.json').read_text())['projects'], [])
            self.assertEqual(subprocess.check_output(['git', '-C', str(root), 'remote'], text=True).strip(), '')
            self.assertTrue((root / 'GEMINI.md').exists())
            self.assertEqual(subprocess.run([sys.executable, str(root / 'scripts/brain.py'), 'check'], capture_output=True).returncode, 0)
        for path in ('findings/README.md', 'incidents/README.md', 'exports/candidates', 'exports/reviews', 'system/company-registry.json', 'automation/run.py'):
            self.assertTrue((self.pair / 'work' / path).exists(), path)
        for path in ('career/index.md', 'career/companies', 'blog', 'learnings'):
            self.assertTrue((self.pair / 'personal' / path).exists(), path)
        self.assertFalse((self.pair / 'work/career').exists())
        self.assertFalse((self.pair / 'personal/exports').exists())
        self.assertEqual(json.loads((self.pair / 'work/system/company-registry.json').read_text())['projects'], {})

    def test_all_four_skill_installs_share_the_same_routes(self):
        for provider in providers.PROVIDERS:
            target = self.base / 'skills' / provider
            result = subprocess.run([sys.executable, str(self.pair / 'personal/scripts/install_sync_skill.py'), '--provider', provider,
                                     '--target', str(target), '--config', str(self.pair / 'config.json')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for scope in ('personal', 'work'):
                d = json.loads(subprocess.check_output([sys.executable, str(target / 'scripts/route.py'), '--scope', scope]))
                self.assertEqual(d['root'], str(self.pair / scope))
                self.assertEqual(d['candidates'], [])
                self.assertTrue(any(f['path'].endswith('GEMINI.md') for f in d['instructions']['files']))

    def test_schedule_generation_is_opt_in_and_scope_checked(self):
        output = self.base / 'jobs'
        generated = subprocess.run([sys.executable, str(self.pair / 'work/automation/install_schedule.py'), '--output-dir', str(output)], capture_output=True, text=True)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        d = json.loads(generated.stdout)
        self.assertFalse(d['activated'])
        self.assertEqual(len(d['files']), 3)
        for path in d['files']:
            job = plistlib.loads(Path(path).read_bytes())
            self.assertIn(str(self.pair / 'work/automation/run.py'), job['ProgramArguments'])
            if job['ProgramArguments'][-1] == 'integration':
                self.assertEqual(job['StartCalendarInterval'], {'Weekday': 6, 'Hour': 9, 'Minute': 0})
            elif job['ProgramArguments'][-1] == 'blog':
                self.assertEqual(job['StartCalendarInterval'], {'Weekday': 0, 'Hour': 10, 'Minute': 0})
        rejected = subprocess.run([sys.executable, str(self.pair / 'personal/automation/install_schedule.py'), '--output-dir', str(self.base / 'bad')], capture_output=True)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertFalse((self.base / 'bad').exists())
        rejected = subprocess.run([sys.executable, str(self.pair / 'personal/automation/host_runner.py'), 'integration', '--artifacts', str(self.base / 'bad-host')], capture_output=True)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertFalse((self.base / 'bad-host').exists())


class ProviderTests(unittest.TestCase):
    def test_direct_and_vendor_envelopes(self):
        result = {'current': [], 'history': [], 'markdown': '', 'deferred': []}
        for envelope in (result, {'response': json.dumps(result)}, {'result': json.dumps(result)}, {'structured_output': result}):
            self.assertEqual(providers.decode(json.dumps(envelope), result), result)
        for bad in ({'is_error': True, 'result': json.dumps(result)}, {'response': '{}'}, {'unknown': result}):
            with self.assertRaises(ValueError):
                providers.decode(json.dumps(bad), result)

    def test_provider_configuration_does_not_execute_a_shell(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'automation').mkdir()
            path = root / 'automation/config.json'
            for provider in providers.PROVIDERS:
                path.write_text(json.dumps({'provider': provider}))
                with patch.object(automation_run.shutil, 'which', return_value='/synthetic/cli'):
                    self.assertEqual(automation_run.configuration(root), (provider, provider))
            path.write_text(json.dumps({'provider': 'unknown'}))
            with self.assertRaises(ValueError):
                automation_run.configuration(root)


if __name__ == '__main__':
    unittest.main()
