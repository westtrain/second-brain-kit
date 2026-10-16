#!/usr/bin/env python3
"""Work-local candidates and exact-revision, user-reviewed personal exports. No network."""
import argparse
import json
from pathlib import Path
import re
from subprocess import CalledProcessError
import sys

import brain
import project_registry as registry
from git_guard import linked_checkout, require_isolated
from session_sync import atomic, digest, locked, safe, secret_check, slug

ROOT = Path(__file__).resolve().parents[1]
DESTINATIONS = {'blog': 'blog', 'career': 'career', 'learning': 'learnings'}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n'


def companies(work):
    path = safe(work, 'system/company-registry.json')
    raw = path.read_text(encoding='utf-8') if path.exists() else ''
    data = json.loads(raw) if raw else {'version': 1, 'companies': {}, 'projects': {}}
    if data.get('version') != 1 or not isinstance(data.get('companies'), dict) or not isinstance(data.get('projects'), dict):
        raise ValueError('invalid company registry')
    names = set()
    for identifier, name in data['companies'].items():
        slug(identifier)
        if not isinstance(name, str) or not name.strip() or len(name) > 200 or '\n' in name or '\r' in name:
            raise ValueError('invalid company name')
        normalized = registry.norm(name)
        if not normalized or normalized in names:
            raise ValueError('duplicate company identity')
        names.add(normalized)
    for project, entry in data['projects'].items():
        slug(project)
        if entry['company_id'] not in data['companies'] or not entry['source'].strip():
            raise ValueError('invalid company binding')
    return data, digest(raw)


def bind_company(work, request):
    """Register explicit historical ownership. No mutable current-company default."""
    with locked(work):
        data, revision = companies(work)
        projects, project_revision = registry.load(work)
        if request['expected'] != revision or request['expected_registry'] != project_revision:
            raise ValueError('stale company or project registry')
        identifier, name = slug(request['company_id']), request['company_name'].strip()
        secret_check(name)
        secret_check(request['source'])
        if identifier in data['companies'] and data['companies'][identifier] != name:
            raise ValueError('company identity cannot change')
        selected = request['projects']
        if not isinstance(selected, list) or not selected or len(set(selected)) != len(selected):
            raise ValueError('explicit canonical projects required')
        canonical = {p['id'] for p in projects['projects']}
        for project in selected:
            if project not in canonical:
                raise ValueError('unknown canonical project')
            previous = data['projects'].get(project)
            if previous and previous['company_id'] != identifier:
                raise ValueError('historical ownership cannot be reassigned')
            data['projects'].setdefault(project, {'company_id': identifier, 'source': request['source']})
        if not registry.norm(name) or any(registry.norm(n) == registry.norm(name) and k != identifier for k, n in data['companies'].items()):
            raise ValueError('duplicate company identity')
        if len(name) > 200 or '\n' in name or '\r' in name:
            raise ValueError('invalid company name')
        data['companies'][identifier] = name
        atomic(safe(work, 'system/company-registry.json'), encode(data))
        return {'registry': data, 'expected': digest(encode(data))}


def company_for(work, project):
    data, _ = companies(work)
    if project not in data['projects']:
        raise ValueError('project company must be registered before career export')
    identifier = data['projects'][project]['company_id']
    return {'id': identifier, 'name': data['companies'][identifier]}


def destination(data):
    if data['kind'] == 'career':
        return 'career/companies/' + slug(data['company']['id']) + '/experiences/' + slug(data['id']) + '.md'
    return DESTINATIONS[data['kind']] + '/' + slug(data['id']) + '.md'


def check_company(work, data):
    if data['kind'] == 'career' and data.get('company') != company_for(work, data['project']):
        raise ValueError('missing or changed company; re-propose and review explicitly')


