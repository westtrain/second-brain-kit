#!/usr/bin/env python3
"""Local Git workflow guard; server-side permissions remain separate."""
from pathlib import Path
import subprocess
import sys


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True, stderr=subprocess.DEVNULL).strip()


def common(root):
    return Path(git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')).resolve()


def require_isolated(root):
    branch = git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD')
    if branch in ('main', 'master', 'develop'):
        raise ValueError('protected branch')
    if Path(git(root, 'rev-parse', '--absolute-git-dir')).resolve() == common(root):
        raise ValueError('linked worktree required')


def linked_checkout(canonical, checkout):
    checkout = Path(checkout).expanduser().absolute()
    if any(p.is_symlink() for p in (checkout, *checkout.parents)):
        raise ValueError('symlink checkout')
    try:
        if common(canonical) != common(checkout):
            raise ValueError('checkout belongs to another repository')
        require_isolated(checkout)
    except subprocess.CalledProcessError as exc:
        raise ValueError('valid linked checkout required') from exc
    return checkout


def main():
    try:
        require_isolated(Path.cwd())
        if len(sys.argv) > 1 and sys.argv[1] == 'pre-push':
            for line in sys.stdin:
                fields = line.split()
                if len(fields) != 4 or fields[2] in ('refs/heads/main', 'refs/heads/master', 'refs/heads/develop'):
                    raise ValueError('direct push to protected destination')
        return 0
    except (ValueError, subprocess.CalledProcessError):
        print('BLOCKED: use a task branch in a linked worktree, then push that branch and open a PR.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
