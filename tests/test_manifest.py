import hashlib
import tempfile
import unittest
from pathlib import Path
from projects.manifest.core import snapshot, compare


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_known_digest(self):
        (self.root / 'hello.txt').write_bytes(b'hello')
        record = snapshot(self.root)['files']['hello.txt']
        self.assertEqual(record, {'size': 5, 'sha256': hashlib.sha256(b'hello').hexdigest()})

    def test_nested_unicode_and_empty(self):
        (self.root / 'nested').mkdir()
        (self.root / 'nested' / 'café.txt').write_bytes(b'')
        self.assertIn('nested/café.txt', snapshot(self.root)['files'])

    def test_added_removed_modified(self):
        for name in ['removed', 'changed', 'unchanged']:
            (self.root / name).write_text('before')
        before = snapshot(self.root)
        (self.root / 'removed').unlink()
        (self.root / 'changed').write_text('after')
        (self.root / 'added').write_text('new')
        self.assertEqual(compare(before, snapshot(self.root)),
                         {'added': ['added'], 'removed': ['removed'], 'modified': ['changed']})

    def test_metadata_only_change_ignored(self):
        path = self.root / 'data'
        path.write_text('same')
        before = snapshot(self.root)
        path.touch()
        self.assertFalse(any(compare(before, snapshot(self.root)).values()))

    def test_symlink_rejected(self):
        (self.root / 'target').write_text('data')
        try:
            (self.root / 'link').symlink_to(self.root / 'target')
        except OSError:
            self.skipTest('symlink creation unavailable')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            snapshot(self.root)

    def test_invalid_manifest(self):
        with self.assertRaises(ValueError):
            compare({'files': {}}, snapshot(self.root))

    def test_stable_output(self):
        for name in ['z', 'a', 'm']:
            (self.root / name).write_text(name)
        self.assertEqual(list(snapshot(self.root)['files']), ['a', 'm', 'z'])
        self.assertEqual(snapshot(self.root), snapshot(self.root))
