# Enrico Cagliari · Engineering portfolio

**Python · SQL · LLM agents · Data integrity · Financial systems**

Small, inspectable systems for problems where getting the numbers almost right is still wrong.

My background is in accounting and financial analysis. These projects explore the engineering underneath that work: reconciling inconsistent data, preserving journal invariants, checking whether files have changed, and letting an LLM draft a close workpaper without letting it touch a number. Each has a runnable CLI, synthetic examples, automated tests, and notes on the decisions and limits.

## Projects

| Project | What it does | Engineering focus |
| :--- | :--- | :--- |
| [Closeout](projects/closeout) | AI accounting close agent: reconciles, flags exceptions, drafts a cited workpaper, and scores itself | Claude tool loop with strict schemas, deterministic engine, evaluation harness for accuracy, false positives, time, and cost |
| [ClearMatch](projects/reconcile) | Reconciles two transaction exports without guessing ambiguous matches | Candidate graphs, deterministic results, exact money parsing |
| [Journal](projects/ledger) | Stores balanced, append-only double-entry postings in SQLite | Transactions, concurrent retries, idempotency, reversals |
| [FileProof](projects/manifest) | Creates portable file manifests and reports content changes | Streaming hashes, filesystem edge cases, automation exit codes |

**Start with [Closeout](projects/closeout)** for AI product and applied LLM work, **[Journal](projects/ledger)** for backend and database work, or **[ClearMatch](projects/reconcile)** for data processing and algorithms.

## Run in two minutes

Python 3.11 or newer. No third-party runtime dependencies, accounts, or API keys. Closeout's Claude provider is optional and needs `pip install anthropic` plus an API key; everything else, including the tests, runs offline.

```sh
git clone https://github.com/enricocagliari/Python.git
cd Python
python -m unittest discover -s tests -v
python -m projects.closeout.core projects/closeout/examples/acme-2026-03 --out workpaper.md
python -m projects.closeout.evaluate cases --generate 10
python -m projects.reconcile.core projects/reconcile/examples/bank.csv projects/reconcile/examples/books.csv
python -m projects.ledger.core --db demo.db post projects/ledger/examples/sale.json
python -m projects.ledger.core --db demo.db balances
```

The close example produces a Markdown workpaper with six findings, each citing its source lines, and a bank reconciliation that explains the full difference. The evaluation generates ten labeled synthetic cases and scores the offline rules provider; add `--provider claude` to score the model. The reconciliation example produces two matches, two ambiguous bank entries for review, and one bank entry with no candidate. Repeating the journal post returns the same journal ID without changing balances.

## What to inspect

- [Close engine](projects/closeout/core.py): candidates carry file-and-line citations; the provider's answer is audited before rendering.
- [Claude provider](projects/closeout/providers.py): tool loop with strict schemas, refusal handling, and per-run cost accounting; the rules provider is the offline baseline.
- [Evaluation harness](projects/closeout/evaluate.py): accuracy, false positives, time, and cost per case against labeled synthetic data.
- [Matching policy](projects/reconcile/core.py): neither CSV order nor a nearest-date guess determines an ambiguous result.
- [Posting transaction](projects/ledger/core.py): the retry lookup and insert share a SQLite write transaction.
- [Concurrency test](tests/test_ledger.py): 24 concurrent retries must produce exactly one journal.
- [File scanner](projects/manifest/core.py): bounded read buffers, portable paths, and checks for files changing while read.
- [Architecture decisions](docs/decisions.md): trade-offs and the boundaries of the implementation.
- [Development guide](docs/development.md): test commands and extension points.

## Scope

These are working portfolio projects, not claims of production deployment. Samples are fictional and contain no client data. The tools deliberately have small interfaces and explicit limits; project READMEs explain where they should be extended before operational use.

Earlier exercises remain in the repository history and in `coinchange.py`.
