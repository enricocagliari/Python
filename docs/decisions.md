# Architecture decisions

## 01 · Standard library first

The core of every project has no third-party runtime dependencies. Their interesting behavior is in matching rules, transaction boundaries, and filesystem handling. Keeping dependency setup out of the quick start makes those behaviors easier to inspect.

Trade-off: CLI interfaces are basic and there is no web UI. If a UI is added, keep it separate from the tested core. Closeout's Claude provider is the one optional dependency; it is imported only when selected, so the test suite and the default demo stay offline.

## 02 · Exact representations for money

ClearMatch parses decimal strings and converts them to integer cents. Journal accepts integer minor units directly. Binary floats are not accepted for monetary input.

Trade-off: ClearMatch supports only two-decimal inputs; Journal requires the caller to know the currency's unit convention.

## 03 · Uncertainty is output

ClearMatch does not use a greedy nearest-date match or global optimization to resolve conflicts. Mutually unique candidates match; everything else remains visible.

Trade-off: fewer automatic matches. This is intentional when a false positive can hide a missing transaction.

## 04 · Make retry semantics part of persistence

Journal stores a request key and a hash of the canonical payload. A SQLite immediate transaction protects the complete check-and-insert operation.

Trade-off: one writer at a time. This suits a local component; a service with sustained concurrent writes would warrant a database and operational model designed for that workload.

## 05 · Correct by adding, not rewriting

Journal reversals add new postings. Triggers reject edits and deletions of existing rows.

Trade-off: a balance calculation aggregates history. Materialized balance tables would need their own atomic update and reconciliation rules.

## 06 · Keep file manifests portable

FileProof records relative paths, byte counts, and content hashes. Absolute paths and timestamps are omitted.

Trade-off: this is content comparison, not preservation of permissions, empty directories, or ownership. A trusted manifest must be stored separately; hashing alone does not establish authenticity.

## 07 · The model classifies, the engine computes

Closeout's engine reconciles, runs integrity checks, and produces candidates with source citations. The LLM receives those candidates, may read other records through two lookup tools, and returns one classification per candidate through a strict-schema tool. Amounts, record IDs, and balances in the workpaper come from the engine. Any candidate the model skips or mislabels is escalated, never dropped.

Trade-off: the model cannot raise an exception the engine did not detect. That is deliberate; a new check is a code change with a test, not a prompt change.

## 08 · Evaluate the whole system, not the prompt

Labels describe the exceptions an accountant would raise. A candidate with no label must be classified as no exception, so false positives are measured, and a label with no candidate is counted against the engine. Time and token cost are recorded per case alongside accuracy.

Trade-off: synthetic cases encode the author's assumptions about what is routine. The generator's injection types are the ceiling of what the evaluation can detect, and the model-provider results are not checked in because they cost money and drift across model versions.
