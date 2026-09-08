"""Portable SHA-256 directory manifests and change reports."""
import argparse
import hashlib
import json
import os
import stat
from pathlib import Path


def snapshot(root: Path) -> dict:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('root must be a directory')
    files = {}
    def fail(error):
        raise error
    for parent, directories, names in os.walk(root, followlinks=False, onerror=fail):
        for name in directories + names:
            if (Path(parent) / name).is_symlink():
                raise ValueError(f'symlinks are not supported: {name}')
        for name in sorted(names):
            path = Path(parent) / name
            before = path.stat()
            if not stat.S_ISREG(before.st_mode):
                raise ValueError(f'not a regular file: {name}')
            digest = hashlib.sha256()
            with path.open('rb') as source:
                opened = os.fstat(source.fileno())
                if (before.st_ino, before.st_dev) != (opened.st_ino, opened.st_dev):
                    raise ValueError(f'file changed while opening: {name}')
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(block)
                after = os.fstat(source.fileno())
            final = path.stat()
            fingerprint = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            if fingerprint(before) != fingerprint(after) or fingerprint(after) != fingerprint(final):
                raise ValueError(f'file changed during scan: {name}')
            files[path.relative_to(root).as_posix()] = {'size': after.st_size, 'sha256': digest.hexdigest()}
    return {'version': 1, 'algorithm': 'sha256', 'files': dict(sorted(files.items()))}


def validate(manifest: dict) -> dict:
    if not isinstance(manifest, dict) or manifest.get('version') != 1 or manifest.get('algorithm') != 'sha256' or not isinstance(manifest.get('files'), dict):
        raise ValueError('unsupported manifest format')
    for name, entry in manifest['files'].items():
        if not isinstance(entry, dict) or type(entry.get('size')) is not int or entry['size'] < 0:
            raise ValueError(f'invalid file entry: {name}')
        digest = entry.get('sha256', '')
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError(f'invalid digest: {name}')
    return manifest


def compare(before: dict, after: dict) -> dict:
    old, new = validate(before)['files'], validate(after)['files']
    return {'added': sorted(new.keys() - old.keys()),
            'removed': sorted(old.keys() - new.keys()),
            'modified': sorted(k for k in old.keys() & new.keys() if old[k] != new[k])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    scan = sub.add_parser('scan')
    scan.add_argument('root', type=Path)
    diff = sub.add_parser('diff')
    diff.add_argument('before', type=Path)
    diff.add_argument('after', type=Path)
    args = parser.parse_args()
    try:
        result = snapshot(args.root) if args.command == 'scan' else compare(
            json.loads(args.before.read_text()), json.loads(args.after.read_text()))
    except (OSError, ValueError) as exc:
        parser.exit(2, f'error: {exc}\n')
    print(json.dumps(result, indent=2))
    if args.command == 'diff' and any(result.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
