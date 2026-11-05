"""Check the two separate submission size limits and frozen source identity."""
import hashlib
import json
from pathlib import Path
import sys


def main():
    source, executable = map(Path, sys.argv[1:3])
    limit = 1_048_576
    for p in (source, executable):
        size = p.stat().st_size
        if size > limit:
            raise SystemExit(f'{p}: {size} bytes exceeds {limit}')
        print(f'{p}: {size} bytes')
    manifest = json.loads((Path(__file__).resolve().parents[1] / 'docs/current_release.json').read_text())
    actual = hashlib.sha256(source.read_bytes()).hexdigest()
    if actual != manifest['source_sha256']:
        raise SystemExit('Source differs from current_release.json; review and update the release record.')
    print('Source SHA256 matches the recorded online release.')


if __name__ == '__main__':
    main()
