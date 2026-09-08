# ClearMatch

**A reconciliation tool that knows when not to match.**

Two exports can contain equal amounts on nearby dates without describing the same transaction. Choosing the first candidate silently turns uncertainty into an apparent fact. ClearMatch reports that uncertainty.

## Try it

Run from the repository root:

```sh
python -m projects.reconcile.core projects/reconcile/examples/bank.csv projects/reconcile/examples/books.csv --days 3
```

| Bank row | Outcome | Explanation |
| --- | --- | --- |
| B001 | Matches L001 | USD 1,250; one-day difference; unique in both directions |
| B002 | Matches L002 | USD -39; same day; unique in both directions |
| B003, B004 | Review | Both could explain L003 |
| B005 | Unmatched | No corresponding USD -12.50 entry |

JSON output includes matched IDs, a reason for every accepted pair, review candidates, unmatched IDs, and the policy used. Unmatched right-hand rows include candidates still pending review.

## Input contract

UTF-8 CSV, optional BOM, with `id,date,amount,currency,description` columns. IDs must be unique within each file. Dates use ISO YYYY-MM-DD. Amounts are signed decimal strings with no more than two fractional digits. Currency codes are three letters and normalized to uppercase; this is syntax validation, not an ISO currency registry.

Both exports must use the same sign convention. Descriptions are retained in the input model but do not influence matching.

## Algorithm

1. Index right-hand transactions by currency and integer amount.
2. Build candidate edges for dates within the inclusive window.
3. Accept an edge only when each endpoint has exactly one candidate.
4. Leave every ambiguous edge for review; sort all output by IDs.

This is deliberately more conservative than maximum-cardinality bipartite matching. A mathematically possible assignment is not evidence that payments correspond. It does not iteratively force leftover candidates.

Typical candidate discovery is much smaller than a full cross-product, but repeated identical amounts can still make runtime and candidate storage O(n × m). This implementation reads both inputs into memory.

## Tests and limits

```sh
python -m unittest discover -s tests -p 'test_reconcile.py' -v
```

Tests cover order invariance, many-to-one conflicts, currency and sign differences, date boundaries, invalid decimals, duplicate IDs, and UTF-8 BOM input.

No split payments, fees, FX conversion, fuzzy descriptions, or three-decimal currencies. A next extension would be a separate, human-approved split-match proposal stage; it should never silently weaken the exact-match policy.
