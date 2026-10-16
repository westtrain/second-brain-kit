#!/usr/bin/env python3
"""Local helpers. Standard library only; no network, model, or background tasks."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ("memory", "projects", "notes", "decisions", "career", "learnings", "life", "blog", "findings", "incidents")
INCIDENT_SEVERITIES = ("심각", "높음", "보통", "낮음")
INCIDENT_STATES = ("대응중", "복구됨", "사후분석완료", "종료")
PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("api-token", re.compile(r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b")),
    ("assigned-secret", re.compile(r"(?im)^\s*(?:password|api_key|secret|access_token)\s*[:=]\s*[\"']?\S{6,}")),
    ("restricted-label", re.compile(r"(?:회사\s*기밀|사내\s*기밀|company\s+confidential)", re.I)),
)

def today():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()

def violations(text):
    return [name for name, pattern in PATTERNS if pattern.search(text)]

def safe_files(root, folders):
    for folder in folders:
        base = root / folder
        if not base.exists():
            continue
        if base.is_symlink():
            raise ValueError("symlink directory excluded: " + folder)
        for p in sorted(base.rglob("*.md")):
            if p.is_symlink() or root.resolve() not in p.resolve().parents:
                raise ValueError("symlink or outside path excluded")
            # Reject symlink ancestors even when they point inside the repository.
            if any((root / a).is_symlink() for a in p.relative_to(root).parents):
                raise ValueError("symlink ancestor")
            yield p

def capture(root, title, source, body):
    if not title.strip() or not source.strip() or not body.strip():
        raise ValueError("title, source and body are required")
    if len(title) > 200 or "\n" in title or "\r" in title:
        raise ValueError("title must be a short single line")
    found = violations(title + "\n" + source + "\n" + body)
    if found:
        raise ValueError("input rejected before writing; categories: " + ", ".join(found))
    body = body.strip()
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    # Search active notes AND archived inbox, so a repeated capture stays idempotent.
    for p in safe_files(root, (*CONTENT, "inbox", "archive")):
        text = p.read_text(encoding="utf-8")
        if ("capture_hash: " + digest) in text:
            return p, False
    inbox = root / "inbox"
    if inbox.is_symlink():
        raise ValueError("inbox must not be a symlink")
    inbox.mkdir(exist_ok=True)
    stamp = today()
    p = inbox / (stamp + "-capture-" + digest[:12] + ".md")
    text = (
        "---\nstatus: draft\nupdated: " + stamp
        + "\nsource: " + json.dumps(source, ensure_ascii=False)
        + "\ncapture_hash: " + digest
        + "\n---\n# " + title + "\n\n"
        + body + "\n\n## 처리\n미처리\n"
    )
    # Never overwrite even a hash-prefix collision or an existing unrelated file.
    with p.open("x", encoding="utf-8") as f:
        f.write(text)
    return p, True

def search(root, query, include_inbox=False, include_archive=False, include_sessions=False):
    folders = list(CONTENT)
    if include_inbox:
        folders.append("inbox")
    if include_archive:
        folders.append("archive")
    if include_sessions:
        folders.append("sessions")
    words = query.casefold().split()
    for p in safe_files(root, folders):
        body = p.read_text(encoding="utf-8")
        if words and all(w in body.casefold() for w in words):
            # Show filenames only: avoid echoing potentially sensitive snippets.
            yield p.relative_to(root).as_posix()

def metadata_value(front, key):
    match = re.search(r"(?m)^" + key + r":\s*(.*\S)\s*$", front)
    return match.group(1).strip() if match else None

def incident_time(value):
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None

def check(root):
    errors = []
    paths = list(safe_files(root, (*CONTENT, "inbox", "archive", "sessions", "system", "templates")))
    for name in ("README.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md", "MEMORY.md", "INDEX.md"):
        if (root / name).exists():
            paths.append(root / name)
    for p in paths:
        text = p.read_text(encoding="utf-8")
        rel = p.relative_to(root).as_posix()
        front = None
        if rel.split("/")[0] in (*CONTENT, "inbox", "archive", "sessions"):
            if not text.startswith("---\n"):
                errors.append(rel + ": missing metadata")
            else:
                parts = text.split("---", 2)
                if len(parts) < 3:
                    errors.append(rel + ": unclosed metadata")
                else:
                    front = parts[1]
                    for key in ("status", "updated", "source"):
                        if not re.search(r"(?m)^" + key + r":\s*\S", front):
                            errors.append(rel + ": missing " + key)
                    status = re.search(r"(?m)^status:\s*(\S+)", front)
                    if status and status.group(1) not in ("draft", "confirmed", "archived"):
                        errors.append(rel + ": invalid status")
                    for key in ("updated", "as_of"):
                        val = re.search(r"(?m)^" + key + r":\s*(\S+)", front)
                        if val:
                            try:
                                dt.date.fromisoformat(val.group(1))
                            except ValueError:
                                errors.append(rel + ": invalid " + key)
                    if rel.startswith("projects/") and not re.search(r"(?m)^as_of:", front):
                        errors.append(rel + ": missing as_of")
        if rel.startswith("incidents/") and p.name != "README.md" and front is not None:
            values = {key: metadata_value(front, key) for key in
                      ("severity", "state", "detected", "resolved", "owner", "systems")}
            for key, value in values.items():
                if not value:
                    errors.append(rel + ": missing " + key)
            if values["severity"] and values["severity"] not in INCIDENT_SEVERITIES:
                errors.append(rel + ": invalid severity")
            if values["state"] and values["state"] not in INCIDENT_STATES:
                errors.append(rel + ": invalid state")
            detected = incident_time(values["detected"])
            if values["detected"] and detected is None:
                errors.append(rel + ": invalid detected")
            resolved = None if values["resolved"] == "미정" else incident_time(values["resolved"])
            if values["resolved"] and values["resolved"] != "미정" and resolved is None:
                errors.append(rel + ": invalid resolved")
            if detected and resolved and resolved < detected:
                errors.append(rel + ": resolved before detected")
            if detected and not p.name.startswith(detected.date().isoformat() + "-"):
                errors.append(rel + ": filename date differs from detected")
        # Check actual inline links outside fenced examples. External URLs aren't fetched.
        prose = re.sub(r"```.*?```", "", text, flags=re.S)
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", prose):
            target = target.strip("<>").split("#", 1)[0]
            if not target or re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            resolved = (p.parent / target).resolve()
            if root.resolve() != resolved and root.resolve() not in resolved.parents:
                errors.append(rel + ": link outside repository")
            elif not resolved.exists():
                errors.append(rel + ": missing link target " + target)
    incidents = root / "incidents"
    if incidents.exists() and not incidents.is_symlink():
        index = incidents / "README.md"
        details = [p for p in incidents.glob("*.md") if p.name != "README.md"]
        if details and not index.is_file():
            errors.append("incidents/README.md: missing incident index")
        elif index.is_file():
            index_text = index.read_text(encoding="utf-8")
            for detail in details:
                if "(" + detail.name + ")" not in index_text:
                    errors.append("incidents/README.md: unindexed incident " + detail.name)
    return errors

def staged_check(root):
    """Inspect index blobs, not working files: partial staging is respected."""
    run = lambda *args: subprocess.check_output(["git", "-C", str(root), *args])
    paths = run("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").decode().split("\0")
    errors = []
    for name in filter(None, paths):
        parts = Path(name).parts
        mode = run("ls-files", "--stage", "--", name).split(b" ", 1)[0]
        if mode == b"120000":
            errors.append(name + ": symbolic links are not allowed in the knowledge repository")
            continue
        if any(x in ("private", "private-vault", "secrets", ".obsidian") for x in parts) or Path(name).name.startswith(".env") or Path(name).suffix in (".key", ".pem", ".bundle", ".zip"):
            errors.append(name + ": prohibited path")
            continue
        data = run("show", ":" + name)
        if len(data) > 2_000_000 or b"\0" in data:
            errors.append(name + ": binary or oversized file requires separate storage")
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(name + ": non-UTF8 file")
            continue
        # Policy documents can discuss company confidentiality; token detection still applies.
        found = [v for v in violations(text) if v != "restricted-label"]
        if found:
            errors.append(name + ": blocked categories: " + ", ".join(found))
    return errors

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    cap = sub.add_parser("capture", help="Read selected non-sensitive content from stdin")
    cap.add_argument("--title", required=True)
    cap.add_argument("--source", required=True)
    find = sub.add_parser("search", help="Literal AND search; active knowledge only by default")
    find.add_argument("query")
    find.add_argument("--inbox", action="store_true")
    find.add_argument("--archive", action="store_true")
    find.add_argument("--sessions", action="store_true")
    sub.add_parser("check")
    sub.add_parser("staged-check")
    args = parser.parse_args()
    try:
        if args.command == "capture":
            p, created = capture(ROOT, args.title, args.source, sys.stdin.read())
            print(("saved: " if created else "existing: ") + p.relative_to(ROOT).as_posix())
        elif args.command == "search":
            matches = list(search(ROOT, args.query, args.inbox, args.archive, args.sessions))
            print("\n".join(matches) if matches else "No matching records.")
        else:
            errors = staged_check(ROOT) if args.command == "staged-check" else check(ROOT)
            print("\n".join(errors) if errors else "PASS")
            return bool(errors)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
