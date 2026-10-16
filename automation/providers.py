"""CLI planners with restricted tools; no SDKs, API keys, or model-written commands."""
import json
from pathlib import Path
import subprocess
import tempfile

PROVIDERS = ('codex', 'claude', 'gemini', 'grok')


def decode(raw, fields):
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get('is_error') or value.get('error'):
        raise ValueError('planner reported an error')
    if set(value) == set(fields):
        return value
    for key in ('structured_output', 'response', 'result'):
        nested = value.get(key)
        if isinstance(nested, str):
            text = nested.strip()
            if text.startswith('```') and text.endswith('```'):
                text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
            try:
                nested = json.loads(text)
            except ValueError:
                continue
        if isinstance(nested, dict) and set(nested) == set(fields):
            return nested
    raise ValueError('planner returned no matching structured result')


def generate(provider, executable, prompt, schema, artifact_dir, timeout=600):
    if provider not in PROVIDERS:
        raise ValueError('unknown planner provider')
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    cwd = Path(tempfile.mkdtemp(prefix=provider + '-plan-', dir=artifact_dir))
    prompt_file, schema_file, output_file = (cwd / name for name in ('prompt.txt', 'schema.json', 'output.json'))
    schema_text = json.dumps(schema, ensure_ascii=False)
    prompt += '\nReturn only JSON matching this schema. Do not call tools or write files.\n' + schema_text
    prompt_file.write_text(prompt, encoding='utf-8')
    schema_file.write_text(schema_text, encoding='utf-8')
    stdin = prompt
    if provider == 'codex':
        command = [executable, '--ask-for-approval', 'never', 'exec', '--ephemeral', '--color', 'never',
                   '--sandbox', 'read-only', '--skip-git-repo-check', '--cd', str(cwd),
                   '--output-schema', str(schema_file), '--output-last-message', str(output_file), '-']
    elif provider == 'claude':
        command = [executable, '-p', '--tools', '', '--permission-mode', 'plan', '--output-format', 'json',
                   '--json-schema', schema_text]
    elif provider == 'gemini':
        command = [executable, '--skip-trust', '--approval-mode', 'plan', '--output-format', 'json', '-p', 'Return the JSON plan requested on stdin.']
    else:
        command = [executable, '--prompt-file', str(prompt_file), '--tools', '', '--sandbox', 'read-only',
                   '--permission-mode', 'plan', '--no-subagents', '--no-memory', '--disable-web-search',
                   '--json-schema', schema_text, '--output-format', 'json']
        stdin = None
    with (cwd / 'stderr.log').open('w', encoding='utf-8') as error_log, (cwd / 'stdout.log').open('w', encoding='utf-8') as output_log:
        result = subprocess.run(command, cwd=cwd, input=stdin, text=True, stdout=output_log, stderr=error_log, timeout=timeout)
    if result.returncode:
        raise ValueError(provider + ' planner failed; see local artifacts')
    raw = output_file.read_text() if provider == 'codex' else (cwd / 'stdout.log').read_text()
    if len(raw.encode('utf-8')) > 2_000_000:
        raise ValueError('planner output oversized')
    return decode(raw, schema['properties'])
