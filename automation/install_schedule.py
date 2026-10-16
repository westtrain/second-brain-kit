#!/usr/bin/env python3
"""Generate repository-specific launchd jobs; activate only with an explicit flag."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def render(root, runtime, python):
    token = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    jobs = {}
    for task, weekday, hour in [('integration', 6, 9), ('blog', 0, 10), ('catch-up', None, None)]:
        label = 'org.second-brain.' + token + '.' + task
        data = {'Label': label, 'ProgramArguments': [str(python), str(root / 'automation/run.py'), task],
                'StandardOutPath': str(runtime / (task + '.out.log')), 'StandardErrorPath': str(runtime / (task + '.err.log'))}
        if weekday is not None:
            data['StartCalendarInterval'] = {'Weekday': weekday, 'Hour': hour, 'Minute': 0}
        else:
            data['RunAtLoad'] = True
            data['StartInterval'] = 3600
        jobs[label + '.plist'] = plistlib.dumps(data)
    return jobs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--activate', action='store_true')
    args = parser.parse_args()
    if args.activate and sys.platform != 'darwin':
        parser.error('launchd activation is macOS-only; use run.py with your scheduler on Linux')
    try:
        if json.loads((ROOT / 'system/scope.json').read_text()).get('scope') != 'work':
            raise ValueError('schedule requires a separate work brain')
        target = args.output_dir.expanduser().absolute()
        if any(p.is_symlink() for p in (target, *target.parents)):
            raise ValueError('symlink schedule target')
        from run import runtime_dir
        runtime = runtime_dir(ROOT) / 'launchd'
        jobs = render(ROOT, runtime, sys.executable)
        for name, content in jobs.items():
            path = target / name
            if path.is_symlink() or (path.exists() and path.read_bytes() != content):
                raise ValueError('existing job differs; review before replacing')
        target.mkdir(parents=True, exist_ok=True)
        for name, content in jobs.items():
            (target / name).write_bytes(content)
        if args.activate:
            import os
            runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
            domain = 'gui/' + str(os.getuid())
            for name in jobs:
                subprocess.run(['launchctl', 'bootout', domain, str(target / name)], capture_output=True)
                subprocess.run(['launchctl', 'bootstrap', domain, str(target / name)], check=True)
        print(json.dumps({'files': [str(target / n) for n in jobs], 'activated': args.activate}, indent=2))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print('Schedule stopped: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
