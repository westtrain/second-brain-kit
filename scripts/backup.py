#!/usr/bin/env python3
"""Local Git + all registered checkout snapshots. No network or automatic deletion."""
import argparse
from contextlib import ExitStack
import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from session_sync import locked


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def plain(path):
    path = Path(path).expanduser().absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symlink path')
    return path


def child(root, relative):
    parts = Path(relative).parts
    if not relative or Path(relative).is_absolute() or '..' in parts or '.git' in parts:
        raise ValueError('unsafe snapshot path')
    path = plain(root / relative)
    if root not in path.parents:
        raise ValueError('outside snapshot')
    return path


def refs(root):
    lines = git(root, 'for-each-ref', '--format=%(refname) %(objectname)').decode().splitlines()
    return dict(line.split(' ', 1) for line in lines)


def checkouts(root):
    common = git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir').strip()
    entries = []
    for block in git(root, 'worktree', 'list', '--porcelain').decode().strip().split('\n\n'):
        line = block.splitlines()[0]
        if not line.startswith('worktree '):
            raise ValueError('invalid worktree inventory')
        path = plain(line[len('worktree '):])
        if not path.is_dir() or git(path, 'rev-parse', '--path-format=absolute', '--git-common-dir').strip() != common:
            raise ValueError('unavailable checkout; backup would be incomplete')
        entries.append(path)
    return entries


