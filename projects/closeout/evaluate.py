"""Score a provider against labeled cases: accuracy, false positives, time, cost.

A case's `expected` list names the exceptions a careful accountant would
raise, each as a category plus the record ids (or check name) that identify
it. Every engine candidate with no label is expected to be classified
no_exception; flagging it is a false positive. A label with no candidate is
an engine miss and counts as a false negative against the whole system.
"""
import argparse
import json
from pathlib import Path

from projects.closeout.core import load_case, make_provider, run_close


def expected_category(candidate: dict, labels: list) -> tuple[str, dict | None]:
    ids = sorted(r['id'] for r in candidate['records'])
    for label in labels:
        if label.get('check') == candidate['check'] or sorted(label.get('ids', [])) == ids:
            return label['category'], label
    return 'no_exception', None


def score_case(report: dict, labels: list) -> dict:
    rows, used = [], []
    for c, f in zip(report['candidates'], report['findings']):
        expected, label = expected_category(c, labels)
        if label is not None:
            used.append(label)
        rows.append({'candidate': c['id'], 'check': c['check'], 'expected': expected, 'predicted': f['category']})
    for label in labels:
        if label not in used:
            rows.append({'candidate': None, 'check': 'engine_miss', 'expected': label['category'],
                         'predicted': 'no_exception'})
    tp = sum(r['expected'] != 'no_exception' and r['predicted'] != 'no_exception' for r in rows)
    fp = sum(r['expected'] == 'no_exception' and r['predicted'] != 'no_exception' for r in rows)
    fn = sum(r['expected'] != 'no_exception' and r['predicted'] == 'no_exception' for r in rows)
    exact = sum(r['expected'] == r['predicted'] for r in rows)
    return {'rows': rows, 'decisions': len(rows), 'exact': exact, 'tp': tp, 'fp': fp, 'fn': fn,
            'seconds': report['metrics']['seconds'], 'cost_usd': report['metrics'].get('cost_usd', 0.0),
            'input_tokens': report['metrics'].get('input_tokens', 0),
            'output_tokens': report['metrics'].get('output_tokens', 0)}


def aggregate(results: dict) -> dict:
    totals = {k: sum(r[k] for r in results.values())
              for k in ('decisions', 'exact', 'tp', 'fp', 'fn', 'seconds', 'cost_usd', 'input_tokens', 'output_tokens')}
    precision = totals['tp'] / (totals['tp'] + totals['fp']) if totals['tp'] + totals['fp'] else 1.0
    recall = totals['tp'] / (totals['tp'] + totals['fn']) if totals['tp'] + totals['fn'] else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    n = len(results) or 1
    return {'cases': len(results), 'category_accuracy': round(totals['exact'] / max(totals['decisions'], 1), 4),
            'precision': round(precision, 4), 'recall': round(recall, 4), 'f1': round(f1, 4),
            'false_positives': totals['fp'], 'false_negatives': totals['fn'],
            'seconds_per_case': round(totals['seconds'] / n, 3), 'cost_usd_per_case': round(totals['cost_usd'] / n, 6),
            'tokens_per_case': round((totals['input_tokens'] + totals['output_tokens']) / n)}


def evaluate(directory: Path, provider_name: str) -> dict:
    results = {}
    for case_dir in sorted(p for p in directory.iterdir() if (p / 'case.json').exists()):
        case = load_case(case_dir)
        report = run_close(case, make_provider(provider_name))
        results[case_dir.name] = score_case(report, case.meta.get('expected', []))
    return {'provider': provider_name, 'summary': aggregate(results), 'cases': results}


def render(result: dict) -> str:
    s = result['summary']
    lines = [f"Provider: {result['provider']}  Cases: {s['cases']}", '',
             '| Metric | Value |', '| :--- | ---: |',
             f"| Category accuracy | {s['category_accuracy']:.1%} |",
             f"| Precision | {s['precision']:.1%} |", f"| Recall | {s['recall']:.1%} |", f"| F1 | {s['f1']:.1%} |",
             f"| False positives | {s['false_positives']} |", f"| False negatives | {s['false_negatives']} |",
             f"| Seconds per case | {s['seconds_per_case']} |", f"| Cost per case (USD) | {s['cost_usd_per_case']:.4f} |",
             f"| Tokens per case | {s['tokens_per_case']} |", '']
    for name, case in result['cases'].items():
        wrong = [r for r in case['rows'] if r['expected'] != r['predicted']]
        lines.append(f"{name}: {case['exact']}/{case['decisions']} correct"
                     + (', ' + '; '.join(f"{r['candidate'] or r['check']} expected {r['expected']} "
                                         f"got {r['predicted']}" for r in wrong) if wrong else ''))
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cases', type=Path, help='directory containing one subdirectory per case')
    parser.add_argument('--provider', choices=('rules', 'claude'), default='rules')
    parser.add_argument('--generate', type=int, default=0, help='first synthesize this many cases into CASES')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--json', type=Path, help='write the full result here')
    args = parser.parse_args()
    try:
        if args.generate:
            from projects.closeout.synth import generate, write_case
            for seed in range(args.seed, args.seed + args.generate):
                write_case(generate(seed), args.cases / f'case-{seed:03d}')
        result = evaluate(args.cases, args.provider)
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        parser.exit(2, f'error: {exc}\n')
    if args.json:
        args.json.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(render(result))


if __name__ == '__main__':
    main()
