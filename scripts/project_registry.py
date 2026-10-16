"""Explicit project ownership; no directory, keyword, or repository-wide default."""
import hashlib
import json
from pathlib import Path
import re
import unicodedata


def norm(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', value).casefold() if c.isalnum())


def load(root):
    path = Path(root) / 'system/project-registry.json'
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('registry symlink rejected')
    text = path.read_text(encoding='utf-8') if path.exists() else ''
    data = json.loads(text) if text else {'version': 1, 'projects': []}
    validate(data)
    return data, hashlib.sha256(text.encode('utf-8')).hexdigest()


def validate(data):
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('projects'), list):
        raise ValueError('invalid registry')
    owners = {}
    ids = set()
    for entry in data['projects']:
        if not isinstance(entry, dict):
            raise ValueError('invalid entry')
        key = entry.get('id')
        if not isinstance(key, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', key) or key in ids:
            raise ValueError('invalid or duplicate project id')
        ids.add(key)
        for field in ('title', 'purpose', 'source'):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ValueError('project title, purpose, and source required')
        for field in ('aliases', 'session_groups'):
            if not isinstance(entry.get(field), list) or not all(isinstance(v, str) and norm(v) for v in entry[field]):
                raise ValueError('invalid project aliases or groups')
        if any(not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', x) for x in entry['session_groups']):
            raise ValueError('invalid session group')
        for value in (key, entry['title'], *entry['aliases'], *entry['session_groups']):
            normalized = norm(value)
            if normalized in owners and owners[normalized] != key:
                raise ValueError('project alias or session group belongs to multiple projects')
            owners[normalized] = key


def matches(data, query):
    query = query.strip()
    tokens = {norm(query)}
    # Only explicit ticket identifiers, never substrings such as PRJ-1 inside PRJ-10.
    tokens.update(norm(x) for x in re.findall(r'(?<![A-Za-z0-9_-])[A-Za-z]+-\d+(?![A-Za-z0-9_-])', query))
    result = []
    for entry in data['projects']:
        keys = (entry['id'], entry['title'], *entry['aliases'], *entry['session_groups'])
        if tokens & {norm(k) for k in keys}:
            result.append(entry)
    return result


def resolve(root, query):
    data, revision = load(root)
    found = matches(data, query)
    if len(found) != 1:
        raise ValueError('unregistered or ambiguous project; register or clarify before saving')
    return found[0], revision


def groups(entry):
    return sorted(set([entry['id'], *entry['session_groups']]))
