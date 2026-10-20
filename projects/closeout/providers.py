"""Classification providers for Closeout candidates.

RulesProvider is deterministic and offline; it is the baseline the evaluation
compares against and the provider the tests use. ClaudeProvider drives a tool
loop on the Claude API and must finish by calling `submit_findings`. Both
return one Finding per candidate; the engine audits that before rendering.
"""
import json
from datetime import timedelta

from projects.closeout.core import CATEGORIES, SEVERITIES, Case, Candidate, Finding, money

MODEL = 'claude-opus-5-5'
# USD per million tokens: input, output, cache write (5 minute), cache read.
PRICES = {'claude-opus-5-5': (4.00, 20.00, 5.00, 0.20),
          'claude-sonnet-5-5': (2.00, 10.00, 2.50, 0.20),
          'claude-haiku-5-5': (0.10, 0.50, 0.125, 0.01)}

SYSTEM = """You are a senior accountant reviewing cash close exceptions for a small company.
A deterministic engine has already reconciled the bank statement to the cash ledger and
produced candidate exceptions with the exact records behind each one. Your job is to
classify every candidate, explain it in one or two sentences a reviewer can verify from the
cited records, and propose a balanced adjusting entry when one is warranted.

Categories: bank_fee (bank charge not yet booked), interest (bank interest not yet booked),
timing (deposit in transit or outstanding payment that will clear next period; no entry),
ambiguous (several postings could explain a bank line; reviewer must pick; no entry),
duplicate (the same posting booked twice; propose reversing the duplicate journal),
missing_entry (a real transaction with no counterpart; propose the entry or escalate),
unbalanced (journal debits do not equal credits; propose a suspense entry), tax_variance
(sales tax payable disagrees with sales times rate; propose the correction), cutoff (posting
dated outside the period; propose moving it), no_exception (the candidate is explained by
the records and needs no action).

Rules: never change an amount; sign convention is positive for debits and negative for
credits, and a proposed entry must sum to zero; use account names exactly as they appear in
the ledger; when evidence is insufficient choose missing_entry with severity high rather than
guessing. Use lookup_records and search_records if you need context beyond the candidate.
Finish by calling submit_findings exactly once with one finding for every candidate id."""

FINDING_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['candidate', 'category', 'severity', 'explanation', 'proposed_entry'],
    'properties': {
        'candidate': {'type': 'string'},
        'category': {'type': 'string', 'enum': list(CATEGORIES)},
        'severity': {'type': 'string', 'enum': list(SEVERITIES)},
        'explanation': {'type': 'string'},
        'proposed_entry': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['account', 'amount'],
            'properties': {'account': {'type': 'string'},
                           'amount': {'type': 'integer', 'description': 'cents; debit positive'}}}}}}

TOOLS = [
    {'name': 'lookup_records', 'description': 'Return ledger or bank records by id.', 'strict': True,
     'input_schema': {'type': 'object', 'additionalProperties': False, 'required': ['ids'],
                      'properties': {'ids': {'type': 'array', 'items': {'type': 'string'}}}}},
    {'name': 'search_records', 'strict': True,
     'description': 'Search ledger and bank records by description substring, account, or exact amount in cents.',
     'input_schema': {'type': 'object', 'additionalProperties': False,
                      'required': ['text', 'account', 'amount_cents'],
                      'properties': {'text': {'type': ['string', 'null']},
                                     'account': {'type': ['string', 'null']},
                                     'amount_cents': {'type': ['integer', 'null']}}}},
    {'name': 'submit_findings', 'description': 'Submit the final classification for every candidate.',
     'strict': True,
     'input_schema': {'type': 'object', 'additionalProperties': False, 'required': ['findings'],
                      'properties': {'findings': {'type': 'array', 'items': FINDING_SCHEMA}}}},
]


def record_dict(r) -> dict:
    return {'id': r.id, 'ref': r.ref, 'date': str(r.date), 'amount_cents': r.amount,
            'currency': r.currency, 'description': r.description, 'account': r.account, 'journal': r.journal}


def reversal(case: Case, journal: str) -> list[dict]:
    return [{'account': r.account, 'amount': -r.amount} for r in case.ledger if r.journal == journal]


