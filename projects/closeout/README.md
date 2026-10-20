# Closeout

**An AI accounting close agent whose numbers never come from the model.**

Month-end cash close is repetitive, but the failure mode is expensive: a bank fee booked as revenue, a duplicate payment that nets into "timing differences", a workpaper nobody can trace back to a source line. Closeout splits the job the way a good senior would. A deterministic engine reconciles the bank statement to the cash ledger, runs integrity checks, and produces candidate exceptions with file-and-line citations. A provider, either Claude or a keyword rule set, classifies each candidate, explains it, and proposes a balanced adjusting entry. The engine audits the answer before it reaches the workpaper, and an evaluation harness scores providers on labeled synthetic cases.

## Try it

Run from the repository root. The rules provider needs no network, account, or API key.

```sh
python -m projects.closeout.core projects/closeout/examples/acme-2026-03 --out workpaper.md
python -m projects.closeout.evaluate projects/closeout/examples
```

The example is a fictional studio's March close with seven bank lines and ten journals.

| Candidate | Evidence | Rules provider says | Correct answer |
| --- | --- | --- | --- |
| C001 | `MONTHLY SERVICE FEE -25.00` not in ledger | bank_fee, entry proposed | bank_fee |
| C002 | `INTEREST PAID 4.12` not in ledger | interest, entry proposed | interest |
| C003 | Cash posting L016 never hit the bank | missing_entry | duplicate of L014 |
| C004 | Cash posting L023 dated 03-30, no bank line | timing | timing |
| C005, C006 | J007 repeats J006 line for line | duplicate, reversal proposed | duplicate |

The workpaper shows the book balance, the bank balance, and that the difference reaches 0.00 after the findings. Every finding lists its source records as `bank.csv#L7` style references so a reviewer can open the file at that line. The exit code is 1 when any finding needs action, so a scheduled run can fail loudly.

Candidate C003 is the point of the project. The rules provider sees a cash posting with no bank line in mid-month and calls it a missing entry. The right call requires reading C006 and noticing that L016 is the second leg of a duplicated payment. That is what an LLM provider is for.

## Run with Claude

```sh
pip install anthropic
export ANTHROPIC_API_KEY=...
python -m projects.closeout.core projects/closeout/examples/acme-2026-03 --provider claude
python -m projects.closeout.evaluate cases --generate 10 --provider claude --json claude.json
```

The Claude provider uses the official SDK and model `claude-opus-5-5` at high effort with server-side refusal fallbacks enabled. It receives the candidates and their records, can call `lookup_records` and `search_records` to read any other line, and must finish by calling `submit_findings`, a strict-schema tool whose category enum is the engine's own list. Amounts are never free text. If the model skips a candidate, returns an unknown category, hits `max_tokens`, or is declined, the engine escalates that candidate as `missing_entry` with severity high rather than dropping it. The system prompt is frozen and cache-marked so repeated runs pay the cached rate for it.

Token usage is accumulated from every turn and priced from a small per-model table, so each workpaper and each evaluation reports cost in dollars.

## Input contract

A case directory holds three files.

- `ledger.csv`: `id,journal,date,account,amount,currency,description`. Debits positive, credits negative, amounts with at most two decimals, ISO dates. IDs are unique.
- `bank.csv`: `id,date,amount,currency,description`. Deposits positive.
- `case.json`: entity, period, cash account name, opening balances in cents, optional account names for proposed entries, an optional `sales_tax` block, and `expected` labels used only by the evaluation.

## Checks

1. Bank-to-ledger reconciliation of the cash account using ClearMatch's policy: a bank line matches only a mutually unique ledger posting within the date window.
2. Unmatched bank lines, unmatched cash postings, and ambiguous bank lines each become a candidate.
3. Duplicate postings: same account, amount, and description within the period.
4. Unbalanced journals: debits minus credits is not zero.
5. Period cutoff: ledger dates outside the close period.
6. Sales tax reasonableness: payable postings versus sales times the configured rate.

Each check cites the records it used. The provider receives the same citations and cannot add records the engine did not load.

## Evaluation

`evaluate.py` runs a provider across a directory of cases and reports category accuracy, precision, recall, F1, false positives, false negatives, seconds per case, tokens per case, and cost per case. Labels are the exceptions a careful accountant would raise; any engine candidate without a label must be classified `no_exception`, so a provider that flags everything is punished on precision.

`synth.py` generates labeled cases from a seed: clean matched activity plus a chosen number of injected exceptions (bank fee, interest, timing, duplicate, missing entry, unbalanced journal, cutoff, sales tax variance). The test suite asserts that every injected label corresponds to an engine candidate, so the evaluation measures the provider and not generator drift.

The rules baseline on twenty generated cases:

| Metric | Rules |
| :--- | ---: |
| Category accuracy | 89.4% |
| Precision / recall | 100% / 100% |
| Cost per case | $0 |

Its misses are all the same shape as C003 above. Rerun with `--provider claude` to fill in the second column for your own API key; results are not checked in because they cost money and vary by model version.

## Tests and limits

```sh
python -m unittest discover -s tests -p 'test_closeout.py' -v
```

Tests cover the engine checks, citation format, the audit that escalates missing or invalid provider answers, a scripted Claude client exercising the tool loop, refusal handling and cost accounting, strict tool schemas, generator determinism and label consistency, scoring arithmetic, and the CLIs.

Single currency per case. One cash account. No fuzzy description matching, no split payments, no accruals beyond the sales tax check, and no tax return preparation. The Claude provider is not run in CI. Proposed entries are drafts for a human to approve; nothing posts them.
