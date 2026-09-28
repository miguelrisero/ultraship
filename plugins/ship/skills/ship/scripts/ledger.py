#!/usr/bin/env python3
"""Ship run ledger: one TSV per branch under the repository's common Git dir.

Row: epoch<TAB>step<TAB>agent<TAB>sha<TAB>verdict<TAB>note
"""
import subprocess
import sys
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


def ledger_path(cwd='.'):
    common = Path(cwd, git(cwd, 'rev-parse', '--git-common-dir')).resolve()
    branch = git(cwd, 'rev-parse', '--abbrev-ref', 'HEAD').replace('/', '__')
    return common / 'ship' / 'ledger' / f'{branch}.tsv'


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
    with path.open('a') as fh:
        fh.write('\t'.join([str(int(time.time())), *clean]) + '\n')


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
