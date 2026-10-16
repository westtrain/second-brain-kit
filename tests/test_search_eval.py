import copy
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
sys.path.insert(0, str(SOURCE / 'scripts'))
from brain_access import BrainAccess
from evaluate_search import evaluate, validate_cases


class ScopedFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        shutil.copytree(SOURCE / 'examples/search-eval', self.base / 'fixtures')
        self.root = self.base / 'fixtures/work'
        self.access = BrainAccess(self.root, 'work')


class SearchTests(ScopedFixture):
    def test_scope_and_document_ids_are_bound_to_one_brain(self):
        with self.assertRaises(ValueError):
            BrainAccess(self.root, 'personal')
        work = self.access.search('문서 검토')['results'][0]
        personal = BrainAccess(self.base / 'fixtures/personal', 'personal')
        with self.assertRaises(ValueError):
            personal.get_document(work['document_id'])
        for value in ('../system/scope.json', '/etc/passwd', 'a' * 24):
            with self.assertRaises(ValueError):
                self.access.get_document(value)
        self.assertEqual(work['content_hash'], self.access.get_document(work['document_id'])['content_hash'])
        self.assertEqual(self.access.search('notes/review-cycle.md')['results'][0]['document_id'], work['document_id'])

    def test_sessions_are_visible_archive_is_explicit_and_excerpts_are_current(self):
        hits = self.access.search('로그인')['results']
        self.assertEqual({h['path'] for h in hits}, {'projects/reading-app.md', 'sessions/reading-app/new-test.md'})
        self.assertTrue(any(h['kind'] == 'session' for h in hits))
        self.assertEqual(len(self.access.search('로그인', include_archive=True)['results']), 3)
        old_id = hits[0]['document_id']
        p = self.root / hits[0]['path']
        p.write_text(p.read_text() + '\n추가 확인 근거\n')
        fresh = self.access.get_document(old_id, max_lines=100)
        self.assertIn('추가 확인 근거', fresh['excerpt'])
        self.assertNotEqual(fresh['content_hash'], hits[0]['content_hash'])

    def test_symlink_and_hardlink_reads_fail_closed(self):
        outside = self.base / 'outside.md'
        outside.write_text('outside marker')
        link = self.root / 'notes/link.md'
        link.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.access.search('outside')
        link.unlink()
        os.link(outside, link)
        with self.assertRaises(ValueError):
            self.access.search('outside')
        link.unlink()
        (self.root / 'notes/linked-dir').symlink_to(self.base, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            self.access.read_relative('notes/linked-dir/outside.md')
        for path in ('../outside.md', 'notes/../outside.md', '/etc/passwd'):
            with self.assertRaises(ValueError):
                self.access.read_relative(path)

    def test_root_symlinks_unknown_backends_and_invalid_limits_rejected(self):
        link = self.base / 'linked-root'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            BrainAccess(link, 'work')
        for limit in (-1, 0, True, 10000):
            with self.assertRaises(ValueError):
                self.access.search('검토', limit)
        with self.assertRaises(ValueError):
            self.access.search('검토', backend='unknown')
        with self.assertRaises(ValueError):
            self.access.search('검토', backend='qmd-hybrid')

    def test_parent_directory_replaced_by_symlink_after_startup_is_rejected(self):
        original = self.base / 'fixtures'
        retired = self.base / 'retired'
        original.rename(retired)
        original.symlink_to(retired, target_is_directory=True)
        with self.assertRaises(OSError):
            self.access.read_relative('notes/review-cycle.md')

    def test_qmd_adapter_discards_index_body_and_reopens_only_allowed_files(self):
        access = BrainAccess(self.root, 'work', qmd_index='synthetic-work', qmd_collection='work')
        raw = [{'file': './notes/review-cycle.md', 'line': 6, 'snippet': 'untrusted stale result'},
               {'file': str(self.root / 'archive/old-login.md'), 'snippet': 'not included'}]
        with patch('brain_access.subprocess.run', return_value=subprocess.CompletedProcess([], 0, json.dumps(raw), '')) as run:
            hits = access.search('문서 검토', backend='qmd-keyword')['results']
        self.assertEqual(len(hits), 1)
        self.assertIn('연 2회', hits[0]['excerpt'])
        self.assertNotIn('untrusted', hits[0]['excerpt'])
        argv = run.call_args.args[0]
        self.assertEqual(argv[argv.index('-c') + 1], 'work')
        self.assertEqual(argv[argv.index('--index') + 1], 'synthetic-work')
        self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_qmd_cross_scope_or_stale_results_are_errors(self):
        access = BrainAccess(self.root, 'work', qmd_index='synthetic-work', qmd_collection='work')
        paths = [str(self.base / 'fixtures/personal/notes/reading-habit.md'), 'qmd://work/deleted.md',
                 str(self.root / 'notes/deleted.md')]
        for path in paths:
            with self.subTest(path=path), patch('brain_access.subprocess.run', return_value=
                    subprocess.CompletedProcess([], 0, json.dumps([{'file': path}]), '')):
                if path.endswith('deleted.md') and path.startswith(str(self.root)):
                    # A no-longer-indexable in-root result is dropped; no cached body is exposed.
                    self.assertEqual(access.search('x', backend='qmd-hybrid')['results'], [])
                else:
                    with self.assertRaises(ValueError):
                        access.search('x', backend='qmd-hybrid')


class EvaluationTests(ScopedFixture):
    def cases(self):
        return json.loads((self.base / 'fixtures/cases.json').read_text())

    def test_metrics_expose_paraphrase_misses_and_separate_splits(self):
        result = evaluate(self.access, self.cases(), 'development')
        self.assertEqual(result['cases'], 4)
        self.assertEqual(result['positive_cases'], 3)
        self.assertAlmostEqual(result['metrics']['hit_rate_at_k'], 2 / 3)
        self.assertEqual(result['metrics']['no_answer_accuracy'], 1)
        self.assertEqual(result['metrics']['boundary_violations'], 0)
        self.assertEqual({d['id'] for d in result['details']}, {'work-001', 'work-002', 'work-003', 'work-004'})
        self.assertNotEqual(evaluate(self.access, self.cases(), 'test')['details'], result['details'])

    def test_ground_truth_must_be_reviewed_current_and_in_scope(self):
        for change in ('candidate', 'stale', 'escape', 'duplicate'):
            cases = copy.deepcopy(self.cases())
            if change == 'candidate':
                cases[0]['review_status'] = 'candidate'
            elif change == 'stale':
                cases[0]['evidence']['notes/review-cycle.md'] = 'a quote absent from the source'
            elif change == 'escape':
                cases[0]['forbidden_paths'] = ['../personal/notes/reading-habit.md']
            else:
                cases.append(cases[0])
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_cases(self.access, cases)

    def test_forbidden_results_and_incorrect_scope_are_reported(self):
        cases = [dict(id='negative', query='missing', scope='work', split='test', category='boundary',
                      review_status='reviewed', relevant_paths=[], evidence={}, forbidden_paths=['notes/forbidden.md'])]
        response = {'results': [dict(path='notes/forbidden.md', scope='personal', excerpt='x')]}
        with patch.object(self.access, 'search', return_value=response):
            result = evaluate(self.access, cases, 'test')
        self.assertEqual(result['metrics']['boundary_violations'], 2)
        self.assertEqual(result['metrics']['no_answer_accuracy'], 0)


if __name__ == '__main__':
    unittest.main()
