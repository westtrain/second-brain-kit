#!/usr/bin/env python3
"""Apply an explicitly requested knowledge write to an isolated, local-only brain."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from brain_access import BrainAccess
import knowledge
import sync_workflow as workflow


def execute(root, scope, command, request, risk='review'):
    root = Path(root).expanduser().absolute()
    if command not in ('capture', 'distill') or risk not in ('routine', 'review'):
        raise ValueError('invalid knowledge workflow operation')
    BrainAccess(root, scope)
    with workflow.workflow_lock(root):
        main = workflow.ensure_canonical(root)
        if workflow.git(root, 'remote').stdout.strip() or workflow.git(root, 'status', '--porcelain').stdout.strip():
            raise ValueError('knowledge workflow requires a clean local brain without remotes')
        branch, checkout, remote, env = workflow.create_checkout(root, 'knowledge-' + command, main)
        access = BrainAccess(checkout, scope)
        result = {'capture': knowledge.capture, 'distill': knowledge.distill}[command](access, request)
        paths = [] if result.get('created') is False else [result['path']]
        commit = workflow.validate_and_commit(checkout, paths, 'docs: ' + command + ' local knowledge')
        if not commit:
            return {'state': 'existing', 'result': result, 'commit': None}
        output = workflow.finish(root, checkout, branch, False, risk, 'local knowledge', None)
        return {**output, 'result': result, 'commit': commit, 'branch': branch, 'worktree': str(checkout)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--scope', required=True, choices=('personal', 'work'))
    parser.add_argument('--risk', choices=('routine', 'review'), default='review')
    parser.add_argument('command', choices=('capture', 'distill'))
    args = parser.parse_args()
    try:
        print(json.dumps(execute(args.root, args.scope, args.command, json.load(sys.stdin), args.risk), ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print('Knowledge workflow stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
