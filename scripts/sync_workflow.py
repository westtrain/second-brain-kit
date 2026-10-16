#!/usr/bin/env python3
"""Run a second-brain mutation in an isolated worktree and finish its Git lifecycle."""
import argparse
from contextlib import contextmanager
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import git_guard
import github_scope


ROOT = Path(__file__).resolve().parents[1]
MUTATIONS = {'record', 'integrate', 'register', 'bind'}


def run(*args, cwd=None, input_text=None, capture=True, env=None):
    return subprocess.run(
        [str(arg) for arg in args], cwd=cwd, input=input_text, text=True,
        capture_output=capture, check=True, env=env,
    )


def git(root, *args, capture=True, env=None):
    return run('git', '-C', root, *args, capture=capture, env=env)


def clean_slug(value):
    value = re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')
    return value[:48] or 'change'


def remote_exists(root):
    return subprocess.run(
        ['git', '-C', str(root), 'remote', 'get-url', 'origin'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


def canonical_root(root):
    root = root.resolve()
    common = git_guard.common(root)
    for line in git(root, 'worktree', 'list', '--porcelain').stdout.splitlines():
        if line.startswith('worktree '):
            candidate = Path(line[9:]).resolve()
            if Path(git_guard.git(candidate, 'rev-parse', '--absolute-git-dir')).resolve() == common:
                return candidate
    raise ValueError('canonical checkout not found')


def worktree_parent(canonical):
    candidates = []
    for line in git(canonical, 'worktree', 'list', '--porcelain').stdout.splitlines():
        if line.startswith('worktree '):
            path = Path(line[9:]).resolve()
            if path != canonical:
                candidates.append(path.parent)
    if candidates and len(set(candidates)) == 1:
        return candidates[0]
    return canonical.parent / (canonical.name + '-worktrees')


@contextmanager
def workflow_lock(canonical):
    path = git_guard.common(canonical) / 'second-brain-workflow.lock'
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('another second-brain Git workflow is running') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def ensure_canonical(canonical):
    if canonical_root(canonical) != canonical:
        raise ValueError('run this command from the canonical checkout')
    branch = git_guard.git(canonical, 'symbolic-ref', '--quiet', '--short', 'HEAD')
    if branch not in ('main', 'master'):
        raise ValueError('canonical checkout must remain on main or master')
    tracked = git(canonical, 'status', '--porcelain', '--untracked-files=no').stdout.strip()
    if tracked:
        raise ValueError('canonical checkout has tracked changes')
    return branch


def unique_checkout(canonical, task):
    token = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    stem = clean_slug(task)
    branch = f'brain/{stem}-{token}'
    checkout = worktree_parent(canonical) / f'{stem}-{token}'
    suffix = 2
    while checkout.exists() or subprocess.run(
            ['git', '-C', str(canonical), 'show-ref', '--verify', '--quiet', 'refs/heads/' + branch]
    ).returncode == 0:
        branch = f'brain/{stem}-{token}-{suffix}'
        checkout = worktree_parent(canonical) / f'{stem}-{token}-{suffix}'
        suffix += 1
    return branch, checkout


def create_checkout(canonical, task, main_branch):
    has_remote = remote_exists(canonical)
    auth_env = None
    if has_remote:
        auth_env = github_scope.environment_for_remote(canonical)
        git(canonical, 'fetch', 'origin', env=auth_env)
        base = 'origin/' + main_branch
    else:
        base = main_branch
    branch, checkout = unique_checkout(canonical, task)
    checkout.parent.mkdir(parents=True, exist_ok=True)
    git(canonical, 'worktree', 'add', '-b', branch, checkout, base)
    git_guard.linked_checkout(canonical, checkout)
    return branch, checkout, has_remote, auth_env


def changed_paths(checkout):
    result = git(checkout, 'status', '--porcelain', '-z', '--untracked-files=all').stdout
    paths = []
    for entry in result.split('\0'):
        if not entry:
            continue
        paths.append(entry[3:])
    return paths


def validate_and_commit(checkout, paths, message):
    if not paths:
        return None
    for path in paths:
        if path.startswith('/') or '..' in Path(path).parts:
            raise ValueError('invalid changed path')
    actual = changed_paths(checkout)
    if sorted(actual) != sorted(paths):
        raise ValueError('unexpected files changed: ' + json.dumps(actual))
    # Validate the mutation's allowlist before adding the one generated artifact.
    index_tool = checkout / 'scripts/memory_tools.py'
    if index_tool.is_file():
        run(sys.executable, index_tool, 'index', cwd=checkout)
        actual = changed_paths(checkout)
        if sorted(p for p in actual if p != 'INDEX.md') != sorted(p for p in paths if p != 'INDEX.md'):
            raise ValueError('unexpected files changed during index generation')
        paths = actual
    run(sys.executable, checkout / 'scripts/brain.py', 'check', cwd=checkout)
    git(checkout, 'add', '--', *paths)
    run(sys.executable, checkout / 'scripts/brain.py', 'staged-check', cwd=checkout)
    git(checkout, 'diff', '--cached', '--check')
    git(checkout, 'commit', '-m', message)
    return git_guard.git(checkout, 'rev-parse', 'HEAD')


def open_pr(checkout, branch, title, auth_env):
    body = ('세컨브레인 공통 동기화 워크플로로 생성한 변경입니다.\n\n'
            '검증: `python3 scripts/brain.py check`, staged-check, diff check')
    git(checkout, 'push', '-u', 'origin', branch, env=auth_env)
    result = run('gh', 'pr', 'create', '--base', 'main', '--head', branch,
                 '--title', title, '--body', body, cwd=checkout, env=auth_env)
    return result.stdout.strip()


def finish(canonical, checkout, branch, has_remote, risk, title, auth_env):
    if has_remote:
        pr = open_pr(checkout, branch, title, auth_env)
        if risk == 'routine':
            run('gh', 'pr', 'merge', pr, '--merge', cwd=checkout, env=auth_env)
            git(canonical, 'fetch', 'origin', env=auth_env)
            git(canonical, 'merge', '--ff-only', 'origin/main')
            return {'state': 'merged', 'pull_request': pr}
        return {'state': 'review', 'pull_request': pr}
    if risk == 'routine':
        git(canonical, 'merge', '--ff-only', branch)
        return {'state': 'merged', 'pull_request': None}
    return {'state': 'review', 'pull_request': None}


def mutation_paths(command, result):
    if command == 'record':
        return [] if result['status'] == 'existing' else [result['path']]
    if command == 'integrate':
        return [result['path']]
    return ['system/project-registry.json']


def execute_mutation(canonical, args, payload):
    main_branch = ensure_canonical(canonical)
    task = args.task or (args.command + '-' + getattr(args, 'project', 'registry'))
    branch, checkout, has_remote, auth_env = create_checkout(canonical, task, main_branch)
    command = [sys.executable, checkout / 'scripts/session_sync.py', args.command]
    if args.command == 'record':
        command += ['--project', args.project, '--session', args.session,
                    '--source', args.source, '--observed', args.observed]
    output = run(*command, cwd=checkout, input_text=payload).stdout
    result = json.loads(output)
    paths = mutation_paths(args.command, result)
    title = args.title or f'docs(brain): {task}'
    commit = validate_and_commit(checkout, paths, title)
    if not commit:
        return {'state': 'existing', 'result': result, 'branch': branch,
                'worktree': str(checkout), 'commit': None}
    final = finish(canonical, checkout, branch, has_remote, args.risk, title, auth_env)
    return {**final, 'result': result, 'branch': branch,
            'worktree': str(checkout), 'commit': commit}


def adopt_event(canonical, args):
    main_branch = ensure_canonical(canonical)
    relative = Path(args.event)
    if relative.is_absolute() or '..' in relative.parts or relative.parts[:1] != ('sessions',):
        raise ValueError('event must be a sessions-relative path')
    source = canonical / relative
    if source.is_symlink() or not source.is_file():
        raise ValueError('untracked event file not found')
    if subprocess.run(['git', '-C', str(canonical), 'ls-files', '--error-unmatch', str(relative)],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        raise ValueError('event is already tracked')
    original = source.read_bytes()
    branch, checkout, has_remote, auth_env = create_checkout(
        canonical, args.task or relative.parent.name, main_branch)
    destination = checkout / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(original)
    # The immutable event validator also checks that metadata hashes to the filename.
    run(sys.executable, checkout / 'scripts/session_sync.py', 'snapshot',
        '--project', relative.parent.name, cwd=checkout)
    title = args.title or f'docs(brain): {relative.parent.name} 세션 기록 회수'
    commit = validate_and_commit(checkout, [str(relative)], title)
    if args.risk == 'routine' and not has_remote:
        source.unlink()
        try:
            final = finish(canonical, checkout, branch, has_remote, args.risk, title, auth_env)
            if source.read_bytes() != original:
                raise RuntimeError('adopted event changed during merge')
        except Exception:
            if not source.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(original)
            raise
    else:
        final = finish(canonical, checkout, branch, has_remote, args.risk, title, auth_env)
    return {**final, 'event': str(relative), 'branch': branch,
            'worktree': str(checkout), 'commit': commit}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest='command', required=True)
    for name in MUTATIONS:
        item = sub.add_parser(name)
        item.add_argument('--risk', choices=('routine', 'review'), default='review')
        item.add_argument('--task')
        item.add_argument('--title')
        if name == 'record':
            for field in ('project', 'session', 'source'):
                item.add_argument('--' + field, required=True)
            item.add_argument('--observed', default='unknown')
    adopt = sub.add_parser('adopt')
    adopt.add_argument('--event', required=True)
    adopt.add_argument('--risk', choices=('routine', 'review'), default='review')
    adopt.add_argument('--task')
    adopt.add_argument('--title')
    return result


def main():
    args = parser().parse_args()
    try:
        canonical = canonical_root(ROOT)
        with workflow_lock(canonical):
            if args.command == 'adopt':
                result = adopt_event(canonical, args)
            else:
                result = execute_mutation(canonical, args, sys.stdin.read())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError, KeyError, TypeError, json.JSONDecodeError):
        print('ERROR: workflow stopped without forcing, overwriting, or pushing protected branches. '
              'Inspect `git worktree list` before retrying.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
