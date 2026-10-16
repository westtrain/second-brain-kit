#!/usr/bin/env python3
"""Portable, opt-in scheduler entrypoint; one lock per local work brain."""
import argparse
from contextlib import contextmanager
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import brain
import host_runner
import providers
import schedule_state


def runtime_dir(root):
    token = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    return Path.home() / '.local/state/second-brain' / token


@contextmanager
def lock(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(directory / 'run.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('another automation run is active') from error
        yield


def configuration(root, filename=None):
    path = filename or root / 'automation/config.json'
    config = json.loads(path.read_text()) if path.exists() else {'provider': 'codex'}
    if config.get('provider') not in providers.PROVIDERS:
        raise ValueError('unsupported provider')
    executable = config.get('executable', config['provider'])
    if not isinstance(executable, str) or not shutil.which(executable):
        raise ValueError('planner CLI not found; install/authenticate chosen provider separately')
    return config['provider'], executable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task', choices=('integration', 'blog', 'catch-up', 'check'))
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    try:
        if json.loads((ROOT / 'system/scope.json').read_text()).get('scope') != 'work':
            raise ValueError('scheduled work integration/blog requires a separate work brain')
        host_runner.clean(ROOT)
        errors = brain.check(ROOT)
        if errors:
            raise ValueError('document checks failed: ' + ', '.join(errors))
        provider, executable = configuration(ROOT, args.config)
        if args.task == 'check':
            print(json.dumps({'ready': True, 'provider': provider, 'root': str(ROOT), 'auth': 'not checked'}))
            return 0
        directory = runtime_dir(ROOT)
        os.environ['SECOND_BRAIN_AUTOMATION_STATE_DIR'] = str(directory / 'state')
        with lock(directory):
            tasks = schedule_state.due(schedule_state.now()) if args.task == 'catch-up' else [args.task]
            for task in tasks:
                artifacts = directory / 'logs' / (task + '-' + dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
                result = subprocess.run([sys.executable, str(ROOT / 'automation/host_runner.py'), task,
                                         '--artifacts', str(artifacts), '--provider', provider, '--executable', executable], cwd=ROOT)
                if result.returncode:
                    return result.returncode
        return 0
    except (OSError, ValueError, KeyError) as error:
        print('Automation stopped: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
