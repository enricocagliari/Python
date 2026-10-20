"""Closeout: an accounting close agent that prepares a reviewable workpaper.

The deterministic engine owns every number. It loads a case, reconciles the
bank statement to the cash ledger with ClearMatch's conservative policy, runs
integrity checks, and emits candidate exceptions with source references.
A provider (rules or Claude) only classifies candidates and drafts the
proposed treatment; it cannot invent amounts or hide a candidate.
"""
import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from projects.reconcile.core import Transaction, reconcile

CATEGORIES = ('bank_fee', 'interest', 'timing', 'ambiguous', 'duplicate', 'missing_entry',
              'unbalanced', 'tax_variance', 'cutoff', 'no_exception')
SEVERITIES = ('low', 'medium', 'high')


def cents(value: str) -> int:
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f'invalid amount: {value!r}') from exc
    if not amount.is_finite() or amount != amount.quantize(Decimal('0.01')):
        raise ValueError('amount must be finite with at most two decimal places')
    return int(amount * 100)


def money(amount: int) -> str:
    sign = '-' if amount < 0 else ''
    return f'{sign}{abs(amount) // 100:,}.{abs(amount) % 100:02d}'


@dataclass(frozen=True)
class Record:
    """One line of a source file. `ref` is the citation used in the workpaper."""
    id: str
    file: str
    line: int
    date: date
    amount: int
    currency: str
    description: str
    account: str = ''
    journal: str = ''

    @property
    def ref(self) -> str:
        return f'{self.file}#L{self.line}'


@dataclass
class Candidate:
    id: str
    check: str
    amount: int
    records: list
    detail: str

    def sources(self) -> list[str]:
        return [f'{r.id} ({r.ref})' for r in self.records]


@dataclass
class Finding:
    candidate: str
    category: str
    severity: str
    explanation: str
    proposed_entry: list = field(default_factory=list)


@dataclass
class Case:
    directory: Path
    meta: dict
    ledger: list
    bank: list

    @property
    def period(self) -> tuple[date, date]:
        return date.fromisoformat(self.meta['period_start']), date.fromisoformat(self.meta['period_end'])


LEDGER_COLUMNS = ('id', 'journal', 'date', 'account', 'amount', 'currency', 'description')
BANK_COLUMNS = ('id', 'date', 'amount', 'currency', 'description')


