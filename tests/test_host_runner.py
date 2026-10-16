import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SOURCE / 'automation'), str(SOURCE / 'scripts')]
import host_runner as host
import schedule_state as state


class HostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'brain'
        # Copy tools only. Actual company notes never enter temporary test repositories.
        self.root.mkdir()
        shutil.copytree(SOURCE / 'scripts', self.root / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
        (self.root / 'system').mkdir()
        (self.root / 'projects').mkdir()
        (self.root / 'AGENTS.md').write_text('Synthetic test repository')
        (self.root / '.gitignore').write_text('.brain-sync.lock\n__pycache__/\n')
        self.project = 'test-project'
        entry = dict(id=self.project, title='Synthetic', purpose='Synthetic test outcome', source='Synthetic test', aliases=[], session_groups=[])
        (self.root / 'system/project-registry.json').write_text(json.dumps(dict(version=1, projects=[entry])))
        document = '---\nstatus: draft\nupdated: 2026-09-30\nas_of: 2026-09-30\nsource: Synthetic test\n---\n# Synthetic\n'
        for heading in ('Current Status', 'Next Actions', 'Blockers', 'History', 'Decisions'):
            document += '\n## ' + heading + '\nSynthetic test content.\n'
        (self.root / 'projects' / (self.project + '.md')).write_text(document)
        host.sessions.record(self.root, self.project, 's-old', 'Synthetic test', '2026-09-01', 'Synthetic historical event')
        host.sessions.record(self.root, self.project, 's-recent', 'Synthetic test', '2026-10-01', 'Synthetic current event')
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.com')
        self.git('config', 'gc.auto', '0')
        self.git('config', 'maintenance.auto', 'false')
        self.git('add', '.')
        self.git('commit', '-m', 'fixture')
        self.snapshot = host.snapshot(self.root, self.project)

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], capture_output=True, text=True, check=True).stdout.strip()

    def deferred(self):
        return {'current': [], 'history': [], 'markdown': '', 'deferred': [dict(id=e['id'], reason='Synthetic review pending') for e in self.snapshot['pending']]}

    def test_reject_unknown_duplicate_missing_ids_before_writing(self):
        before = self.git('rev-parse', 'HEAD')
        for change in ('unknown', 'duplicate', 'missing'):
            result = self.deferred()
            if change == 'unknown':
                result['current'] = ['f' * 64]
            elif change == 'duplicate':
                result['history'] = [self.snapshot['pending'][0]['id']]
            else:
                result['deferred'] = []
            with self.assertRaises(ValueError):
                host.apply_integration(self.root, self.snapshot, result)
            self.assertEqual(self.git('rev-parse', 'HEAD'), before)
        self.assertEqual(self.git('status', '--short'), '')

    def test_stale_plan_rejected_and_verified_history_uses_real_workflow(self):
        result = self.deferred()
        old = next(e for e in self.snapshot['pending'] if e['observed'] < '2026-09-30')
        result['history'] = [old['id']]
        result['deferred'] = [e for e in result['deferred'] if e['id'] != old['id']]
        altered = dict(self.snapshot, expected='0' * 64)
        with self.assertRaisesRegex(ValueError, 'snapshot changed'):
            host.apply_integration(self.root, altered, result)
        original = (self.root / old['path']).read_bytes()
        applied = host.apply_integration(self.root, self.snapshot, result)
        self.assertEqual(len(applied), 1)
        self.assertIn(old['id'], host.sessions.receipts(host.snapshot(self.root, self.project)['markdown']))
        self.assertEqual(original, (self.root / old['path']).read_bytes())
        self.assertEqual(self.git('status', '--short'), '')

    def test_current_update_and_receipts_use_real_workflow(self):
        import re
        observed = host.brain.today()
        event = host.sessions.record(self.root, self.project, 'host-synthetic', 'synthetic test', observed, 'Synthetic current result')
        self.git('add', event['path'])
        self.git('commit', '-m', 'synthetic current event')
        state = host.snapshot(self.root, self.project)
        markdown = re.sub(r'^as_of: .*$', 'as_of: ' + observed, state['markdown'], flags=re.M)
        markdown = re.sub(r'^updated: .*$', 'updated: ' + observed, markdown, flags=re.M)
        markdown += '\n- [Synthetic result](../' + event['path'] + ')\n'
        result = {'current': [event['id']], 'history': [], 'markdown': markdown,
                  'deferred': [dict(id=e['id'], reason='review') for e in state['pending'] if e['id'] != event['id']]}
        applied = host.apply_integration(self.root, state, result)
        self.assertEqual(applied[0]['events'], [event['id']])
        self.assertIn(event['id'], host.sessions.receipts(host.snapshot(self.root, self.project)['markdown']))

    def test_history_cannot_hide_current_events(self):
        result = self.deferred()
        recent = next(e for e in self.snapshot['pending'] if e['observed'] >= '2026-09-30')
        result['history'] = [recent['id']]
        result['deferred'] = [e for e in result['deferred'] if e['id'] != recent['id']]
        with self.assertRaisesRegex(ValueError, 'nonhistorical'):
            host.apply_integration(self.root, self.snapshot, result)

    def test_planner_failure_is_failed_not_success_and_remote_rejected(self):
        report = host.execute('integration', self.root, lambda *_: (_ for _ in ()).throw(ValueError('planner failed')))
        self.assertEqual(report['outcome'], 'failed')
        self.git('remote', 'add', 'origin', 'https://example.invalid/no-network')
        report = host.execute('integration', self.root, lambda *_: self.fail('must not plan'))
        self.assertEqual(report['outcome'], 'failed')

    def test_all_deferred_has_no_commit_and_blog_without_evidence_noop_plan(self):
        before = self.git('rev-parse', 'HEAD')
        def planner(task, context):
            s = context['snapshot']
            return {'current': [], 'history': [], 'markdown': '', 'deferred': [dict(id=e['id'], reason='review') for e in s['pending']]}
        report = host.execute('integration', self.root, planner)
        self.assertEqual(report['outcome'], 'deferred')
        self.assertEqual(before, self.git('rev-parse', 'HEAD'))
        with patch.object(host, 'blog_context', return_value={'evidence': {}, 'existing_candidates': []}):
            report = host.execute('blog', self.root, lambda *_: self.fail('must not plan'))
        self.assertEqual(report['outcome'], 'deferred')

    def test_blog_pair_provenance_and_real_application(self):
        evidence = {'projects/' + self.project + '.md': self.snapshot['markdown']}
        context = {'evidence': {self.project: evidence}, 'existing_candidates': host.exports.catalog(self.root)}
        candidates = [dict(id='synthetic-host-test-' + lang, project=self.project, title='Synthetic', body='Synthetic independent body ' + lang,
                           sources=list(evidence), review_notes='Synthetic test pair; verify before export') for lang in ('ko', 'en')]
        result = dict(candidates=candidates, reason='Synthetic test')
        host.validate_blog(context, result)
        with patch.object(host, 'blog_context', return_value=context):
            applied = host.apply_blog(self.root, context, result)
        self.assertEqual(len(applied), 1)
        for candidate in candidates:
            saved, _ = host.exports.read(self.root, candidate['id'])
            self.assertEqual(saved['state'], 'draft')
        with self.assertRaises(ValueError):
            host.validate_blog(context, dict(candidates=candidates[:1], reason='Incomplete pair'))
        candidates[0]['sources'] = ['system/privacy.md']
        with self.assertRaises(ValueError):
            host.validate_blog(context, result)


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.env = patch.dict(os.environ, SECOND_BRAIN_AUTOMATION_STATE_DIR=str(self.base))
        self.env.start()
        self.addCleanup(self.env.stop)
        self.current = dt.datetime.fromisoformat('2026-10-16T14:00:00+09:00')

    def record(self, outcome):
        result = dict(protocol=2, task='integration', outcome=outcome, reason='test', applied=[], deferred=[])
        evidence = self.base / ('result-' + outcome + '.json')
        evidence.write_text(json.dumps(result))
        state.record('integration', self.current, result, str(evidence))
        return evidence

    def test_legacy_false_success_is_due_and_backed_up(self):
        state.write('integration', self.current, 'success')
        self.assertFalse(state.completed('integration', self.current))
        self.record('success')
        self.assertTrue(state.completed('integration', self.current))
        self.assertTrue(list((self.base / 'history').glob('*.json')))

    def test_failed_retries_deferred_not_success_and_tamper_retries(self):
        self.record('failed')
        self.assertIn('integration', state.due(self.current))
        target = self.record('deferred')
        self.assertNotIn('integration', state.due(self.current))
        self.assertNotIn('completed_at', state.read('integration'))
        target.write_text('{}')
        self.assertIn('integration', state.due(self.current))
        self.record('noop')
        self.assertTrue(state.completed('integration', self.current))
        self.assertIn('integration', state.due(self.current + dt.timedelta(days=7)))


if __name__ == '__main__':
    unittest.main()
