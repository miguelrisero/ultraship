#!/usr/bin/env bash
# Read lock occupancy without taking a lock or changing its file.
set -euo pipefail

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  printf 'usage: lock-idle.sh <lock-file>\n' >&2
  exit 2
fi

exec python3 - "$1" <<'PY'
import os
from pathlib import Path
import re
import sys

path = sys.argv[1]
try:
    info = os.stat(path)
except FileNotFoundError:
    print(f'lock file missing: {path}; holders=0 waiters=0')
    sys.exit(0)
except OSError as exc:
    print(f'cannot inspect lock file: {exc}', file=sys.stderr)
    sys.exit(2)

identity = (os.major(info.st_dev), os.minor(info.st_dev), info.st_ino)
holders = waiters = 0
try:
    with Path('/proc/locks').open() as locks:
        for line in locks:
            fields = line.split()
            for field in fields:
                if re.fullmatch(r'[0-9a-fA-F]+:[0-9a-fA-F]+:[0-9]+', field):
                    major, minor, inode = field.split(':')
                    if (int(major, 16), int(minor, 16), int(inode)) == identity:
                        if '->' in fields:
                            waiters += 1
                        else:
                            holders += 1
                    break
except OSError as exc:
    print(f'cannot read /proc/locks: {exc}', file=sys.stderr)
    sys.exit(2)

print(f'holders={holders} waiters={waiters}: {path}')
sys.exit(1 if holders or waiters else 0)
PY
