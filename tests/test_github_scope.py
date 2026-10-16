import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import github_scope


class GithubScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps({
            'github_accounts': {'personal': 'personal-example', 'work': 'work-example'}
        }), encoding='utf-8')

    def test_account_mapping_is_explicit_and_scope_specific(self):
        self.assertEqual(github_scope.account_for(self.config, 'personal'), 'personal-example')
        self.assertEqual(github_scope.account_for(self.config, 'work'), 'work-example')
        self.config.write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            github_scope.account_for(self.config, 'work')

    def test_process_environment_does_not_change_global_active_account(self):
        completed = subprocess.CompletedProcess([], 0, stdout='secret-token\n', stderr='')
        with patch.object(github_scope.subprocess, 'run', return_value=completed) as called:
            inherited = {
                'GIT_CONFIG_COUNT': '1',
                'GIT_CONFIG_KEY_0': 'credential.interactive',
                'GIT_CONFIG_VALUE_0': 'false',
            }
            with patch.dict(os.environ, inherited, clear=True):
                env = github_scope.environment_for_account('personal-example')
        called.assert_called_once_with(
            ['gh', 'auth', 'token', '--hostname', 'github.com', '--user', 'personal-example'],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(env['GH_TOKEN'], 'secret-token')
        expected = base64.b64encode(b'x-access-token:secret-token').decode('ascii')
        self.assertEqual(env['GIT_CONFIG_COUNT'], '2')
        self.assertEqual(env['GIT_CONFIG_VALUE_0'], 'false')
        self.assertEqual(env['GIT_CONFIG_VALUE_1'], 'AUTHORIZATION: basic ' + expected)
        self.assertNotIn('secret-token', os.environ)

    def test_rejects_incomplete_inherited_git_config(self):
        completed = subprocess.CompletedProcess([], 0, stdout='secret-token\n', stderr='')
        with patch.object(github_scope.subprocess, 'run', return_value=completed):
            with patch.dict(os.environ, {'GIT_CONFIG_COUNT': '1'}, clear=True):
                with self.assertRaises(ValueError):
                    github_scope.environment_for_account('personal-example')

    def test_remote_owner_supports_https_and_ssh(self):
        for url in ('https://github.com/personal-example/brain.git',
                    'git@github.com:work-example/company.git'):
            completed = subprocess.CompletedProcess([], 0, stdout=url + '\n', stderr='')
            with patch.object(github_scope.subprocess, 'run', return_value=completed):
                expected = 'personal-example' if 'personal-example' in url else 'work-example'
                self.assertEqual(github_scope.remote_owner(self.root), expected)

    def test_cli_rejects_arbitrary_command_before_fetching_token(self):
        with patch.object(github_scope, 'environment_for_account') as auth:
            with patch.object(sys, 'argv', ['github_scope.py', '--scope', 'personal', '--', 'env']):
                self.assertEqual(github_scope.main(), 1)
        auth.assert_not_called()


if __name__ == '__main__':
    unittest.main()
