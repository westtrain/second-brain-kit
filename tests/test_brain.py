"""Safety and workflow regression checks using synthetic data in temporary folders."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("brain", Path(__file__).parents[1] / "scripts" / "brain.py")
brain = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(brain)

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="second-brain-test-")
        self.root = Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def put(self, name, text):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p
    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.DEVNULL)
    def test_capture_idempotent_even_after_archive(self):
        p, created = brain.capture(self.root, "합성 메모", "test fixture", "synthetic repeated note")
        self.assertTrue(created)
        (self.root / "archive").mkdir()
        target = self.root / "archive" / p.name
        p.rename(target)
        again, created = brain.capture(self.root, "합성 메모", "test fixture", "synthetic repeated note")
        self.assertFalse(created)
        self.assertEqual(again, target)
    def test_reject_before_any_write(self):
        payloads = ["sk-" + "a" * 30, "password" + "=example-only-value", "회사 " + "기밀: 합성 문서"]
        for payload in payloads:
            with self.assertRaises(ValueError):
                brain.capture(self.root, "test", "fixture", payload)
        self.assertFalse((self.root / "inbox").exists())
    def test_secret_in_source_is_rejected(self):
        with self.assertRaises(ValueError):
            brain.capture(self.root, "test", "sk-" + "b" * 30, "safe body")
        self.assertFalse((self.root / "inbox").exists())
    def test_default_search_excludes_archive_and_inbox(self):
        self.put("notes/a.md", "# synthetic-match")
        self.put("findings/a.md", "# deferred-finding")
        self.put("archive/a.md", "# synthetic-match")
        self.put("inbox/a.md", "# synthetic-match")
        self.assertEqual(list(brain.search(self.root, "synthetic-match")), ["notes/a.md"])
        self.assertEqual(list(brain.search(self.root, "deferred-finding")), ["findings/a.md"])
        self.assertEqual(len(list(brain.search(self.root, "synthetic-match", True, True))), 3)
        self.assertEqual(list(brain.search(self.root, "nonexistent-topic")), [])
    def test_findings_are_validated_as_active_content(self):
        self.put("findings/missing-metadata.md", "# deferred-finding")
        self.assertTrue(any("findings/missing-metadata.md: missing metadata" in error
                            for error in brain.check(self.root)))
    def test_incidents_are_searchable_and_schema_checked(self):
        incident = """---
status: confirmed
updated: 2026-09-22
source: fixture
severity: 높음
state: 대응중
detected: 2026-09-22 08:35
resolved: 미정
owner: 내부
systems: synthetic service
---
# synthetic-incident
"""
        self.put("incidents/README.md", """---
status: confirmed
updated: 2026-09-22
source: fixture
---
[detail](2026-09-22-synthetic.md)
""")
        path = self.put("incidents/2026-09-22-synthetic.md", incident)
        self.assertEqual(list(brain.search(self.root, "synthetic-incident")),
                         ["incidents/2026-09-22-synthetic.md"])
        self.assertEqual(brain.check(self.root), [])
        path.write_text(incident.replace("severity: 높음", "severity: unknown"), encoding="utf-8")
        self.assertIn("incidents/2026-09-22-synthetic.md: invalid severity", brain.check(self.root))
    def test_unindexed_incident_is_rejected(self):
        self.put("incidents/README.md", """---
status: confirmed
updated: 2026-09-22
source: fixture
---
# Empty incident index
""")
        self.put("incidents/2026-09-22-unindexed.md", """---
status: draft
updated: 2026-09-22
source: fixture
severity: 낮음
state: 대응중
detected: 2026-09-22 09:00
resolved: 미정
owner: 내부
systems: synthetic service
---
# Unindexed
""")
        self.assertIn("incidents/README.md: unindexed incident 2026-09-22-unindexed.md",
                      brain.check(self.root))
    def test_symlink_read_and_write_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.root / "inbox").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                brain.capture(self.root, "test", "fixture", "safe body")
            self.assertEqual(list(Path(outside).iterdir()), [])
    def test_link_and_date_validation(self):
        self.put("notes/test.md", "---\nstatus: confirmed\nupdated: 2026-99-12\nsource: fixture\n---\n# Sample\n[missing](missing.md)\n")
        errors = brain.check(self.root)
        self.assertTrue(any("invalid updated" in e for e in errors))
        self.assertTrue(any("missing link" in e for e in errors))
    def test_staged_blob_is_scanned_not_working_copy(self):
        self.git("init", "-q")
        self.put("notes/a.md", "sk-" + "z" * 30)
        self.git("add", "--", "notes/a.md")
        self.put("notes/a.md", "safe working copy")
        self.assertTrue(brain.staged_check(self.root))
        self.git("add", "--", "notes/a.md")
        self.assertEqual(brain.staged_check(self.root), [])
    def test_forced_private_path_blocked(self):
        self.git("init", "-q")
        self.put("private/a.md", "safe but prohibited location")
        self.git("add", "--", "private/a.md")
        self.assertTrue(brain.staged_check(self.root))
    def test_staged_symlink_blocked(self):
        self.git("init", "-q")
        (self.root / "external.md").symlink_to("/tmp/does-not-exist-second-brain")
        self.git("add", "--", "external.md")
        self.assertTrue(brain.staged_check(self.root))
    def test_promotion_link_and_archive_move(self):
        inbox, _ = brain.capture(self.root, "합성 메모", "fixture", "promotion sample")
        self.put("notes/promoted.md", "---\nstatus: confirmed\nupdated: 2026-09-12\nsource: fixture\n---\n# 합성 정본\npromotion sample\n")
        inbox.write_text(inbox.read_text() + "\npromoted_to: [정본](../notes/promoted.md)\n")
        self.assertEqual(brain.check(self.root), [])
        (self.root / "archive").mkdir()
        (self.root / "notes/promoted.md").rename(self.root / "archive/promoted.md")
        self.assertTrue(brain.check(self.root))
        inbox.write_text(inbox.read_text().replace("../notes/promoted.md", "../archive/promoted.md"))
        self.assertEqual(brain.check(self.root), [])
    def test_git_history_and_bundle_restore(self):
        self.git("init", "-q")
        self.git("config", "user.name", "Synthetic Fixture")
        self.git("config", "user.email", "fixture@localhost")
        self.put("notes/a.md", "original fixture")
        self.git("add", "--", "notes/a.md")
        self.git("commit", "-qm", "fixture initial")
        first = self.git("rev-parse", "HEAD").decode().strip()
        self.put("notes/a.md", "updated fixture")
        self.git("add", "--", "notes/a.md")
        self.git("commit", "-qm", "fixture update")
        self.assertEqual(self.git("show", first + ":notes/a.md").decode(), "original fixture")
        with tempfile.TemporaryDirectory(prefix="second-brain-restore-test-") as dest:
            bundle = str(Path(dest) / "fixture.bundle")
            self.git("bundle", "create", bundle, "--all")
            restored = str(Path(dest) / "restored")
            subprocess.check_call(["git", "clone", "-q", bundle, restored], stderr=subprocess.DEVNULL)
            self.assertEqual((Path(restored) / "notes/a.md").read_text(), "updated fixture")

if __name__ == "__main__":
    unittest.main()
