#!/usr/bin/env python3
"""Ship run ledger: one branch TSV in the resolved ledger home.

Row: epoch<TAB>step<TAB>agent<TAB>sha<TAB>verdict<TAB>note
"""
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REQUIRED = {
    'full': ['plan', 'slices', 'panel-high', 'simplify', 'deep-review', 'select',
             'fix-read', 'panel-final', 'pr', 'babysit', 'closing', 'gate'],
    'light': ['slices', 'simplify', 'deep-review', 'fix-read', 'pr', 'babysit', 'gate'],
}
USAGE = """usage: ledger.py path | status | gaps | run-end
       ledger.py run-start <full|light> <run-id> [board-path]
       ledger.py append <step> <agent> <sha> <verdict> [note]"""


def git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def contained(path, workspace):
    resolved = path.resolve()
    if resolved != path or not resolved.is_relative_to(workspace):
        raise ValueError(f'Ledger path escapes workspace or uses a symlink: {path}; set SHIP_LEDGER_DIR to an absolute permitted directory')
    return resolved


def import_legacy(path, legacy):
    """Publish a byte-exact snapshot once; the local TSV is the commit marker."""
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            path.stat()
        except FileNotFoundError:
            pass
        else:
            path.with_suffix('.import.json').stat()
            return
        if path.with_suffix('.import.json').exists():
            raise ValueError(f'Local ledger missing after import: {path}; restore the local snapshot before continuing')
        source = legacy.resolve()
        try:
            legacy.lstat()
        except FileNotFoundError:
            data = b''
            provenance = {'legacy_path': str(source), 'sha256': None}
        else:
            data = source.read_bytes()
            for row in data.decode('utf-8').splitlines():
                if not row:
                    continue
                fields = row.split('\t')
                if (len(fields) != 6 or not fields[0].isascii() or not fields[0].isdigit() or
                        not fields[1] or not fields[4] or
                        (fields[1] == 'run-start' and fields[2] not in REQUIRED)):
                    raise ValueError(f'Malformed legacy ledger: {source}')
            provenance = {'legacy_path': str(source), 'sha256': hashlib.sha256(data).hexdigest()}
        # ponytail: old legacy writers can race this read. The sole driver must
        # hold run custody and retire old writers before import; no cross-home lock.
        for target, content in ((path.with_suffix('.import.json'),
                                 (json.dumps(provenance) + '\n').encode()), (path, data)):
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=target.name + '.',
                                             delete=False) as pending:
                pending.write(content)
                pending.flush()
                os.fsync(pending.fileno())
            os.replace(pending.name, target)


def ledger_path(cwd='.'):
    override = os.environ.get('SHIP_LEDGER_DIR')
    if override is not None and not Path(override).is_absolute():
        raise ValueError('SHIP_LEDGER_DIR must be an absolute path')
    branch = git(cwd, 'rev-parse', '--abbrev-ref', 'HEAD').replace('/', '__')
    if override is not None:
        return Path(override) / f'{branch}.tsv'
    root = Path(git(cwd, 'rev-parse', '--show-toplevel')).resolve()
    common = Path(cwd, git(cwd, 'rev-parse', '--git-common-dir')).resolve()
    legacy = common / 'ship' / 'ledger' / f'{branch}.tsv'
    if common.is_relative_to(root):
        return contained(legacy, root)
    workspace = root.parent
    scratch = contained(workspace / '.scratch', workspace)
    if not scratch.is_dir() or scratch.is_relative_to(root):
        raise ValueError('Cannot identify a workspace scratch directory; set SHIP_LEDGER_DIR to an absolute permitted directory')
    if common.is_relative_to(workspace):
        return contained(legacy, workspace)
    identity = hashlib.sha256(str(root).encode()).hexdigest()
    directory = contained(scratch / 'ship-ledgers' / identity, scratch)
    if directory.is_relative_to(root):
        raise ValueError('Ledger directory enters checkout; set SHIP_LEDGER_DIR to an absolute permitted directory')
    directory.mkdir(parents=True, exist_ok=True)
    path = contained(directory / f'{branch}.tsv', directory)
    for suffix in ('.lock', '.import.json'):
        contained(path.with_suffix(suffix), directory)
    import_legacy(path, legacy)
    return path


def rows(path):
    if not path.exists():
        return []
    return [line.split('\t') for line in path.read_text().splitlines() if line]


def open_run(path):
    """Return (start_row, rows_after_start) for the open run, or None."""
    all_rows = rows(path)
    for i in range(len(all_rows) - 1, -1, -1):
        step = all_rows[i][1]
        if step == 'run-end':
            return None
        if step == 'run-start':
            return all_rows[i], all_rows[i + 1:]
    return None


def gaps(run):
    start, after = run
    done = {r[1] for r in after if r[4] != 'owed'}
    return [s for s in REQUIRED[start[2]] if s not in done]


def append(path, *fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = [f.replace('\t', ' ').replace('\n', ' ') for f in fields]
    with path.open('a+b') as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0, os.SEEK_END)
        if fh.tell():
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b'\n':
                fh.write(b'\n')
        fh.write(('\t'.join([str(int(time.time())), *clean]) + '\n').encode('utf-8'))


def main(argv):
    if not argv:
        sys.exit(USAGE)
    cmd, args = argv[0], argv[1:]
    path = ledger_path()
    run = open_run(path)
    if cmd == 'path':
        print(path)
    elif cmd == 'run-start':
        if len(args) not in (2, 3) or args[0] not in REQUIRED:
            sys.exit(USAGE)
        if run:
            sys.exit(f'run {run[0][5]} is still open; finish it with run-end first')
        append(path, 'run-start', args[0], git('.', 'rev-parse', 'HEAD'), 'open', ' '.join(args[1:]))
        print(path)
    elif cmd == 'append':
        if len(args) not in (4, 5):
            sys.exit(USAGE)
        if not run:
            sys.exit('no open run; start one with run-start')
        append(path, *args, *([''] * (5 - len(args))))
    elif cmd in ('gaps', 'status'):
        if not run:
            print('no open run')
            return
        missing = gaps(run)
        if cmd == 'status':
            print(f'run: {run[0][5]} mode={run[0][2]} ledger={path}')
            for r in run[1]:
                print('  ' + ' '.join(r[1:5]) + (f' — {r[5]}' if len(r) > 5 and r[5] else ''))
        print('gaps: ' + (' '.join(missing) or 'none'))
        if cmd == 'gaps' and missing:
            sys.exit(1)
    elif cmd == 'run-end':
        if not run:
            sys.exit('no open run')
        missing = gaps(run)
        if missing:
            sys.exit('refusing run-end; gaps: ' + ' '.join(missing))
        append(path, 'run-end', '', git('.', 'rev-parse', 'HEAD'), 'closed', run[0][5])
    else:
        sys.exit(USAGE)


if __name__ == '__main__':
    main(sys.argv[1:])
