#!/usr/bin/env python3
"""Read-only scope selection and project discovery. No model or network calls."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

try:
    import project_registry as registry
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
    import project_registry as registry


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', value).casefold() if c.isalnum())


def instruction_state(root, known=None):
    """Hash only instructions in the selected scope; no session content or cache writes."""
    skill = Path(__file__).resolve().parents[1]
    selected = [(skill, 'SKILL.md'), (skill, 'references/experience-export.md')]
    selected += [(root, name) for name in (
        'AGENTS.md', 'CLAUDE.md', 'GEMINI.md', 'README.md', 'MEMORY.md', 'system/memory-maintenance.md', 'system/principles.md', 'system/privacy.md',
        'system/conventions.md', 'system/workflows.md', 'system/git-workflow.md', 'system/bootstrap.md',
        'system/session-handoff.md', 'system/project-registry-guide.md',
        'system/experience-export.md', 'system/company-career.md',
        'findings/README.md', 'incidents/README.md')]
    files = []
    for base, name in selected:
        path = base / name
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != base and base in p.parents):
            raise ValueError('symlink instruction')
        if not path.exists():
            if name in ('SKILL.md', 'AGENTS.md'):
                raise ValueError('required instruction missing')
            continue
        raw = path.read_bytes()
        files.append({'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()})
    revision = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    match = re.search(r'^\s+version:\s*"?([0-9]+\.[0-9]+\.[0-9]+)', (skill / 'SKILL.md').read_text(), re.M)
    return {'skill_version': match.group(1) if match else 'unknown',
            'revision': revision, 'reload_required': known != revision, 'files': files,
            'instruction': 'Read listed instruction files before continuing when reload_required is true. '
                           'Only reuse this revision after actually reading them; always re-read project state and pending records.'}


def discover(config, scope, project=None, known_instructions=None):
    if scope not in ('personal', 'work'):
        return {'status': 'blocked', 'reason': 'scope_unknown'}
    raw = config.get(scope)
    if not raw:
        return {'status': 'blocked', 'reason': scope + '_not_configured'}
    roots = {}
    for name in ('personal', 'work'):
        value = config.get(name)
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise ValueError('invalid root configuration')
            path = Path(value).expanduser()
            if not path.is_absolute():
                raise ValueError('root must be absolute')
            roots[name] = path.resolve()
    if len(roots) == 2:
        a, b = roots.values()
        if a == b or a in b.parents or b in a.parents:
            return {'status': 'blocked', 'reason': 'overlapping_roots'}
    root = roots[scope]
    if not root.is_dir() or not (root / 'AGENTS.md').is_file():
        return {'status': 'blocked', 'reason': 'root_not_ready'}
    instructions = instruction_state(root, known_instructions)
    candidates = []
    for folder in ('projects', 'archive'):
        base = root / folder
        if base.is_symlink():
            return {'status': 'blocked', 'reason': 'symlink_directory'}
        if not base.exists():
            continue
        for path in sorted(base.rglob('*.md')):
            if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root and root in p.parents):
                return {'status': 'blocked', 'reason': 'symlink_document'}
            if root not in path.resolve().parents:
                return {'status': 'blocked', 'reason': 'outside_root'}
            body = path.read_text(encoding='utf-8')
            heading = re.search(r'^# (.+)$', body, re.M)
            title = heading.group(1).strip() if heading else path.stem
            front = body.split('---', 2)[1] if body.startswith('---\n') and body.count('---') >= 2 else ''
            aliases_line = re.search(r'^aliases:\s*(\[.*\])\s*$', front, re.M)
            aliases = json.loads(aliases_line.group(1)) if aliases_line else []
            if not isinstance(aliases, list) or not all(isinstance(x, str) for x in aliases):
                raise ValueError('aliases must be a JSON string array')
            keys = [title, path.stem, *aliases]
            candidates.append({'path': str(path.relative_to(root)), 'title': title,
                               'archived': folder == 'archive',
                               'exact': bool(project and normalized(project) and
                                             normalized(project) in [normalized(x) for x in keys])})
    sessions = root / 'sessions'
    if sessions.is_symlink():
        return {'status': 'blocked', 'reason': 'symlink_directory'}
    for folder in sorted(sessions.iterdir()) if sessions.exists() else []:
        if folder.is_symlink():
            return {'status': 'blocked', 'reason': 'symlink_directory'}
        if folder.is_dir() and re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', folder.name):
            if not (root / 'projects' / (folder.name + '.md')).exists():
                candidates.append({'path': str(folder.relative_to(root)), 'title': folder.name,
                                   'archived': False, 'pending_only': True,
                                   'exact': bool(project and normalized(project) == normalized(folder.name))})
    catalog, revision = registry.load(root)
    found = registry.matches(catalog, project) if project else []
    if catalog['projects']:
        # The registry owns project identity. Legacy filenames remain visible as unassigned candidates.
        for candidate in candidates:
            candidate['exact'] = False
        registered = []
        for entry in catalog['projects']:
            registered.append({'path': 'projects/' + entry['id'] + '.md', 'title': entry['title'],
                               'project': entry['id'], 'purpose': entry['purpose'], 'groups': registry.groups(entry),
                               'registered': True, 'archived': False, 'exact': entry in found})
        candidates = registered + candidates
    exact = [x for x in candidates if x['exact']]
    status = 'list' if not project else 'no_exact_match'
    if exact:
        status = 'ambiguous' if len(exact) > 1 else 'archived_match' if exact[0]['archived'] else 'match'
    if project and not found:
        status = 'registration_required'
    return {'status': status, 'scope': scope, 'root': str(root), 'candidates': candidates,
            'instructions': instructions,
            'expected_registry': revision,
            'instruction': 'Only registered identity permits saving. Compare purpose; register a distinct new project or clarify.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', required=True, choices=('personal', 'work', 'unknown'))
    parser.add_argument('--project')
    parser.add_argument('--known-instructions', help='Revision actually read earlier in this session and scope')
    parser.add_argument('--config', type=Path, default=Path(__file__).resolve().parents[1] / 'config.json')
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding='utf-8'))
        if not isinstance(config, dict):
            raise ValueError('invalid config')
        result = discover(config, args.scope, args.project, args.known_instructions)
    except (OSError, ValueError, TypeError):
        result = {'status': 'blocked', 'reason': 'invalid_or_missing_config_or_document'}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result['status'] == 'blocked' else 0


if __name__ == '__main__':
    sys.exit(main())
