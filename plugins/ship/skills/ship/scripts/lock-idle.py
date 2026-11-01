#!/usr/bin/env python3
"""Inspect Linux lock records without acquiring locks or changing files."""
import os
from pathlib import Path
import re
import sys


def lock_record(line, inode, fd_pid=None):
    fields = line.removeprefix('lock:').split()
    for index, field in enumerate(fields):
        if not re.fullmatch(r'[0-9a-fA-F]+:[0-9a-fA-F]+:[0-9]+', field):
            continue
        _, _, found_inode = field.split(':')
        # Inode-only matching fails closed when btrfs reports another device.
        if int(found_inode) != inode:
            return None
        if index < 4 or len(fields) < index + 3:
            return None
        owner = fields[index - 1]
        waiter = '->' in fields
        # fdinfo repeats records across descriptors; ignore record IDs and devices.
        key = (waiter, *fields[index - 4:index], inode, *fields[index + 1:])
        return key, str(fd_pid) if fd_pid is not None else owner
    return None


def lock_records(info, proc=Path('/proc')):
    records = {}

    def collect(text, fd_pid=None):
        for line in text.splitlines():
            if fd_pid is not None and not line.startswith('lock:'):
                continue
            record = lock_record(line, info.st_ino, fd_pid)
            if record:
                key, pid = record
                records.setdefault(key, set()).add(pid)

    collect((proc / 'locks').read_text())
    for fdinfo in proc.glob('[0-9]*/fdinfo/*'):
        try:
            collect(fdinfo.read_text(), fdinfo.parent.parent.name)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            # Linux hides other users' descriptors; inspect every accessible record.
            continue
    return records


def main(args):
    if len(args) != 1 or not args[0]:
        print('usage: lock-idle.py <lock-file>', file=sys.stderr)
        return 2
    path = args[0]
    try:
        info = os.stat(path)
    except FileNotFoundError:
        print(f'lock file missing: {path}; holders=0 waiters=0')
        return 0
    except OSError as exc:
        print(f'cannot inspect lock file: {exc}', file=sys.stderr)
        return 2
    try:
        records = lock_records(info)
    except OSError as exc:
        print(f'cannot inspect Linux locks: {exc}', file=sys.stderr)
        return 2
    waiters = sum(key[0] for key in records)
    print(f'holders={len(records) - waiters} waiters={waiters}: {path}')
    for key, pids in records.items():
        for pid in sorted(pids):
            print(f'{"waiter" if key[0] else "holder"} pid={pid}')
    return 1 if records else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
