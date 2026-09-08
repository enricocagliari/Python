"""SQLite double-entry journal with atomic posting and idempotency keys."""
import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY,
    request_key TEXT NOT NULL UNIQUE,
    payload_hash TEXT NOT NULL,
    memo TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS posting (
    journal_id INTEGER NOT NULL REFERENCES journal(id),
    account TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK (amount != 0),
    currency TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS posting_account ON posting(account, currency);
CREATE TRIGGER IF NOT EXISTS no_journal_update BEFORE UPDATE ON journal
BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END;
CREATE TRIGGER IF NOT EXISTS no_journal_delete BEFORE DELETE ON journal
BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END;
CREATE TRIGGER IF NOT EXISTS no_posting_update BEFORE UPDATE ON posting
BEGIN SELECT RAISE(ABORT, 'posting is append-only'); END;
CREATE TRIGGER IF NOT EXISTS no_posting_delete BEFORE DELETE ON posting
BEGIN SELECT RAISE(ABORT, 'posting is append-only'); END;
"""


class Ledger:
    def __init__(self, path: str | Path):
        self.path = str(path)
        with closing(self.connect()) as db:
            db.executescript(SCHEMA)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def post(self, key: str, memo: str, entries: list[dict]) -> int:
        if not isinstance(key, str) or not key.strip():
            raise ValueError('request key is required')
        if not isinstance(memo, str) or len(entries) < 2:
            raise ValueError('memo must be text; at least two entries are required')
        totals, normalized = {}, []
        for entry in entries:
            account, amount, currency = (entry.get(k) for k in ('account', 'amount', 'currency'))
            if not isinstance(account, str) or not account.strip():
                raise ValueError('account is required')
            if type(amount) is not int or amount == 0 or abs(amount) > 10**15:
                raise ValueError('amount must be a nonzero integer in minor units, <= 10^15')
            if not isinstance(currency, str) or len(currency) != 3 or not currency.isascii() or not currency.isalpha() or currency != currency.upper():
                raise ValueError('currency must be three uppercase letters')
            totals[currency] = totals.get(currency, 0) + amount
            normalized.append({'account': account, 'amount': amount, 'currency': currency})
        if any(totals.values()):
            raise ValueError('entries must balance separately for each currency')
        normalized.sort(key=lambda e: (e['account'], e['currency'], e['amount']))
        payload = json.dumps({'memo': memo, 'entries': normalized}, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with closing(self.connect()) as db, db:
            # Serialize lookup+insert so concurrent retries cannot double-post.
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT id, payload_hash FROM journal WHERE request_key=?', (key,)).fetchone()
            if existing:
                if existing[1] != digest:
                    raise ValueError('idempotency key already used for a different payload')
                return existing[0]
            cursor = db.execute('INSERT INTO journal(request_key,payload_hash,memo) VALUES (?,?,?)', (key, digest, memo))
            identifier = cursor.lastrowid
            db.executemany('INSERT INTO posting VALUES (?,?,?,?)',
                           [(identifier, e['account'], e['amount'], e['currency']) for e in normalized])
            return identifier

    def balances(self) -> list[dict]:
        with closing(self.connect()) as db:
            rows = db.execute('SELECT account,currency,SUM(amount) FROM posting GROUP BY account,currency ORDER BY account,currency')
            return [{'account': a, 'currency': c, 'balance': b} for a, c, b in rows]

    def reverse(self, journal_id: int, key: str) -> int:
        with closing(self.connect()) as db:
            rows = db.execute('SELECT account,amount,currency FROM posting WHERE journal_id=?', (journal_id,)).fetchall()
        if not rows:
            raise ValueError('journal does not exist')
        return self.post(key, f'Reversal of journal {journal_id}',
                         [{'account': a, 'amount': -v, 'currency': c} for a, v, c in rows])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    post = commands.add_parser('post')
    post.add_argument('file', type=Path, help='JSON containing key, memo, entries')
    commands.add_parser('balances')
    reverse = commands.add_parser('reverse')
    reverse.add_argument('id', type=int)
    reverse.add_argument('--key', required=True)
    args = parser.parse_args()
    try:
        ledger = Ledger(args.db)
        if args.command == 'post':
            data = json.loads(args.file.read_text())
            result = {'journal_id': ledger.post(data['key'], data['memo'], data['entries'])}
        elif args.command == 'reverse':
            result = {'journal_id': ledger.reverse(args.id, args.key)}
        else:
            result = ledger.balances()
        print(json.dumps(result, indent=2))
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
        parser.exit(2, f'error: {exc}\n')


if __name__ == '__main__':
    main()
