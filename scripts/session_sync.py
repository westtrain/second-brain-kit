#!/usr/bin/env python3
"""Immutable session notes and serialized, version-checked project integration (local POSIX)."""
import argparse
from contextlib import contextmanager
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

import brain
import git_guard
import project_registry as registry

ROOT = Path(__file__).resolve().parents[1]
EVENT_FIELDS = ('project', 'session', 'source', 'observed')


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def safe(root, relative):
    path = root / relative
    if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root and root in p.parents):
        raise ValueError('symlink rejected')
    if root not in path.resolve().parents:
        raise ValueError('outside root')
    return path


def slug(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', value):
        raise ValueError('invalid project slug')
    return value


def secret_check(text):
    if not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > 1_000_000:
        raise ValueError('empty or oversized input')
    if brain.violations(text):
        raise ValueError('prohibited content; nothing saved')


def repeated_event_frontmatter(text):
    """Return leading event metadata and remaining body, if a summary repeats it."""
    if not text.startswith('---\n'):
        return None, text
    try:
        front, remainder = text[4:].split('\n---\n', 1)
    except ValueError:
        return None, text
    metadata = {}
    try:
        for key in EVENT_FIELDS:
            match = re.search(r'^' + key + r': (.+)$', front, re.M)
            if not match:
                return None, text
            metadata[key] = json.loads(match.group(1))
    except (json.JSONDecodeError, TypeError):
        return None, text
    return metadata, remainder.strip()


@contextmanager
def locked(root):
    path = safe(root, '.brain-sync.lock')
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('busy: another write is in progress; retry after re-reading')
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def atomic(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.session-write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(body)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def record(root, project, session, source, observed, body):
    project = slug(project)
    # Unknown and month-only dates stay unknown/month-only, never fabricated as today.
    if observed != 'unknown':
        if re.fullmatch(r'\d{4}-\d{2}', observed):
            dt.date.fromisoformat(observed + '-01')
        else:
            dt.date.fromisoformat(observed)
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', observed):
                raise ValueError('observed date must be YYYY-MM-DD, YYYY-MM, or unknown')
    summary = body.strip()
    if repeated_event_frontmatter(summary)[0] is not None:
        raise ValueError('summary must not repeat generated event frontmatter')
    data = {'project': project, 'session': session.strip(), 'source': source.strip(),
            'observed': observed, 'summary': summary}
    for value in data.values():
        secret_check(value)
    with locked(root):
        owner, _ = registry.resolve(root, project)
        if project not in registry.groups(owner):
            project = owner['id']
            data['project'] = project
        event_id = digest(json.dumps(data, sort_keys=True, ensure_ascii=False))
        path = safe(root, 'sessions/' + project + '/' + event_id + '.md')
        header = '\n'.join(k + ': ' + json.dumps(v, ensure_ascii=False) for k, v in data.items() if k != 'summary')
        text = '---\nstatus: draft\nupdated: ' + brain.today() + '\n' + header + '\n---\n' + data['summary'] + '\n'
        if path.exists():
            read_event(path)  # Detect tampering instead of silently treating it as a duplicate.
            return {'status': 'existing', 'project': owner['id'], 'path': str(path.relative_to(root)), 'id': event_id}
        atomic(path, text)
    return {'status': 'saved', 'project': owner['id'], 'path': str(path.relative_to(root)), 'id': event_id}


def read_event(path):
    text = path.read_text(encoding='utf-8')
    if not text.startswith('---\n'):
        raise ValueError('invalid event')
    front, body = text[4:].split('\n---\n', 1)
    data = {}
    for key in EVENT_FIELDS:
        match = re.search(r'^' + key + r': (.+)$', front, re.M)
        if not match:
            raise ValueError('missing event metadata')
        data[key] = json.loads(match.group(1))
    data['summary'] = body.strip()
    if path.stem != digest(json.dumps(data, sort_keys=True, ensure_ascii=False)):
        raise ValueError('event content changed; immutable notes must not be edited')
    repeated, summary = repeated_event_frontmatter(data['summary'])
    if repeated is not None and all(repeated[key] == data[key] for key in EVENT_FIELDS):
        data['summary'] = summary
    return data


def receipts(text):
    front = text.split('\n---\n', 1)[0] if text.startswith('---\n') else ''
    found = re.findall(r'^integrated_sessions: (.+)$', front, re.M)
    if len(found) > 1:
        raise ValueError('duplicate receipt field')
    ids = json.loads(found[0]) if found else []
    if not isinstance(ids, list) or not all(isinstance(x, str) and re.fullmatch('[0-9a-f]{64}', x) for x in ids):
        raise ValueError('invalid receipts')
    return ids


def snapshot_unlocked(root, project):
    owner, revision = registry.resolve(root, project)
    project = owner['id']
    path = safe(root, 'projects/' + slug(project) + '.md')
    text = path.read_text(encoding='utf-8') if path.exists() else ''
    done = receipts(text)
    pending = []
    related = []
    for group in registry.groups(owner):
        if group != project:
            child = safe(root, 'projects/' + group + '.md')
            if child.exists():
                child_text = child.read_text(encoding='utf-8')
                related.append({'path': str(child.relative_to(root)), 'markdown': child_text})
                # Keep child-integrated notes visible: the parent has not necessarily consumed them.
        base = safe(root, 'sessions/' + group)
        for item in sorted(base.glob('*.md')):
            item = safe(root, str(item.relative_to(root)))
            event = read_event(item)
            if event['project'] != group:
                raise ValueError('event project mismatch')
            if item.stem not in done:
                pending.append({'id': item.stem, 'path': str(item.relative_to(root)), **event})
    expected = digest(json.dumps({'markdown': text, 'registry': revision, 'related': related}, sort_keys=True))
    return {'project': project, 'expected': expected, 'document_hash': digest(text),
            'registry_revision': revision, 'groups': registry.groups(owner),
            'markdown': text, 'related_projects': related, 'pending': pending}


def snapshot(root, project):
    with locked(root):
        return snapshot_unlocked(root, project)


def date_field(text, key):
    front = text.split('\n---\n', 1)[0]
    found = re.findall(r'^' + key + r': (\d{4}-\d{2}-\d{2})$', front, re.M)
    if len(found) != 1:
        raise ValueError('missing or invalid ' + key)
    return dt.date.fromisoformat(found[0])


def integrate(root, request):
    project = slug(request['project'])
    with locked(root):
        state = snapshot_unlocked(root, project)
        project = state['project']
        if request['expected'] != state['expected']:
            raise ValueError('stale snapshot: re-read and rebuild integration; no project write')
        ids = request['events']
        pending = {e['id']: e for e in state['pending']}
        if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)) or any(i not in pending for i in ids):
            raise ValueError('events missing, duplicate, or already integrated')
        selected = [pending[i] for i in ids]
        old = state['markdown']
        mode = request['mode']
        if mode == 'history':
            if not old:
                raise ValueError('history needs an existing project; leave events pending')
            # Historical or uncertain events can only append evidence; live state is retained byte-for-byte.
            text = old.rstrip() + '\n\n## Session History\n\n'
            for event in selected:
                text += '- [' + event['observed'] + ' 세션 기록](../' + event['path'] + ')\n'
        elif mode == 'current':
            text = request['markdown']
            secret_check(text)
            if not text.startswith('---\n') or '\n---\n' not in text[4:]:
                raise ValueError('project metadata required')
            new_date = date_field(text, 'as_of')
            date_field(text, 'updated')
            old_date = date_field(old, 'as_of') if old else dt.date.min
            for event in selected:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', event['observed']):
                    raise ValueError('uncertain event date: history only or leave pending')
                event_date = dt.date.fromisoformat(event['observed'])
                if event_date < old_date or new_date < max(old_date, event_date):
                    raise ValueError('historical event or date regression: history only')
            front = text.split('\n---\n', 1)[0]
            if not re.search(r'^status: (draft|confirmed)$', front, re.M) or not re.search(r'^source:\s*\S', front, re.M):
                raise ValueError('status and source required')
            for heading in ('Current Status', 'Next Actions', 'Blockers', 'History', 'Decisions'):
                if not re.search(r'^## ' + heading + r'\s*$', text, re.M):
                    raise ValueError('missing project section')
        else:
            raise ValueError('invalid integration mode')
        front, body = text[4:].split('\n---\n', 1)
        front = re.sub(r'^integrated_sessions:.*\n?', '', front, flags=re.M).rstrip()
        done = sorted(set(receipts(old)) | set(ids))
        text = '---\n' + front + '\nintegrated_sessions: ' + json.dumps(done) + '\n---\n' + body
        secret_check(text)
        prose = re.sub(r'```.*?```', '', text, flags=re.S)
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', prose):
            target = target.strip('<>').split('#', 1)[0]
            if not target or re.match(r'[a-zA-Z][a-zA-Z0-9+.-]*:', target):
                continue
            resolved = (root / 'projects' / target).resolve()
            if root not in resolved.parents or not resolved.exists():
                raise ValueError('invalid project link')
        # Recheck immediately before replace, also catching most non-cooperating editor changes.
        path = safe(root, 'projects/' + project + '.md')
        actual = path.read_text(encoding='utf-8') if path.exists() else ''
        if digest(actual) != state['document_hash'] or registry.load(root)[1] != state['registry_revision']:
            raise ValueError('project changed during integration')
        atomic(path, text)
        return {'status': 'integrated', 'path': str(path.relative_to(root)), 'events': ids, 'mode': mode}


