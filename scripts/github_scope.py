#!/usr/bin/env python3
"""Run Git/GitHub commands with one account without changing gh's global active account."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def account_for(config, scope):
    data = json.loads(Path(config).expanduser().read_text(encoding='utf-8'))
    accounts = data.get('github_accounts', {})
    account = accounts.get(scope)
    if scope not in ('personal', 'work') or not isinstance(account, str):
        raise ValueError('GitHub account is not configured for scope')
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?', account):
        raise ValueError('invalid GitHub account')
    return account


def remote_owner(root):
    url = subprocess.run(
        ['git', '-C', str(root), 'remote', 'get-url', 'origin'],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    match = re.match(r'(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+)/[^/]+(?:\.git)?$', url)
    if not match:
        raise ValueError('GitHub origin required')
    return match.group(1)


def environment_for_account(account):
    token = subprocess.run(
        ['gh', 'auth', 'token', '--hostname', 'github.com', '--user', account],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if not token or '\n' in token or '\r' in token:
        raise ValueError('invalid GitHub token response')
    env = os.environ.copy()
    try:
        config_count = int(env.get('GIT_CONFIG_COUNT', '0'))
    except ValueError as error:
        raise ValueError('invalid inherited Git config count') from error
    if config_count < 0:
        raise ValueError('invalid inherited Git config count')
    for index in range(config_count):
        if f'GIT_CONFIG_KEY_{index}' not in env or f'GIT_CONFIG_VALUE_{index}' not in env:
            raise ValueError('incomplete inherited Git config environment')
    encoded = base64.b64encode(('x-access-token:' + token).encode('utf-8')).decode('ascii')
    env.update({
        'GH_TOKEN': token,
        'GIT_TERMINAL_PROMPT': '0',
        'GIT_CONFIG_COUNT': str(config_count + 1),
        f'GIT_CONFIG_KEY_{config_count}': 'http.https://github.com/.extraheader',
        f'GIT_CONFIG_VALUE_{config_count}': 'AUTHORIZATION: basic ' + encoded,
    })
    return env


def environment_for_remote(root):
    return environment_for_account(remote_owner(root))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=('personal', 'work'), required=True)
    parser.add_argument('--config', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'config.json')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    try:
        if not command or command[0] not in ('git', 'gh'):
            raise ValueError('only git or gh commands are allowed')
        env = environment_for_account(account_for(args.config, args.scope))
        return subprocess.run(command, env=env).returncode
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError,
            subprocess.CalledProcessError):
        print('ERROR: scoped GitHub command rejected; check scope, account login, and command.',
              file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
