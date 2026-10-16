#!/usr/bin/env python3
"""Track completed weekly automation cycles and report missed tasks."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import hashlib
import os
from pathlib import Path


TASKS = {
    "integration": (5, 9, 0),  # Saturday 09:00, Monday=0
    "blog": (6, 10, 0),        # Sunday 10:00
}
REPOSITORY_ID = hashlib.sha256(str(Path(__file__).resolve().parents[1]).encode()).hexdigest()[:16]
DEFAULT_STATE_DIR = Path.home() / '.local/state/second-brain' / REPOSITORY_ID / 'state'


def now() -> dt.datetime:
    override = os.environ.get("SECOND_BRAIN_AUTOMATION_NOW")
    if override:
        value = dt.datetime.fromisoformat(override)
        return value if value.tzinfo else value.astimezone()
    return dt.datetime.now().astimezone()


def state_dir() -> Path:
    return Path(os.environ.get("SECOND_BRAIN_AUTOMATION_STATE_DIR", DEFAULT_STATE_DIR))


def scheduled_for(task: str, current: dt.datetime) -> dt.datetime:
    weekday, hour, minute = TASKS[task]
    candidate_date = current.date() - dt.timedelta(days=(current.weekday() - weekday) % 7)
    candidate = dt.datetime.combine(candidate_date, dt.time(hour, minute), current.tzinfo)
    if candidate > current:
        candidate -= dt.timedelta(days=7)
    return candidate


def path_for(task: str) -> Path:
    return state_dir() / f"{task}.json"


def read(task: str) -> dict | None:
    path = path_for(task)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and data.get("task") == task else None


def completed(task: str, current: dt.datetime) -> bool:
    # Settled for this schedule cycle; deferred/partial are never success markers.
    data = read(task)
    if not (data and data.get('protocol') == 2 and
            data.get('scheduled_for') == scheduled_for(task, current).isoformat() and
            data.get('outcome') in ('success', 'noop', 'partial', 'deferred')):
        return False
    try:
        raw = Path(data['result']).read_bytes()
        result = json.loads(raw)
        return (hashlib.sha256(raw).hexdigest() == data.get('result_sha256') and
                result.get('protocol') == 2 and result.get('task') == task and
                result.get('outcome') == data.get('outcome'))
    except (OSError, KeyError, ValueError, TypeError, AttributeError):
        return False


def record(task: str, current: dt.datetime, report: dict, evidence: str) -> None:
    if (report.get('protocol') != 2 or report.get('task') != task or
            report.get('outcome') not in ('success', 'noop', 'partial', 'deferred', 'failed')):
        raise ValueError('verified host result required')
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    old = path_for(task)
    if old.exists():
        raw = old.read_bytes()
        history = directory / 'history'
        history.mkdir(exist_ok=True)
        backup = history / (task + '-' + hashlib.sha256(raw).hexdigest() + '.json')
        if not backup.exists():
            with backup.open('xb') as handle:
                handle.write(raw)
            os.chmod(backup, 0o600)
    payload = {'protocol': 2, 'task': task, 'scheduled_for': scheduled_for(task, current).isoformat(),
               'outcome': report['outcome'], 'attempted_at': current.isoformat(),
               'reason': report['reason'], 'result': evidence,
               'result_sha256': hashlib.sha256(Path(evidence).read_bytes()).hexdigest()}
    if report['outcome'] in ('success', 'noop'):
        payload['completed_at'] = now().isoformat()
    temporary = directory / f'.{task}.{os.getpid()}.tmp'
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.chmod(temporary, 0o600)
    temporary.replace(old)


def write(task: str, current: dt.datetime, reason: str) -> None:
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "task": task,
        "scheduled_for": scheduled_for(task, current).isoformat(),
        "completed_at": current.isoformat(),
        "reason": reason,
    }
    temporary = directory / f".{task}.{os.getpid()}.tmp"
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path_for(task))


def due(current: dt.datetime) -> list[str]:
    return [task for task in ("integration", "blog") if not completed(task, current)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("due", "mark", "initialize", "status"))
    parser.add_argument("task", nargs="?", choices=tuple(TASKS))
    args = parser.parse_args()
    current = now()

    if args.command == "due":
        print("\n".join(due(current)))
    elif args.command == "mark":
        if not args.task:
            parser.error("mark requires a task")
        parser.error("mark disabled: only verified host results may update success state")
    elif args.command == "initialize":
        for task in TASKS:
            if read(task) is None:
                write(task, current, "initialized")
    else:
        result = {
            "now": current.isoformat(),
            "due": due(current),
            "tasks": {task: read(task) for task in TASKS},
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
