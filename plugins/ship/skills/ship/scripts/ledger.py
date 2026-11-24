#!/usr/bin/env python3
"""Ship run ledger: one branch TSV in the resolved ledger home.

Row: epoch<TAB>step<TAB>agent<TAB>sha<TAB>verdict<TAB>note
A reviewer row names its agent as <agent-type>@<agent-id>; a result binds only to rows with its own agent ID.
"""
import errno
import fcntl
import hashlib
import json
import os
import pwd
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
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
       ledger.py account-auto [--fail-unparsed | --retire-merged | --close-unparsed] <pending.tsv>
       ledger.py correct-binding <pending.tsv> <result-id> <ledger-line> <reason>"""
MARKS = ('run-start', 'run-end', 'account-result', 'correct-binding')
ACCOUNT_COMMANDS = ('account', 'account-auto', 'correct-binding')
AUTO_FLAGS = ('--fail-unparsed', '--retire-merged', '--close-unparsed')
GRANT_LIFETIME_NS = 900_000_000_000
GRANT_REFUSAL = 'Accounting requires a fresh grant from the ship hook. Run the exact command again.'
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


def account_pending_arg(argv):
    if not argv:
        return None
    cmd, args = argv[0], argv[1:]
    if cmd == 'account-auto':
        if len(args) == 2 and args[0] in AUTO_FLAGS:
            return args[1]
        if len(args) == 1:
            return args[0]
    if (cmd, len(args)) in (('account', 7), ('correct-binding', 4)):
        return args[0]
    return None


def grant_store():
    return Path(pwd.getpwuid(os.geteuid()).pw_dir) / '.local/state/ultraship/account-grants'


@contextmanager
def directory_descriptor(path, *, create_tail=0):
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError(GRANT_REFUSAL)
    fd = os.open(path.anchor, DIRECTORY_FLAGS)
    try:
        for index, part in enumerate(path.parts[1:], 1):
            if index >= len(path.parts) - create_tail:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, DIRECTORY_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        try:
            os.close(fd)
        except OSError:
            if not create_tail:
                raise


@contextmanager
def locked_grant_store(*, create=False):
    with directory_descriptor(grant_store(), create_tail=4 if create else 0) as fd:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError(GRANT_REFUSAL)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield fd


def grant_digest(items):
    return hashlib.sha256(json.dumps(items).encode()).hexdigest()


def file_identity(info):
    return [info.st_dev, info.st_ino]


def grant_request(script, argv):
    owed = account_pending_arg(argv)
    if not owed:
        raise ValueError(GRANT_REFUSAL)
    pending = Path(owed)
    if (str(pending) != owed or not pending.is_absolute() or '..' in pending.parts
            or pending.parent.name != 'owed' or pending.suffix != '.tsv'):
        raise ValueError(GRANT_REFUSAL)
    canonical_script = str(Path(script).resolve(strict=True))
    if canonical_script != str(Path(__file__).resolve(strict=True)):
        raise ValueError(GRANT_REFUSAL)
    name = grant_digest([canonical_script, owed]) + '.json'
    fields = {'script': canonical_script, 'pending': owed, 'command': argv[0],
              'argv_sha256': grant_digest([script, *argv])}
    return name, fields, pending


def grant_bytes(record):
    return json.dumps(record, sort_keys=True).encode()


def read_grant(fd, name):
    with os.fdopen(os.open(name, READ_FLAGS, dir_fd=fd), 'rb') as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise ValueError(GRANT_REFUSAL)
        raw = source.read()
    record = json.loads(raw)
    strings = ('script', 'pending', 'command', 'argv_sha256', 'session', 'root')
    identities = ('root_id', 'owed_id')
    if (not isinstance(record, dict) or set(record) != {*strings, *identities, 'issued_ns'}
            or any(type(record[key]) is not str or not record[key] for key in strings)
            or any(not isinstance(record[key], list) or len(record[key]) != 2
                   or any(type(value) is not int or value < 0 for value in record[key]) for key in identities)
            or type(record['issued_ns']) is not int or record['issued_ns'] <= 0
            or grant_bytes(record) != raw):
        raise ValueError(GRANT_REFUSAL)
    return record


@contextmanager
def evidence_root(root):
    if not root.is_absolute() or root.resolve(strict=True) != root:
        raise ValueError(GRANT_REFUSAL)
    with directory_descriptor(root) as fd:
        yield fd


def owed_status(fd, name):
    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Accounting refuses a symlinked or nonregular owed file.')
    return info


def _issue_grant(script, argv, state, session):
    name, fields, pending = grant_request(script, argv)
    if (str(state / 'owed' / (re.sub(r'[^\w.-]', '_', session) + '.tsv')) != str(pending)
            or not session):
        raise ValueError(GRANT_REFUSAL)
    root = state.parent.resolve(strict=True) / state.name
    with evidence_root(root) as evidence_fd:
        owed_fd = os.open('owed', DIRECTORY_FLAGS, dir_fd=evidence_fd)
        try:
            fields.update(session=session, root=str(root), root_id=file_identity(os.fstat(evidence_fd)),
                          owed_id=file_identity(owed_status(owed_fd, pending.name)))
        finally:
            os.close(owed_fd)
    with locked_grant_store(create=True) as fd:
        try:
            saved = read_grant(fd, name)
        except FileNotFoundError:
            pass
        else:
            age = time.time_ns() - saved.pop('issued_ns')
            if age < GRANT_LIFETIME_NS:
                # An identical retry reuses the live grant; its issue time stays, so the window never extends.
                if 0 <= age and saved == json.loads(grant_bytes(fields)):
                    return
                raise ValueError(GRANT_REFUSAL)
        publish_at(fd, name, grant_bytes(dict(fields, issued_ns=time.time_ns())), sync_directory=False)


def publish_at(fd, name, content, *, sync_directory=True):
    temp = '.' + name + '-' + secrets.token_hex(16)
    temp_fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=fd)
    try:
        with os.fdopen(temp_fd, 'wb') as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
    except BaseException:
        os.unlink(temp, dir_fd=fd)
        raise
    if sync_directory:
        os.fsync(fd)


@contextmanager
def consume_grant(script, argv):
    with ExitStack() as evidence:
        try:
            name, fields, pending = grant_request(script, argv)
            with locked_grant_store() as fd:
                record = read_grant(fd, name)
                if (any(record[key] != value for key, value in fields.items())
                        or re.sub(r'[^\w.-]', '_', record['session']) + '.tsv' != pending.name
                        or not 0 <= time.time_ns() - record['issued_ns'] < GRANT_LIFETIME_NS):
                    raise ValueError(GRANT_REFUSAL)
                pending, root, root_fd, owed_fd, source = evidence.enter_context(open_owed(record))
                if not 0 <= time.time_ns() - record['issued_ns'] < GRANT_LIFETIME_NS:
                    raise ValueError(GRANT_REFUSAL)
                os.unlink(name, dir_fd=fd)
                os.fsync(fd)
        except OwedSymlink:
            raise ValueError('Accounting refuses a symlinked owed file.') from None
        except (OSError, KeyError, ValueError, RuntimeError):
            raise ValueError(GRANT_REFUSAL) from None
        fcntl.flock(source, fcntl.LOCK_EX)
        if file_identity(owed_status(owed_fd, pending.name)) != record['owed_id']:
            raise ValueError('Accounting owed file changed. Run the exact command again.')
        yield pending, root, root_fd, source


class OwedSymlink(ValueError):
    pass


@contextmanager
def open_owed(record):
    pending = Path(record['pending'])
    root = Path(record['root'])
    with evidence_root(root) as root_fd:
        if (file_identity(os.fstat(root_fd)) != record['root_id']
                or pending.parent.parent.resolve(strict=True) != root):
            raise ValueError('Accounting evidence directory changed. Run the exact command again.')
        owed_fd = os.open('owed', DIRECTORY_FLAGS, dir_fd=root_fd)
        try:
            try:
                source_fd = os.open(pending.name, READ_FLAGS, dir_fd=owed_fd)
            except OSError as exc:
                if exc.errno == errno.ELOOP:
                    raise OwedSymlink from None
                raise
            with os.fdopen(source_fd) as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or file_identity(info) != record['owed_id']:
                    raise ValueError('Accounting owed file changed. Run the exact command again.')
                yield pending, root, root_fd, owed_fd, source
        finally:
            os.close(owed_fd)


@contextmanager
def locked_receipts(root_fd):
    fd = os.open('accounted.lock', os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                 0o600, dir_fd=root_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('Accounting receipt lock must be a regular file.')
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


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
    managed = None
    for parent in root.parents:
        if parent.name == '.scratch':
            break
        if parent.parent.name == '.bettercoding-workspaces':
            managed = parent
            break
    workspace = managed or root.parent
    scratch = contained(workspace / '.scratch', workspace)
    if workspace.name == '.bettercoding-workspaces' or scratch.is_relative_to(root):
        raise ValueError('Cannot identify a workspace scratch directory; set SHIP_LEDGER_DIR to an absolute permitted directory')
    identity = hashlib.sha256(str(root).encode()).hexdigest()

    def local_path(folder):
        directory = contained(folder / 'ship-ledgers' / identity, folder)
        path = contained(directory / f'{branch}.tsv', directory)
        for suffix in ('.lock', '.import.json'):
            contained(path.with_suffix(suffix), directory)
        return path

    path = local_path(scratch)
    candidates = [path]
    parent_uses_common = False
    if workspace != root.parent:
        parent_scratch = contained(root.parent / '.scratch', root.parent)
        if parent_scratch.is_dir() and not parent_scratch.is_relative_to(root):
            if common.is_relative_to(root.parent):
                parent_uses_common = True
            else:
                candidates.append(local_path(parent_scratch))
    existing = [candidate for candidate in candidates
                if candidate.exists() or candidate.with_suffix('.import.json').exists()]
    if len(existing) > 1:
        raise ValueError('Multiple workspace ledger homes contain evidence; set SHIP_LEDGER_DIR to an absolute permitted directory')
    if existing:
        path = existing[0]
    elif parent_uses_common:
        return contained(legacy, root.parent)
    elif not scratch.is_dir():
        raise ValueError('Cannot identify a workspace scratch directory; set SHIP_LEDGER_DIR to an absolute permitted directory')
    elif common.is_relative_to(workspace):
        return contained(legacy, workspace)
    # New imports share one home even if the immediate parent gains a scratch directory.
    path.parent.mkdir(parents=True, exist_ok=True)
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


def account(pending, identifier, step, agent, sha, verdict, evidence, *, entries):
    """Append bookkeeping for a completed result; preserve the bound run's historical rows and closure."""
    if (not all((step, agent, sha, verdict, evidence.strip())) or verdict == 'owed'
            or any('\t' in f or '\n' in f or '\r' in f for f in (step, agent, sha, verdict))):
        raise ValueError('completed result needs single-line step, agent, sha, verdict and evidence')
    matches = []
    for line in entries:
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
    named = f'{kind}@{result["agent_id"]}' if result.get('agent_id') else kind
    row = ['account-result', named, sha, verdict, json.dumps(note)]
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