def register(root, request):
    """Append a distinct project. Changing an existing ownership mapping requires explicit review."""
    with locked(root):
        data, revision = registry.load(root)
        if request['expected_registry'] != revision:
            raise ValueError('stale registry; re-read before registering')
        entry = request['entry']
        secret_check(json.dumps(entry, ensure_ascii=False))
        data['projects'].append(entry)
        registry.validate(data)
        # Never claim an existing session folder in a new project by accident.
        for group in registry.groups(entry):
            if safe(root, 'sessions/' + group).exists() or safe(root, 'projects/' + group + '.md').exists():
                raise ValueError('existing records need explicit ownership review')
        atomic(safe(root, 'system/project-registry.json'), json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        return {'status': 'registered', 'project': entry['id']}


def bind(root, request):
    """Add explicitly confirmed ownership; never steal another project's keys."""
    with locked(root):
        data, revision = registry.load(root)
        if request['expected_registry'] != revision:
            raise ValueError('stale registry')
        secret_check(json.dumps(request, ensure_ascii=False))
        secret_check(request['source'])
        found = [p for p in data['projects'] if p['id'] == request['project']]
        if len(found) != 1:
            raise ValueError('canonical project required')
        owner = found[0]
        for field in ('aliases', 'session_groups'):
            additions = request.get(field, [])
            if not isinstance(additions, list) or not all(isinstance(v, str) for v in additions):
                raise ValueError('invalid bindings')
            owner[field] = sorted(set(owner[field] + additions))
        owner['source'] += '\n' + request['source']
        registry.validate(data)
        atomic(safe(root, 'system/project-registry.json'), json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        return {'status': 'bound', 'project': owner['id']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    save = sub.add_parser('record')
    for name in ('project', 'session', 'source'):
        save.add_argument('--' + name, required=True)
    save.add_argument('--observed', default='unknown')
    view = sub.add_parser('snapshot')
    view.add_argument('--project', required=True)
    sub.add_parser('integrate')
    sub.add_parser('register')
    sub.add_parser('catalog')
    sub.add_parser('bind')
    args = parser.parse_args()
    try:
        if args.command in {'record', 'integrate', 'register', 'bind'}:
            git_guard.require_isolated(ROOT)
        if args.command == 'record':
            result = record(ROOT, args.project, args.session, args.source, args.observed, sys.stdin.read())
        elif args.command == 'snapshot':
            result = snapshot(ROOT, args.project)
        elif args.command == 'integrate':
            result = integrate(ROOT, json.load(sys.stdin))
        elif args.command == 'register':
            result = register(ROOT, json.load(sys.stdin))
        elif args.command == 'bind':
            result = bind(ROOT, json.load(sys.stdin))
        else:
            data, revision = registry.load(ROOT)
            result = {'registry': data, 'expected_registry': revision}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError):
        # Do not echo input or filesystem exceptions containing possible secrets.
        print('ERROR: request rejected. Writes require a task branch in a linked worktree; '
              'use scripts/sync_workflow.py from the canonical repository. '
              'Also check dates, snapshot, paths, and pending IDs.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