def roots(config, work, personal_checkout=None):
    data = json.loads(config.read_text(encoding='utf-8'))
    paths = [Path(data[k]).expanduser().absolute() for k in ('work', 'personal')]
    for path in paths:
        if any(p.is_symlink() for p in (path, *path.parents)) or not (path / 'AGENTS.md').is_file():
            raise ValueError('invalid brain root')
    company, personal = paths
    if company == personal or company in personal.parents or personal in company.parents:
        raise ValueError('work tool and disjoint configured roots required')
    if company != work:
        linked_checkout(company, work)
    if personal_checkout:
        personal = linked_checkout(personal, personal_checkout)
    return work, personal


def candidate_path(work, identifier):
    return safe(work, 'exports/candidates/' + slug(identifier) + '.json')


def read(work, identifier):
    path = candidate_path(work, identifier)
    raw = path.read_text(encoding='utf-8') if path.exists() else ''
    return (json.loads(raw) if raw else None), digest(raw)


def catalog(work):
    with locked(work):
        directory = safe(work, 'exports/candidates')
        result = []
        for path in sorted(directory.glob('*.json')):
            data, revision = read(work, path.stem)
            result.append({**data, 'expected': revision})
        return result


def propose(work, request):
    """AI supplies a selected, rewritten body; provenance stays in the work brain."""
    identifier = slug(request['id'])
    with locked(work):
        old, revision = read(work, identifier)
        if request['expected'] != revision:
            raise ValueError('stale candidate')
        if old and old['state'] != 'draft':
            raise ValueError('review frozen; explicitly reopen before editing')
        owner, _ = registry.resolve(work, request['project'])
        kind = request['kind']
        if kind not in DESTINATIONS:
            raise ValueError('invalid kind')
        if old and (old['project'] != owner['id'] or old['kind'] != kind):
            raise ValueError('candidate identity cannot change')
        sources = request['sources']
        if not isinstance(sources, list) or not sources:
            raise ValueError('evidence required')
        evidence = []
        allowed = ['projects/' + g + '.md' for g in registry.groups(owner)]
        for source in sources:
            path = safe(work, source)
            relative = path.relative_to(work).as_posix()
            if relative not in allowed and not any(relative.startswith('sessions/' + g + '/') for g in registry.groups(owner)):
                raise ValueError('source outside selected project')
            if path.suffix != '.md' or not path.is_file():
                raise ValueError('missing evidence')
            evidence.append({'path': relative, 'hash': digest(path.read_text(encoding='utf-8'))})
        title, body = request['title'].strip(), request['body'].strip()
        if not title or len(title) > 200 or '\n' in title or '\r' in title:
            raise ValueError('invalid title')
        for value in (title, body, request['review_notes']):
            secret_check(value)
        data = {'id': identifier, 'state': 'draft', 'project': owner['id'], 'kind': kind,
                'title': title, 'body': body, 'sources': evidence,
                'review_notes': request['review_notes'], 'updated': brain.today()}
        if kind == 'career':
            data['company'] = company_for(work, owner['id'])
            if old and old.get('company') and old['company'] != data['company']:
                raise ValueError('candidate company cannot change')
        atomic(candidate_path(work, identifier), encode(data))
        return {**data, 'expected': digest(encode(data))}


def markdown(data):
    # Never serialize source paths, tickets, private notes, or approval messages here.
    company = ''
    if data['kind'] == 'career':
        company = '\ncompany_id: ' + json.dumps(data['company']['id']) + '\ncompany_name: ' + json.dumps(data['company']['name'], ensure_ascii=False)
    return ('---\nstatus: draft\nupdated: ' + data['updated']
            + company + '\nsource: "사용자가 개인 보관을 검토한 경험 기록"\n---\n# '
            + data['title'] + '\n\n' + data['body'] + '\n')


def export_check(data, payload):
    secret_check(payload)
    # Obvious local references are never useful in a portable personal article.
    if re.search(r'(?:file://|/Users/|/home/|[A-Za-z]:\\)', payload):
        raise ValueError('local path in export body')
    for source in data['sources']:
        if source['path'] in payload:
            raise ValueError('work provenance in export body')
    for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', payload):
        if not target.startswith(('https://', 'http://', '#')):
            raise ValueError('nonportable link in export body')


