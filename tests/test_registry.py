import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import project_registry as registry
import session_sync as sync


def entry(key, aliases=None, groups=None):
    return {'id': key, 'title': key, 'purpose': 'Synthetic independent outcome', 'source': 'test',
            'aliases': aliases or [], 'session_groups': groups or []}


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'system').mkdir()
        self.file = self.root / 'system/project-registry.json'
        self.data = {'version': 1, 'projects': [entry('parent', ['TASK-1'], ['child-a', 'child-b']), entry('separate', ['TASK-10'])]}
        self.save()

    def save(self):
        self.file.write_text(json.dumps(self.data), encoding='utf-8')

    def record(self, project):
        return sync.record(self.root, project, 's', 'test', '2026-09-12', 'Synthetic outcome')

    def test_explicit_groups_aggregate_without_changing_originals(self):
        a = self.record('child-a')
        b = self.record('child-b')
        self.record('separate')
        path = self.root / a['path']
        before = path.read_bytes()
        state = sync.snapshot(self.root, 'child-a')
        self.assertEqual(state['project'], 'parent')
        self.assertEqual({x['id'] for x in state['pending']}, {a['id'], b['id']})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(sync.snapshot(self.root, 'separate')['pending']), 1)

    def test_distinct_new_project_does_not_enter_existing_parent(self):
        sync.register(self.root, {'expected_registry': registry.load(self.root)[1], 'entry': entry('new-product')})
        self.record('new-product')
        self.assertEqual(sync.snapshot(self.root, 'parent')['pending'], [])
        self.assertEqual(len(sync.snapshot(self.root, 'new-product')['pending']), 1)

    def test_unknown_project_rejected_without_event_file(self):
        with self.assertRaisesRegex(ValueError, 'unregistered'):
            self.record('unknown-project')
        self.assertFalse((self.root / 'sessions').exists())

    def test_ticket_alias_saves_into_canonical_group(self):
        event = self.record('task-1')
        self.assertIn('sessions/parent/', event['path'])
        self.assertEqual(sync.snapshot(self.root, 'parent')['pending'][0]['id'], event['id'])

    def test_ticket_boundaries_and_multiple_projects(self):
        self.assertEqual(registry.resolve(self.root, 'TASK-1 작업')[0]['id'], 'parent')
        self.assertEqual(registry.resolve(self.root, 'TASK-10 작업')[0]['id'], 'separate')
        with self.assertRaises(ValueError):
            registry.resolve(self.root, 'TASK-1과 TASK-10 작업')
        with self.assertRaises(ValueError):
            registry.resolve(self.root, 'TASK-100')

    def test_duplicate_alias_or_group_rejected(self):
        for extra in (entry('other', ['TASK-1']), entry('other', groups=['child-a']), entry('child-a')):
            with self.assertRaises(ValueError):
                registry.validate({'version': 1, 'projects': self.data['projects'] + [extra]})

    def test_registry_change_invalidates_integration(self):
        event = self.record('child-a')
        state = sync.snapshot(self.root, 'parent')
        self.data['projects'][0]['aliases'].append('another-name')
        self.save()
        with self.assertRaisesRegex(ValueError, 'stale'):
            sync.integrate(self.root, {'project': 'parent', 'expected': state['expected'], 'events': [event['id']], 'mode': 'history'})

    def test_foreign_event_cannot_be_consumed(self):
        event = self.record('separate')
        state = sync.snapshot(self.root, 'parent')
        with self.assertRaisesRegex(ValueError, 'events missing'):
            sync.integrate(self.root, {'project': 'parent', 'expected': state['expected'], 'events': [event['id']], 'mode': 'history'})

    def test_registration_requires_current_registry(self):
        revision = registry.load(self.root)[1]
        sync.register(self.root, {'expected_registry': revision, 'entry': entry('first-new')})
        with self.assertRaisesRegex(ValueError, 'stale registry'):
            sync.register(self.root, {'expected_registry': revision, 'entry': entry('second-new')})

    def test_cannot_claim_existing_records_through_new_registration(self):
        (self.root / 'sessions/unassigned').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'ownership review'):
            sync.register(self.root, {'expected_registry': registry.load(self.root)[1],
                                      'entry': entry('new-project', groups=['unassigned'])})

    def test_registry_symlink_rejected(self):
        self.file.unlink()
        self.file.symlink_to(self.root / 'not-a-registry')
        with self.assertRaises(ValueError):
            registry.load(self.root)

    def test_confirmed_binding_and_foreign_key_rejection(self):
        sync.bind(self.root, {'expected_registry': registry.load(self.root)[1], 'project': 'parent',
                             'aliases': ['TASK-2'], 'session_groups': ['child-c'], 'source': 'User confirmed test relation'})
        self.assertEqual(registry.resolve(self.root, 'TASK-2')[0]['id'], 'parent')
        self.record('child-c')
        self.assertEqual(len(sync.snapshot(self.root, 'parent')['pending']), 1)
        before = self.file.read_bytes()
        with self.assertRaises(ValueError):
            sync.bind(self.root, {'expected_registry': registry.load(self.root)[1], 'project': 'parent',
                                 'aliases': ['TASK-10'], 'source': 'test'})
        self.assertEqual(before, self.file.read_bytes())


if __name__ == '__main__':
    unittest.main()
