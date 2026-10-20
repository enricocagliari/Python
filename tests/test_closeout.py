import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from projects.closeout import evaluate, synth
from projects.closeout.core import (CATEGORIES, Finding, find_candidates, load_case, read_records,
                                    render_workpaper, run_close, LEDGER_COLUMNS)
from projects.closeout.providers import ClaudeProvider, RulesProvider, TOOLS

EXAMPLE = Path('projects/closeout/examples/acme-2026-03')


def write_case(directory, meta, ledger, bank):
    (directory / 'case.json').write_text(json.dumps(meta))
    (directory / 'ledger.csv').write_text('id,journal,date,account,amount,currency,description\n' + ledger)
    (directory / 'bank.csv').write_text('id,date,amount,currency,description\n' + bank)
    return load_case(directory)


BASE_META = {'entity': 'T', 'period_start': '2026-03-01', 'period_end': '2026-03-31', 'cash_account': 'Cash',
             'bank_opening_balance': 0, 'book_opening_balance': 0}


class EngineTests(unittest.TestCase):
    def test_example_candidates_and_balances(self):
        summary, candidates = find_candidates(load_case(EXAMPLE))
        self.assertEqual([c.check for c in candidates],
                         ['unmatched_bank', 'unmatched_bank', 'unmatched_ledger', 'unmatched_ledger',
                          'duplicate_posting', 'duplicate_posting'])
        self.assertEqual(summary['book_balance'] - summary['bank_balance'], -41812)
        self.assertEqual(summary['matched'], 5)

    def test_every_candidate_cites_file_and_line(self):
        _, candidates = find_candidates(load_case(EXAMPLE))
        for candidate in candidates:
            for source in candidate.sources():
                self.assertRegex(source, r'\((ledger|bank)\.csv#L\d+\)')

    def test_unbalanced_cutoff_and_tax_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            meta = {**BASE_META, 'sales_tax': {'rate': 0.1, 'sales_account': 'Sales', 'payable_account': 'Tax',
                                               'tolerance_cents': 0}}
            case = write_case(Path(directory), meta,
                              'L1,J1,2026-03-05,AR,110.00,USD,inv\nL2,J1,2026-03-05,Sales,-100.00,USD,inv\n'
                              'L3,J1,2026-03-05,Tax,-5.00,USD,inv\nL4,J2,2026-04-02,Rent,50.00,USD,late\n'
                              'L5,J2,2026-04-02,AP,-50.00,USD,late\n', '')
            _, candidates = find_candidates(case)
            checks = {c.check: c for c in candidates}
            self.assertEqual(checks['unbalanced_journal'].amount, 500)
            self.assertEqual(checks['sales_tax_variance'].amount, 500)
            self.assertEqual({r.id for c in candidates if c.check == 'period_cutoff' for r in c.records}, {'L4', 'L5'})

    def test_clean_case_has_no_findings(self):
        with tempfile.TemporaryDirectory() as directory:
            case = write_case(Path(directory), BASE_META,
                              'L1,J1,2026-03-05,Cash,10.00,USD,a\nL2,J1,2026-03-05,AR,-10.00,USD,a\n',
                              'B1,2026-03-06,10.00,USD,A\n')
            report = run_close(case, RulesProvider())
            self.assertEqual(report['findings'], [])
            self.assertIn('No exceptions', render_workpaper(report))

    def test_invalid_rows_name_file_and_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ledger.csv'
            path.write_text('id,journal,date,account,amount,currency,description\nL1,J1,2026-03-05,Cash,1.005,USD,a\n')
            with self.assertRaisesRegex(ValueError, 'ledger.csv:2'):
                read_records(path, LEDGER_COLUMNS)

    def test_engine_escalates_when_provider_skips_a_candidate(self):
        class Silent:
            def describe(self):
                return 'silent'

            def usage(self):
                return {}

            def classify(self, case, candidates):
                return [Finding(candidates[0].id, 'nonsense', 'low', 'x')]

        report = run_close(load_case(EXAMPLE), Silent())
        self.assertEqual(len(report['findings']), len(report['candidates']))
        self.assertTrue(all(f['category'] == 'missing_entry' and f['severity'] == 'high' for f in report['findings']))

    def test_workpaper_reconciles_to_zero_and_lists_entries(self):
        report = run_close(load_case(EXAMPLE), RulesProvider())
        text = render_workpaper(report)
        self.assertIn('Difference after reconciling items below: 0.00.', text)
        self.assertIn('| 6900 Bank charges | 25.00 |  |', text)
        for finding in report['findings']:
            self.assertEqual(sum(e['amount'] for e in finding['proposed_entry']), 0)


class FakeClient:
    """Scripted Claude responses: first a lookup tool call, then the submission."""

    def __init__(self, scripts):
        self.scripts, self.requests = list(scripts), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.requests.append(request)
        content, stop = self.scripts.pop(0)
        usage = SimpleNamespace(input_tokens=1000, output_tokens=100, cache_creation_input_tokens=0,
                                cache_read_input_tokens=0)
        return SimpleNamespace(content=content, stop_reason=stop, usage=usage)


def tool_use(name, args, identifier='t1'):
    return SimpleNamespace(type='tool_use', name=name, input=args, id=identifier)


