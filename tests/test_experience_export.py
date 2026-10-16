import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import experience_export as export


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.work, self.personal = self.base / 'work', self.base / 'personal'
        for root in (self.work, self.personal):
            root.mkdir()
            (root / 'AGENTS.md').write_text('test')
        (self.work / 'system').mkdir()
        (self.work / 'system/project-registry.json').write_text(json.dumps({'version': 1, 'projects': [
            {'id': 'example', 'title': 'Example', 'purpose': 'Test', 'source': 'Test', 'aliases': [], 'session_groups': []}]}))
        (self.work / 'projects').mkdir()
        (self.work / 'projects/example.md').write_text('Synthetic evidence. INTERNAL_SENTINEL')
        self.request = {'id': 'race-condition', 'project': 'example', 'kind': 'blog',
                        'expected': export.digest(''), 'title': '동시성 문제 해결',
                        'body': '가상 사례로 설명하는 상태 전이와 검증 방법.',
                        'sources': ['projects/example.md'], 'review_notes': 'PRIVATE_REVIEW_SENTINEL'}

    def propose(self):
        return export.propose(self.work, self.request)

    def review(self):
        data = self.propose()
        return export.review(self.work, {'id': data['id'], 'expected': data['expected']})

    def approval(self, review):
        return {'id': review['id'], 'review_hash': review['review_hash'],
                'approved_for': 'personal-storage', 'approval_source': 'Synthetic user approval'}

    def bind(self, company='first-employer', project='example'):
        _, revision = export.companies(self.work)
        _, project_revision = export.registry.load(self.work)
        return export.bind_company(self.work, {'company_id': company, 'company_name': company,
            'projects': [project], 'source': 'Synthetic employment ownership',
            'expected': revision, 'expected_registry': project_revision})

    def test_no_personal_content_before_approval(self):
        self.review()
        self.assertEqual([p.name for p in self.personal.iterdir()], ['AGENTS.md'])

    def test_only_reviewed_body_exported_and_searchable(self):
        review = self.review()
        result = export.release(self.work, self.personal, self.approval(review))
        body = Path(result['path']).read_text()
        self.assertEqual(body, review['markdown'])
        for private in ('INTERNAL_SENTINEL', 'PRIVATE_REVIEW_SENTINEL', 'projects/example.md', 'approval_source'):
            self.assertNotIn(private, body)
        self.assertEqual(list(export.brain.search(self.personal, '동시성')), ['blog/race-condition.md'])
        self.assertEqual(export.brain.check(self.personal), [])

    def test_missing_approval_and_wrong_hash_rejected(self):
        review = self.review()
        for key in ('approved_for', 'approval_source', 'review_hash'):
            request = self.approval(review)
            request[key] = ''
            with self.assertRaises(ValueError):
                export.release(self.work, self.personal, request)
        self.assertFalse((self.personal / 'blog').exists())

    def test_frozen_review_and_stale_edits(self):
        review = self.review()
        self.request['expected'] = review['expected']
        with self.assertRaises(ValueError):
            self.propose()
        reopened = export.reopen(self.work, {'id': review['id'], 'expected': review['expected']})
        self.request.update(expected=reopened['expected'], body='수정된 설명')
        current = self.propose()
        with self.assertRaises(ValueError):
            self.propose()
        new_review = export.review(self.work, {'id': current['id'], 'expected': current['expected']})
        self.assertNotEqual(new_review['review_hash'], review['review_hash'])
        with self.assertRaises(ValueError):
            export.release(self.work, self.personal, self.approval(review))

    def test_idempotent_release_does_not_overwrite_personal_edits(self):
        review = self.review()
        approval = self.approval(review)
        result = export.release(self.work, self.personal, approval)
        self.assertEqual(result, export.release(self.work, self.personal, approval))
        Path(result['path']).write_text('User edits')
        with self.assertRaises(ValueError):
            export.release(self.work, self.personal, approval)
        self.assertEqual(Path(result['path']).read_text(), 'User edits')

    def test_retry_after_copy_before_receipt(self):
        review = self.review()
        atomic = export.atomic
        def fail_receipt(path, body):
            if path.suffix == '.json':
                raise OSError('simulated interrupted receipt')
            atomic(path, body)
        with patch.object(export, 'atomic', side_effect=fail_receipt):
            with self.assertRaises(OSError):
                export.release(self.work, self.personal, self.approval(review))
        self.assertEqual(export.read(self.work, review['id'])[0]['state'], 'review')
        export.release(self.work, self.personal, self.approval(review))
        self.assertEqual(len(list((self.personal / 'blog').glob('*.md'))), 1)

    def test_review_tampering_rejected(self):
        review = self.review()
        (self.work / review['review_path']).write_text('changed')
        with self.assertRaises(ValueError):
            export.release(self.work, self.personal, self.approval(review))

    def test_wrong_project_evidence_and_traversal_rejected(self):
        for source in ('../personal/AGENTS.md', 'projects/another.md', 'projects/../AGENTS.md'):
            self.request['sources'] = [source]
            with self.assertRaises(ValueError):
                self.propose()
        self.assertFalse((self.work / 'exports').exists())

    def test_secrets_rejected_before_writing(self):
        self.request['body'] = 'password: ' + 'synthetic-test-only'
        with self.assertRaises(ValueError):
            self.propose()
        self.assertFalse((self.work / 'exports').exists())

    def test_internal_paths_rejected_at_review(self):
        for body in ('See /Users/example/data', '[evidence](../projects/example.md)'):
            self.request['body'] = body
            self.request['expected'] = export.read(self.work, self.request['id'])[1]
            draft = self.propose()
            with self.assertRaises(ValueError):
                export.review(self.work, {'id': draft['id'], 'expected': draft['expected']})

    def test_symlink_destination_rejected(self):
        review = self.review()
        (self.personal / 'blog').symlink_to(self.work, target_is_directory=True)
        with self.assertRaises(ValueError):
            export.release(self.work, self.personal, self.approval(review))
        self.assertFalse((self.work / 'race-condition.md').exists())

    def test_busy_personal_store_keeps_candidate_in_review(self):
        review = self.review()
        with export.locked(self.personal):
            with self.assertRaises(ValueError):
                export.release(self.work, self.personal, self.approval(review))
        self.assertEqual(export.read(self.work, review['id'])[0]['state'], 'review')
        self.assertFalse((self.personal / 'blog').exists())

    def test_candidate_symlink_is_not_followed(self):
        directory = self.work / 'exports/candidates'
        directory.mkdir(parents=True)
        path = directory / 'race-condition.json'
        path.symlink_to(self.personal / 'untouched.json')
        with self.assertRaises(ValueError):
            self.propose()
        self.assertFalse((self.personal / 'untouched.json').exists())

    def test_config_requires_company_tool_and_separate_roots(self):
        config = self.base / 'config.json'
        config.write_text(json.dumps({'work': str(self.work), 'personal': str(self.personal)}))
        self.assertEqual(export.roots(config, self.work), (self.work, self.personal))
        with self.assertRaises(ValueError):
            export.roots(config, self.personal)
        config.write_text(json.dumps({'work': str(self.work), 'personal': str(self.work)}))
        with self.assertRaises(ValueError):
            export.roots(config, self.work)

    def test_kinds_route_to_distinct_personal_folders(self):
        self.bind()
        for kind, directory in export.DESTINATIONS.items():
            self.request.update(id='example-' + kind, kind=kind)
            review = self.review()
            result = export.release(self.work, self.personal, self.approval(review))
            target = 'career/companies/first-employer/experiences' if kind == 'career' else directory
            self.assertEqual(Path(result['path']).parent, self.personal / target)

    def test_career_without_company_stops_before_save(self):
        self.request['kind'] = 'career'
        with self.assertRaises(ValueError):
            self.propose()
        self.assertFalse((self.work / 'exports').exists())

    def test_job_change_preserves_old_project_and_review(self):
        self.bind()
        self.request['kind'] = 'career'
        old = self.review()
        path = self.work / 'system/project-registry.json'
        data = json.loads(path.read_text())
        data['projects'].append({'id': 'new-job-project', 'title': 'New goal', 'purpose': 'Test', 'source': 'Test', 'aliases': [], 'session_groups': []})
        path.write_text(json.dumps(data))
        self.bind('second-employer', 'new-job-project')
        (self.work / 'projects/new-job-project.md').write_text('New employer synthetic evidence')
        self.request.update(id='new-experience', project='new-job-project', sources=['projects/new-job-project.md'])
        new = self.review()
        for item, company in ((old, 'first-employer'), (new, 'second-employer')):
            result = export.release(self.work, self.personal, self.approval(item))
            self.assertIn('/companies/' + company + '/', result['path'])
            self.assertIn('company_id: "' + company + '"', Path(result['path']).read_text())
        self.assertNotEqual(old['review_hash'], new['review_hash'])
        self.assertEqual(export.brain.check(self.personal), [])

    def test_cannot_reassign_company(self):
        self.bind()
        before = (self.work / 'system/company-registry.json').read_bytes()
        with self.assertRaises(ValueError):
            self.bind('second-employer')
        self.assertEqual(before, (self.work / 'system/company-registry.json').read_bytes())

    def test_stale_company_registration_rejected(self):
        _, project_revision = export.registry.load(self.work)
        self.bind()
        with self.assertRaises(ValueError):
            export.bind_company(self.work, {'company_id': 'first-employer', 'company_name': 'first-employer',
                'projects': ['example'], 'source': 'Test', 'expected': export.digest(''), 'expected_registry': project_revision})

    def test_company_tamper_after_review_rejected(self):
        self.bind()
        self.request['kind'] = 'career'
        review = self.review()
        path = self.work / 'system/company-registry.json'
        data = json.loads(path.read_text())
        data['companies']['first-employer'] = 'Changed name'
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            export.release(self.work, self.personal, self.approval(review))
        self.assertFalse((self.personal / 'career').exists())

    def test_legacy_career_review_needs_new_review(self):
        self.bind()
        self.request['kind'] = 'career'
        data = self.propose()
        data.pop('company')
        data.pop('expected')
        path = export.candidate_path(self.work, data['id'])
        path.write_text(export.encode(data))
        with self.assertRaises(ValueError):
            export.review(self.work, {'id': data['id'], 'expected': export.digest(export.encode(data))})
        self.request['expected'] = export.read(self.work, data['id'])[1]
        updated = self.propose()
        self.assertEqual(updated['company']['id'], 'first-employer')

    def test_nested_company_directory_symlink_rejected(self):
        self.bind()
        self.request['kind'] = 'career'
        review = self.review()
        parent = self.personal / 'career/companies'
        parent.mkdir(parents=True)
        (parent / 'first-employer').symlink_to(self.work, target_is_directory=True)
        with self.assertRaises(ValueError):
            export.release(self.work, self.personal, self.approval(review))
        self.assertFalse((self.work / 'experiences').exists())

    def test_company_registry_symlink_rejected(self):
        (self.work / 'system/company-registry.json').symlink_to(self.personal / 'untouched.json')
        with self.assertRaises(ValueError):
            self.bind()
        self.assertFalse((self.personal / 'untouched.json').exists())


if __name__ == '__main__':
    unittest.main()
