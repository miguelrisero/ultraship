#!/usr/bin/env python3
"""Escalation records for refused Bash calls, and single-use manager approvals.

Usage: escalation.py list | show <id> | approve <id> --reason <text> | reject <id> --reason <text>

The ship `pre` hook writes every record and every decision, signed with the text_lint receipt key.
This CLI only prints them, so a lane that runs `approve` gets a hook refusal and no approval.
"""
from datetime import datetime, timezone
import functools
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import uuid

TTL = 3600
ID = re.compile(r'[0-9a-f]{32}')
CD_PREFIX = re.compile(r"cd '([^']+)' && (.+)", re.S)


def store():
    return Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'ultraship' / 'escalations'


@functools.lru_cache(maxsize=1)
def text_lint():
    spec = importlib.util.spec_from_file_location('ultraship_text_lint', Path(__file__).resolve().with_name('text_lint.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sign(record):
    lint = text_lint()
    return dict(record, mac=lint.signature(record, lint.receipt_key()))


def signed(record):
    lint = text_lint()
    return (isinstance(record, dict) and isinstance(record.get('mac'), str)
            and hmac.compare_digest(record['mac'], lint.signature(record, lint.receipt_key())))


def digest(command):
    return hashlib.sha256(command.encode()).hexdigest()


def head(cwd):
    try:
        result = subprocess.run(['git', '-C', cwd, 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def real(path):
    return os.path.realpath(path) if isinstance(path, str) and path else None


def manager_label(record):
    manager = record['manager']
    return 'the CoC' if manager['kind'] == 'coc' else 'the parent main session ' + manager['session_id']


def write_new(path, record):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(record, output, sort_keys=True)


def load(path, accept=lambda record: True):
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) and accept(record) and signed(record) else None


def record(data, rule):
    """Write a signed escalation for a refused Bash call and return it, or None when the call has no session."""
    session = data.get('session_id')
    if not isinstance(session, str) or not session:
        return None
    command = str((data.get('tool_input') or {}).get('command', ''))
    cwd = real(data.get('cwd') or os.getcwd())
    agent_id = data.get('agent_id') or None
    entry = {
        'id': uuid.uuid4().hex, 'v': 1,
        'actor': {'session_id': session, 'agent_id': agent_id, 'agent_type': data.get('agent_type') or None},
        'command': command, 'sha256': digest(command), 'rule': rule, 'cwd': cwd, 'head': head(cwd),
        'time': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'manager': {'kind': 'parent', 'session_id': session} if agent_id else {'kind': 'coc'},
    }
    entry = sign(entry)
    write_new(store() / (entry['id'] + '.json'), entry)
    return entry


def get(identifier):
    return load(store() / (identifier + '.json')) if ID.fullmatch(identifier or '') else None


def decision(identifier):
    return load(store() / (identifier + '.decision.json')) if ID.fullmatch(identifier or '') else None


def coc_caller(data):
    root = real(os.environ.get('ULTRASHIP_COC_DIR'))
    cwd = real(data.get('cwd') or os.getcwd())
    return bool(root and cwd and (cwd == root or cwd.startswith(root.rstrip('/') + '/')))


def manager_caller(data, entry):
    """Whether this hook event comes from the record's manager: a main session, never a subagent."""
    if data.get('agent_id'):
        return False
    if entry['manager']['kind'] == 'parent':
        return data.get('session_id') == entry['manager']['session_id']
    return coc_caller(data)


def cli_decision(command):
    """Return (verb, id, reason) when the command is exactly one `escalation.py approve|reject` call."""
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    if (len(words) == 6 and re.fullmatch(r'python3?', os.path.basename(words[0]))
            and real(words[1]) == os.path.realpath(__file__) and words[2] in ('approve', 'reject')
            and words[4] == '--reason' and words[5].strip()):
        return words[2], words[3], words[5]
    return None


def decide(data, verb, identifier, reason, hold):
    """Write the manager's decision. Return None on success, else the refusal reason."""
    entry = get(identifier)
    if entry is None:
        return 'no signed escalation record ' + identifier
    if not manager_caller(data, entry):
        return 'only ' + manager_label(entry) + ' decides escalation ' + identifier
    if verb == 'approve' and hold:
        return 'absolute hold (' + hold + '); only the owner decides this command'
    now = int(time.time())
    try:
        write_new(store() / (identifier + '.decision.json'), sign({
            'id': identifier, 'decision': verb, 'reason': reason, 'sha256': entry['sha256'], 'cwd': entry['cwd'],
            'head': entry['head'], 'approver': data['session_id'], 'time': now, 'expires': now + TTL}))
    except FileExistsError:
        return 'escalation ' + identifier + ' already has a decision'
    return None


def approved(data, command, consume=True):
    """Return the id of an unexpired, unused approval that binds this exact command, cwd, head and session."""
    if data.get('agent_id') or not data.get('session_id'):
        return None
    candidates = [(digest(command), real(data.get('cwd') or os.getcwd()))]
    prefixed = CD_PREFIX.fullmatch(command)
    if prefixed:
        candidates.append((digest(prefixed[2]), real(prefixed[1])))
    folder = store()
    if not folder.is_dir():
        return None
    now = int(time.time())
    for path in sorted(folder.glob('*.decision.json'))[-500:]:
        # Check the cheap bindings first, so most calls verify no signature.
        grant = load(path, lambda grant: (
            grant.get('decision') == 'approve' and grant.get('approver') == data['session_id']
            and isinstance(grant.get('expires'), int) and now < grant['expires']
            and (grant.get('sha256'), grant.get('cwd')) in candidates and bool(ID.fullmatch(str(grant.get('id'))))
            and path.name == grant['id'] + '.decision.json'))
        if not grant or (folder / (grant['id'] + '.consumed')).exists() or head(grant['cwd']) != grant.get('head'):
            continue
        if not consume:
            return grant['id']
        try:
            write_new(folder / (grant['id'] + '.consumed'), {'id': grant['id'], 'time': now})
        except FileExistsError:
            continue
        return grant['id']
    return None


def pending(agent_id):
    """Undecided escalation ids raised by one subagent."""
    folder = store()
    if not agent_id or not folder.is_dir():
        return []
    ids = []
    for path in sorted(folder.glob('*.json')):
        if '.' in path.stem:
            continue
        entry = load(path)
        if entry and entry['actor'].get('agent_id') == agent_id and not (folder / (path.stem + '.decision.json')).exists():
            ids.append(entry['id'])
    return ids


def show(entry):
    grant = decision(entry['id'])
    lines = [f"{entry['id']}  {entry['time']}  rule: {entry['rule']}",
             f"  actor: {entry['actor']['agent_type'] or 'main session'} {entry['actor']['agent_id'] or ''} "
             f"in session {entry['actor']['session_id']}",
             f"  manager: {manager_label(entry)}",
             f"  cwd: {entry['cwd']}  head: {entry['head']}",
             f"  decision: {grant['decision'] + ' (' + grant['reason'] + ')' if grant else 'pending'}",
             f"  run as: cd {shlex.quote(entry['cwd'])} && <command>" if entry['cwd'] else '',
             '  command:', entry['command']]
    return '\n'.join(line for line in lines if line)


def main(argv):
    if argv[:1] == ['list'] and len(argv) == 1:
        folder = store()
        for path in sorted(folder.glob('*.json')) if folder.is_dir() else []:
            entry = None if '.' in path.stem else load(path)
            if entry and not decision(entry['id']):
                print(f"{entry['id']}  {entry['time']}  {manager_label(entry)}  {entry['rule']}")
        return 0
    if len(argv) == 2 and argv[0] == 'show':
        entry = get(argv[1])
        if not entry:
            print('No signed escalation record ' + argv[1], file=sys.stderr)
            return 1
        print(show(entry))
        return 0
    if len(argv) == 4 and argv[0] in ('approve', 'reject') and argv[2] == '--reason':
        grant = decision(argv[1])
        if not grant or grant['decision'] != argv[0]:
            print('No hook-written ' + argv[0] + ' decision for ' + argv[1] + '. The ship hook writes it only '
                  'when the lane\'s manager runs this exact command.', file=sys.stderr)
            return 1
        entry = get(argv[1])
        print(f"{argv[0]}d {argv[1]} until {datetime.fromtimestamp(grant['expires'], timezone.utc):%H:%MZ}. "
              "Run the exact command once from your session, prefixed with `cd '<cwd>' && `:")
        print(show(entry))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