TRANSCRIPT_SCAN_LIMIT = 64 * 1024 * 1024
TRANSCRIPT_CHUNK = 64 * 1024


class TranscriptLimit(Exception):
    pass


def reverse_lines(fh, budget):
    position = fh.seek(0, os.SEEK_END)
    fragments = []
    while position:
        size = min(position, TRANSCRIPT_CHUNK, budget[0])
        if not size:
            raise TranscriptLimit
        position -= size
        fh.seek(position)
        data = fh.read(size)
        budget[0] -= size
        if len(data) != size:
            raise OSError('transcript read incomplete')
        first, *lines = data.split(b'\n')
        if not lines:
            fragments.append(first)
            continue
        yield b''.join([lines.pop(), *reversed(fragments)])
        yield from reversed(lines)
        fragments = [first]
    yield b''.join(reversed(fragments))


def final_turn_text(path, epoch, budgets):
    texts = []
    after_tool = True
    newest = float('inf')
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW), 'rb', buffering=0) as fh:
            info = os.fstat(fh.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise OSError('transcript must be a regular file')
            budget = budgets.setdefault((info.st_dev, info.st_ino), [TRANSCRIPT_SCAN_LIMIT])
            for line in reverse_lines(fh, budget):
                if not line.strip():
                    continue
                entry = json.loads(line)
                role = entry['type']
                if role not in ('user', 'assistant'):
                    continue
                stamp = datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00'))
                if stamp.tzinfo is None:
                    raise TypeError('transcript timestamp has no time zone')
                when = stamp.timestamp()
                if when > newest:
                    raise ValueError('transcript timestamps out of order')
                newest = when
                if when > epoch + 1:
                    continue
                content = entry['message']['content']
                if isinstance(content, str) and role == 'user':
                    content = [{'type': 'text', 'text': content}]
                if not isinstance(content, list):
                    raise TypeError('transcript content must have blocks')
                if role == 'user':
                    if any(block['type'] != 'tool_result' for block in content):
                        # A prompt in the grace second makes turn ownership ambiguous.
                        return '\n'.join(reversed(texts)).strip() if when <= epoch else ''
                elif any(block['type'] in ('tool_use', 'server_tool_use') for block in content):
                    after_tool = False
                elif after_tool:
                    texts.extend(block['text'] for block in reversed(content) if block['type'] == 'text')
    except TranscriptLimit:
        raise ValueError('transcript scan limit reached') from None
    except FileNotFoundError:
        raise ValueError('no transcript') from None
    except OSError:
        raise ValueError('transcript unavailable') from None
    except (AttributeError, KeyError, TypeError, OverflowError, RecursionError, ValueError):
        raise ValueError('transcript parse error') from None
    return ''


def load_receipts(path, *, root_fd=None):
    try:
        if root_fd is None:
            return json.loads(path.read_text())
        with os.fdopen(os.open(path.name, READ_FLAGS, dir_fd=root_fd)) as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError('Accounting receipts must be in a regular file.')
            return json.load(source)
    except FileNotFoundError:
        return {}


COMMIT = r'(?<![0-9a-fA-F])([0-9a-fA-F]{40})(?![0-9a-fA-F])'
# A frozen label is the word, up to three subject words, then the SHA on the same line: "Frozen commit: `<sha>`".
# "Frozen base" labels no subject.
FROZEN_COMMIT = re.compile(
    r'(?<!\w)frozen(?:[ _]+(?:final|review|reviewed|subject|head|commit|sha|snapshot)){0,3}[ \t:|`*=_-]*' + COMMIT,
    re.I)
# A negation before the SHA on the label's line, as in "Not **frozen commit:**", labels no subject.
NEGATION = re.compile(r"\b(?:not|non|never)\b|n['’]t\b", re.I)
VERDICT_LABEL = re.compile(r'^[\s*>#_-]*(?:verdict|overall)[*_]*:(.*)', re.I)
VERDICT_WORD = r'(?:pass|fail(?:ed|s|ing|ure)?|findings|blocked)\b'
# A bare verdict line starts at the margin with a verdict word, then the line end, a dash or "(":
# "**FAIL** — two findings".
BARE_VERDICT = re.compile(r'^[*#_`]*(' + VERDICT_WORD + r'[*_`]*(?:\s*$|\s*[—–(]|\s+-\s).*)', re.I)
# A closing paragraph with a list item, a quote or a second verdict-led line holds no bare verdict.
VERDICT_RIVAL = re.compile(r'^\s*(?:>|(?:[-*+]|\d+[.)])\s)|^[\W\d_]*' + VERDICT_WORD, re.I)
VERDICT_WORDS = {'pass', 'fail', 'failed', 'fails', 'failing', 'failure', 'findings'}
MERGE_GIT_SECONDS = 60


def prose(text):
    """Return `text` with every line of fenced code emptied, so an example states no label and no verdict."""
    lines, fence = [], ''
    for line in text.split('\n'):
        marker = re.match(r' {0,3}(`{3,}|~{3,})', line)
        if marker and not fence:
            fence, line = marker[1], ''
        elif marker and marker[1].startswith(fence) and line.strip() == marker[1]:
            # Only a fence of the same character and at least the opening length closes the block.
            fence, line = '', ''
        lines.append('' if fence else line)
    return '\n'.join(lines)


def own_lines(text):
    """Return the lines that the reviewer states: no fenced code, no paragraph with a quote, no indented code."""
    lines = []
    for paragraph in re.split(r'\n[ \t]*\n', prose(text)):
        rows = paragraph.split('\n')
        # A line after a quoted line continues the quote, so the whole paragraph is the quote.
        if not any(row.lstrip().startswith('>') for row in rows):
            lines += [row for row in rows if not row.startswith(('    ', '\t'))]
    return lines


def frozen_commits(text):
    """Return the commits that a frozen label names in the reviewer's own lines."""
    commits = set()
    for line in own_lines(text):
        # Emphasis markers become spaces, so `_not_` reads as a word and each position stays.
        negation = NEGATION.search(re.sub(r'[*_`~]', ' ', line))
        for match in FROZEN_COMMIT.finditer(line):
            if not negation or negation.start() > match.start(1):
                commits.add(match[1].lower())
    return commits


def subject_commit(text):
    """Return the one commit a review names, or among several the one it labels frozen."""
    commits = {match[1].lower() for match in re.finditer(COMMIT, text)}
    if len(commits) > 1:
        commits = frozen_commits(text)
    elif not re.search(COMMIT, prose(text)):
        # A lone commit in fenced code is an example, so it names no subject.
        commits = set()
    if len(commits) != 1:
        raise ValueError('expected one commit')
    return commits.pop()


def final_verdict(text):
    """Return the verdict of the one verdict line: the only label line, or the single line that ends the review."""
    fenced = sum(1 for line in text.splitlines() if VERDICT_LABEL.match(line))
    text = prose(text)
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError('expected one verdict')
    labels = [match[1] for line in lines if (match := VERDICT_LABEL.match(line))]
    bare = not labels
    if len(labels) == 1 and fenced > 1 and not any(VERDICT_LABEL.match(line) for line in own_lines(text)):
        # Beside a fenced label, a quoted or indented label is one more example.
        raise ValueError('expected one verdict')
    if len(labels) != 1:
        # Label lines above the closing paragraph are earlier rounds; a bare verdict counts only as the last line.
        # Between several labels only a last line that starts with the label at the margin decides: a list
        # item, an indented line or a closing paragraph with a quote repeats a check or another report.
        closing = re.split(r'\n\s*\n', text.strip())[-1].splitlines()
        last = (BARE_VERDICT if bare else VERDICT_LABEL).match(lines[-1])
        rivals = sum(1 for line in closing if (VERDICT_RIVAL if bare else VERDICT_LABEL).match(line))
        # A bare verdict line above the closing paragraph is a second candidate.
        if (not last or rivals != 1 or not re.match(r'[*#_`]*[a-z]', lines[-1], re.I)
                or bare and sum(1 for line in lines if BARE_VERDICT.match(line)) != 1
                or any(line.lstrip().startswith('>') for line in closing)):
            raise ValueError('expected one verdict')
        labels = [last[1]]
    words = [word for token in re.findall(r"\w+(?:['’]\w+)*", labels[0].lower()) if (word := token.strip('_'))]
    if not words or words[0] not in VERDICT_WORDS | {'blocked'}:
        raise ValueError('expected one verdict')
    # "Findings — none" is a heading with no finding, so it states no verdict.
    if bare and words[0] == 'findings' and any(word in ('none', 'no', 'zero', '0') for word in words[1:]):
        raise ValueError('expected one verdict')
    if 'pass' in words and (words[0] != 'pass' or any(
            word in VERDICT_WORDS or word in ('blocked', 'not', 'no', 'never', 'without')
            or word.endswith(("n't", 'n’t')) for word in words[1:])):
        raise ValueError('expected one verdict')
    return ('pass' if words[0] == 'pass' else 'blocked' if words[0] == 'blocked'
            else 'findings' if 'findings' in words else 'fail')


def merge_git(cwd, *args):
    """Run one bounded local Git read without inherited overrides, replacement objects, grafts or lazy fetch."""
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_NO_REPLACE_OBJECTS='1', GIT_NO_LAZY_FETCH='1', GIT_GRAFT_FILE=os.devnull)
    return subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True, check=True,
                          env=env, timeout=MERGE_GIT_SECONDS).stdout.removesuffix('\n')


