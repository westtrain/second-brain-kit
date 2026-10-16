import concurrent.futures
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import brain
import session_sync as sync


def document(day='2026-09-12', status='작업 중'):
    return ('---\nstatus: confirmed\nupdated: 2026-09-12\nas_of: ' + day +
            '\nsource: "합성 테스트"\n---\n# Test\n\n## Current Status\n' + status +
            '\n\n## Next Actions\n테스트\n\n## Blockers\n없음\n\n## History\n시작\n\n## Decisions\n미정\n')


def concurrent_record(args):
    root, number = args
    for _ in range(100):
        try:
            return sync.record(Path(root), 'game', 'session-' + str(number), 'synthetic', '2026-09-12', '작업 ' + str(number))
        except ValueError as exc:
            if not str(exc).startswith('busy:'):
                raise
            time.sleep(.01)
    raise RuntimeError('lock retry exhausted')


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'system').mkdir()
        (self.root / 'system/project-registry.json').write_text(json.dumps({'version': 1, 'projects': [
            {'id': 'game', 'title': 'Game', 'purpose': 'Synthetic game', 'source': 'test',
             'aliases': [], 'session_groups': []}]}), encoding='utf-8')
        (self.root / 'projects').mkdir()
        self.project = self.root / 'projects/game.md'
        self.project.write_text(document(), encoding='utf-8')

    def event(self, session='one', observed='2026-09-12', body='구현 완료'):
        return sync.record(self.root, 'game', session, 'synthetic', observed, body)['id']

    def request(self, ids, mode='current', text=None):
        state = sync.snapshot(self.root, 'game')
        return {'project': 'game', 'expected': state['expected'], 'events': ids,
                'mode': mode, 'markdown': text or document(status='구현 완료')}

    def test_record_is_idempotent_and_project_unchanged(self):
        before = self.project.read_bytes()
        first = self.event()
        self.assertEqual(first, self.event())
        self.assertEqual(len(list((self.root / 'sessions/game').glob('*.md'))), 1)
        self.assertEqual(before, self.project.read_bytes())
        self.assertEqual(brain.check(self.root), [])

    def test_concurrent_writers_preserve_all_events(self):
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(concurrent_record, [(str(self.root), i) for i in range(12)]))
        self.assertEqual(len({r['id'] for r in results}), 12)
        self.assertEqual(len(sync.snapshot(self.root, 'game')['pending']), 12)

    def test_stale_integrator_rejected(self):
        first, second = self.event('A'), self.event('B')
        a, b = self.request([first]), self.request([second])
        sync.integrate(self.root, a)
        before = self.project.read_bytes()
        with self.assertRaisesRegex(ValueError, 'stale'):
            sync.integrate(self.root, b)
        self.assertEqual(before, self.project.read_bytes())
        self.assertEqual([x['id'] for x in sync.snapshot(self.root, 'game')['pending']], [second])

    def test_same_events_cannot_be_integrated_twice(self):
        event = self.event()
        sync.integrate(self.root, self.request([event]))
        with self.assertRaisesRegex(ValueError, 'already integrated'):
            sync.integrate(self.root, self.request([event]))
        self.assertEqual(sync.snapshot(self.root, 'game')['pending'], [])

    def test_old_or_unknown_dates_only_append_history(self):
        for index, date in enumerate(('2026-09-01', '2026-09', 'unknown')):
            event = self.event(str(index), date)
            with self.assertRaises(ValueError):
                sync.integrate(self.root, self.request([event]))
            old = self.project.read_text()
            sync.integrate(self.root, self.request([event], mode='history'))
            new = self.project.read_text()
            self.assertIn(old.split('\n---\n', 1)[1].rstrip(), new)
            self.assertEqual(sync.date_field(new, 'as_of'), sync.date_field(old, 'as_of'))

    def test_failed_replace_leaves_receipts_and_state_unchanged(self):
        event = self.event()
        before = self.project.read_bytes()
        with patch.object(sync.os, 'replace', side_effect=OSError('simulated failure')):
            with self.assertRaises(OSError):
                sync.integrate(self.root, self.request([event]))
        self.assertEqual(before, self.project.read_bytes())
        self.assertEqual(len(sync.snapshot(self.root, 'game')['pending']), 1)
        self.assertFalse(list(self.root.rglob('.session-write-*')))

    def test_tampering_detected(self):
        event = self.event()
        path = self.root / 'sessions/game' / (event + '.md')
        path.write_text(path.read_text() + '변경')
        with self.assertRaisesRegex(ValueError, 'immutable'):
            sync.snapshot(self.root, 'game')

    def test_secret_rejected_before_event_storage(self):
        with self.assertRaises(ValueError):
            self.event(body='api_' + 'key: ' + 'x' * 30)
        self.assertFalse((self.root / 'sessions').exists())

    def test_repeated_event_frontmatter_rejected_before_storage(self):
        body = ('---\nstatus: draft\nupdated: 2026-09-20\nproject: "game"\n'
                'session: "one"\nsource: "synthetic"\nobserved: "2026-09-12"\n'
                '---\n구현 완료')
        with self.assertRaisesRegex(ValueError, 'must not repeat'):
            self.event(body=body)
        self.assertFalse((self.root / 'sessions').exists())

    def test_legacy_repeated_frontmatter_is_ignored_without_editing_event(self):
        repeated = ('---\nstatus: draft\nupdated: 2026-09-20\nproject: "game"\n'
                    'session: "legacy"\nsource: "synthetic"\nobserved: "2026-09-12"\n'
                    '---\n구현 완료')
        data = {'project': 'game', 'session': 'legacy', 'source': 'synthetic',
                'observed': '2026-09-12', 'summary': repeated}
        event_id = sync.digest(json.dumps(data, sort_keys=True, ensure_ascii=False))
        path = self.root / 'sessions/game' / (event_id + '.md')
        path.parent.mkdir(parents=True)
        header = '\n'.join(key + ': ' + json.dumps(value, ensure_ascii=False)
                           for key, value in data.items() if key != 'summary')
        path.write_text('---\nstatus: draft\nupdated: 2026-09-20\n' + header +
                        '\n---\n' + repeated + '\n', encoding='utf-8')
        before = path.read_bytes()

        event = sync.read_event(path)

        self.assertEqual(event['summary'], '구현 완료')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(sync.snapshot(self.root, 'game')['pending'][0]['summary'], '구현 완료')

    def test_symlink_and_traversal_rejected(self):
        (self.root / 'sessions').symlink_to(self.root / 'projects', target_is_directory=True)
        with self.assertRaises(ValueError):
            self.event()
        with self.assertRaises(ValueError):
            sync.record(self.root, '../outside', 's', 'test', 'unknown', 'text')

    def test_new_project_and_new_arrivals(self):
        self.project.unlink()
        event = self.event()
        request = self.request([event])
        later = self.event('later')
        sync.integrate(self.root, request)
        self.assertEqual([x['id'] for x in sync.snapshot(self.root, 'game')['pending']], [later])
        self.assertEqual(brain.check(self.root), [])

    def test_lock_released_on_error(self):
        with self.assertRaises(RuntimeError):
            with sync.locked(self.root):
                raise RuntimeError('failure')
        self.event()

    def test_broken_link_rejects_entire_integration(self):
        event = self.event()
        before = self.project.read_bytes()
        with self.assertRaisesRegex(ValueError, 'invalid project link'):
            sync.integrate(self.root, self.request([event], text=document() + '\n[missing](missing.md)\n'))
        self.assertEqual(before, self.project.read_bytes())
        self.assertEqual(len(sync.snapshot(self.root, 'game')['pending']), 1)

    def test_same_input_from_concurrent_processes_is_one_event(self):
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(concurrent_record, [(str(self.root), 1)] * 8))
        self.assertEqual(len({r['id'] for r in results}), 1)
        self.assertEqual(len(sync.snapshot(self.root, 'game')['pending']), 1)


if __name__ == '__main__':
    unittest.main()
