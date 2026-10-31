#!/usr/bin/env python3
"""Ultraship hooks. Usage: ultraship.py pre|subagent-stop|stop|compact < hook-input.json"""
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path

STATE = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'ultraship'
RESEARCH_BUDGET = 40
DISCOVERY = re.compile(r'^(Read|Grep|Glob|LSP|WebFetch|WebSearch|mcp__fff__\w+)$')
# ponytail: a command-string match, so a writer can still reach these through a script it writes.
# Upgrade path: run writers in a sandbox without push credentials.
# Quoted commit messages containing `echo git push` also match; this guard scans raw text.
WRITER_BASH = re.compile(r"""(^|[;&|(`\s])(
    git\s+(?:
        (?:-[Cc]|--(?:git-dir|work-tree|namespace|config-env|super-prefix))\s+
            (?:"[^"\n]*"|'[^'\n]*'|[^\s;&|`'"]+)\s+ |
        (?:--[\w-]+(?:=(?:"[^"\n]*"|'[^'\n]*'|[^\s;&|`'"]+))?|
            -[Cc][^\s;&|`'"]+|-[a-zA-Z]+)\s+
    )*push |
    gh\s+(pr\s+(create|merge|ready|close|edit|comment|review)|release|workflow\s+run|repo\s+(create|delete|edit)) |
    (npm|pnpm|yarn|bun)\s+publish | cargo\s+publish | twine\s+upload | gem\s+push |
    terraform\s+(apply|destroy) | kubectl\s+(apply|delete|rollout) | helm\s+(install|upgrade|uninstall) |
    vercel(\s+\S+)*\s+--prod | vercel\s+deploy | wrangler\s+(deploy|publish) | fly(ctl)?\s+deploy | docker\s+push
)\b""", re.X)
HARNESS_PATH = re.compile(r'(^|/)\.claude/settings[^/]*\.json$')
LEDGER_ROLES = re.compile(r'^(ship:)?(reviewer|triage|verifier)--')


def role(data, name):
    return re.match(rf'^(ship:)?{name}--', data.get('agent_type') or '') is not None


def deny(reason):
    print(json.dumps({'hookSpecificOutput': {
        'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': reason}}))
    sys.exit(0)


