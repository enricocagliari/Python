"""Generate labeled synthetic close cases. No real data is ever involved.

Each case is a clean set of matched bank and ledger activity with a chosen
number of injected, labeled exceptions. The labels in case.json are what the
evaluation scores a provider against.
"""
import argparse
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

CASH, SALES, TAX, AR, AP = '1010 Cash', '4000 Sales', '2200 Sales tax payable', '1200 Receivables', '2000 Payables'
VENDORS = ['Northwind Supplies', 'Lakeside Properties', 'Beacon Insurance', 'Granite Utilities', 'Orbit Software']
CUSTOMERS = ['Harbor Dental', 'Juniper Bakery', 'Summit Fitness', 'Pine Street Clinic', 'Redwood Legal']
INJECTIONS = ('bank_fee', 'interest', 'timing', 'duplicate', 'missing_entry', 'unbalanced', 'cutoff', 'tax_variance')


def generate(seed: int, transactions: int = 20, exceptions: int = 4, start: date = date(2026, 3, 1)) -> dict:
    rng = random.Random(seed)
    end = start + timedelta(days=30)
    ledger, bank, labels = [], [], []
    counters = {'J': 0, 'L': 0, 'B': 0}

    def nid(prefix):
        counters[prefix] += 1
        return f'{prefix}{counters[prefix]:03d}'

    def post(journal, day, account, amount, text):
        ledger.append({'id': nid('L'), 'journal': journal, 'date': day, 'account': account,
                       'amount': amount, 'currency': 'USD', 'description': text})
        return ledger[-1]

    def bank_line(day, amount, text):
        bank.append({'id': nid('B'), 'date': day, 'amount': amount, 'currency': 'USD', 'description': text})
        return bank[-1]

    used = set()

    def unique_amount(party):
        while True:
            amount = rng.randrange(5, 250) * 100
            if amount not in used:
                used.add(amount)
                return amount

    def sale(day, net):
        tax = round(net * 0.08)
        j = nid('J')
        post(j, day, AR, net + tax, f'Invoice {customer}')
        post(j, day, SALES, -net, f'Invoice {customer}')
        post(j, day, TAX, -tax, f'Invoice {customer}')
        return j

    for _ in range(transactions):
        day = start + timedelta(days=rng.randrange(0, 26))
        if rng.random() < 0.5:
            customer = rng.choice(CUSTOMERS)
            net = unique_amount(customer)
            sale(day, net)
            gross = net + round(net * 0.08)
            j = nid('J')
            post(j, day + timedelta(days=1), CASH, gross, f'Receipt {customer}')
            post(j, day + timedelta(days=1), AR, -gross, f'Receipt {customer}')
            bank_line(day + timedelta(days=2), gross, f'DEPOSIT {customer.upper()}')
        else:
            vendor = rng.choice(VENDORS)
            amount = unique_amount(vendor)
            j = nid('J')
            post(j, day, AP, amount, f'Payment {vendor}')
            post(j, day, CASH, -amount, f'Payment {vendor}')
            bank_line(day + timedelta(days=1), -amount, f'ACH {vendor.upper()}')

    chosen = rng.sample(INJECTIONS, min(exceptions, len(INJECTIONS)))
    for kind in chosen:
        if kind == 'bank_fee':
            line = bank_line(end - timedelta(days=1), -rng.randrange(10, 40) * 100, 'MONTHLY SERVICE FEE')
            labels.append({'category': 'bank_fee', 'ids': [line['id']]})
        elif kind == 'interest':
            line = bank_line(end, rng.randrange(1, 15) * 100 + 37, 'INTEREST PAID')
            labels.append({'category': 'interest', 'ids': [line['id']]})
        elif kind == 'timing':
            vendor = rng.choice(VENDORS)
            amount = unique_amount(vendor)
            j = nid('J')
            post(j, end - timedelta(days=1), AP, amount, f'Payment {vendor}')
            row = post(j, end - timedelta(days=1), CASH, -amount, f'Payment {vendor}')
            labels.append({'category': 'timing', 'ids': [row['id']]})
        elif kind == 'duplicate':
            original = rng.choice([r for r in ledger if r['account'] == AP and r['amount'] > 0
                                   and r['date'] <= end - timedelta(days=6)])
            cash_original = next(r for r in ledger if r['journal'] == original['journal'] and r['account'] == CASH)
            j = nid('J')
            again = original['date'] + timedelta(days=5)
            dup_ap = post(j, again, AP, original['amount'], original['description'])
            dup_cash = post(j, again, CASH, -original['amount'], original['description'])
            labels.append({'category': 'duplicate', 'ids': sorted([original['id'], dup_ap['id']])})
            labels.append({'category': 'duplicate', 'ids': sorted([cash_original['id'], dup_cash['id']])})
            labels.append({'category': 'duplicate', 'ids': [dup_cash['id']]})
        elif kind == 'missing_entry':
            customer = rng.choice(CUSTOMERS)
            line = bank_line(start + timedelta(days=rng.randrange(3, 20)), rng.randrange(50, 300) * 100,
                             f'WIRE IN {customer.upper()}')
            labels.append({'category': 'missing_entry', 'ids': [line['id']]})
        elif kind == 'unbalanced':
            vendor = rng.choice(VENDORS)
            j = nid('J')
            post(j, start + timedelta(days=rng.randrange(3, 20)), '6100 Rent', 120000, f'Accrual {vendor}')
            rows = [ledger[-1], post(j, ledger[-1]['date'], AP, -102000, f'Accrual {vendor}')]
            labels.append({'category': 'unbalanced', 'ids': sorted(r['id'] for r in rows)})
        elif kind == 'cutoff':
            vendor = rng.choice(VENDORS)
            j = nid('J')
            rows = [post(j, end + timedelta(days=3), '6300 Utilities', 8800, f'Bill {vendor}'),
                    post(j, end + timedelta(days=3), AP, -8800, f'Bill {vendor}')]
            for row in rows:
                labels.append({'category': 'cutoff', 'ids': [row['id']]})
        elif kind == 'tax_variance':
            customer = rng.choice(CUSTOMERS)
            net = 30000
            j = nid('J')
            post(j, start + timedelta(days=10), AR, net + 2400, f'Invoice {customer}')
            post(j, start + timedelta(days=10), SALES, -net - 2400, f'Invoice {customer}')
            labels.append({'category': 'tax_variance', 'check': 'sales_tax_variance'})

    ledger.sort(key=lambda r: (r['date'], r['id']))
    bank.sort(key=lambda r: (r['date'], r['id']))
    meta = {'entity': f'Synthetic Co {seed}', 'period_start': str(start), 'period_end': str(end),
            'cash_account': CASH, 'bank_opening_balance': 1_000_000, 'book_opening_balance': 1_000_000,
            'accounts': {'bank_charges': '6900 Bank charges', 'interest_income': '7100 Interest income',
                         'suspense': '9999 Suspense'},
            'sales_tax': {'rate': 0.08, 'sales_account': SALES, 'payable_account': TAX, 'tolerance_cents': 100},
            'expected': labels, 'seed': seed}
    return {'meta': meta, 'ledger': ledger, 'bank': bank}


def write_case(case: dict, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, rows, columns in (('ledger.csv', case['ledger'], ('id', 'journal', 'date', 'account', 'amount',
                                                                 'currency', 'description')),
                                ('bank.csv', case['bank'], ('id', 'date', 'amount', 'currency', 'description'))):
        with (directory / name).open('w', newline='', encoding='utf-8') as out:
            writer = csv.DictWriter(out, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({**row, 'amount': f"{row['amount'] / 100:.2f}"})
    (directory / 'case.json').write_text(json.dumps(case['meta'], indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path, help='directory that receives one subdirectory per case')
    parser.add_argument('--cases', type=int, default=5)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--transactions', type=int, default=20)
    parser.add_argument('--exceptions', type=int, default=4)
    args = parser.parse_args()
    for seed in range(args.seed, args.seed + args.cases):
        write_case(generate(seed, args.transactions, args.exceptions), args.out / f'case-{seed:03d}')
    print(f'wrote {args.cases} cases to {args.out}')


if __name__ == '__main__':
    main()
