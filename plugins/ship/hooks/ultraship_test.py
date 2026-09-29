#!/usr/bin/env python3
"""Self-check for hooks/ultraship.py and skills/ship/scripts/ledger.py. Run with a workspace-local TMPDIR."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

HOOK = Path(__file__).resolve().parent / 'ultraship.py'
LEDGER = HOOK.parents[1] / 'skills/ship/scripts/ledger.py'


def run(args, payload=None, cwd=None, env=None, check=False):
    return subprocess.run(args, input=json.dumps(payload or {}), capture_output=True, text=True,
                          cwd=cwd, env=env, check=check)


def hook(mode, payload, env):
    out = run(['python3', str(HOOK), mode], payload, env=env, check=True).stdout
    return json.loads(out) if out.strip().startswith('{') else out


def denied(result):
    return isinstance(result, dict) and result['hookSpecificOutput']['permissionDecision'] == 'deny'


with tempfile.TemporaryDirectory() as tmp:
    env = {**os.environ, 'XDG_STATE_HOME': tmp, 'HOME': tmp}
    writer = {'agent_type': 'ship:writer--sol', 'agent_id': 'w1', 'tool_name': 'Bash'}

    assert denied(hook('pre', {'tool_name': 'Agent', 'tool_input': {'subagent_type': 'ship:reviewer--glm', 'model': 'opus'}}, env))
    assert not denied(hook('pre', {'tool_name': 'Agent', 'tool_input': {'subagent_type': 'ship:reviewer--glm'}}, env))
    assert not denied(hook('pre', {'tool_name': 'Agent', 'tool_input': {'subagent_type': 'Explore', 'model': 'haiku'}}, env))

    for cmd in ['git push origin HEAD', 'cd x && gh pr merge 3 --squash', 'npm publish', 'vercel --prod', 'terraform apply']:
        assert denied(hook('pre', {**writer, 'tool_input': {'command': cmd}}, env)), cmd
    for cmd in ['git commit -m "no push here"', 'gh pr view 3', 'npm test', 'git status']:
        assert not denied(hook('pre', {**writer, 'tool_input': {'command': cmd}}, env)), cmd
    assert not denied(hook('pre', {'agent_type': 'ship:driver', 'tool_name': 'Bash', 'tool_input': {'command': 'git push'}}, env))
    assert denied(hook('pre', {**writer, 'tool_name': 'Write', 'tool_input': {'file_path': '/r/.claude/settings.local.json'}}, env))
    assert denied(hook('pre', {**writer, 'tool_name': 'Edit', 'tool_input': {'file_path': f'{tmp}/.claude/CLAUDE.md'}}, env))
    assert not denied(hook('pre', {**writer, 'tool_name': 'Edit', 'tool_input': {'file_path': '/r/src/app.py'}}, env))

    researcher = {'agent_type': 'ship:researcher--flash', 'agent_id': 'r1', 'tool_name': 'mcp__fff__grep', 'tool_input': {}}
    for _ in range(40):
        assert not denied(hook('pre', researcher, env))
    assert denied(hook('pre', researcher, env))
    assert not denied(hook('pre', {**researcher, 'agent_id': 'r2'}, env))

    repo = Path(tmp, 'repo')
    repo.mkdir()
    git = lambda *a: subprocess.run(['git', '-C', str(repo), *a], check=True, capture_output=True)
    git('init', '-q', '-b', 'feat/x')
    git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'init')
    ledger = lambda *a: run(['python3', str(LEDGER), *a], cwd=repo)

    assert 'ship/ledger/feat__x.tsv' in ledger('path').stdout
    assert ledger('append', 'slices', 'a', 'sha', 'pass').returncode != 0
    assert ledger('run-start', 'light', 'run-1', '/b/board.md').returncode == 0
    assert ledger('run-start', 'light', 'run-2').returncode != 0
    assert ledger('gaps').returncode == 1
    assert 'refusing' in ledger('run-end').stderr

    session = {'session_id': 's1', 'cwd': str(repo)}
    assert 'Open ship run: run-1' in hook('compact', session, env)
    hook('subagent-stop', {**session, 'agent_type': 'ship:reviewer--sol-xhigh'}, env)
    hook('subagent-stop', {**session, 'agent_type': 'ship:writer--sol'}, env)
    blocked = hook('stop', session, env)
    assert blocked['decision'] == 'block' and 'reviewer--sol-xhigh' in blocked['reason']
    assert hook('stop', session, env) == ''

    hook('subagent-stop', {**session, 'agent_type': 'ship:reviewer--opus'}, env)
    for step in ['slices', 'simplify', 'deep-review', 'fix-read', 'pr', 'babysit', 'gate']:
        assert ledger('append', step, 'ship:reviewer--opus', 'sha', 'pass').returncode == 0
    assert hook('stop', session, env) == ''
    assert ledger('gaps').returncode == 0
    assert ledger('run-end').returncode == 0
    assert 'no open run' in ledger('status').stdout
    assert 'Open ship run' not in hook('compact', session, env)

print('ultraship hooks: ok')