def read_records(path: Path, columns: tuple) -> list[Record]:
    result, seen = [], set()
    with path.open(newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        if set(columns) - set(reader.fieldnames or []):
            raise ValueError(f'{path}: expected columns {list(columns)}')
        for line, row in enumerate(reader, 2):
            try:
                identifier = row['id'].strip()
                if not identifier or identifier in seen:
                    raise ValueError('empty or duplicate id')
                currency = row['currency'].strip().upper()
                if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
                    raise ValueError('currency must be a three-letter code')
                result.append(Record(identifier, path.name, line, date.fromisoformat(row['date'].strip()),
                                     cents(row['amount']), currency, row['description'].strip(),
                                     row.get('account', '').strip(), row.get('journal', '').strip()))
                seen.add(identifier)
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValueError(f'{path}:{line}: {exc}') from exc
    return result


def load_case(directory: Path) -> Case:
    meta = json.loads((directory / 'case.json').read_text(encoding='utf-8'))
    for key in ('entity', 'period_start', 'period_end', 'cash_account', 'bank_opening_balance',
                'book_opening_balance'):
        if key not in meta:
            raise ValueError(f'case.json missing {key!r}')
    return Case(directory, meta, read_records(directory / 'ledger.csv', LEDGER_COLUMNS),
                read_records(directory / 'bank.csv', BANK_COLUMNS))


def find_candidates(case: Case, days: int = 3) -> tuple[dict, list[Candidate]]:
    """Deterministic checks. Every candidate cites the records that produced it."""
    start, end = case.period
    by_id = {r.id: r for r in case.ledger + case.bank}
    cash = [r for r in case.ledger if r.account == case.meta['cash_account']]
    rec = reconcile([Transaction(r.id, r.date, r.amount, r.currency) for r in case.bank],
                    [Transaction(r.id, r.date, r.amount, r.currency) for r in cash], days)
    candidates = []

    def add(check, records, detail, amount=None):
        candidates.append(Candidate(f'C{len(candidates) + 1:03d}', check,
                                    sum(r.amount for r in records) if amount is None else amount,
                                    records, detail))

    for identifier in rec['unmatched_left']:
        add('unmatched_bank', [by_id[identifier]], 'bank line with no cash ledger candidate')
    for identifier in rec['unmatched_right']:
        add('unmatched_ledger', [by_id[identifier]], 'cash ledger posting with no bank candidate')
    for item in rec['review']:
        add('ambiguous_match', [by_id[item['left']]] + [by_id[c] for c in item['candidates']],
            'several ledger postings could explain this bank line', by_id[item['left']].amount)
    seen = {}
    for r in sorted(case.ledger, key=lambda r: r.id):
        key = (r.account, r.amount, r.description.lower())
        if key in seen:
            add('duplicate_posting', [seen[key], r], 'same account, amount and description within the period',
                r.amount)
        else:
            seen[key] = r
    journals = {}
    for r in case.ledger:
        journals.setdefault(r.journal, []).append(r)
    for journal, rows in sorted(journals.items()):
        total = sum(r.amount for r in rows)
        if total:
            add('unbalanced_journal', rows, f'journal {journal} debits minus credits = {money(total)}', total)
    for r in sorted(case.ledger, key=lambda r: r.id):
        if not start <= r.date <= end:
            add('period_cutoff', [r], f'posting dated outside {start} to {end}')
    tax = case.meta.get('sales_tax')
    if tax:
        sales = [r for r in case.ledger if r.account == tax['sales_account']]
        payable = [r for r in case.ledger if r.account == tax['payable_account']]
        expected = int(round(sum(r.amount for r in sales) * Decimal(str(tax['rate']))))
        actual = sum(r.amount for r in payable)
        if abs(expected - actual) > tax.get('tolerance_cents', 100):
            add('sales_tax_variance', sales + payable,
                f'sales tax payable {money(actual)} vs expected {money(expected)} '
                f'at {tax["rate"]} on sales {money(-sum(r.amount for r in sales))}', actual - expected)
    book = case.meta['book_opening_balance'] + sum(r.amount for r in cash)
    bank = case.meta['bank_opening_balance'] + sum(r.amount for r in case.bank)
    summary = {'bank_lines': len(case.bank), 'cash_postings': len(cash), 'matched': len(rec['matches']),
               'book_balance': book, 'bank_balance': bank, 'difference': book - bank,
               'policy': rec['policy']}
    return summary, candidates


def run_close(case: Case, provider, days: int = 3) -> dict:
    """Engine first, provider second, then an audit that the provider answered everything."""
    started = time.perf_counter()
    summary, candidates = find_candidates(case, days)
    findings = provider.classify(case, candidates) if candidates else []
    by_candidate = {f.candidate: f for f in findings}
    audited = []
    for candidate in candidates:
        finding = by_candidate.get(candidate.id)
        if finding is None or finding.category not in CATEGORIES or finding.severity not in SEVERITIES:
            finding = Finding(candidate.id, 'missing_entry', 'high',
                              'provider returned no valid classification; escalated for review')
        audited.append(finding)
    return {'entity': case.meta['entity'], 'period': [str(d) for d in case.period],
            'provider': provider.describe(), 'summary': summary,
            'candidates': [{**asdict(c), 'records': [asdict(r) | {'date': str(r.date), 'ref': r.ref}
                                                     for r in c.records]} for c in candidates],
            'findings': [asdict(f) for f in audited],
            'metrics': {'seconds': round(time.perf_counter() - started, 3), **provider.usage()}}


def render_workpaper(report: dict) -> str:
    """Markdown the reviewer reads. Every finding cites file and line of its evidence."""
    s = report['summary']
    lines = [f"# Cash close workpaper: {report['entity']}", '',
             f"Period {report['period'][0]} to {report['period'][1]}. "
             f"Prepared by Closeout ({report['provider']}). Status: **draft, awaiting review**.", '',
             '## Reconciliation', '', '| Item | Amount |', '| :--- | ---: |',
             f"| Book cash balance | {money(s['book_balance'])} |",
             f"| Bank statement balance | {money(s['bank_balance'])} |",
             f"| Unexplained difference | {money(s['difference'])} |",
             f"| Bank lines matched | {s['matched']} of {s['bank_lines']} |", '']
    unexplained = s['difference']
    for c, f in zip(report['candidates'], report['findings']):
        if c['check'] == 'unmatched_ledger' and f['category'] != 'no_exception':
            unexplained -= c['amount']
        elif c['check'] == 'ambiguous_match' or (c['check'] == 'unmatched_bank'
                                                 and f['category'] != 'no_exception'):
            unexplained += c['amount']
    lines += [f'Difference after reconciling items below: {money(unexplained)}.', '',
              '## Findings', '']
    if not report['findings']:
        lines.append('No exceptions. All bank lines matched and all checks passed.')
    for c, f in zip(report['candidates'], report['findings']):
        lines += [f"### {c['id']} · {f['category']} · {f['severity']}", '',
                  f"Check `{c['check']}`: {c['detail']}. Amount {money(c['amount'])}.", '',
                  f"{f['explanation']}", '', 'Sources:']
        lines += [f"- {r['id']} {r['date']} {money(r['amount'])} {r['description']} ({r['ref']})"
                  for r in c['records']]
        if f['proposed_entry']:
            lines += ['', 'Proposed entry:', '', '| Account | Debit | Credit |', '| :--- | ---: | ---: |']
            for e in f['proposed_entry']:
                amount = e['amount']
                lines.append(f"| {e['account']} | {money(amount) if amount > 0 else ''} | "
                             f"{money(-amount) if amount < 0 else ''} |")
        lines.append('')
    m = report['metrics']
    lines += ['## Run', '', f"Seconds {m['seconds']}; input tokens {m.get('input_tokens', 0)}; "
              f"output tokens {m.get('output_tokens', 0)}; estimated cost USD {m.get('cost_usd', 0):.4f}.", '',
              '## Review', '', '- [ ] Findings reviewed', '- [ ] Proposed entries approved or rejected',
              '- [ ] Reviewer: ____________  Date: ________', '']
    return '\n'.join(lines)


def make_provider(name: str):
    from projects.closeout import providers
    if name == 'rules':
        return providers.RulesProvider()
    if name == 'claude':
        return providers.ClaudeProvider()
    raise ValueError(f'unknown provider {name!r}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path, help='directory with case.json, ledger.csv, bank.csv')
    parser.add_argument('--provider', choices=('rules', 'claude'), default='rules')
    parser.add_argument('--days', type=int, default=3)
    parser.add_argument('--json', action='store_true', help='print the report as JSON instead of Markdown')
    parser.add_argument('--out', type=Path, help='also write the Markdown workpaper here')
    args = parser.parse_args()
    try:
        report = run_close(load_case(args.case), make_provider(args.provider), args.days)
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        parser.exit(2, f'error: {exc}\n')
    workpaper = render_workpaper(report)
    if args.out:
        args.out.write_text(workpaper, encoding='utf-8')
    print(json.dumps(report, indent=2) if args.json else workpaper)
    sys.exit(1 if any(f['category'] != 'no_exception' for f in report['findings']) else 0)


if __name__ == '__main__':
    main()
