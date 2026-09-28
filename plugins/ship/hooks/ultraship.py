#!/usr/bin/env python3
"""Ultraship hooks. Usage: ultraship.py pre|subagent-stop|stop|compact < hook-input.json"""
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

STATE = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'ultraship'
RESEARCH_BUDGET = 40
DISCOVERY = re.compile(r'^(Read|Grep|Glob|LSP|WebFetch|WebSearch|mcp__fff__\w+)$')
# ponytail: a command-string match, so a writer can still reach these through a script it writes.
# Upgrade path: run writers in a sandbox without push credentials.
WRITER_BASH = re.compile(r"""(^|[;&|(`\s])(
    git\s+push |
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
        if tool == 'Bash' and WRITER_BASH.search(tin.get('command', '')):
            deny('Writers do not push, merge, deploy, publish, or release. Report back; the driver ships.')
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


def subagent_stop(data):
    if LEDGER_ROLES.match(data.get('agent_type') or ''):
        path = owed_file(data)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as fh:
            fh.write(f"{int(time.time())}\t{data['agent_type']}\t{data.get('cwd') or os.getcwd()}\n")


def stop(data):
    path = owed_file(data)
    if data.get('stop_hook_active') or not path.exists():
        return
    owed = [line.split('\t') for line in path.read_text().splitlines() if line]
    path.unlink()
    ledger = load_ledger()
    missing = []
    for cwd in {o[2] for o in owed}:
        try:
            run = ledger.open_run(ledger.ledger_path(cwd))
        except Exception:
            continue
        if not run:
            continue
        mine = [o for o in owed if o[2] == cwd]
        since = min(int(o[0]) for o in mine)
        recorded = sum(1 for r in run[1] if int(r[0]) >= since - 5)
        if recorded < len(mine):
            missing += [o[1] for o in mine[recorded:]]
    if missing:
        print(json.dumps({'decision': 'block', 'reason':
              'Review results have no ledger row: ' + ', '.join(missing) +
              '. Record each with `ledger.py append <step> <agent> <sha> <verdict> [note]`, then continue.'}))


def compact(data):
    lines = ['Context was compacted. Re-establish state from disk before you continue: run git status and '
             'git diff --stat, re-read the active plan and run board, and never guess dropped state.']
    try:
        ledger = load_ledger()
        path = ledger.ledger_path(data.get('cwd') or '.')
        run = ledger.open_run(path)
    except Exception:
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
