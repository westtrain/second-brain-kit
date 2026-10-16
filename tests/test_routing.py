import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/second-brain-sync/scripts/route.py'
spec = importlib.util.spec_from_file_location('route', SCRIPT)
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.personal = self.base / 'personal'
        self.work = self.base / 'work'
        for root in (self.personal, self.work):
            (root / 'projects').mkdir(parents=True)
            (root / 'AGENTS.md').write_text('Synthetic test workspace', encoding='utf-8')
        self.config = {'personal': str(self.personal), 'work': str(self.work)}

    def note(self, root, name, title, extra=''):
        (root / 'projects' / name).write_text('---\n' + extra + '---\n# ' + title + '\n', encoding='utf-8')

    def test_memory_entry_and_policy_changes_reload_instructions(self):
        before = route.discover(self.config, 'personal')['instructions']['revision']
        (self.personal / 'MEMORY.md').write_text('Synthetic entry')
        after = route.discover(self.config, 'personal', known_instructions=before)['instructions']
        self.assertTrue(after['reload_required'])
        self.assertNotEqual(before, after['revision'])
        (self.personal / 'system').mkdir()
        (self.personal / 'system/memory-maintenance.md').write_text('Synthetic policy')
        self.assertTrue(route.discover(self.config, 'personal', known_instructions=after['revision'])['instructions']['reload_required'])

    def test_work_never_falls_back_to_personal(self):
        self.config['work'] = None
        self.assertEqual(route.discover(self.config, 'work')['reason'], 'work_not_configured')
        self.assertEqual(route.discover(self.config, 'unknown')['reason'], 'scope_unknown')

    def test_scopes_isolate_same_project_names(self):
        self.note(self.personal, 'personal.md', 'Shared name')
        self.note(self.work, 'work.md', 'Shared name')
        found = route.discover(self.config, 'work', 'Shared name')
        self.assertEqual([x['path'] for x in found['candidates']], ['projects/work.md'])

    def test_nested_or_same_roots_are_blocked(self):
        for value in (str(self.personal), str(self.personal / 'company')):
            self.config['work'] = value
            self.assertEqual(route.discover(self.config, 'personal')['reason'], 'overlapping_roots')

    def test_alias_matches_without_new_project(self):
        self.note(self.personal, 'renamed.md', 'New name', 'aliases: ["Old name"]\n')
        self.assertEqual(route.discover(self.config, 'personal', 'old-name')['status'], 'registration_required')
        self.assertTrue(route.discover(self.config, 'personal', 'old-name')['candidates'][0]['exact'])

    def test_ambiguous_names_require_review(self):
        self.note(self.personal, 'one.md', 'Game')
        self.note(self.personal, 'two.md', 'Game')
        self.assertEqual(route.discover(self.config, 'personal', 'Game')['status'], 'registration_required')

    def test_unmatched_project_does_not_write(self):
        before = sorted(self.personal.rglob('*'))
        found = route.discover(self.config, 'personal', '../new-project')
        self.assertEqual(found['status'], 'registration_required')
        self.assertEqual(before, sorted(self.personal.rglob('*')))

    def test_archived_match_is_not_new(self):
        (self.personal / 'archive').mkdir()
        (self.personal / 'archive/old.md').write_text('# Old game\n', encoding='utf-8')
        self.assertEqual(route.discover(self.config, 'personal', 'Old game')['status'], 'registration_required')
        self.assertTrue(route.discover(self.config, 'personal', 'Old game')['candidates'][0]['archived'])

    def test_symlink_document_blocked(self):
        self.note(self.work, 'company.md', 'Company only')
        (self.personal / 'projects/link.md').symlink_to(self.work / 'projects/company.md')
        self.assertEqual(route.discover(self.config, 'personal')['reason'], 'symlink_document')

    def test_cli_from_unrelated_working_directory(self):
        self.note(self.personal, 'game.md', 'Game')
        config = self.base / 'config.json'
        config.write_text(json.dumps(self.config), encoding='utf-8')
        result = subprocess.run([sys.executable, str(SCRIPT), '--config', str(config),
                                 '--scope', 'personal', '--project', 'Game'],
                                cwd=self.work, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)['status'], 'registration_required')

    def test_reinstall_preserves_company_configuration(self):
        installer = SCRIPT.parents[3] / 'scripts/install_sync_skill.py'
        target = self.base / 'installed'
        command = [sys.executable, str(installer), '--target', str(target)]
        subprocess.run(command, capture_output=True, check=True)
        (target / 'config.json').write_text(json.dumps(self.config), encoding='utf-8')
        subprocess.run(command, capture_output=True, check=True)
        self.assertEqual(json.loads((target / 'config.json').read_text()), self.config)
        self.assertEqual((target / 'scripts/route.py').read_bytes(), SCRIPT.read_bytes())

    def test_pending_project_is_discoverable_before_integration(self):
        (self.personal / 'sessions/new-game').mkdir(parents=True)
        found = route.discover(self.config, 'personal', 'New Game')
        self.assertEqual(found['status'], 'registration_required')
        self.assertTrue(found['candidates'][0]['pending_only'])

    def test_instruction_revision_changes_when_policy_changes(self):
        first = route.discover(self.config, 'personal')['instructions']
        self.assertTrue(first['reload_required'])
        same = route.discover(self.config, 'personal', known_instructions=first['revision'])['instructions']
        self.assertFalse(same['reload_required'])
        (self.personal / 'AGENTS.md').write_text('Changed instructions')
        changed = route.discover(self.config, 'personal', known_instructions=first['revision'])['instructions']
        self.assertTrue(changed['reload_required'])

    def test_scope_switch_reloads_without_exposing_other_scope(self):
        first = route.discover(self.config, 'personal')['instructions']
        work = route.discover(self.config, 'work', known_instructions=first['revision'])['instructions']
        self.assertTrue(work['reload_required'])
        self.assertFalse(any(str(self.personal) in p['path'] for p in work['files']))

    def test_added_and_removed_policy_changes_revision(self):
        first = route.discover(self.config, 'personal')['instructions']['revision']
        (self.personal / 'system').mkdir()
        path = self.personal / 'system/git-workflow.md'
        path.write_text('New instruction')
        second = route.discover(self.config, 'personal')['instructions']['revision']
        self.assertNotEqual(first, second)
        path.unlink()
        self.assertTrue(route.discover(self.config, 'personal', known_instructions=second)['instructions']['reload_required'])

    def test_findings_policy_changes_instruction_revision(self):
        first = route.discover(self.config, 'work')['instructions']['revision']
        (self.work / 'findings').mkdir()
        policy = self.work / 'findings/README.md'
        policy.write_text('Synthetic findings policy', encoding='utf-8')
        changed = route.discover(self.config, 'work', known_instructions=first)['instructions']
        self.assertTrue(changed['reload_required'])
        self.assertTrue(any(item['path'] == str(policy) for item in changed['files']))

    def test_incidents_policy_changes_instruction_revision(self):
        first = route.discover(self.config, 'work')['instructions']['revision']
        (self.work / 'incidents').mkdir()
        policy = self.work / 'incidents/README.md'
        policy.write_text('Synthetic incidents policy', encoding='utf-8')
        changed = route.discover(self.config, 'work', known_instructions=first)['instructions']
        self.assertTrue(changed['reload_required'])
        self.assertTrue(any(item['path'] == str(policy) for item in changed['files']))

    def test_instruction_symlink_is_rejected(self):
        (self.personal / 'system').mkdir()
        (self.personal / 'system/privacy.md').symlink_to(self.work / 'AGENTS.md')
        with self.assertRaises(ValueError):
            route.discover(self.config, 'personal')

    def test_instruction_digest_does_not_cache_project_content(self):
        first = route.discover(self.config, 'personal')['instructions']['revision']
        self.note(self.personal, 'new-project.md', 'New data')
        result = route.discover(self.config, 'personal', known_instructions=first)
        self.assertFalse(result['instructions']['reload_required'])
        self.assertEqual(result['candidates'][0]['title'], 'New data')


if __name__ == '__main__':
    unittest.main()