class ClaudeProviderTests(unittest.TestCase):
    def submission(self, candidates):
        return tool_use('submit_findings', {'findings': [
            {'candidate': c.id, 'category': 'duplicate' if c.check == 'unmatched_ledger' else 'bank_fee',
             'severity': 'low', 'explanation': 'because', 'proposed_entry': []} for c in candidates]})

    def test_tool_loop_then_submission(self):
        case = load_case(EXAMPLE)
        _, candidates = find_candidates(case)
        client = FakeClient([([tool_use('lookup_records', {'ids': ['L014']})], 'tool_use'),
                             ([self.submission(candidates)], 'tool_use')])
        provider = ClaudeProvider(client=client, model='claude-opus-5-5')
        findings = provider.classify(case, candidates)
        self.assertEqual(len(findings), len(candidates))
        self.assertEqual(client.requests[0]['model'], 'claude-opus-5-5')
        self.assertEqual(client.requests[0]['fallbacks'], 'default')
        self.assertEqual([t['name'] for t in client.requests[0]['tools']], [t['name'] for t in TOOLS])
        tool_results = [m for m in client.requests[1]['messages'] if m['role'] == 'user'][1]['content']
        result = json.loads(tool_results[0]['content'])
        self.assertEqual(result[0]['ref'], 'ledger.csv#L15')
        usage = provider.usage()
        self.assertEqual(usage['input_tokens'], 2000)
        self.assertAlmostEqual(usage['cost_usd'], 2000 * 4 / 1e6 + 200 * 20 / 1e6)

    def test_refusal_and_missing_submission_raise(self):
        case = load_case(EXAMPLE)
        _, candidates = find_candidates(case)
        with self.assertRaisesRegex(RuntimeError, 'declined'):
            ClaudeProvider(client=FakeClient([([], 'refusal')])).classify(case, candidates)
        text = SimpleNamespace(type='text', text='done')
        provider = ClaudeProvider(client=FakeClient([([text], 'end_turn')] * 2), max_turns=2)
        with self.assertRaisesRegex(RuntimeError, 'no submission'):
            provider.classify(case, candidates)

    def test_tool_schemas_are_strict_and_categories_match_engine(self):
        for tool in TOOLS:
            self.assertTrue(tool['strict'])
            self.assertFalse(tool['input_schema']['additionalProperties'])
        submit = next(t for t in TOOLS if t['name'] == 'submit_findings')
        enum = submit['input_schema']['properties']['findings']['items']['properties']['category']['enum']
        self.assertEqual(tuple(enum), CATEGORIES)


class SynthAndEvalTests(unittest.TestCase):
    def test_generation_is_deterministic_and_labels_match_engine(self):
        self.assertEqual(synth.generate(7), synth.generate(7))
        with tempfile.TemporaryDirectory() as directory:
            for seed in range(1, 6):
                target = Path(directory) / f'case-{seed}'
                synth.write_case(synth.generate(seed, exceptions=8), target)
                case = load_case(target)
                _, candidates = find_candidates(case)
                ids = [sorted(r.id for r in c.records) for c in candidates]
                checks = {c.check for c in candidates}
                for label in case.meta['expected']:
                    if 'check' in label:
                        self.assertIn(label['check'], checks)
                    else:
                        self.assertIn(sorted(label['ids']), ids, label)

    def test_scoring_counts_false_positives_and_engine_misses(self):
        report = {'candidates': [{'id': 'C001', 'check': 'unmatched_bank', 'records': [{'id': 'B1'}]},
                                 {'id': 'C002', 'check': 'unmatched_bank', 'records': [{'id': 'B2'}]}],
                  'findings': [{'category': 'bank_fee'}, {'category': 'bank_fee'}],
                  'metrics': {'seconds': 1.0, 'cost_usd': 0.5}}
        labels = [{'category': 'bank_fee', 'ids': ['B1']}, {'category': 'timing', 'ids': ['L9']}]
        score = evaluate.score_case(report, labels)
        self.assertEqual((score['tp'], score['fp'], score['fn'], score['exact']), (1, 1, 1, 1))
        summary = evaluate.aggregate({'x': score})
        self.assertEqual(summary['precision'], 0.5)
        self.assertEqual(summary['cost_usd_per_case'], 0.5)

    def test_example_evaluation_with_rules_provider(self):
        result = evaluate.evaluate(EXAMPLE.parent, 'rules')
        self.assertEqual(result['summary']['false_positives'], 0)
        self.assertEqual(result['cases']['acme-2026-03']['exact'], 5)


class CliTests(unittest.TestCase):
    def run_cli(self, module, *args):
        return subprocess.run([sys.executable, '-m', module, *map(str, args)], capture_output=True, text=True)

    def test_workpaper_exit_code_and_output_file(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'workpaper.md'
            result = self.run_cli('projects.closeout.core', EXAMPLE, '--out', out, '--json')
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(len(json.loads(result.stdout)['findings']), 6)
            self.assertIn('bank.csv#L7', out.read_text())

    def test_evaluate_generates_and_scores(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_cli('projects.closeout.evaluate', directory, '--generate', '3')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Cases: 3', result.stdout)

    def test_missing_case_exit_code(self):
        result = self.run_cli('projects.closeout.core', 'nowhere')
        self.assertEqual(result.returncode, 2)
        self.assertIn('error:', result.stderr)


if __name__ == '__main__':
    unittest.main()
