#!/usr/bin/env python3
"""Ship run ledger: one branch TSV in the resolved ledger home.

Row: epoch<TAB>step<TAB>agent<TAB>sha<TAB>verdict<TAB>note
A reviewer row names its agent as <agent-type>@<agent-id>; a result binds only to rows with its own agent ID.
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
       ledger.py append <step> <agent>[@<agent-id>] <sha> <verdict> [note]
       ledger.py account <pending.tsv> <result-id> <step> <agent> <sha> <verdict> <evidence>
       ledger.py correct-binding <result-id> <ledger-line> <reason>"""
STATE = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'ultraship'
MARKS = ('run-start', 'run-end', 'account-result', 'correct-binding')


def agent_key(field):
    """Split an agent column `<agent-type>[@<agent-id>]` into (type, ID or None)."""
    kind, _, ident = field.partition('@')
    return kind, ident or None


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



def run_identity(index, row):
    return [index, hashlib.sha256(json.dumps(row).encode()).hexdigest()]


def accounting_row(row, result_id, run):
    """An explicit accounting row binds one pending result to its original run, even after run-end."""
    if row[1] != 'account-result':
        return False
    value = json.loads(row[5])
    return value['result'] == result_id and value['run'] == run


def account(pending, identifier, step, agent, sha, verdict, evidence):
    """Append bookkeeping for a completed result; preserve the bound run's historical rows and closure."""
    if (not all((step, agent, sha, verdict, evidence.strip())) or verdict == 'owed'
            or any('\t' in f or '\n' in f or '\r' in f for f in (step, agent, sha, verdict))):
        raise ValueError('completed result needs single-line step, agent, sha, verdict and evidence')
    pending = Path(pending).absolute()  # Keep the hook's path spelling, including a symlinked XDG_STATE_HOME.
    matches = []
    for line in pending.read_text().splitlines():
        fields = line.split('\t')
        if len(fields) == 4 and json.loads(fields[3]).get('id') == identifier:
            matches.append(fields)
    if len(matches) != 1:
        raise ValueError('pending result ID must match exactly one notification')
    epoch, expected_agent, cwd, raw = matches[0]
    result = json.loads(raw)
    kind, ident = agent_key(agent)
    if (kind != expected_agent or ident not in (None, result.get('agent_id'))
            or not result.get('run') or not result.get('ledger')):
        raise ValueError('pending result needs its recorded agent, ledger and run')
    home = Path(result['ledger'])
    if not home.is_absolute() or home.resolve() != home:
        raise ValueError('recorded ledger must be an absolute path without symlinks')
    result_id = json.dumps([str(pending), cwd, identifier])
    note = {'result': result_id, 'run': result['run'], 'step': step, 'evidence': evidence}
    row = ['account-result', agent, sha, verdict, json.dumps(note)]
    with home.open('r+b') as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        history = [line.split('\t') for line in fh.read().decode().splitlines() if line]
        starts = [i for i, r in enumerate(history) if r[1] == 'run-start' and run_identity(i, r) == result['run']]
        if len(starts) != 1 or int(epoch) < int(history[starts[0]][0]):
            raise ValueError('recorded run is missing or differs')
        for saved in history:
            if accounting_row(saved, result_id, result['run']):
                if saved[1:] != row:
                    raise ValueError('result already has a different accounting record')
                return home
        fh.seek(0, os.SEEK_END)
        if fh.tell():
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b'\n':
                fh.write(b'\n')
        fh.write(('\t'.join([str(int(time.time())), *row]) + '\n').encode())
        fh.flush()
        os.fsync(fh.fileno())
    return home


def publish(path, value):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix=path.name + '.', delete=False) as saved:
        json.dump(value, saved)
        saved.flush()
        os.fsync(saved.fileno())
    os.replace(saved.name, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def correct_binding(identifier, line, reason):
    """Move one accounted result to another review row of its bound run.

    The audit row is appended before the hook-state receipts change; the ledger is never rewritten.
    A target row already credited to another result swaps credit with it."""
    if not reason.strip() or '\t' in reason or '\n' in reason:
        raise ValueError('correction needs a single-line reason')
    receipt_path = STATE / 'accounted.json'
    with (STATE / 'accounted.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        receipts = json.loads(receipt_path.read_text())
        keys = [k for k in receipts if json.loads(k)[2] == identifier]
        if len(keys) != 1:
            raise ValueError('result ID must match exactly one accounted result')
        key = keys[0]
        saved = receipts[key]
        home, run, old = Path(saved[0]), saved[1], saved[2]
        with home.open('r+b') as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            text = fh.read().decode()
            history = [r.split('\t') for r in text.splitlines() if r]
            if text.rstrip('\n').split('\n') != text.splitlines() or '' in text.splitlines():
                raise ValueError('ledger lines differ from its rows; name the row by hand-checked evidence instead')
            starts = [i for i, r in enumerate(history) if r[1] == 'run-start']
            start = [i for i in starts if run_identity(i, history[i]) == run]
            if len(start) != 1 or not 0 <= old[0] < len(history) or run_identity(old[0], history[old[0]]) != old:
                raise ValueError('bound run or row is missing or differs; restore the ledger evidence')
            start = start[0]
            end = next((i for i in starts if i > start), len(history))
            end = next((i for i in range(start + 1, end) if history[i][1] == 'run-end'), end)
            index = int(line) - 1 if line.isdigit() else -1

            def review(i):
                return start < i < end and history[i][1] not in MARKS and history[i][4] != 'owed'

            def fits(i, receipt):
                # A bound row names its result's agent ID, because Stop binds only on a matching ID.
                return agent_key(history[i][2]) == agent_key(history[receipt[2][0]][2])
            if not review(index) or not fits(index, saved):
                raise ValueError("target line must be a completed review row of this result's run and agent")
            new = run_identity(index, history[index])
            if new == old:
                return home
            other = next((k for k, v in receipts.items() if v[0] == saved[0] and v[2] == new), None)
            if other and (receipts[other][1] != run or not review(old[0])):
                raise ValueError('target row is credited to another result that cannot take the current row')
            note = {'result': key, 'agent': history[index][2], 'from': old, 'to': new, 'swap': other, 'reason': reason}
            # The '-' agent keeps older hooks from taking the audit row as a review.
            row = [str(int(time.time())), 'correct-binding', '-', history[index][3], 'corrected', json.dumps(note)]
            last = [json.loads(r[5]) for r in history if r[1] == 'correct-binding' and json.loads(r[5])['result'] == key]
            # A matching last audit row means a crash came before publish: publish only.
            if not last or [last[-1][k] for k in ('from', 'to', 'swap')] != [old, new, other]:
                fh.seek(0, os.SEEK_END)
                if fh.tell():
                    fh.seek(-1, os.SEEK_END)
                    if fh.read(1) != b'\n':
                        fh.write(b'\n')
                fh.write(('\t'.join(row) + '\n').encode())
                fh.flush()
                os.fsync(fh.fileno())
        if other:
            receipts[other] = [*receipts[other][:2], old]
        receipts[key] = [*saved[:2], new]
        publish(receipt_path, receipts)
    return home


def main(argv):
    if not argv:
        sys.exit(USAGE)
    cmd, args = argv[0], argv[1:]
    if cmd == 'account':
        if len(args) != 7:
            sys.exit(USAGE)
        print(account(*args))
        return
    if cmd == 'correct-binding':
        if len(args) != 3:
            sys.exit(USAGE)
        print(correct_binding(*args))
        return
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
        if args[0] in MARKS:
            sys.exit(f'{args[0]} rows come only from their own command')
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
