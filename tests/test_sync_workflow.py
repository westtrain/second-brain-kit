import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1]


class SyncWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'brain'
        shutil.copytree(SOURCE, self.root, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        (self.root / 'system/project-registry.json').write_text(json.dumps({'version': 1, 'projects': [
            dict(id='synthetic-project', title='Synthetic project', purpose='Test only', source='Synthetic test', aliases=[], session_groups=[])
        ]}))
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Test User')
        self.git('config', 'user.email', 'test@example.com')
        self.git('config', 'gc.auto', '0')
        self.git('config', 'maintenance.auto', 'false')
        self.git('add', '.')
        self.git('commit', '-m', 'initial')
        registry = json.loads((self.root / 'system/project-registry.json').read_text(encoding='utf-8'))
        self.project_id = registry['projects'][0]['id']

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], capture_output=True,
                              text=True, check=True).stdout.strip()

    def invoke(self, *args, body=''):
        return subprocess.run([sys.executable, str(self.root / 'scripts/sync_workflow.py'), *args],
                              input=body, capture_output=True, text=True)

    def record_args(self, risk='routine', session='test-session'):
        return ('record', '--risk', risk, '--project', self.project_id, '--session', session,
                '--source', 'synthetic test', '--observed', '2026-09-14')

    def test_direct_mutation_on_canonical_is_rejected(self):
        before = set((self.root / 'sessions' / self.project_id).glob('*.md'))
        result = subprocess.run(
            [sys.executable, str(self.root / 'scripts/session_sync.py'), 'record',
             '--project', self.project_id, '--session', 'direct',
             '--source', 'synthetic', '--observed', '2026-09-14'],
            input='직접 쓰기', capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('linked worktree', result.stderr)
        self.assertEqual(before, set((self.root / 'sessions' / self.project_id).glob('*.md')))

    def test_routine_record_commits_and_fast_forwards_local_main(self):
        before = self.git('rev-parse', 'HEAD')
        result = self.invoke(*self.record_args(), body='공통 실행기 저장 테스트')
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['state'], 'merged')
        self.assertNotEqual(before, self.git('rev-parse', 'HEAD'))
        self.assertEqual(self.git('status', '--short'), '')
        self.assertTrue((self.root / output['result']['path']).is_file())
        self.assertEqual(self.git('ls-files', output['result']['path']), output['result']['path'])
        self.assertIn(output['result']['path'], (self.root / 'INDEX.md').read_text())
        index_check = subprocess.run([sys.executable, str(self.root / 'scripts/memory_tools.py'), 'index', '--check'], capture_output=True)
        self.assertEqual(index_check.returncode, 0, index_check.stderr)

    def test_review_record_leaves_canonical_main_unchanged(self):
        before = self.git('rev-parse', 'HEAD')
        result = self.invoke(*self.record_args('review', 'review-session'), body='검토 대기 테스트')
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['state'], 'review')
        self.assertEqual(before, self.git('rev-parse', 'HEAD'))
        self.assertTrue(Path(output['worktree'], output['result']['path']).is_file())

    def test_adopt_preserves_existing_untracked_event_exactly(self):
        data = {'project': self.project_id, 'session': 'legacy-session',
                'source': 'synthetic', 'observed': '2026-09-14', 'summary': '기존 미추적 기록'}
        event_id = hashlib.sha256(json.dumps(
            data, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
        relative = 'sessions/' + self.project_id + '/' + event_id + '.md'
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        header = '\n'.join(key + ': ' + json.dumps(value, ensure_ascii=False)
                           for key, value in data.items() if key != 'summary')
        path.write_text('---\nstatus: draft\nupdated: 2026-09-14\n' + header +
                        '\n---\n' + data['summary'] + '\n', encoding='utf-8')
        original = path.read_bytes()
        adopted = self.invoke('adopt', '--risk', 'routine', '--event', relative)
        self.assertEqual(adopted.returncode, 0, adopted.stderr)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.git('ls-files', relative), relative)
        self.assertEqual(self.git('status', '--short'), '')


if __name__ == '__main__':
    unittest.main()
