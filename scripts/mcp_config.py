#!/usr/bin/env python3
"""Print a scoped MCP client configuration; never changes an AI application's settings."""
import argparse
import json
from pathlib import Path
import sys

from brain_access import BrainAccess


def configuration(root, scope, enable_writes=False, qmd_index=None, qmd_collection=None):
    access = BrainAccess(root, scope, enable_writes, qmd_index, qmd_collection)
    arguments = [str(Path(__file__).with_name('mcp_server.py').resolve()),
                 '--root', str(access.root), '--scope', scope]
    if enable_writes:
        arguments.append('--enable-writes')
    if qmd_index:
        arguments += ['--qmd-index', qmd_index, '--qmd-collection', qmd_collection]
    return {'command': sys.executable, 'args': arguments}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--scope', choices=('personal', 'work'), required=True)
    parser.add_argument('--enable-writes', action='store_true')
    parser.add_argument('--qmd-index')
    parser.add_argument('--qmd-collection')
    parser.add_argument('--format', choices=('json', 'codex'), default='json')
    args = parser.parse_args()
    try:
        config = configuration(args.root, args.scope, args.enable_writes, args.qmd_index, args.qmd_collection)
        name = 'second-brain-' + args.scope
        if args.format == 'json':
            print(json.dumps({'mcpServers': {name: config}}, ensure_ascii=False, indent=2))
        else:
            print('[mcp_servers.' + name + ']')
            print('command = ' + json.dumps(config['command']))
            print('args = ' + json.dumps(config['args']))
        return 0
    except (ValueError, OSError) as error:
        print('MCP configuration rejected: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
