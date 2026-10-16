import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import memory_tools as memory
import session_sync


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / 'system').mkdir()
        data = {'version': 1, 'projects': [dict(id='parent', title='Parent', purpose='Synthetic', source='test', aliases=[], session_groups=['child'])]}
        self.write('system/project-registry.json', json.dumps(data))
        self.write('projects/parent.md', '---\nstatus: draft\nupdated: 2026-01-01\nas_of: 2026-01-01\nsource: test\n---\n# Parent\n\n## Blockers\n- Pending decision\n')

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def files(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_group_pending_receipts_and_missing_project(self):
        event = session_sync.record(self.root, 'child', 's', 'test', 'unknown', 'Synthetic')
        output = memory.render_index(self.root)
        self.assertIn('child: 1건', output)
        p = self.root / 'projects/parent.md'
        p.write_text(p.read_text().replace('status: draft', 'integrated_sessions: ' + json.dumps([event['id']]) + '\nstatus: draft'))
        self.assertIn('child: 0건', memory.render_index(self.root))
        p.unlink()
        self.assertIn('정본 없음', memory.render_index(self.root))

    def test_deterministic_and_read_only(self):
        before = self.files()
        first = memory.render_index(self.root)
        self.assertEqual(first, memory.render_index(self.root))
        one = memory.audit(self.root, dt.date(2026, 10, 16))
        self.assertEqual(one, memory.audit(self.root, dt.date(2026, 10, 16)))
        self.assertEqual(before, self.files())
        self.write('INDEX.md', first)
        self.assertNotIn('index-drift', {i['kind'] for i in memory.audit(self.root, dt.date(2026, 10, 16))})
        self.write('notes/new.md', '---\nstatus: draft\nupdated: 2026-01-01\n---\n# New\n충돌 후보\n[missing](missing.md)\n')
        kinds = {i['kind'] for i in memory.audit(self.root, dt.date(2026, 10, 16))}
        self.assertTrue({'index-drift', 'missing-source', 'broken-link', 'orphan-candidate', 'old-draft', 'stale-project', 'old-blocker-candidate', 'conflict-candidate'} <= kinds)

    def test_unknown_observed_uses_record_date_and_open_states(self):
        event = session_sync.record(self.root, 'child', 's', 'test', 'unknown', 'Synthetic')
        p = self.root / event['path']
        p.write_text(p.read_text().replace('updated: ' + memory.brain.today(), 'updated: 2026-01-01'))
        self.write('findings/open.md', '---\nstatus: confirmed\nstate: 열림\nupdated: 2026-01-01\nsource: test\n---\n# Open\n')
        self.write('findings/closed.md', '---\nstatus: confirmed\nstate: 해결됨\nupdated: 2026-01-01\nsource: test\n---\n# Closed\n')
        items = memory.audit(self.root, dt.date(2026, 10, 16))
        self.assertTrue(any(i['kind'] == 'old-pending' and 'observed=unknown' in i['reason'] for i in items))
        opened = [i['path'] for i in items if i['kind'] == 'old-open-item']
        self.assertEqual(opened, ['findings/open.md'])

    def test_reject_symlink_and_tampered_event(self):
        (self.root / 'notes').symlink_to(self.root / 'projects', target_is_directory=True)
        with self.assertRaises(ValueError):
            memory.render_index(self.root)
        (self.root / 'notes').unlink()
        event = session_sync.record(self.root, 'child', 's', 'test', '2026-10-16', 'Original')
        p = self.root / event['path']
        p.write_text(p.read_text().replace('Original', 'Changed'))
        with self.assertRaisesRegex(ValueError, 'immutable'):
            memory.render_index(self.root)


if __name__ == '__main__':
    unittest.main()