def tracking_ref(cwd, name):
    """Return (commit, symbolic target) of the ref with this exact name; Git revision lookup also tries tags."""
    fields = '%(refname)%00%(objecttype)%00%(objectname)%00%(symref)'
    for line in merge_git(cwd, 'for-each-ref', '--format=' + fields, name).split('\n'):
        refname, kind, sha, target = (line.split('\0') + [''] * 3)[:4]
        if refname == name and kind == 'commit':
            return sha, target
    raise OSError('no such tracking ref')


def default_branch(cwd):
    """Return (ref, tip) of the plain `refs/remotes/origin/` branch that is the remote default."""
    # An absent or plain `origin/HEAD` names no default branch, so the read fails and proves nothing.
    ref = merge_git(cwd, 'symbolic-ref', '--no-recurse', '--quiet', 'refs/remotes/origin/HEAD')
    tip, target = tracking_ref(cwd, ref)
    if target or not ref.startswith('refs/remotes/origin/'):
        raise OSError('the remote default branch is no plain tracking branch')
    return ref, tip


def merged_proof(cwd, text, branches):
    """Return (sha, proof) when local Git shows the one commit the review labels frozen on the remote default branch.

    An unlabelled commit can be the base, which is on the default branch before any merge. A pull request URL is no
    proof: local Git holds no pull request record. A Git read that fails or is late proves nothing."""
    frozen = frozen_commits(text)
    if len(frozen) != 1:
        return None
    sha = frozen.pop()
    try:
        if cwd not in branches:
            branches[cwd] = default_branch(cwd)
        ref, tip = branches[cwd]
        # The name must be a commit itself; an annotated tag would peel to one.
        if merge_git(cwd, 'rev-parse', '--verify', '--quiet', sha + '^{commit}') != sha:
            return None
        merge_git(cwd, 'merge-base', '--is-ancestor', sha, tip)
    except (subprocess.SubprocessError, OSError, UnicodeError):
        return None
    return sha, f'commit {sha} is an ancestor of {ref} at {tip}'


