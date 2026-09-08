import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from projects.ledger.core import Ledger


def entries(amount=100):
    return [{'account': 'cash', 'amount': amount, 'currency': 'USD'},
            {'account': 'revenue', 'amount': -amount, 'currency': 'USD'}]


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Ledger(Path(self.tmp.name) / 'ledger.db')

    def test_balances(self):
        self.ledger.post('a', 'sale', entries())
        self.assertEqual([x['balance'] for x in self.ledger.balances()], [100, -100])

    def test_retry_returns_same_id(self):
        first = self.ledger.post('a', 'sale', entries())
        self.assertEqual(self.ledger.post('a', 'sale', list(reversed(entries()))), first)
        self.assertEqual(self.ledger.balances()[0]['balance'], 100)

    def test_conflicting_retry_rejected(self):
        self.ledger.post('a', 'sale', entries())
        with self.assertRaisesRegex(ValueError, 'different payload'):
            self.ledger.post('a', 'sale', entries(200))

    def test_unbalanced_does_not_write(self):
        data = entries()
        data[1]['amount'] = -99
        with self.assertRaises(ValueError):
            self.ledger.post('a', 'sale', data)
        self.assertEqual(self.ledger.balances(), [])

    def test_cross_currency_cannot_balance(self):
        data = entries()
        data[1]['currency'] = 'EUR'
        with self.assertRaises(ValueError):
            self.ledger.post('a', 'sale', data)

    def test_reversal_preserves_original(self):
        identifier = self.ledger.post('a', 'sale', entries())
        self.ledger.reverse(identifier, 'reverse-a')
        self.assertEqual([x['balance'] for x in self.ledger.balances()], [0, 0])
        with sqlite3.connect(self.ledger.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM journal').fetchone()[0], 2)

    def test_reversal_retry(self):
        identifier = self.ledger.post('a', 'sale', entries())
        first = self.ledger.reverse(identifier, 'reverse-a')
        self.assertEqual(self.ledger.reverse(identifier, 'reverse-a'), first)

    def test_missing_reversal(self):
        with self.assertRaises(ValueError):
            self.ledger.reverse(123, 'missing')

    def test_concurrent_retries_post_once(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(lambda _: self.ledger.post('same', 'sale', entries()), range(24)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(self.ledger.balances()[0]['balance'], 100)

    def test_mutation_triggers(self):
        self.ledger.post('a', 'sale', entries())
        for sql in ['DELETE FROM journal', 'DELETE FROM posting',
                    "UPDATE journal SET memo='changed'", 'UPDATE posting SET amount=999']:
            with sqlite3.connect(self.ledger.path) as db:
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(sql)

    def test_invalid_amounts(self):
        for value in [True, 0, 1.5, '100', 10**16]:
            data = entries()
            data[0]['amount'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.ledger.post('a', 'sale', data)