def review(work, request):
    with locked(work):
        data, revision = read(work, request['id'])
        if not data or request['expected'] != revision or data['state'] not in ('draft', 'review'):
            raise ValueError('stale or invalid review')
        check_company(work, data)
        payload = markdown(data)
        export_check(data, payload)
        version = digest(payload)
        relative = 'exports/reviews/' + data['id'] + '-' + version + '.md'
        path = safe(work, relative)
        if path.exists() and path.read_text(encoding='utf-8') != payload:
            raise ValueError('review file changed')
        if not path.exists():
            atomic(path, payload)
        data.update(state='review', review_hash=version, review_path=relative, destination=destination(data))
        atomic(candidate_path(work, data['id']), encode(data))
        return {**data, 'expected': digest(encode(data)), 'markdown': payload}


def reopen(work, request):
    with locked(work):
        data, revision = read(work, request['id'])
        if not data or request['expected'] != revision or data['state'] != 'review':
            raise ValueError('only current review may reopen')
        data['state'] = 'draft'
        data.pop('review_hash', None)
        data.pop('review_path', None)
        data.pop('destination', None)
        atomic(candidate_path(work, data['id']), encode(data))
        return {**data, 'expected': digest(encode(data))}


def release(work, personal, request):
    """Caller must have explicit user approval for this reviewed body and destination.

    This CLI records that approval; it cannot authenticate a human or classify secrets.
    Copy first, record receipt second; retry compares exact bytes after interruption.
    """
    with locked(work), locked(personal):
        data, revision = read(work, request['id'])
        if not data or data['state'] not in ('review', 'exported'):
            raise ValueError('review required')
        if request.get('approved_for') != 'personal-storage' or not request.get('approval_source', '').strip():
            raise ValueError('explicit personal-storage approval required')
        if request['review_hash'] != data['review_hash']:
            raise ValueError('approval is for another revision')
        check_company(work, data)
        payload = markdown(data)
        review_file = safe(work, data['review_path'])
        if digest(payload) != request['review_hash'] or review_file.read_text(encoding='utf-8') != payload:
            raise ValueError('review content changed')
        export_check(data, payload)
        secret_check(request['approval_source'])
        target = destination(data)
        if data.get('destination', target) != target:
            raise ValueError('reviewed destination changed')
        path = safe(personal, target)
        if path.exists():
            if path.read_text(encoding='utf-8') != payload:
                raise ValueError('personal document exists; never overwrite')
        else:
            if data['state'] == 'exported':
                raise ValueError('previous export removed; do not silently recreate')
            atomic(path, payload)
        data.update(state='exported', exported_to=target,
                    approval_source=request['approval_source'], exported_on=brain.today())
        atomic(candidate_path(work, data['id']), encode(data))
        return {'state': 'exported', 'path': str(path), 'review_hash': data['review_hash']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('catalog', 'propose', 'review', 'reopen', 'release', 'companies', 'bind-company'))
    parser.add_argument('--config', type=Path, default=Path.home() / '.claude/skills/second-brain-sync/config.json')
    parser.add_argument('--personal-checkout', type=Path)
    args = parser.parse_args()
    try:
        work, personal = roots(args.config, ROOT, args.personal_checkout)
        if args.command not in ('catalog', 'companies'):
            require_isolated(work)
        if args.command == 'release':
            if not args.personal_checkout:
                raise ValueError('personal task checkout required')
            require_isolated(personal)
        if args.command == 'catalog':
            result = catalog(work)
        elif args.command == 'companies':
            with locked(work):
                data, revision = companies(work)
                _, project_revision = registry.load(work)
                result = {'registry': data, 'expected': revision, 'expected_registry': project_revision}
        else:
            request = json.load(sys.stdin)
            if args.command == 'release':
                result = release(work, personal, request)
            else:
                result = {'propose': propose, 'review': review, 'reopen': reopen, 'bind-company': bind_company}[args.command](work, request)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError, AttributeError, CalledProcessError):
        print('ERROR: export rejected; re-read candidate, evidence, review and configuration.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
