from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import git_guard as guard


class GitGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.repo = self.base / 'repo'
        self.task = self.base / 'task'
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(self.repo)], check=True)
        for key, value in [('user.name', 'Test'), ('user.email', 'test@example.invalid'), ('commit.gpgsign', 'false')]:
            guard.git(self.repo, 'config', key, value)
        guard.git(self.repo, '-c', 'core.hooksPath=/dev/null', 'commit', '--allow-empty', '-m', 'fixture')
        guard.git(self.repo, 'worktree', 'add', '-b', 'task', str(self.task))

    def test_main_and_primary_checkout_rejected(self):
        with self.assertRaises(ValueError):
            guard.require_isolated(self.repo)
        guard.git(self.repo, 'checkout', '-b', 'other')
        with self.assertRaises(ValueError):
            guard.require_isolated(self.repo)

    def test_linked_task_allowed(self):
        guard.require_isolated(self.task)
        self.assertEqual(guard.linked_checkout(self.repo, self.task), self.task)

    def test_other_repository_rejected(self):
        other = self.base / 'other'
        subprocess.run(['git', 'init', '-q', str(other)], check=True)
        with self.assertRaises(ValueError):
            guard.linked_checkout(other, self.task)

    def test_push_checks_remote_destination(self):
        script = Path(guard.__file__)
        for remote, expected in [('refs/heads/main', 1), ('refs/heads/master', 1), ('refs/heads/task', 0)]:
            result = subprocess.run([sys.executable, str(script), 'pre-push'], cwd=self.task,
                input='refs/heads/task ' + 'a'*40 + ' ' + remote + ' ' + 'b'*40 + '\n',
                text=True, capture_output=True)
            self.assertEqual(result.returncode, expected)

    def test_detached_head_rejected(self):
        guard.git(self.task, 'checkout', '--detach')
        result = subprocess.run([sys.executable, str(Path(guard.__file__))], cwd=self.task, capture_output=True)
        self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    unittest.main()
