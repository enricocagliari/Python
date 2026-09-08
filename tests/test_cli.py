import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CliTests(unittest.TestCase):
    def run_cli(self, module, *args):
        return subprocess.run([sys.executable, '-m', module, *map(str, args)],
                              capture_output=True, text=True)

    def test_reconciliation_demo(self):
        result = self.run_cli('projects.reconcile.core', 'projects/reconcile/examples/bank.csv',
                              'projects/reconcile/examples/books.csv')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)['matches']), 2)

    def test_ledger_retry_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            args = ('--db', Path(directory) / 'demo.db', 'post', 'projects/ledger/examples/sale.json')
            first = self.run_cli('projects.ledger.core', *args)
            second = self.run_cli('projects.ledger.core', *args)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(first.stdout, second.stdout)

    def test_manifest_diff_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / 'data'
            data.mkdir()
            first = self.run_cli('projects.manifest.core', 'scan', data)
            (root / 'before.json').write_text(first.stdout)
            (data / 'added').write_text('new')
            second = self.run_cli('projects.manifest.core', 'scan', data)
            (root / 'after.json').write_text(second.stdout)
            changed = self.run_cli('projects.manifest.core', 'diff', root / 'before.json', root / 'after.json')
            self.assertEqual(changed.returncode, 1, changed.stderr)
            same = self.run_cli('projects.manifest.core', 'diff', root / 'before.json', root / 'before.json')
            self.assertEqual(same.returncode, 0, same.stderr)

    def test_bad_csv_exit_code(self):
        result = self.run_cli('projects.reconcile.core', 'missing.csv', 'missing.csv')
        self.assertEqual(result.returncode, 2)
        self.assertIn('error:', result.stderr)
