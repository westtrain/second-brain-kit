#!/usr/bin/env python3
"""Create a fresh local brain from toolkit files. No remote or account changes."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ('memory', 'projects', 'sessions', 'notes', 'decisions', 'inbox', 'archive', 'career', 'learnings', 'blog', 'findings', 'incidents')


def initialize(target, scope='personal'):
    if scope not in ('personal', 'work'):
        raise ValueError('scope must be personal or work')
    target = Path(target).expanduser().absolute()
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError('target path must not contain symlinks')
    if target.exists() or os.path.lexists(target):
        raise ValueError('target already exists; choose a new directory')
    if ROOT == target or ROOT in target.parents:
        raise ValueError('create your brain outside the public toolkit')
    target.mkdir(parents=True)
    # Infrastructure allowlist. Never copy content folders, INDEX, .git, or machine config.
    files = [Path(n) for n in ('AGENTS.md', 'CLAUDE.md', 'GEMINI.md', 'MEMORY.md', '.gitignore', 'LICENSE')]
    for folder, pattern in [('scripts', '*.py'), ('tests', 'test_*.py'), ('templates', '*.md'), ('.githooks', '*'), ('system', '*.md')]:
        files.extend(Path(folder) / p.name for p in sorted((ROOT / folder).glob(pattern)) if p.is_file())
    for folder in ('automation', 'profiles', 'docs'):
        for source in sorted((ROOT / folder).rglob('*')):
            if source.is_file() and source.suffix in ('.py', '.md', '.json') and source.name != 'config.json':
                files.append(source.relative_to(ROOT))
    skill = Path('skills/second-brain-sync')
    files.extend(skill / n for n in ('SKILL.md', 'scripts/route.py', 'references/experience-export.md', 'config.example.json'))
    for relative in files:
        source = ROOT / relative
        if source.is_symlink() or any(p.is_symlink() for p in source.parents if ROOT in p.parents):
            raise ValueError('symlink source rejected')
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    agent = target / 'AGENTS.md'
    agent.write_text(agent.read_text().split('이 공개 저장소는 도구 배포본이다.')[0] + '이 저장소는 사용자의 로컬 기억 정본이다. 원격 연결·외부 공유는 명시적인 요청이 있을 때만 설정한다.\n', encoding='utf-8')
    (target / 'README.md').write_text((ROOT / 'docs/brain-readme.md').read_text().replace('](../', ']('), encoding='utf-8')
    # Keep the initializer usable in a generated brain as well.
    (target / 'docs').mkdir(exist_ok=True)
    shutil.copy2(ROOT / 'docs/brain-readme.md', target / 'docs/brain-readme.md')
    (target / 'system/project-registry.json').write_text(json.dumps({'version': 1, 'projects': []}, indent=2) + '\n')
    (target / 'MEMORY.md').write_text('''# 나의 세컨브레인

- [시작 안내](README.md) · [정보 경계](system/privacy.md)
- [현재 프로젝트](INDEX.md#프로젝트) · [전체 색인](INDEX.md)
- [프로젝트 등록부](system/project-registry.json)
- [운영 흐름](system/workflows.md) · [Git 절차](system/git-workflow.md)
- [기억 점검](system/memory-maintenance.md)
''', encoding='utf-8')
    (target / 'system/scope.json').write_text(json.dumps({'scope': scope}) + '\n')
    if scope == 'work':
        (target / 'system/company-registry.json').write_text(json.dumps({'version': 1, 'companies': {}, 'projects': {}}, indent=2) + '\n')
    selected = ('memory', 'projects', 'sessions', 'notes', 'decisions', 'inbox', 'archive')
    selected += ('career/companies', 'learnings', 'blog') if scope == 'personal' else ('findings', 'incidents', 'exports/candidates', 'exports/reviews')
    for relative in (ROOT / 'profiles' / scope).rglob('*.md'):
        destination = target / relative.relative_to(ROOT / 'profiles' / scope)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(relative, destination)
    memory = target / 'MEMORY.md'
    scope_links = '\n- [회사별 경력](career/index.md)\n' if scope == 'personal' else '\n- [미뤄 둔 문제](findings/README.md) · [실제 장애](incidents/README.md)\n- [경험 검토·전달](system/experience-export.md) · [예약 자동화](automation/README.md)\n'
    memory.write_text(memory.read_text() + scope_links, encoding='utf-8')
    for folder in selected:
        (target / folder).mkdir(parents=True, exist_ok=True)
        (target / folder / '.gitkeep').touch()
    def git(*args):
        return subprocess.run(['git', '-C', str(target), *args], check=True, capture_output=True, text=True)
    git('init', '-b', 'main')
    git('config', 'user.name', 'Second Brain Local')
    git('config', 'user.email', 'second-brain@localhost')
    # Initial creation only; subsequent index writes require an isolated worktree.
    sys.path.insert(0, str(target / 'scripts'))
    import memory_tools
    (target / 'INDEX.md').write_text(memory_tools.render_index(target.resolve()), encoding='utf-8')
    subprocess.run([sys.executable, str(target / 'scripts/brain.py'), 'check'], check=True, capture_output=True, text=True)
    git('add', '.')
    git('commit', '-m', 'chore: initialize empty local second brain')
    git('config', 'core.hooksPath', '.githooks')
    return {'created': str(target), 'remote': None, 'projects': 0, 'hooks_enabled': True, 'scope': scope}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True, type=Path)
    parser.add_argument('--scope', choices=('personal', 'work'), default='personal')
    parser.add_argument('--pair', action='store_true', help='Create independent personal/work repos and one local routing config')
    args = parser.parse_args()
    try:
        if args.pair:
            base = args.target.expanduser().absolute()
            if base.exists() or any(p.is_symlink() for p in (base, *base.parents)) or ROOT == base or ROOT in base.parents:
                raise ValueError('pair requires a new non-symlink directory outside toolkit')
            personal = initialize(base / 'personal', 'personal')
            work = initialize(base / 'work', 'work')
            config = base / 'config.json'
            config.write_text(json.dumps({'personal': personal['created'], 'work': work['created']}, indent=2) + '\n')
            os.chmod(config, 0o600)
            output = {'personal': personal, 'work': work, 'config': str(config)}
        else:
            output = initialize(args.target, args.scope)
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print('Initialization stopped: ' + str(error) + '. Existing files are never replaced.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
