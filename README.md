# Enrico Cagliari · Engineering portfolio

**Python · SQL · Data integrity · Financial systems**

Small, inspectable systems for problems where getting the numbers almost right is still wrong.

My background is in accounting and financial analysis. These projects explore the engineering underneath that work: reconciling inconsistent data, preserving journal invariants, and checking whether files have changed. Each has a runnable CLI, synthetic examples, automated tests, and notes on the decisions and limits.

## Projects

| Project | What it does | Engineering focus |
| :--- | :--- | :--- |
| [ClearMatch](projects/reconcile) | Reconciles two transaction exports without guessing ambiguous matches | Candidate graphs, deterministic results, exact money parsing |
| [Journal](projects/ledger) | Stores balanced, append-only double-entry postings in SQLite | Transactions, concurrent retries, idempotency, reversals |
| [FileProof](projects/manifest) | Creates portable file manifests and reports content changes | Streaming hashes, filesystem edge cases, automation exit codes |

**Start with [Journal](projects/ledger)** for backend and database work, or **[ClearMatch](projects/reconcile)** for data processing and algorithms.

## Run in two minutes

Python 3.11 or newer. No third-party runtime dependencies, accounts, or API keys.

```sh
git clone https://github.com/enricocagliari/Python.git
cd Python
python -m unittest discover -s tests -v
python -m projects.reconcile.core projects/reconcile/examples/bank.csv projects/reconcile/examples/books.csv
python -m projects.ledger.core --db demo.db post projects/ledger/examples/sale.json
python -m projects.ledger.core --db demo.db balances
```

The reconciliation example produces two matches, two ambiguous bank entries for review, and one bank entry with no candidate. Repeating the journal post returns the same journal ID without changing balances.

## What to inspect

- [Matching policy](projects/reconcile/core.py): neither CSV order nor a nearest-date guess determines an ambiguous result.
- [Posting transaction](projects/ledger/core.py): the retry lookup and insert share a SQLite write transaction.
- [Concurrency test](tests/test_ledger.py): 24 concurrent retries must produce exactly one journal.
- [File scanner](projects/manifest/core.py): bounded read buffers, portable paths, and checks for files changing while read.
- [Architecture decisions](docs/decisions.md): trade-offs and the boundaries of the implementation.
- [Development guide](docs/development.md): test commands and extension points.

## Scope

These are working portfolio projects, not claims of production deployment. Samples are fictional and contain no client data. The tools deliberately have small interfaces and explicit limits; project READMEs explain where they should be extended before operational use.

Earlier exercises remain in the repository history and in `coinchange.py`.
