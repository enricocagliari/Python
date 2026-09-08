"""Conservative one-to-one transaction reconciliation."""
import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path


@dataclass(frozen=True)
class Transaction:
    id: str
    date: date
    amount: int
    currency: str
    description: str = ''


def cents(value: str) -> int:
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount != amount.quantize(Decimal('0.01')):
            raise ValueError('amount must be finite with at most two decimal places')
        return int(amount * 100)
    except InvalidOperation as exc:
        raise ValueError(f'invalid amount: {value!r}') from exc


def read_csv(path: Path) -> list[Transaction]:
    result, seen = [], set()
    with path.open(newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        required = {'id', 'date', 'amount', 'currency', 'description'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f'{path}: expected columns {sorted(required)}')
        for line, row in enumerate(reader, 2):
            try:
                identifier = row['id'].strip()
                if not identifier or identifier in seen:
                    raise ValueError('empty or duplicate id')
                currency = row['currency'].strip().upper()
                if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
                    raise ValueError('currency must be a three-letter code')
                result.append(Transaction(identifier, date.fromisoformat(row['date']),
                                          cents(row['amount']), currency,
                                          row['description'].strip()))
                seen.add(identifier)
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValueError(f'{path}:{line}: {exc}') from exc
    return result


def reconcile(left: list[Transaction], right: list[Transaction], days: int = 3) -> dict:
    """Only mutually unique candidates match. Input order cannot break ties."""
    if days < 0:
        raise ValueError('days must be nonnegative')
    for records in (left, right):
        if len({t.id for t in records}) != len(records):
            raise ValueError('duplicate transaction id')
    index = defaultdict(list)
    for item in right:
        index[item.currency, item.amount].append(item)
    candidates, reverse = {}, defaultdict(list)
    for item in left:
        hits = sorted(other.id for other in index[item.currency, item.amount]
                      if abs((item.date - other.date).days) <= days)
        candidates[item.id] = hits
        for identifier in hits:
            reverse[identifier].append(item.id)
    matches, review, unmatched = [], [], []
    matched_right = set()
    for identifier, hits in sorted(candidates.items()):
        if len(hits) == 1 and len(reverse[hits[0]]) == 1:
            matches.append({'left': identifier, 'right': hits[0],
                            'reason': 'equal amount/currency; mutually unique within date window'})
            matched_right.add(hits[0])
        elif hits:
            review.append({'left': identifier, 'candidates': hits})
        else:
            unmatched.append(identifier)
    return {'matches': matches, 'review': review, 'unmatched_left': unmatched,
            'unmatched_right': sorted(t.id for t in right if t.id not in matched_right),
            'policy': {'date_window_days': days, 'amount_tolerance_cents': 0}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('left', type=Path)
    parser.add_argument('right', type=Path)
    parser.add_argument('--days', type=int, default=3)
    args = parser.parse_args()
    try:
        report = reconcile(read_csv(args.left), read_csv(args.right), args.days)
    except (ValueError, OSError) as exc:
        parser.exit(2, f'error: {exc}\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