def account_auto(pending, entries, receipts, *, flag=None):
    """Account for each clear result; a flag selects one disposition for a result that stays unclear."""
    unparsed = ('expected one commit', 'expected one verdict', 'transcript parse error')
    budgets, merges = {}, {}
    counts = dict.fromkeys(('accounted', 'retired', 'closed'), 0)
    remaining = already = awaiting = 0
    for fields in (line.split('\t') for line in entries if line):
        identifier = 'unknown'
        try:
            if len(fields) != 4:
                raise ValueError('no recorded transcript')
            epoch, agent, cwd, raw = fields
            result = json.loads(raw)
            identifier = result['id']
            key = json.dumps([str(pending), cwd, identifier])
            if result.get('v') == 2 and ('ledger' not in result or 'run' not in result) and key not in receipts:
                # This diagnostic is never a ledger row or a Stop receipt.
                agent_id = result.get('agent_id')
                print('orphaned ' + json.dumps({
                    'id': identifier, 'agent': f'{agent}@{agent_id}' if agent_id else agent, 'sha': '',
                    'transcript': result.get('agent_transcript_path'),
                    'reason': 'original ledger and run binding is missing',
                }))
                remaining += 1
                continue
            home = Path(result['ledger'])
            if not home.is_absolute() or home.resolve() != home:
                raise ValueError('recorded ledger must be an absolute path without symlinks')
            run = result['run']
            history = rows(home)
            starts = [i for i, r in enumerate(history) if r[1] == 'run-start' and run_identity(i, r) == run]
            if len(starts) != 1:
                raise ValueError('recorded run is missing or differs')
            if key in receipts:
                saved_home, saved_run, identity = receipts[key]
                if saved_home != result['ledger'] or saved_run != run:
                    raise ValueError('Stop receipt names a different ledger or run')
                index = identity[0]
                if not 0 <= index < len(history) or run_identity(index, history[index]) != identity:
                    raise ValueError('Stop receipt row is missing or differs')
                row = history[index]
                start = starts[0]
                end = next((i for i in range(start + 1, len(history))
                            if history[i][1] in ('run-start', 'run-end')), len(history))
                if not start < index < end and not accounting_row(row, key, run):
                    raise ValueError('Stop receipt row belongs to another run')
            else:
                row = next((r for r in history if accounting_row(r, key, run)), None)
            if row is not None:
                if len(row) < 5:
                    raise ValueError('accounting record is incomplete')
                if key in receipts:
                    already += 1
                else:
                    awaiting += 1
                continue
            else:
                source = result.get('agent_transcript_path')
                if not source:
                    raise ValueError('no transcript')
                path = Path(source)
                agent_id = result.get('agent_id')
                if (not isinstance(agent_id, str) or not agent_id or not path.is_absolute()
                        or path.name != f'agent-{agent_id}.jsonl' or path.parent.name != 'subagents'
                        or path.parent.parent.name != pending.stem):
                    raise ValueError('transcript path does not match the recorded agent and session')
                try:
                    canonical = source == str(path) == os.path.realpath(source)
                except (OSError, RuntimeError):
                    canonical = False
                if not canonical:
                    raise ValueError('transcript path does not match the recorded agent and session')
                epoch = int(epoch)
                when = datetime.fromtimestamp(epoch, timezone.utc).isoformat()
                step = 'review'
                try:
                    text = final_turn_text(path, epoch, budgets)
                    if not text:
                        raise ValueError('no final turn text')
                    sha = subject_commit(text)
                    verdict = final_verdict(text)
                except ValueError as exc:
                    reason = str(exc)
                    proof = (merged_proof(cwd, text, merges)
                             if flag in ('--retire-merged', '--close-unparsed') and reason in unparsed[:2] else None)
                    if proof:
                        # A retired row records the merge proof; it never states a review verdict.
                        step = verdict = 'retired'
                        sha, reason = proof[0], f'{reason}; merged: {proof[1]}'
                    elif flag == '--close-unparsed' and reason in unparsed:
                        # A closed row records that the result holds no review evidence: no commit, no verdict.
                        step, sha, verdict = 'closed', '-', 'no-evidence'
                        reason += '; closed without review evidence'
                    elif flag == '--fail-unparsed' and reason in unparsed:
                        sha, verdict = '0' * 40, 'fail'
                    else:
                        raise
                else:
                    reason = verdict
                account(pending, identifier, step, agent, sha, verdict, f'{source} at {when}: {reason}',
                        entries=entries)
                named = f'{agent}@{result["agent_id"]}' if result.get('agent_id') else agent
        except (json.JSONDecodeError, UnicodeError, OverflowError, RecursionError):
            reason = 'transcript or accounting parse error'
        except (OSError, KeyError, IndexError, TypeError):
            reason = 'accounting data missing or invalid'
        except ValueError as exc:
            reason = str(exc)
        else:
            if step in counts:
                print(f'{step} {identifier} {named} {sha} {reason}')
            else:
                print(f'accounted {identifier} {named} {sha} {verdict}')
            counts[step if step in counts else 'accounted'] += 1
            continue
        print(f'pending {identifier} {reason}')
        remaining += 1
    if counts['retired']:
        print(f"{counts['retired']} retired as merged")
    if counts['closed']:
        print(f"{counts['closed']} closed without review evidence")
    if awaiting:
        print(f'{awaiting} recorded and awaiting Stop')
    if already:
        print(f'{already} accounted at an earlier Stop')
    print(f"{counts['accounted']} accounted, {remaining} pending")


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


