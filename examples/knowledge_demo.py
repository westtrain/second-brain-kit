#!/usr/bin/env python3
"""Run an entirely synthetic knowledge lifecycle in a fresh local brain. No AI/network."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'scripts'))
from brain_access import BrainAccess
import init_brain
import knowledge


def demo(target):
    init_brain.initialize(target, 'personal')
    target = target.resolve()
    receipts = []

    def apply(command, request):
        result = subprocess.run([sys.executable, str(target / 'scripts/knowledge_workflow.py'),
                                 '--root', str(target), '--scope', 'personal', '--risk', 'routine', command],
                                input=json.dumps(request), text=True, capture_output=True, check=True)
        output = json.loads(result.stdout)
        receipts.append(output)
        return output['result']['path']

    def evidence(path, quote, relation='supports'):
        text = BrainAccess(target, 'personal').read_relative(path)
        return dict(path=path, hash=knowledge.fingerprint(text), quote=quote, relation=relation)

    first_quote = 'Synthetic case: duplicate deliveries created two tasks because request identity was not stored.'
    first = apply('capture', dict(title='Fictional duplicate task investigation', source='Synthetic case A, not a real incident',
                                 source_kind='work', body=first_quote))
    evidence_a = dict(status='supported', sources=[evidence(first, first_quote)],
                      claims=[dict(text='Preserve a request identity before retrying a state-changing operation.', confidence='inferred', sources=[0])])
    note = dict(id='retry-identity', expected=knowledge.fingerprint(''), kind='concept',
                title='재시도 식별자 / Retry identity (synthetic)', summary='A stable request identity can distinguish a retry from a new task.',
                conditions=['The input represents the same logical operation.'],
                limits=['An identity alone does not prove crash-safe behavior.'],
                open_questions=['What happens if the worker stops after a partial write?'],
                change_reason='Extract a reusable hypothesis from fictional case A.', evidence=evidence_a)
    note_path = apply('distill', note)
    access = BrainAccess(target, 'personal')
    packet = knowledge.context(access, [note_path])
    assert len(packet['documents']) == 1

    second_quote = 'Synthetic case B: a stored request ID did not record whether the task finished before the worker stopped.'
    second = apply('capture', dict(title='Fictional partial-write recovery', source='Synthetic case B, not a real incident',
                                  source_kind='article', body=second_quote))
    revised = dict(note, expected=knowledge.fingerprint(access.read_relative(note_path)), kind='synthesis',
                   summary='Retry identity must be paired with an explicit recovery rule for partial completion.',
                   limits=['Neither fictional example establishes transaction behavior in an actual database.'],
                   change_reason='Case B challenges identity-only recovery; preserve case A and narrow the claim.',
                   evidence=dict(status='supported', sources=[evidence(first, first_quote), evidence(second, second_quote, 'challenges')],
                                 claims=[dict(text='A request identity does not by itself describe the result of a partially completed operation.',
                                              confidence='inferred', sources=[0, 1])]))
    apply('distill', revised)
    current = access.read_relative(note_path)
    assert note['summary'] in current and revised['summary'] in current
    # These are fixture assertions, not a test of an AI's natural-language decisions.
    outputs = {}
    for mode in ('answer', 'quiz', 'report', 'decision'):
        outputs[mode] = knowledge.verify(access, revised['evidence'])
    missing = knowledge.verify(access, dict(status='not_covered', sources=[], claims=[]))
    return dict(brain=str(target), receipts=receipts, reused=note_path, verified_outputs=outputs,
                missing_answer=missing, no_model_called=True,
                notice='Synthetic fixture demonstrates mechanics; it does not measure model reasoning quality.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(demo(args.target), ensure_ascii=False, indent=2))