class RulesProvider:
    """Keyword and date heuristics. Cheap, fast, and wrong in predictable ways."""

    def describe(self) -> str:
        return 'rules provider'

    def usage(self) -> dict:
        return {'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0.0}

    def classify(self, case: Case, candidates: list[Candidate]) -> list[Finding]:
        cash = case.meta['cash_account']
        accounts = case.meta.get('accounts', {})
        end = case.period[1]
        findings = []
        for c in candidates:
            r = c.records[0]
            text = r.description.lower()
            if c.check == 'unmatched_bank':
                if any(w in text for w in ('fee', 'charge', 'service')):
                    f = Finding(c.id, 'bank_fee', 'low', f'Bank charge of {money(-r.amount)} not yet booked.',
                                [{'account': accounts.get('bank_charges', 'Bank charges'), 'amount': -r.amount},
                                 {'account': cash, 'amount': r.amount}])
                elif 'interest' in text:
                    f = Finding(c.id, 'interest', 'low', f'Bank interest of {money(r.amount)} not yet booked.',
                                [{'account': cash, 'amount': r.amount},
                                 {'account': accounts.get('interest_income', 'Interest income'), 'amount': -r.amount}])
                else:
                    f = Finding(c.id, 'missing_entry', 'high',
                                'Bank movement with no ledger counterpart; needs supporting document before posting.')
            elif c.check == 'unmatched_ledger':
                if r.date >= end - timedelta(days=5):
                    kind = 'outstanding payment' if r.amount < 0 else 'deposit in transit'
                    f = Finding(c.id, 'timing', 'low', f'Posted {r.date}; likely {kind} clearing next period.')
                else:
                    f = Finding(c.id, 'missing_entry', 'medium',
                                'Cash posting never reached the bank; confirm the payment was made.')
            elif c.check == 'ambiguous_match':
                f = Finding(c.id, 'ambiguous', 'medium',
                            'More than one ledger posting fits; reviewer must choose using remittance detail.')
            elif c.check == 'duplicate_posting':
                f = Finding(c.id, 'duplicate', 'medium',
                            f'{c.records[1].id} repeats {c.records[0].id}; reverse journal {c.records[1].journal}.',
                            reversal(case, c.records[1].journal))
            elif c.check == 'unbalanced_journal':
                f = Finding(c.id, 'unbalanced', 'high', f'Journal {r.journal} is out of balance by {money(c.amount)}.',
                            [{'account': accounts.get('suspense', 'Suspense'), 'amount': -c.amount}])
            elif c.check == 'period_cutoff':
                f = Finding(c.id, 'cutoff', 'medium', f'Dated {r.date}, outside the close period.')
            elif c.check == 'sales_tax_variance':
                tax = case.meta['sales_tax']
                f = Finding(c.id, 'tax_variance', 'high', 'Sales tax payable disagrees with sales times rate; '
                            'reclassify the difference from sales.',
                            [{'account': tax['sales_account'], 'amount': c.amount},
                             {'account': tax['payable_account'], 'amount': -c.amount}])
            else:
                f = Finding(c.id, 'missing_entry', 'high', 'Unknown check; escalated.')
            findings.append(f)
        return findings


class ClaudeProvider:
    """Tool loop on the Claude API. The engine's candidates are the only facts it may cite."""

    def __init__(self, client=None, model: str = MODEL, max_turns: int = 12):
        if client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise RuntimeError('pip install anthropic, then set ANTHROPIC_API_KEY') from exc
            client = anthropic.Anthropic()
        self.client, self.model, self.max_turns = client, model, max_turns
        self.tokens = {'input_tokens': 0, 'output_tokens': 0,
                       'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0}
        self.turns = 0

    def describe(self) -> str:
        return f'Claude provider, {self.model}'

    def usage(self) -> dict:
        prices = PRICES.get(self.model, (0, 0, 0, 0))
        keys = ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')
        cost = sum(self.tokens[k] * p for k, p in zip(keys, prices)) / 1_000_000
        return {**self.tokens, 'turns': self.turns, 'cost_usd': round(cost, 6)}

    def _tool(self, case: Case, name: str, args: dict):
        records = case.ledger + case.bank
        if name == 'lookup_records':
            wanted = set(args['ids'])
            return [record_dict(r) for r in records if r.id in wanted]
        if name == 'search_records':
            hits = [r for r in records
                    if (args['text'] is None or args['text'].lower() in r.description.lower())
                    and (args['account'] is None or r.account == args['account'])
                    and (args['amount_cents'] is None or r.amount == args['amount_cents'])]
            return [record_dict(r) for r in hits[:50]]
        raise KeyError(name)

    def classify(self, case: Case, candidates: list[Candidate]) -> list[Finding]:
        task = {'entity': case.meta['entity'], 'period': [str(d) for d in case.period],
                'cash_account': case.meta['cash_account'], 'accounts': case.meta.get('accounts', {}),
                'sales_tax': case.meta.get('sales_tax'),
                'chart_of_accounts': sorted({r.account for r in case.ledger}),
                'candidates': [{'id': c.id, 'check': c.check, 'amount_cents': c.amount, 'detail': c.detail,
                                'records': [record_dict(r) for r in c.records]} for c in candidates]}
        messages = [{'role': 'user', 'content': 'Classify every candidate.\n\n' + json.dumps(task, indent=1)}]
        for self.turns in range(1, self.max_turns + 1):
            response = self.client.beta.messages.create(
                model=self.model, max_tokens=16000,
                betas=['server-side-fallback-2026-07-01'], fallbacks='default',
                output_config={'effort': 'high'},
                system=[{'type': 'text', 'text': SYSTEM, 'cache_control': {'type': 'ephemeral'}}],
                tools=TOOLS, messages=messages)
            for key in self.tokens:
                self.tokens[key] += getattr(response.usage, key, 0) or 0
            if response.stop_reason == 'refusal':
                raise RuntimeError('the model declined the request')
            if response.stop_reason == 'max_tokens':
                raise RuntimeError('response truncated at max_tokens')
            messages.append({'role': 'assistant', 'content': response.content})
            calls = [b for b in response.content if b.type == 'tool_use']
            if not calls:
                if response.stop_reason == 'pause_turn':
                    continue
                messages.append({'role': 'user', 'content': 'Call submit_findings now with every candidate.'})
                continue
            results = []
            for call in calls:
                if call.name == 'submit_findings':
                    return [Finding(**f) for f in call.input['findings']]
                try:
                    content = json.dumps(self._tool(case, call.name, call.input))
                    results.append({'type': 'tool_result', 'tool_use_id': call.id, 'content': content})
                except (KeyError, TypeError, AttributeError) as exc:
                    results.append({'type': 'tool_result', 'tool_use_id': call.id,
                                    'content': f'error: {exc}', 'is_error': True})
            messages.append({'role': 'user', 'content': results})
        raise RuntimeError(f'no submission after {self.max_turns} turns')