def snapshot(root):
    if git(root, 'ls-files', '--unmerged'):
        raise ValueError('resolve index conflicts before backup')
    head = git(root, 'rev-parse', 'HEAD').decode().strip()
    branch = subprocess.run(['git', '-C', str(root), 'symbolic-ref', '-q', 'HEAD'], capture_output=True, text=True).stdout.strip()
    names = set(filter(None, git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z').decode().split('\0')))
    files = {}
    for name in sorted(names):
        if name == '.brain-sync.lock' or any(p.startswith('.session-write-') for p in Path(name).parts):
            continue
        path = child(root, name)
        if not path.exists():
            continue  # Tracked deletion is represented by absence from the complete checkout snapshot.
        if not path.is_file():
            raise ValueError('submodule or special file unsupported')
        if path.stat().st_size > 20_000_000:
            raise ValueError('oversized file; review backup scope')
        files[name] = {'data': path.read_bytes(), 'mode': 0o755 if path.stat().st_mode & 0o111 else 0o644}
    patch = git(root, 'diff', '--cached', '--no-ext-diff', '--no-textconv', '--binary', '--full-index', 'HEAD', '--')
    return {'head': head, 'branch': branch, 'files': files, 'index_patch': patch}


def create(root, destination, scope):
    root, destination = plain(root), plain(destination)
    if scope not in ('personal', 'work') or not destination.is_dir():
        raise ValueError('configured existing destination required')
    trees = checkouts(root)
    for tree in trees:
        if destination == tree or tree in destination.parents or destination in tree.parents:
            raise ValueError('backup destination overlaps source')
    with ExitStack() as stack:
        for tree in sorted(trees):
            stack.enter_context(locked(tree))
        before_refs = refs(root)
        states = [snapshot(tree) for tree in trees]
        # Detached worktree HEADs without refs are not covered by --all; fail explicitly.
        for state in states:
            if not git(root, 'for-each-ref', '--contains', state['head']).strip():
                raise ValueError('unreferenced detached HEAD; create a branch before backup')
        stage = Path(tempfile.mkdtemp(prefix='.' + scope + '-incomplete-', dir=destination))
        try:
            git(root, 'bundle', 'create', str(stage / 'repo.bundle'), '--all')
            git(root, 'bundle', 'verify', str(stage / 'repo.bundle'))
            manifest = {'version': 1, 'scope': scope, 'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                        'refs': before_refs, 'checkouts': [], 'checksums': {}}
            for number, (tree, state) in enumerate(zip(trees, states)):
                identifier = str(number)
                base = stage / 'checkouts' / identifier
                base.mkdir(parents=True)
                metadata = {'id': identifier, 'source_path': str(tree), 'head': state['head'],
                            'branch': state['branch'], 'files': {}}
                for name, item in state['files'].items():
                    path = child(base / 'files', name)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(item['data'])
                    metadata['files'][name] = item['mode']
                (base / 'index.patch').write_bytes(state['index_patch'])
                manifest['checkouts'].append(metadata)
            if refs(root) != before_refs or checkouts(root) != trees or any(snapshot(t) != s for t, s in zip(trees, states)):
                raise ValueError('source changed during backup; retry when writers stop')
            for path in stage.rglob('*'):
                if path.is_file():
                    manifest['checksums'][str(path.relative_to(stage))] = sha(path.read_bytes())
            (stage / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
            (stage / 'manifest.sha256').write_text(sha((stage / 'manifest.json').read_bytes()) + '\n')
            verify(stage, scope)
            for path in stage.rglob('*'):
                if path.is_file():
                    with path.open('rb') as handle:
                        os.fsync(handle.fileno())
            final = destination / (scope + '-' + stage.name.split('-incomplete-', 1)[1])
            if final.exists():
                raise ValueError('backup name collision')
            stage.rename(final)
            return final
        except BaseException:
            shutil.rmtree(stage)
            raise


def verify(archive, scope):
    archive = plain(archive)
    raw = plain(archive / 'manifest.json').read_bytes()
    if sha(raw) != plain(archive / 'manifest.sha256').read_text().strip():
        raise ValueError('manifest checksum mismatch')
    manifest = json.loads(raw)
    if manifest['version'] != 1 or manifest['scope'] != scope:
        raise ValueError('backup scope mismatch')
    actual = set()
    for path in archive.rglob('*'):
        plain(path)
        if path.is_file() and path not in (archive / 'manifest.json', archive / 'manifest.sha256'):
            actual.add(str(path.relative_to(archive)))
    if actual != set(manifest['checksums']):
        raise ValueError('incomplete or unexpected backup files')
    for name, expected in manifest['checksums'].items():
        path = child(archive, name)
        if sha(path.read_bytes()) != expected:
            raise ValueError('backup checksum mismatch')
    return manifest


def restore(archive, target, scope, checkout):
    archive, target = plain(archive), plain(target)
    manifest = verify(archive, scope)
    selected = [c for c in manifest['checkouts'] if c['id'] == checkout]
    if len(selected) != 1 or target.exists() or archive in target.parents:
        raise ValueError('select one checkout and a new restore directory')
    state = selected[0]
    base = child(archive, 'checkouts/' + state['id'])
    for name in state['files']:
        child(base / 'files', name)
        child(target, name)
    for ref, oid in manifest['refs'].items():
        subprocess.run(['git', 'check-ref-format', ref], check=True, capture_output=True)
        if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', oid):
            raise ValueError('invalid object ID')
    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', state['head']):
        raise ValueError('invalid HEAD')
    if state['branch'] and (state['branch'] not in manifest['refs'] or manifest['refs'][state['branch']] != state['head']):
        raise ValueError('invalid HEAD metadata')
    target.mkdir(mode=0o700, parents=False)
    try:
        subprocess.run(['git', 'init', '-q', str(target)], check=True, capture_output=True)
        git(target, 'bundle', 'verify', str(archive / 'repo.bundle'))
        git(target, 'bundle', 'unbundle', str(archive / 'repo.bundle'))
        for ref, oid in manifest['refs'].items():
            git(target, 'update-ref', ref, oid)
        if state['branch']:
            git(target, 'symbolic-ref', 'HEAD', state['branch'])
        else:
            git(target, 'update-ref', '--no-deref', 'HEAD', state['head'])
        git(target, 'read-tree', state['head'])
        patch = base / 'index.patch'
        if patch.stat().st_size:
            git(target, 'apply', '--cached', '--binary', str(patch))
        for name, mode in state['files'].items():
            if mode not in (0o644, 0o755):
                raise ValueError('invalid restored file mode')
            path = child(target, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(child(base / 'files', name), path)
            path.chmod(mode)
        git(target, 'fsck', '--no-reflogs')
        recovered = snapshot(target)
        if recovered['head'] != state['head'] or recovered['index_patch'] != patch.read_bytes() or set(recovered['files']) != set(state['files']):
            raise ValueError('restore validation failed')
        for name, item in recovered['files'].items():
            if item['mode'] != state['files'][name] or item['data'] != child(base / 'files', name).read_bytes():
                raise ValueError('restored content or mode differs')
        # Restored repositories are independent; no remote URLs, hooks config or credentials are copied.
        return target
    except BaseException:
        shutil.rmtree(target)
        raise


def configuration(path, scope):
    data = json.loads(path.read_text())
    source = plain(data[scope])
    destination = plain(data['backups'][scope])
    other = 'work' if scope == 'personal' else 'personal'
    for value in (data.get(other), data.get('backups', {}).get(other)):
        if value:
            forbidden = plain(value)
            if destination == forbidden or forbidden in destination.parents or destination in forbidden.parents:
                raise ValueError('scope destinations overlap')
    if data.get(other):
        other_source = plain(data[other])
        if source == other_source or source in other_source.parents or other_source in source.parents:
            raise ValueError('source scopes overlap')
    return source, destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('create', 'verify', 'restore'))
    parser.add_argument('--scope', required=True, choices=('personal', 'work'))
    parser.add_argument('--config', type=Path, default=Path.home() / '.claude/skills/second-brain-sync/config.json')
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--target', type=Path)
    parser.add_argument('--checkout', default='0')
    args = parser.parse_args()
    try:
        source, destination = configuration(args.config, args.scope)
        if args.command == 'create':
            result = {'backup': str(create(source, destination, args.scope))}
        else:
            archive = plain(args.archive)
            if destination not in archive.parents:
                raise ValueError('archive outside configured scope destination')
            if args.command == 'verify':
                result = verify(archive, args.scope)
            else:
                target = plain(args.target)
                # Restore only inside the chosen backup area until the user reviews recovery.
                if destination not in target.parents:
                    raise ValueError('restore target must be in configured scope backup area')
                result = {'restored': str(restore(archive, target, args.scope, args.checkout))}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError):
        print('ERROR: backup operation rejected; check scope configuration, paths, integrity and concurrent writers.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
