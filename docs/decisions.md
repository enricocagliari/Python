# Architecture decisions

## 01 · Standard library first

The three projects have no third-party runtime dependencies. Their interesting behavior is in matching rules, transaction boundaries, and filesystem handling. Keeping dependency setup out of the quick start makes those behaviors easier to inspect.

Trade-off: CLI interfaces are basic and there is no web UI. If a UI is added, keep it separate from the tested core.

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
