# Development

Use Python 3.11+. Run commands from the repository root.

```sh
python -m unittest discover -s tests -v
python -m compileall -q projects tests
```

The suite includes unit tests and subprocess CLI tests. All data is generated in temporary directories or comes from the committed synthetic fixtures. Tests do not require network access; the Claude provider is exercised with a scripted fake client, and a live run needs `pip install anthropic` and `ANTHROPIC_API_KEY`.

## Layout

| Path | Purpose |
| --- | --- |
| projects/closeout | Close engine, rules and Claude providers, synthetic case generator, evaluation harness, sample case |
| projects/reconcile | CSV adapter, matching policy, CLI, samples |
| projects/ledger | SQLite schema, posting service, CLI, sample journal |
| projects/manifest | File scanner, manifest validation, diff, CLI |
| tests | Failure cases, invariants, concurrency, end-to-end behavior |
| docs | Design decisions and contributor guidance |

## Change discipline

Add tests for the failure a change addresses. Keep input adaptation separate from the core policy. Preserve deterministic outputs and document schema or exit-code changes. Use fictional data in fixtures; never add real financial exports.

## Useful next increments

- Closeout: multi-currency cases, a Claude evaluation run checked in with its model version, accrual and prepaid checks, and a second model provider for cost comparison; keep the engine as the only source of numbers.
- ClearMatch: date-sorted candidate buckets for large repeated-amount groups; retain the conservative acceptance rule.
- Journal: an explicit reversal relationship, schema migrations, and a service boundary with authentication.
- FileProof: signed manifests and optional filesystem snapshot integration; preserve the distinction between integrity checking and provenance.

The current code implements the scope documented in each project README. These increments are future work, not existing features.
