#!/usr/bin/env python3
"""Install the versioned Claude skill without replacing machine-specific settings."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def install(target, personal_root, config_source=None):
    if config_source:
        initial = json.loads(config_source.read_text(encoding='utf-8'))
        if not isinstance(initial, dict) or not initial.get('personal'):
            raise ValueError('routing config requires personal root')
        paths = [Path(initial[k]).expanduser().resolve() for k in ('personal', 'work') if initial.get(k)]
        if len(paths) == 2 and (paths[0] == paths[1] or paths[0] in paths[1].parents or paths[1] in paths[0].parents):
            raise ValueError('personal/work roots must be disjoint')
    target = target.expanduser().absolute()
    for path in (target, *target.parents):
        if path.is_symlink():
            raise ValueError('installation path must not contain symlinks')
    source = ROOT / 'skills/second-brain-sync'
    files = {'SKILL.md': source / 'SKILL.md', 'scripts/route.py': source / 'scripts/route.py',
             'scripts/github_scope.py': ROOT / 'scripts/github_scope.py',
             'scripts/project_registry.py': ROOT / 'scripts/project_registry.py',
             'references/experience-export.md': source / 'references/experience-export.md',
             'references/knowledge.md': source / 'references/knowledge.md'}
    config = target / 'config.json'
    if config.exists():
        if config.is_symlink():
            raise ValueError('config must not be a symlink')
        data = json.loads(config.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('invalid existing config; left unchanged')
    for name in files:
        dest = target / name
        if dest.is_symlink() or dest.parent.is_symlink():
            raise ValueError('installed files must not be symlinks')
    backup = None
    if any((target / name).exists() for name in files):
        backup = Path(tempfile.mkdtemp(prefix='second-brain-skill-backup-'))
        for name in files:
            if (target / name).exists():
                (backup / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target / name, backup / name)
    for name in files:
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(files[name], dest)
    if not config.exists():
        with config.open('x', encoding='utf-8') as out:
            initial = json.loads(config_source.read_text()) if config_source else {'personal': str(personal_root.resolve()), 'work': None}
            json.dump(initial, out, indent=2)
            out.write('\n')
    return {'installed': str(target), 'backup': str(backup) if backup else None,
            'config': str(config), 'existing_config_preserved': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path)
    parser.add_argument('--provider', choices=('claude', 'codex', 'gemini', 'grok'), default='claude')
    parser.add_argument('--config', type=Path, help='Local routing config used only for a fresh installation')
    args = parser.parse_args()
    paths = {'claude': '.claude', 'codex': '.agents', 'gemini': '.gemini', 'grok': '.grok'}
    target = args.target or Path.home() / paths[args.provider] / 'skills/second-brain-sync'
    print(json.dumps(install(target, ROOT, args.config), ensure_ascii=False, indent=2))
