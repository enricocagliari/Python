import itertools
import tempfile
import unittest
from datetime import date
from pathlib import Path
from projects.reconcile.core import Transaction, cents, read_csv, reconcile


def tx(identifier, amount=100, day=1, currency='USD'):
    return Transaction(identifier, date(2026, 1, day), amount, currency)


class ReconcileTests(unittest.TestCase):
    def test_exact_match(self):
        result = reconcile([tx('a')], [tx('b', day=4)])
        self.assertEqual(result['matches'][0]['right'], 'b')

    def test_outside_window(self):
        self.assertEqual(reconcile([tx('a')], [tx('b', day=5)])['unmatched_left'], ['a'])

    def test_currency_and_sign_must_match(self):
        result = reconcile([tx('a')], [tx('b', currency='EUR'), tx('c', amount=-100)])
        self.assertFalse(result['matches'])

    def test_many_to_one_is_review(self):
        result = reconcile([tx('a'), tx('b')], [tx('c')])
        self.assertFalse(result['matches'])
        self.assertEqual(len(result['review']), 2)

    def test_one_to_many_is_review(self):
        result = reconcile([tx('a')], [tx('b'), tx('c')])
        self.assertEqual(result['review'], [{'left': 'a', 'candidates': ['b', 'c']}])

    def test_order_invariant(self):
        left, right = [tx('a'), tx('b'), tx('c', 200)], [tx('x'), tx('y', 200)]
        baseline = reconcile(left, right)
        for a in itertools.permutations(left):
            for b in itertools.permutations(right):
                self.assertEqual(reconcile(a, b), baseline)

    def test_empty(self):
        self.assertEqual(reconcile([], [])['matches'], [])

    def test_duplicates_and_negative_window(self):
        with self.assertRaises(ValueError):
            reconcile([tx('a'), tx('a')], [])
        with self.assertRaises(ValueError):
            reconcile([], [], -1)

    def test_decimal_validation(self):
        self.assertEqual(cents('0.29'), 29)
        self.assertEqual(cents('-10.01'), -1001)
        for invalid in ['NaN', 'Infinity', '0.001', 'abc']:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                cents(invalid)

    def test_csv_bom_and_duplicate_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.csv'
            path.write_text('\ufeffid,date,amount,currency,description\na,2026-01-01,1.00,usd,Sale\n')
            self.assertEqual(read_csv(path)[0].amount, 100)
            with path.open('a') as stream:
                stream.write('a,2026-01-02,1.00,USD,Duplicate\n')
            with self.assertRaisesRegex(ValueError, ':3:'):
                read_csv(path)
