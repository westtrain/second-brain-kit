#!/usr/bin/env python3
"""Evaluate retrieval against reviewed questions and exact evidence. Never calls an answer model."""
import argparse
import json
from pathlib import Path
import sys

from brain_access import BrainAccess, bounded_int, relative_path, text_value


def validate_cases(access, cases):
    if not isinstance(cases, list) or not cases or len(cases) > 2000:
        raise ValueError('dataset must be a nonempty array of at most 2000 cases')
    identifiers = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError('each case must be an object')
        text_value(case.get('id'), 'case ID', 120)
        if case['id'] in identifiers:
            raise ValueError('duplicate case ID')
        identifiers.add(case['id'])
        text_value(case.get('query'), 'query')
        text_value(case.get('category'), 'category', 80)
        if case.get('scope') not in ('personal', 'work') or case.get('split') not in ('development', 'test'):
            raise ValueError('case needs personal/work scope and development/test split')
        if case.get('review_status') != 'reviewed':
            raise ValueError('review evidence before using a generated evaluation candidate')
        paths = case.get('relevant_paths')
        evidence = case.get('evidence')
        if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths) or len(set(paths)) != len(paths):
            raise ValueError('relevant_paths must be a unique string array; [] means no answer')
        if not isinstance(evidence, dict) or set(evidence) != set(paths):
            raise ValueError('evidence must contain exactly one nonempty quote per relevant path')
        forbidden = case.get('forbidden_paths', [])
        if not isinstance(forbidden, list) or any(not isinstance(p, str) for p in forbidden):
            raise ValueError('forbidden_paths must be an array of relative paths')
        for path in [*paths, *forbidden]:
            relative_path(path)
        if set(paths) & set(forbidden):
            raise ValueError('relevant and forbidden paths overlap')
        for flag in ('include_inbox', 'include_archive'):
            if type(case.get(flag, False)) is not bool:
                raise ValueError('inclusion flags must be booleans')
        if case['scope'] == access.scope:
            allowed = set(access.paths(case.get('include_inbox', False), case.get('include_archive', False)))
            for path in paths:
                if path not in allowed:
                    raise ValueError('ground truth is outside the searchable scope: ' + case['id'])
                quote = text_value(evidence[path], 'evidence quote', 12000)
                if quote not in access.read_relative(path):
                    raise ValueError('stale or incorrect evidence in case ' + case['id'])


def evaluate(access, cases, split, limit=5, backend='literal'):
    bounded_int(limit, 1, 50, 'limit')
    if split not in ('development', 'test'):
        raise ValueError('choose development or test explicitly')
    validate_cases(access, cases)
    selected = [c for c in cases if c['scope'] == access.scope and c['split'] == split]
    if not selected:
        raise ValueError('no cases for this scope and split')
    details = []
    positives, negatives, reciprocal, recalls, evidence_coverage = [], [], [], [], []
    violations = 0
    for case in selected:
        results = access.search(case['query'], limit, backend, case.get('include_inbox', False),
                                case.get('include_archive', False))['results']
        paths = [r['path'] for r in results]
        relevant = set(case['relevant_paths'])
        forbidden_hits = sorted(set(paths) & set(case.get('forbidden_paths', [])))
        wrong_scope = any(r['scope'] != access.scope for r in results)
        violations += len(forbidden_hits) + int(wrong_scope)
        if relevant:
            hits = relevant & set(paths)
            rank = next((i for i, path in enumerate(paths, 1) if path in relevant), None)
            evidence_hits = sum(r['path'] in relevant and case['evidence'][r['path']] in r['excerpt'] for r in results)
            positives.append(bool(hits))
            reciprocal.append(1 / rank if rank else 0)
            recalls.append(len(hits) / len(relevant))
            evidence_coverage.append(evidence_hits / len(relevant))
        else:
            negatives.append(not results)
        details.append({'id': case['id'], 'category': case['category'], 'retrieved_paths': paths,
                        'relevant_paths': case['relevant_paths'], 'forbidden_hits': forbidden_hits,
                        'wrong_scope': wrong_scope})
    mean = lambda values: sum(values) / len(values) if values else None
    return {'scope': access.scope, 'split': split, 'backend': backend, 'k': limit,
            'cases': len(selected), 'positive_cases': len(positives), 'negative_cases': len(negatives),
            'metrics': {'hit_rate_at_k': mean(positives), 'recall_at_k': mean(recalls),
                        'mrr_at_k': mean(reciprocal), 'evidence_coverage_at_k': mean(evidence_coverage),
                        'no_answer_accuracy': mean(negatives), 'boundary_violations': violations},
            'details': details,
            'limitations': 'Measures retrieval and excerpt coverage only, not answer correctness, '
                          'current-state resolution, permission enforcement, or production Korean quality.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--scope', choices=('personal', 'work'), required=True)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--split', choices=('development', 'test'), required=True)
    parser.add_argument('--backend', choices=('literal', 'qmd-keyword', 'qmd-hybrid'), default='literal')
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--qmd-index')
    parser.add_argument('--qmd-collection')
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    try:
        access = BrainAccess(args.root, args.scope, qmd_index=args.qmd_index, qmd_collection=args.qmd_collection)
        cases = json.loads(args.dataset.read_text(encoding='utf-8'))
        if args.validate_only:
            validate_cases(access, cases)
            result = {'validated': True, 'scope': args.scope}
        else:
            result = evaluate(access, cases, args.split, args.limit, args.backend)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get('metrics', {}).get('boundary_violations', 0) else 0
    except (ValueError, OSError) as error:
        print('Evaluation stopped: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