def load_ledger():
    path = Path(__file__).resolve().parents[1] / 'skills/ship/scripts/ledger.py'
    spec = importlib.util.spec_from_file_location('ledger', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pre(data):
    tool, tin = data.get('tool_name', ''), data.get('tool_input') or {}
    if tool in ('Agent', 'Task') and str(tin.get('subagent_type', '')).startswith('ship:') and tin.get('model'):
        deny('ship agents pin their own model. Remove the `model` field and call the scoped agent '
             'or the next agent in its fallback chain.')
    if role(data, 'writer'):
        if tool in ('mcp__bettercoding__create_input', 'mcp__bettercoding__update_input',
                    'mcp__bettercoding__set_input_status'):
            deny('Writers return owner decision needs to the driver. Only the driver maintains Inputs.')
        if tool == 'Bash' and WRITER_BASH.search(tin.get('command', '')):
            deny('Writers never push, run `/merge` or `gh pr merge`, deploy, publish, or release; '
                 'commit grants permit local base-branch merges into their own lane branch.')
        target = tin.get('file_path') or tin.get('notebook_path') or ''
        if tool in ('Edit', 'Write', 'NotebookEdit') and (
                HARNESS_PATH.search(target) or target.startswith(str(Path.home() / '.claude') + '/')):
            deny('Writers do not edit harness configuration.')
    if role(data, 'researcher') and DISCOVERY.match(tool):
        counter = STATE / 'budget' / re.sub(r'[^\w.-]', '_', data.get('agent_id') or 'unknown')
        counter.parent.mkdir(parents=True, exist_ok=True)
        used = int(counter.read_text() or 0) if counter.exists() else 0
        if used >= RESEARCH_BUDGET:
            deny(f'Research budget of {RESEARCH_BUDGET} discovery calls is spent. Return your answer '
                 'with the evidence you have and list what stays unconfirmed.')
        counter.write_text(str(used + 1))


def owed_file(data):
    return STATE / 'owed' / (re.sub(r'[^\w.-]', '_', data.get('session_id') or 'unknown') + '.tsv')


def run_identity(index, row):
    return [index, hashlib.sha256(json.dumps(row).encode()).hexdigest()]


def subagent_stop(data):
    if LEDGER_ROLES.match(data.get('agent_type') or ''):
        path = owed_file(data)
        path.parent.mkdir(parents=True, exist_ok=True)
        cwd = data.get('cwd') or os.getcwd()
        result = {'id': str(uuid.uuid4())}
        try:
            ledger = load_ledger()
            home = ledger.ledger_path(cwd).resolve()
            history = ledger.rows(home)
            starts = [i for i, row in enumerate(history) if row[1] == 'run-start']
            result.update(ledger=str(home), run=run_identity(starts[-1], history[starts[-1]]) if starts else None)
        except Exception:
            # Always retain the notification, including when ledger access fails.
            pass
        with path.open('a') as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.write(f"{int(time.time())}\t{data['agent_type']}\t{cwd}\t{json.dumps(result)}\n")


def account(ledger, cwd, notifications, receipts, session):
    home = ledger.ledger_path(cwd).resolve()
    history = ledger.rows(home)
    starts = [i for i, row in enumerate(history) if row[1] == 'run-start']
    occurrences = {}
    for owed in notifications:
        epoch, agent, _ = owed[:3]
        if len(owed) == 4:
            result = json.loads(owed[3])
        else:
            line = '\t'.join(owed)
            ordinal = occurrences.get(line, 0)
            occurrences[line] = ordinal + 1
            result = {'id': 'legacy:' + hashlib.sha256(
                json.dumps([session, line, ordinal]).encode()).hexdigest()}
        result_id = json.dumps([session, cwd, result['id']])
        if 'ledger' in result:
            if result['ledger'] != str(home):
                raise ValueError(f'Ledger home differs for pending result {result["id"]}; restore {result["ledger"]}')
            candidates = [i for i in starts if run_identity(i, history[i]) == result['run']]
        else:
            # Legacy notifications have no run identity: accept only one time-containing run.
            candidates = []
            for pos, start in enumerate(starts):
                end = starts[pos + 1] if pos + 1 < len(starts) else len(history)
                closed = next((r for r in history[start + 1:end] if r[1] == 'run-end'), None)
                if int(history[start][0]) <= int(epoch) and (closed is None or int(epoch) <= int(closed[0])):
                    candidates.append(start)
        if len(candidates) != 1:
            raise ValueError(f'No unambiguous ship run in {cwd} for pending result {result["id"]}; restore the intended run')
        start = candidates[0]
        end = next((i for i in starts if i > start), len(history))
        end = next((i for i in range(start + 1, end) if history[i][1] == 'run-end'), end)
        if result_id in receipts:
            saved = receipts[result_id]
            if saved[0] != str(home) or saved[1] != run_identity(start, history[start]):
                raise ValueError('Accounting receipt names a different ledger or run')
            index = saved[2][0]
            if not start < index < end or saved[2] != run_identity(index, history[index]):
                raise ValueError('Accounting receipt row is missing or differs; restore the ledger evidence')
            continue
        used = {json.dumps(value) for value in receipts.values()}
        for i in range(start + 1, end):
            row = history[i]
            identity = [str(home), run_identity(start, history[start]), run_identity(i, row)]
            if (row[1] not in ('run-start', 'run-end') and row[2] == agent and row[4] != 'owed'
                    and int(row[0]) >= int(epoch) - 5 and json.dumps(identity) not in used):
                receipts[result_id] = identity
                break
        else:
            raise ValueError(f'Review results have no unused ledger row: {agent}')


def stop(data):
    path = owed_file(data)
    if data.get('stop_hook_active'):
        return
    try:
        try:
            path.stat()
        except FileNotFoundError:
            return
        with path.open('r+') as pending:
            fcntl.flock(pending, fcntl.LOCK_EX)
            owed = [line.split('\t') for line in pending.read().splitlines() if line]
            if not owed:
                return
            ledger = load_ledger()
            receipt_path = STATE / 'accounted.json'
            # ponytail: one hook-state receipt lock serializes Stops; shard by ledger
            # if concurrent Stop throughput matters. This never locks a legacy home.
            with (STATE / 'accounted.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    receipts = json.loads(receipt_path.read_text())
                except FileNotFoundError:
                    receipts = {}
                for cwd in {o[2] for o in owed}:
                    account(ledger, cwd, [o for o in owed if o[2] == cwd], receipts, str(path))
                with tempfile.NamedTemporaryFile(mode='w', dir=STATE, prefix='accounted.',
                                                 delete=False) as saved:
                    json.dump(receipts, saved)
                    saved.flush()
                    os.fsync(saved.fileno())
                os.replace(saved.name, receipt_path)
                directory = os.open(STATE, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            # Clear only after every result has a successful accounting row.
            # Keep this inode so concurrent SubagentStop writers share the lock.
            pending.seek(0)
            pending.truncate()
    except Exception as exc:
        print(json.dumps({'decision': 'block', 'reason':
              f'Pending review evidence retained at {path}: {exc}. '
              'Resolve ledger access (set SHIP_LEDGER_DIR to an absolute permitted directory if needed). '
              'Record each result with `ledger.py append <step> <agent> <sha> <verdict> [note]`, then continue.'}))


def compact(data):
    lines = ['Context was compacted. Re-establish state from disk before you continue: run git status and '
             'git diff --stat, re-read the active plan and run board, and never guess dropped state.']
    try:
        ledger = load_ledger()
        path = ledger.ledger_path(data.get('cwd') or '.')
        run = ledger.open_run(path)
    except Exception as exc:
        lines.append(f'Ledger resolution failed: {exc}. Pending review evidence remains at {owed_file(data)}. '
                     'Restore ledger access or set SHIP_LEDGER_DIR to an absolute permitted directory before continuing.')
        run = None
    if run:
        lines.append(f'Open ship run: {run[0][5]} (mode {run[0][2]}). Ledger: {path}. '
                     f'Gaps: {" ".join(ledger.gaps(run)) or "none"}. The run note names the board path.')
    print('\n'.join(lines))


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    handler = {'pre': pre, 'subagent-stop': subagent_stop, 'stop': stop, 'compact': compact}.get(mode)
    if not handler:
        sys.exit(__doc__)
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    handler(payload)
