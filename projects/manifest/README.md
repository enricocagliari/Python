# FileProof

**Content changes, without relying on filenames or modification dates alone.**

FileProof creates a deterministic SHA-256 manifest of a directory and compares two snapshots. A renamed file appears as a removal and an addition. A timestamp-only change does not count as changed content.

## Try it

Run from the repository root. Save manifests outside the scanned directory:

```sh
python -m projects.manifest.core scan projects/reconcile/examples > before.json
python -m projects.manifest.core scan projects/reconcile/examples > after.json
python -m projects.manifest.core diff before.json after.json
```

Output on unchanged files:

```json
{"added": [], "removed": [], "modified": []}
```

Change a sample file and create another snapshot to see it listed as modified.

## Format

```json
{
  "version": 1,
  "algorithm": "sha256",
  "files": {
    "nested/example.txt": {
      "size": 5,
      "sha256": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    }
  }
}
```

Paths are relative and use forward slashes. File contents are read in one-MiB blocks. Memory use is O(number of files) for metadata, plus one read buffer. Runtime is O(total bytes + file sorting).

## Filesystem behavior

- Rejects symlinks and nonregular files.
- Raises on inaccessible traversal rather than silently dropping files.
- Compares inode, device, size, and timestamps around reads to detect common concurrent modifications.
- Includes empty and binary files.
- Excludes empty directories and filesystem metadata from the manifest.

These checks do not provide an atomic directory snapshot. Scan a stable copy for consistent results. This is not designed for hostile concurrent filesystem writers, and it is not a forensic chain-of-custody system. A digest detects a difference against a trusted baseline; it does not prove who created a file or protect an unsigned baseline from replacement.

## Automation

| Exit code | Meaning |
| --- | --- |
| 0 | Scan succeeded, or compared snapshots are equal |
| 1 | Diff found changes |
| 2 | Invalid input or filesystem error |

```sh
python -m unittest discover -s tests -p 'test_manifest.py' -v
```

Tests cover known digests, Unicode nested paths, empty files, symlinks, malformed manifests, metadata-only changes, and added/removed/modified output. End-to-end CLI tests verify exit status behavior.