def correct_binding(pending, root, root_fd, identifier, line, reason):
    """Move one accounted result to another review row of its bound run.

    The audit row is appended before the hook-state receipts change; the ledger is never rewritten.
    A target row already credited to another result swaps credit with it."""
    if not reason.strip() or '\t' in reason or '\n' in reason:
        raise ValueError('correction needs a single-line reason')
    receipt_path = root / 'accounted.json'
    missing = ('result ID must match exactly one accounted result: this result has no Stop receipt. '
               'Account the retained result if needed, then run Stop to publish its receipt.')
    with locked_receipts(root_fd):
        receipts = load_receipts(receipt_path, root_fd=root_fd)
        keys = [k for k in receipts if json.loads(k)[2] == identifier]
        if not keys:
            raise ValueError(missing)
        if len(keys) != 1:
            raise ValueError('result ID must match exactly one accounted result')
        key = keys[0]
        if json.loads(key)[0] != str(pending):
            raise ValueError('Accounting receipt belongs to a different owed file.')
        saved = receipts[key]
        home, run, old = Path(saved[0]), saved[1], saved[2]
        if not home.is_absolute() or home.resolve() != home:
            raise ValueError('recorded ledger must be an absolute path without symlinks')
        with home.open('r+b') as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            text = fh.read().decode()
            history = [r.split('\t') for r in text.splitlines() if r]
            if text.rstrip('\n').split('\n') != text.splitlines() or '' in text.splitlines():
                # shortcut: one blank line or extra line break blocks correction on this ledger; map lines to rows if that occurs.
                raise ValueError('ledger lines differ from its rows; correct-binding cannot name a row in this ledger')
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
            own_record = (0 <= index < len(history) and history[index][4] != 'owed'
                          and accounting_row(history[index], key, run))
            if not (review(index) or own_record) or not fits(index, saved):
                raise ValueError("target line must be a completed review row of this result's run and agent")
            new = run_identity(index, history[index])
            if new == old:
                return home
            other = next((k for k, v in receipts.items() if v[0] == saved[0] and v[2] == new), None)
            if other and (json.loads(other)[0] != str(pending)
                          or receipts[other][1] != run or not review(old[0])):
                raise ValueError('target row is credited to another result that cannot take the current row')
            note = {'result': key, 'agent': history[index][2], 'from': old, 'to': new, 'swap': other, 'reason': reason}
            # The '-' agent keeps older hooks from taking the audit row as a review.
            row = [str(int(time.time())), 'correct-binding', '-', history[index][3], 'corrected', json.dumps(note)]
            last = [json.loads(r[5]) for r in history if r[1] == 'correct-binding'][-1:]
            # The ledger's last audit row naming this move means a crash came before publish: publish only.
            if not last or [last[0][k] for k in ('result', 'from', 'to', 'swap')] != [key, old, new, other]:
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
        publish_at(root_fd, receipt_path.name, json.dumps(receipts).encode())
    return home


def main(argv):
    if not argv:
        sys.exit(USAGE)
    cmd, args = argv[0], argv[1:]
    if cmd in ACCOUNT_COMMANDS:
        if account_pending_arg(argv) is None:
            sys.exit(USAGE)
        try:
            with consume_grant(sys.argv[0], argv) as (pending, root, root_fd, source):
                if cmd == 'correct-binding':
                    print(correct_binding(pending, root, root_fd, *args[1:]))
                elif cmd == 'account':
                    print(account(pending, *args[1:], entries=source.read().splitlines()))
                else:
                    with locked_receipts(root_fd):
                        account_auto(pending, source.read().splitlines(),
                                     load_receipts(root / 'accounted.json', root_fd=root_fd),
                                     flag=args[0] if len(args) == 2 else None)
        except OSError:
            sys.exit('Accounting evidence is unavailable. Run the exact command again.')
        except ValueError as exc:
            sys.exit(str(exc))
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
