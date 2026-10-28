import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'scripts'))
from brain_access import BrainAccess
import knowledge as k
import knowledge_workflow as workflow


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / 'brain'
        subprocess.run([sys.executable, str(SOURCE / 'scripts/init_brain.py'), '--target', str(self.root)],
                       capture_output=True, text=True, check=True)
        self.access = BrainAccess(self.root, 'personal')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()

    def capture(self, body='Synthetic retry operation was delivered twice.'):
        return workflow.execute(self.root, 'personal', 'capture',
                                dict(title='Fictional task', source='Synthetic test fixture', source_kind='work', body=body), 'routine')['result']['path']

    def note(self, path):
        text = self.access.read_relative(path)
        return dict(id='retry-rule', expected=k.fingerprint(''), kind='concept', title='Synthetic retry rule',
                    summary='Preserve logical request identity before retrying.', conditions=['Same logical request.'],
                    limits=['Crash recovery is not established.'], open_questions=['How should partial completion be recovered?'],
                    change_reason='A hypothesis extracted from fictional evidence.',
                    evidence=dict(status='supported', sources=[dict(path=path, hash=k.fingerprint(text),
                                  quote='Synthetic retry operation was delivered twice.', relation='supports')],
                                  claims=[dict(text='Retries need an explicit logical identity.', confidence='inferred', sources=[0])]))

    def test_capture_is_idempotent_and_main_direct_writes_are_rejected(self):
        first = self.capture()
        before = self.git('rev-parse', 'HEAD')
        self.assertEqual(first, self.capture())
        self.assertEqual(before, self.git('rev-parse', 'HEAD'))
        with self.assertRaises(ValueError):
            k.capture(self.access, dict(title='No', source='Synthetic', source_kind='pdf', body='Not an actual PDF parser'))
        self.assertEqual(self.git('status', '--short'), '')

    def test_source_versions_quotes_and_claim_refs_are_verified(self):
        path = self.capture()
        request = self.note(path)['evidence']
        self.assertTrue(k.verify(self.access, request)['verified'])
        for field, value in [('hash', '0' * 64), ('quote', 'invented quotation'), ('path', '../other-brain/private.md')]:
            invalid = copy.deepcopy(request)
            invalid['sources'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                k.verify(self.access, invalid)
        invalid = copy.deepcopy(request)
        invalid['claims'][0]['sources'] = [99]
        with self.assertRaisesRegex(ValueError, 'source indices'):
            k.verify(self.access, invalid)
        self.assertEqual(self.git('status', '--short'), '')

    def test_not_covered_cannot_hide_an_unsupported_answer(self):
        self.assertEqual(k.verify(self.access, dict(status='not_covered', sources=[], claims=[]))['status'], 'not_covered')
        with self.assertRaises(ValueError):
            k.verify(self.access, dict(status='not_covered', sources=[], claims=['An unsupported answer']))
        with self.assertRaises(ValueError):
            k.verify(self.access, dict(status='supported', sources=[], claims=[]))

    def test_budget_scope_and_explicit_document_selection(self):
        path = self.capture()
        packet = k.context(self.access, [path])
        self.assertEqual([d['path'] for d in packet['documents']], [path])
        self.assertEqual(packet['documents'][0]['hash'], k.fingerprint(self.access.read_relative(path)))
        with self.assertRaisesRegex(ValueError, 'budget'):
            k.context(self.access, [path], 100)
        with self.assertRaises(ValueError):
            k.context(self.access, ['../other-brain/private.md'])
        with self.assertRaises(ValueError):
            BrainAccess(self.root, 'work')
        with self.assertRaises(ValueError):
            k.context(self.access, [path, path])
        self.assertEqual(self.git('status', '--short'), '')

    def test_history_is_retained_and_stale_update_does_not_replace_main(self):
        request = self.note(self.capture())
        result = workflow.execute(self.root, 'personal', 'distill', request, 'routine')
        note_path = result['result']['path']
        old = self.access.read_relative(note_path)
        update = dict(request, expected=k.fingerprint(old), summary='Identity needs a separate partial-completion recovery rule.',
                      change_reason='Narrow the earlier hypothesis; recovery is still unverified.')
        workflow.execute(self.root, 'personal', 'distill', update, 'routine')
        current = self.access.read_relative(note_path)
        self.assertIn(request['summary'], current)
        self.assertIn(update['summary'], current)
        self.assertIn(old.split('\n---\n', 1)[1], current)
        source = request['evidence']['sources'][0]['path']
        self.assertIn(note_path, k.context(self.access, [source])['documents'][0]['related_paths'])
        before = self.git('rev-parse', 'HEAD')
        with self.assertRaisesRegex(ValueError, 'stale note'):
            workflow.execute(self.root, 'personal', 'distill', update, 'routine')
        self.assertEqual(before, self.git('rev-parse', 'HEAD'))
        self.assertEqual(current, self.access.read_relative(note_path))

    def test_duplicate_canonical_title_and_fake_synthesis_are_rejected(self):
        request = self.note(self.capture())
        with self.assertRaisesRegex(ValueError, 'two different'):
            workflow.execute(self.root, 'personal', 'distill', dict(request, kind='synthesis'), 'routine')
        workflow.execute(self.root, 'personal', 'distill', request, 'routine')
        before = self.git('rev-parse', 'HEAD')
        with self.assertRaisesRegex(ValueError, 'canonical ID'):
            workflow.execute(self.root, 'personal', 'distill', dict(request, id='renamed-duplicate'), 'routine')
        self.assertEqual(before, self.git('rev-parse', 'HEAD'))

    def test_capture_secret_remote_and_symlink_are_blocked(self):
        with self.assertRaises(ValueError):
            workflow.execute(self.root, 'personal', 'capture', dict(title='Synthetic', source='fixture',
                             source_kind='conversation', body='sk-' + 'a' * 30), 'routine')
        self.git('remote', 'add', 'origin', 'https://example.invalid/never-contact')
        with self.assertRaisesRegex(ValueError, 'without remotes'):
            self.capture()
        self.git('remote', 'remove', 'origin')
        outside = Path(self.tmp.name) / 'outside.md'
        outside.write_text('Synthetic external content')
        (self.root / 'notes' / 'escape.md').symlink_to(outside)
        with self.assertRaises(ValueError):
            k.catalog(self.access)

    def test_default_review_does_not_change_main(self):
        path = self.capture()
        before = self.git('rev-parse', 'HEAD')
        result = workflow.execute(self.root, 'personal', 'distill', self.note(path))
        self.assertEqual(result['state'], 'review')
        self.assertEqual(before, self.git('rev-parse', 'HEAD'))
        self.assertFalse((self.root / 'notes/retry-rule.md').exists())

    def test_complete_synthetic_demo_installs_and_runs_from_generated_brain(self):
        target = Path(self.tmp.name).resolve() / 'demo'
        result = subprocess.run([sys.executable, str(SOURCE / 'examples/knowledge_demo.py'), '--target', str(target)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertTrue(output['no_model_called'])
        self.assertEqual(len(output['receipts']), 4)
        self.assertTrue(all(r['state'] == 'merged' for r in output['receipts']))
        self.assertEqual(output['missing_answer']['status'], 'not_covered')
        self.assertEqual(set(output['verified_outputs']), {'answer', 'quiz', 'report', 'decision'})
        self.assertTrue((target / 'skills/second-brain-sync/references/knowledge.md').is_file())
        self.assertEqual(subprocess.check_output(['git', '-C', str(target), 'status', '--short'], text=True), '')
        # Generated brains carry the walkthrough and tools; test that copy too.
        second = Path(self.tmp.name).resolve() / 'second-demo'
        result = subprocess.run([sys.executable, str(target / 'examples/knowledge_demo.py'), '--target', str(second)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
