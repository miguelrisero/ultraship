#!/usr/bin/env python3
"""Self-check for hooks/ultraship.py and skills/ship/scripts/ledger.py. Run with a workspace-local TMPDIR."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import time
import os
import re
import subprocess
import tempfile
import uuid
import unittest
from unittest.mock import patch
import shlex
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent / 'ultraship.py'
LEDGER = HOOK.parents[1] / 'skills/ship/scripts/ledger.py'


def run(args, payload=None, cwd=None, env=None, check=False):
    return subprocess.run(args, input=json.dumps(payload or {}), capture_output=True, text=True,
                          cwd=cwd, env=env, check=check)


def hook(mode, payload, env):
    out = run([sys.executable, str(HOOK), mode], payload, env=env, check=True).stdout
    return json.loads(out) if out.strip().startswith('{') else out


def denied(result):
    return isinstance(result, dict) and result['hookSpecificOutput'].get('permissionDecision') == 'deny'


spec = importlib.util.spec_from_file_location('ultraship', HOOK)
ultraship = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ultraship)
started = time.monotonic()
assert not ultraship.git_push('git ' + '-Cc ' * 200 + 'status')
assert ultraship.git_push('git ' + '-Cc ' * 200 + 'push')
assert time.monotonic() - started < 0.1

with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory(dir=HOOK.parents[3]) as symlink_tmp:
    env = {**os.environ, 'XDG_STATE_HOME': tmp, 'HOME': tmp}
    writer = {'agent_type': 'ship:writer--sol', 'agent_id': 'w1', 'tool_name': 'Bash'}
    cat_append = ('cd /workspace/repo && cat >> backend/api/tests/integration/test_approval_expiry.py <<\'EOF\'\n'
                  'r.rpush("jobs", *[1, 2])\nEOF\n')
    sync_write = "cat > {path} <<'EOF'\nimport os\nos.system('git push')\nEOF\n"
    installed = Path(symlink_tmp, 'site-packages')
    installed.mkdir()
    linked = Path(symlink_tmp, 'linked')
    linked.symlink_to(installed, target_is_directory=True)
    tools = Path(symlink_tmp, 'tools')
    tools.mkdir()
    driver = tools / 'driver.py'
    driver.write_text('')
    aliased_ruff = Path(symlink_tmp, 'aliased/.venv/bin/ruff')
    aliased_ruff.parent.mkdir(parents=True)
    aliased_ruff.symlink_to(driver)
    real_ruff = Path(symlink_tmp, 'real/.venv/bin/ruff')
    real_ruff.parent.mkdir(parents=True)
    real_ruff.write_text('')
    ruff_remainder = ('uv run --frozen --directory backend/api ruff check --fix tests/integration/test_approval_expiry.py'
                      ' && uv run --frozen --directory backend/api ruff format tests/integration/test_approval_expiry.py')

    receipt_store = Path(tmp) / 'ultraship' / 'text-lint'
    custody = ('Only the text_lint hook reads or writes refusal receipts (custody rule). '
               'Report the blocked scope to the driver.')
    for caller in ({'agent_type': 'ship:writer--sol'}, {'agent_type': 'ship:driver'}, {}):
        for tool, inputs in (
                ('Edit', {'file_path': str(receipt_store / 'key')}),
                ('Write', {'file_path': str(receipt_store / 'receipts/a.json')}),
                ('NotebookEdit', {'notebook_path': str(receipt_store / 'book.ipynb')}),
                ('Read', {'file_path': str(receipt_store / 'key')}),
                ('Grep', {'path': str(receipt_store), 'pattern': 'key'}),
                ('Grep', {'path': str(receipt_store.parent), 'pattern': 'key'}),
                ('Grep', {'path': tmp, 'pattern': 'key'}),
                ('Glob', {'pattern': str(receipt_store / '*')}),
                ('Glob', {'pattern': str(receipt_store.parent / '*')}),
                ('LSP', {'file_path': str(receipt_store / 'key')}),
                ('LSP', {'filePath': str(receipt_store / 'key')}),
                ('mcp__fff__grep', {'pattern': str(receipt_store)}),
                ('Bash', {'command': 'echo forged > ' + str(receipt_store / 'key')}),
                ('Bash', {'command': 'python3 plugins/ship/hooks/text_lint.py' + ' hook'}),
                ('Bash', {'command': 'python3 "plugins/ship/hooks/text_lint.py"' + ' hook'}),
                ('Bash', {'command': 'cat ' + str(receipt_store / 'key').replace('text-lint', "text-''lint")}),
                ('Bash', {'command': 'cat ' + str(receipt_store / 'key').replace('/text-lint', '//text-lint')}),
                ('Bash', {'command': 'cat ' + str(receipt_store / 'key').replace('/text-lint', '/./text-lint')}),
                ('Bash', {'command': 'cat ${XDG_STATE_HOME:-' + tmp + '}/ultraship/*'}),
                ('Bash', {'command': "python3 plugins/ship/hooks/text_lint.py ho''ok"}),
                ('Bash', {'command': 'python3 -m plugins.ship.hooks.text_lint hook'}),
                ('Bash', {'command': "python3 -c 'import text_lint'"}),
                ('Read', {'file_path': str(receipt_store / 'key').upper()}),
                ('mcp__fff__grep', {'query': {'text': str(receipt_store)}})):
            result = hook('pre', {**caller, 'tool_name': tool, 'tool_input': inputs}, env)
            assert denied(result), (caller, tool, inputs)
            assert result['hookSpecificOutput']['permissionDecisionReason'] == custody
        for tool, inputs in (('Bash', {'command': 'git status --short'}),
                             ('Bash', {'command': 'git add plugins/ship/hooks/text_lint.py'}),
                             ('Bash', {'command': 'python3 -m unittest scripts.test_text_lint'}),
                             ('Bash', {'command': 'python3 plugins/ship/hooks/text_lint.py --self-test'}),
                             ('Grep', {'path': str(HOOK.parent), 'pattern': 'key'}),
                             ('Grep', {'path': str(HOOK.parent), 'pattern': '/'}),
                             ('Read', {'file_path': str(Path(tmp) / 'ordinary.txt')})):
            assert not denied(hook('pre', {**caller, 'tool_name': tool, 'tool_input': inputs}, env)), (caller, tool, inputs)
        for cwd in (tmp, str(receipt_store.parent), str(receipt_store)):
            for tool, inputs in (('Grep', {'pattern': 'key'}), ('Glob', {'pattern': '*'}),
                                 ('Bash', {'command': 'pwd'})):
                result = hook('pre', {**caller, 'cwd': cwd, 'tool_name': tool, 'tool_input': inputs}, env)
                assert denied(result), (caller, cwd, tool)
                assert result['hookSpecificOutput']['permissionDecisionReason'] == custody
    receipt_alias = Path(tmp) / 'ReceiptAlias'
    receipt_store.mkdir(parents=True)
    receipt_alias.symlink_to(receipt_store, target_is_directory=True)
    for caller in ({'agent_type': 'ship:writer--sol'}, {'agent_type': 'ship:driver'}, {}):
        for tool in ('Edit', 'Read', 'Write'):
            result = hook('pre', {**caller, 'tool_name': tool,
                                  'tool_input': {'file_path': str(receipt_alias / 'key')}}, env)
            assert denied(result), (caller, tool)
            assert result['hookSpecificOutput']['permissionDecisionReason'] == custody
        for command, state_root in (
                ('cat ~/.local/sta[t]e/ultraship/*/key', str(Path(tmp) / '.local/state')),
                ('cat $HOME/.local/sta[t]e/ultraship/*/key', str(Path(tmp) / '.local/state')),
                ('cat ${HOME}/.local/sta[t]e/ultraship/*/key', str(Path(tmp) / '.local/state')),
                ('cat $XDG_STATE_HOME/ultra*/t*/key', tmp),
                ('cat ${XDG_STATE_HOME}/ultra*/t*/key', tmp)):
            result = hook('pre', {**caller, 'tool_name': 'Bash', 'tool_input': {'command': command}},
                          {**env, 'XDG_STATE_HOME': state_root})
            assert denied(result), (caller, command)
            assert result['hookSpecificOutput']['permissionDecisionReason'] == custody
    assert denied(hook('pre', {'tool_name': 'Write', 'tool_input': {'file_path': str(receipt_store).upper()}}, env))

    assert denied(hook('pre', {'tool_name': 'Agent', 'tool_input': {'subagent_type': 'ship:reviewer--sol', 'model': 'opus'}}, env))
    assert not denied(hook('pre', {'tool_name': 'Agent', 'tool_input': {'subagent_type': 'ship:reviewer--sol'}}, env))
    assert not denied(hook('pre', {'tool_name': 'Agent', 'tool_input': {'subagent_type': 'Explore', 'model': 'haiku'}}, env))

    for agent in ['ship:writer--sol', 'ship:writer--sonnet', 'ship:writer--fable52']:
        destination_cases = ('setup.py', 'pkg/sitecustomize.py', 'pkg/usercustomize/__init__.py',
                             'lib/python3.13/x.py', 'x.pth', 'x.toml', 'lib/x.py', 'python3.13/x.py')
        destination_decisions = [
            denied(hook('pre', {**writer, 'agent_type': agent, 'tool_input': {
                'command': 'cd /repo && ' + sync_write.format(path=path) + 'ruff check'}}, env))
            for path in destination_cases]
        assert all(destination_decisions), (agent, list(zip(destination_cases, destination_decisions)))
        review_inputs = (
            'cd /repo/.venv/lib/python3.13/site-packages && '
            + sync_write.format(path='sitecustomize.py') + 'uv run --no-sync --project /repo ruff check',
            'cd /repo && ' + sync_write.format(path='backend.py') + 'uv run ruff check',
            'cd /repo && ' + sync_write.format(path='backend.py') + 'uv run ruff check --no-sync',
            'cd /repo && ' + sync_write.format(path='backend.py') + 'uv run --directory --no-sync ruff check',
            'cd - && ' + sync_write.format(path='sitecustomize/__init__.py') + 'uv run --no-sync ruff check',
            'cd sub && ' + sync_write.format(path='x.py') + 'ruff check x.py',
            sync_write.format(path='x.py') + 'ruff check x.py',
            'cd /repo && ' + sync_write.format(path='sitecustomize/__init__.py') + 'uv run --no-sync ruff check',
            sync_write.format(path=linked / 'x.py') + 'ruff check x.py',
            cat_append + ruff_remainder.replace('uv run ', 'uv run --no-sync '),
            cat_append + '.venv/bin/ruff check backend/api/tests/integration/test_approval_expiry.py',
            sync_write.format(path=driver) + f'{aliased_ruff} check {driver}',
        )
        decisions = [denied(hook('pre', {**writer, 'agent_type': agent, 'tool_input': {'command': cmd}}, env))
                     for cmd in review_inputs]
        assert decisions == [True] * len(review_inputs), (agent, decisions, review_inputs)
        for cmd in ['git push origin HEAD', 'git -C /w push origin HEAD', 'git -c core.x=y push',
                    'git --git-dir=/w/.git push', 'cd /w && git -C /w push',
                    'git -C "/a b" -c core.x=y --no-pager push', 'git --git-dir /w/.git push',
                    'git --no-pager push', 'git -C/w -ccore.x=y push',
                    'git commit -m "echo git push"', 'git commit -m "git push"',
                    'git -c core.sshCommand="ssh -F /dev/null" push',
                    'git -c user.name=A+B push', 'git -c user.name=A#B push',
                    'git -C /w#x push', 'git ' + '\\' + '\n' + 'push',
                    'echo `git push`', 'x=`git -C /w push`', '"`git push`"',
                    "bash -lc 'git -C /w push'", '/usr/bin/git push',
                    "sh -c 'git --attr-source HEAD push'", 'git push "',
                    'git 2>/dev/null push origin HEAD', 'git >log 2>&1 push', 'git &>/dev/null push',
                    'git -C $(pwd) push origin HEAD', 'git -C $(dirname $(pwd))/w push',
                    'git -C $(git push) status', 'git; /usr/bin/git push',
                    'git -C $(git -C $(git push)) status', 'git -C `pwd` push', 'git -C "$(pwd)" push',
                    'git -C >log . push origin HEAD', 'git >|log push origin HEAD', 'git <<<x push', 'git <<- log push origin HEAD\nlog', "git >'>' push origin HEAD", 'git <<- - push', 'git >&- push', 'git > `printf log` push origin HEAD', 'git >"$(x)" push', 'git <<< - push', "git $'push' origin HEAD", 'git $"push"', 'git -C "$PWD" push', 'git {push,} origin HEAD', "$'git' push origin HEAD", '$"git" push', 'g?t push', '/usr/bin/gi[t] push', '"$G" push', "$'git' $'push'", "$'git' p{u,}sh", 'git pu?h', 'git -C ~/w push', 'git -C $(pwd) pu""sh', 'git -C . pu""sh',
                    'g${X}it ${Y}push', 'git ${X:0:0}push', 'git ${Xr}push',
                    'pu{s,}h', 'git p*sh', 'git $(echo push)',
                    'cat <<EOF > f.py\n$(git push)\nEOF',
                    'cat <<\'EOF\' | bash\ngit push\nEOF',
                    'cat <<\'EOF\' > f.sh\ngit push\nEOF\n; bash f.sh',
                    'cat <<\'EOF\' > f\ngit push\nEOF\n&& git push',
                    'cat <<\'EOF\' > $X\ngit push\nEOF',
                    'cat <<\'EOF\' >| f.py\ngit push\nEOF',
                    'cat <<\'EOF\' > f.py\ngit push',
                    'cat >> f.py <<\'EOF\'; git push\nr.rpush("q", 1)\nEOF',
                    cat_append + ruff_remainder,
                    cat_append + 'git push origin HEAD',
                    cat_append + 'ruff format x && git push',
                    cat_append + "bash -c 'git push'",
                    cat_append + 'python3 f.py',
                    cat_append + "sh -c 'x'",
                    cat_append + 'uv run bash f.sh',
                    cat_append + 'timeout 5 sh f.sh',
                    cat_append + 'nohup python3.13 f.py',
                    cat_append + '"bash" f.sh',
                    cat_append + '`bash f.sh`',
                    cat_append + '$SHELL f.sh',
                    cat_append + 'uv run f.py',
                    cat_append + 'make',
                    cat_append + 'pytest',
                    cat_append + 'uv run --frozen pytest',
                    cat_append + 'ruff check x; bash f.sh',
                    cat_append + 'uv run --script f.py ruff check',
                    cat_append + 'uv run --with ./pkg ruff check',
                    cat_append + 'uv run --python f.py ruff check',
                    sync_write.format(path='backend/api/setup.py') + 'uv run --directory backend/api ruff check',
                    sync_write.format(path='backend/api/pyproject.toml') + 'uv run --frozen --directory backend/api ruff check',
                    sync_write.format(path='uv.lock') + 'uv run --frozen --directory backend/api ruff check',
                    sync_write.format(path='backend/api/setup.py') + 'uv run --no-sync --directory backend/api ruff check',
                    sync_write.format(path='.venv/bin/ruff') + 'uv run ruff check',
                    sync_write.format(path='bin/ruff') + 'ruff check',
                    sync_write.format(path='ruff') + 'ruff check',
                    sync_write.format(path='.venv/lib/python3.13/site-packages/x.pth') + 'ruff check',
                    'cat <<\'EOF\' > f.sh\ngit push\nEOF\nbash f.sh',
                    'git -C $(pwd) status',
                    'git -C "$W" push', 'git -C "${W}" push origin HEAD', 'git --work-tree "$W" push',
                    'git --git-dir "$G" status', 'git --work-tree "$W" diff --stat',
                    'git -C $W status', 'git -C "$W" status; git -C $W status', 'git -C "$W" $CMD',
                    'git -C "$W" -c x=y push', 'git -c "$X" status', 'git -C "$W*" status',
                    'git -C ""$W status', 'git -C "$W"$X status', 'git -C "$W"" push" status',
                    'git "-C" $W status', 'git -C "$W"x status', 'git -C "$W" status; echo $W',
                    'git -C "x $W" status', "git -C '$W' status; git -C $W status",
                    'git -C ""$W"" status', 'git -C x"$W" status', 'git -C "$W" status # $W',
                    'eval git -C "$W"', 'watch git -C "$W" status', 'bash -c "git -C \\"$W\\""',
                    'bash <<EOF\ngit -C "$W"\nEOF', 'git --shallow-file -C "$W"', 'eval "git -C \\"$W\\" status"',
                    "bash -lc 'git -C \"$W\" push'", "bash -lc 'git -C \"$W\" status'",
                    'bash <<EOF\n:; git -C "$W"\nEOF', 'bash <\\\n<EOF\n:; git -C "$W"\nEOF', 'git -C "$W" "$CMD"',
                    '''bash -c 'bash -c "git -C \\"$W\\""' ''', '''bash -c 'bash <''<EOF\n:; git -C "$W"\nEOF' ''',
                    '`echo eval` git -C "$W"', "eval : ';' git -C \"$W\"", 'eval : \\; git -C "$W"',
                    "# '\nbash -c \"git -C \\\"$W\\\"\"\n# '", "echo $'x'; git -C \"$W\" status",
                    'eval ${E:-:;git -C "$W" }', 'eval ${E:-(git -C "$W" )}', 'a=(git -C "$W"); eval ${a[@]}',
                    'declare -a a=(git -C "$W"); eval ${a[@]}', '((git -C "$W" ))', 'echo $((git -C "$W" ))',
                    'echo $[0|git -C "$W" ]', 'a[0|git -C "$W" ]=1', 'a[(git -C "$W" )]=1', 'a[0&git -C "$W" ]+=1',
                    'eval @(git -C "$W" )', 'eval !(git -C "$W" )', 'eval +(git -C "$W" )',
                    'for x (git -C "$W") eval $x', 'foreach x (git -C "$W")\neval $x\nend', '( git -C "$W" status )',
                    'git --version && /usr/bin/ssh -C "$W" h', 'git -C ; /usr/bin/ssh -C "$W" h',
                    'git --version\n/usr/bin/ssh -C "$W" h', 'Y=$(git --version); /usr/bin/ssh -C "$W" h',
                    'Y=$(git --version)&&/usr/bin/ssh -C "$W" h',
                    'gh pr merge 3 --squash', 'cd x && gh pr merge 3 --squash', 'npm publish', 'vercel --prod', 'terraform apply']:
            assert denied(hook('pre', {**writer, 'agent_type': agent, 'tool_input': {'command': cmd}}, env)), (agent, cmd)
        for cmd in [
                    cat_append + ('/workspace/repo/backend/api/.venv/bin/ruff check --fix '
                                  'backend/api/tests/integration/test_approval_expiry.py && '
                                  '/workspace/repo/backend/api/.venv/bin/ruff format '
                                  'backend/api/tests/integration/test_approval_expiry.py'),
                    cat_append + 'ruff check backend/api/tests/integration/test_approval_expiry.py',
                    sync_write.format(path=driver) + f'{real_ruff} check {driver}',
                    cat_append + 'ruff format a.py && ruff check --fix a.py',
                    'cd /workspace/repo && ' + sync_write.format(path='tests/x.py') + 'ruff format tests/x.py',
                    'cat <<\'EOF\' > tests/test_queue.py\nimport redis\n\ndef test_push(r):\n    r.rpush("jobs", *[1, 2])\n    assert r.lrange("jobs", 0, -1) == [b"1", b"2"]\nEOF',
                    'cat <<\'EOF\' > tests/test_queue.py\ndef test_queue(r):\n    jobs = {}\n    r.lpush("jobs", 1)\n    assert r.lrange("jobs", 0, -1) == [b"1"]\nEOF',
                    'cat <<"EOF" > f.py\nr.rpush("q", [1])\nEOF',
                    'cat > f.py <<\'EOF\'\nr.rpush("q", [1])\nEOF',
                    'cd /w && cat <<-\'EOF\' >> f.py\n\tr.rpush("q", [1])\n\tEOF\ncat f.py',
                    'cd /w && cat >> f.py <<-"EOF"\n\tr.lpush("q", {})\n\tEOF',
                    'git merge origin/main', 'git fetch origin main && git merge origin/main',
                    'git -C /w status', 'git -C /w merge origin/main',
                    'git -c push.default=current status', 'git -C push-service status',
                    'git -C . status 2>&1', 'git log --grep push 2>/dev/null', 'git log >push',
                    'git -C /w commit -m "no push here"', 'git commit -m "push"', 'git log --grep push',
                    'git commit -m "no push here"', 'gh pr view 3', 'npm test', 'git status',
                    'git -C "$W" status', 'git -C "${W}" log --oneline -3',
                    "printf 'HEAD %s\\n' x; git -C \"$W\" status"]:
            assert not denied(hook('pre', {**writer, 'agent_type': agent, 'tool_input': {'command': cmd}}, env)), (agent, cmd)
    assert not denied(hook('pre', {'agent_type': 'ship:driver', 'tool_name': 'Bash', 'tool_input': {'command': 'git push'}}, env))
    assert denied(hook('pre', {**writer, 'tool_name': 'Write', 'tool_input': {'file_path': '/r/.claude/settings.local.json'}}, env))
    assert denied(hook('pre', {**writer, 'tool_name': 'Edit', 'tool_input': {'file_path': f'{tmp}/.claude/CLAUDE.md'}}, env))
    assert not denied(hook('pre', {**writer, 'tool_name': 'Edit', 'tool_input': {'file_path': '/r/src/app.py'}}, env))

    matcher = json.loads(HOOK.with_name('hooks.json').read_text())['hooks']['PreToolUse'][0]['matcher']
    for action in ['create_input', 'update_input', 'set_input_status']:
        tool = f'mcp__bettercoding__{action}'
        assert re.fullmatch(matcher, tool), tool
        for agent in ['ship:writer--sol', 'ship:writer--sonnet', 'ship:writer--fable52']:
            assert denied(hook('pre', {'agent_type': agent, 'tool_name': tool}, env)), (agent, tool)
        assert not denied(hook('pre', {'agent_type': 'ship:driver', 'tool_name': tool}, env)), tool
    for action in ['get_input', 'list_inputs', 'get_input_events']:
        assert not denied(hook('pre', {**writer, 'tool_name': f'mcp__bettercoding__{action}'}, env)), action

    researcher = {'agent_type': 'ship:researcher--luna', 'agent_id': 'r1', 'tool_name': 'mcp__fff__grep', 'tool_input': {}}
    for _ in range(40):
        assert not denied(hook('pre', researcher, env))
    assert denied(hook('pre', researcher, env))
    assert not denied(hook('pre', {**researcher, 'agent_id': 'r2'}, env))

    repo = Path(tmp, 'repo')
    repo.mkdir()
    git = lambda *a: subprocess.run(['git', '-C', str(repo), *a], check=True, capture_output=True)
    git('init', '-q', '-b', 'feat/x')
    git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'init')
    ledger = lambda *a: run([sys.executable, str(LEDGER), *a], cwd=repo)

    assert 'ship/ledger/feat__x.tsv' in ledger('path').stdout
    session = {'session_id': 's1', 'cwd': str(repo)}
    owed = Path(tmp, 'ultraship/owed/s1.tsv')
    hook('subagent-stop', {**session, 'agent_type': 'ship:reviewer--sol'}, env)
    assert not owed.exists() or owed.read_text() == ''
    assert hook('stop', session, env) == ''

    result = {'id': 'no-run', 'ledger': ledger('path').stdout.strip(), 'run': None}
    owed.parent.mkdir(parents=True, exist_ok=True)
    owed.write_text(f'{int(time.time())}\tship:reviewer--sol\t{repo}\t{json.dumps(result)}\n')
    assert hook('stop', session, env) == ''
    assert owed.read_text() == ''

    assert ledger('append', 'slices', 'a', 'sha', 'pass').returncode != 0
    assert ledger('run-start', 'light', 'run-1', '/b/board.md').returncode == 0
    assert ledger('run-start', 'light', 'run-2').returncode != 0
    assert ledger('gaps').returncode == 1
    assert 'refusing' in ledger('run-end').stderr

    assert 'Open ship run: run-1' in hook('compact', session, env)
    provenance = {'agent_id': 'reviewer-terminal-1',
                  'agent_transcript_path': str(Path(tmp, 'unopened-transcript.jsonl'))}
    hook('subagent-stop', {**session, 'agent_type': 'ship:reviewer--sol', **provenance}, env)
    result = json.loads(owed.read_text().split('\t')[3])
    assert {key: result.get(key) for key in provenance} == provenance
    assert uuid.UUID(result['id']).version == 4 and result['id'] != provenance['agent_id']
    assert result['run'] is not None and result['ledger'] == ledger('path').stdout.strip()
    assert set(result) == {'id', 'v', 'ledger', 'run', *provenance}
    assert not Path(provenance['agent_transcript_path']).exists()
    hook('subagent-stop', {**session, 'agent_type': 'ship:writer--sol'}, env)
    blocked = hook('stop', session, env)
    assert blocked['decision'] == 'block' and 'reviewer--sol' in blocked['reason']
    assert 'ship:reviewer--sol@reviewer-terminal-1' in blocked['reason']
    assert hook('stop', session, env) == ''
    assert ledger('append', 'deep-review', 'ship:reviewer--sol@reviewer-terminal-1', 'sha', 'pass').returncode == 0
    assert hook('stop', session, env) == ''

    metadata_cases = [({}, {}), *[({key: value}, {key: value}) for key, value in provenance.items()]]
    metadata_cases.extend(({'agent_id': value, 'agent_transcript_path': value}, {})
                          for value in (None, '', ' \t\n', 7, False, [], {}))
    for metadata, expected in metadata_cases:
        hook('subagent-stop', {**session, 'agent_type': 'ship:reviewer--sol', **metadata}, env)
        result = json.loads(owed.read_text().split('\t')[3])
        assert {key: result[key] for key in provenance if key in result} == expected, metadata
        assert set(result) == {'id', 'v', 'ledger', 'run', *expected}, metadata
        assert result['run'] is not None
        assert hook('stop', session, env)['decision'] == 'block'
        named = 'ship:reviewer--sol' + (f"@{expected['agent_id']}" if 'agent_id' in expected else '')
        assert ledger('append', 'deep-review', named, 'sha', 'pass').returncode == 0
        assert hook('stop', session, env) == ''

    hook('subagent-stop', {**session, 'agent_type': 'ship:reviewer--opus'}, env)
    for step in ['slices', 'simplify', 'deep-review', 'fix-read', 'pr', 'babysit', 'gate']:
        assert ledger('append', step, 'ship:reviewer--opus', 'sha', 'pass').returncode == 0
    assert hook('stop', session, env) == ''
    assert ledger('gaps').returncode == 0
    assert ledger('run-end').returncode == 0
    assert 'no open run' in ledger('status').stdout
    assert 'Open ship run' not in hook('compact', session, env)
    hook('subagent-stop', {**session, 'agent_type': 'ship:reviewer--sol'}, env)
    assert owed.read_text() == ''
    assert hook('stop', session, env) == ''

print('ultraship hooks: ok')


class PreInputTests(unittest.TestCase):
    def test_pre_denies_input_that_is_not_a_json_object(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = {**os.environ, 'HOME': temporary, 'XDG_STATE_HOME': temporary}
            for raw in ('', 'not json', '{', '[]', 'null', '"Bash"', '1'):
                with self.subTest(raw=raw):
                    result = subprocess.run([sys.executable, str(HOOK), 'pre'], input=raw,
                                            capture_output=True, text=True, env=env)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    output = json.loads(result.stdout or '{}').get('hookSpecificOutput', {})
                    self.assertEqual(output.get('permissionDecision'), 'deny')
                    self.assertEqual(output.get('permissionDecisionReason'), (
                        'The ship hook could not read its input as a JSON object, so it denies this call. '
                        'Report the blocked scope to the driver.'))


class ReceiptCustodyTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.state = Path(temporary).resolve() / 'custom-state'
        self.cwd = Path(temporary).resolve() / 'repo'
        self.cwd.mkdir()
        self.enterContext(patch.dict(os.environ, {'HOME': temporary, 'XDG_STATE_HOME': str(self.state)}))
        self.store = self.state / 'ultraship' / 'text-lint'

    def assert_custody_denial(self, event, reason=(
            'Only the text_lint hook reads or writes refusal receipts (custody rule). '
            'Report the blocked scope to the driver.')):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit:
            ultraship.guarded_pre({'cwd': str(self.cwd), **event})
        self.assertEqual(exit.exception.code, 0)
        result = json.loads(output.getvalue())['hookSpecificOutput']
        self.assertEqual(result['permissionDecision'], 'deny')
        self.assertEqual(result['permissionDecisionReason'], reason)

    def own_account_event(self):
        os.environ.pop('XDG_STATE_HOME', None)
        state = Path(os.environ['HOME']) / '.local/state/ultraship'
        self.enterContext(patch.object(ultraship, 'STATE', state))
        self.account_words = ['python3', str(LEDGER), 'account', str(state / 'owed/session-context.tsv'),
                              '12345678-1234-1234-1234-123456789abc', 'slice-review',
                              'ship:reviewer--sol@reviewer-a', 'abcdef1', 'pass', 'reviewed context, [P2] nit']
        return {'session_id': 'session-context', 'agent_type': '', 'tool_name': 'Bash',
                'tool_input': {'command': shlex.join(self.account_words)}}

    def test_own_account_call_allows_main_and_driver(self):
        event = self.own_account_event()
        for caller in ('', 'ship:driver', 'driver', 'ship:driver--sol'):
            for ledger in (str(LEDGER), '"' + str(LEDGER) + '"'):
                command = shlex.join(self.account_words).replace(str(LEDGER), ledger, 1)
                with self.subTest(caller=caller, ledger=ledger):
                    output = io.StringIO()
                    with redirect_stdout(output), redirect_stderr(io.StringIO()):
                        self.assertIsNone(ultraship.guarded_pre(
                            {'cwd': str(self.cwd), **event, 'agent_type': caller,
                             'tool_input': {'command': command}}))
                    self.assertEqual(output.getvalue(), '')

        for evidence in ('"reviewed context, [P2] nit"', r"'Reviewer'\''s [P2] context'"):
            command = shlex.join(self.account_words[:-1]) + ' ' + evidence
            with self.subTest(evidence=evidence):
                output = io.StringIO()
                with redirect_stdout(output), redirect_stderr(io.StringIO()):
                    self.assertIsNone(ultraship.guarded_pre(
                        {'cwd': str(self.cwd), **event, 'tool_input': {'command': command}}))
                self.assertEqual(output.getvalue(), '')

    def test_stop_account_diagnostic_admits_quoted_paths(self):
        event = self.own_account_event()
        home = Path(os.environ['HOME']) / 'home with space'
        state = home / '.local/state/ultraship'
        script = self.cwd / 'plugin with space/ledger.py'
        with patch.dict(os.environ, {'HOME': str(home)}), \
                patch.object(ultraship, 'STATE', state), \
                patch.object(ultraship, 'ledger_script', return_value=script), \
                patch.object(ultraship, 'load_ledger', return_value=None), \
                patch.object(ultraship, 'account', side_effect=ValueError('synthetic missing review')):
            pending = ultraship.owed_file(event)
            pending.parent.mkdir(parents=True)
            pending.write_text('100\tship:reviewer--sol\t' + str(self.cwd) + '\t' +
                               json.dumps({'id': self.account_words[4], 'v': 2}) + '\n')
            output = io.StringIO()
            with redirect_stdout(output):
                ultraship.stop(event)
            diagnostic = json.loads(output.getvalue())
            self.assertEqual(diagnostic['decision'], 'block')
            commands = re.findall(r'`([^`]* account [^`]*)`', diagnostic['reason'])
            self.assertEqual(len(commands), 1)
            command = commands[0]
            for placeholder, value in zip(('<result-id>', '<step>', '<agent>', '<sha>', '<verdict>', '<evidence>'),
                                          self.account_words[4:]):
                command = command.replace(placeholder, value)
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(io.StringIO()):
                self.assertIsNone(ultraship.guarded_pre(
                    {'cwd': str(self.cwd), **event, 'tool_input': {'command': command}}))
            self.assertEqual(output.getvalue(), '')

    def test_own_account_call_denies_other_commands_and_callers(self):
        event = self.own_account_event()
        command = event['tool_input']['command']
        commands = [command.replace('session-context.tsv', 'sibling-context.tsv'),
                    command.replace(str(LEDGER), str(self.cwd / 'ledger.py')),
                    shlex.join(self.account_words[:-1]), command + ' extra',
                    'cd ' + str(self.cwd) + ' && ' + command]
        commands.extend(command.replace('python3', interpreter, 1)
                        for interpreter in ('python', 'python3 -I', 'env python3', 'bash -c'))
        commands.extend(command + suffix for suffix in
                        ('; echo done', ' && echo done', ' | cat', ' > output', '\necho done', '\n'))
        commands.extend(command.replace("'reviewed context, [P2] nit'", evidence) for evidence in
                        ('"$(echo context)"', '"`echo context`"', '"${HOME} context"', '$HOME',
                         'context*', 'context?', 'context[ab]', 'context{a,b}', 'context\\ text',
                         '"context!"', '"context\\text"', '"context\ntext"', "'context\ntext'"))
        commands.extend(shlex.join(self.account_words[:-1]) + ' ' + evidence for evidence in
                        ("'reviewed context';id", "'reviewed context'&&id", "'reviewed context'|cat",
                         "'reviewed context'>out", "'reviewed context'<in", "'reviewed context'(id)",
                         "\n'reviewed context'", '=ls'))
        commands.extend(command.replace(' account ', ' ' + subcommand + ' ', 1)
                        for subcommand in ('correct-binding', 'run-start'))
        for invalid in commands:
            with self.subTest(command=invalid):
                self.assert_custody_denial({**event, 'tool_input': {'command': invalid}})
        for caller in ('ship:writer--sol', 'ship:reviewer--sol', 'ship:driver-extra'):
            with self.subTest(caller=caller):
                self.assert_custody_denial({**event, 'agent_type': caller})

    def test_own_account_call_requires_session_and_valid_fields(self):
        event = self.own_account_event()
        for session in (None, '', 1):
            command = event['tool_input']['command']
            if session is None or session == '':
                command = command.replace('session-context.tsv', 'unknown.tsv')
            with self.subTest(session=session):
                self.assert_custody_denial({**event, 'session_id': session,
                                           'tool_input': {'command': command}})
        invalid_fields = ((4, '12345678-1234-1234-1234-123456789abC'), (4, 'invalid'),
                          (5, 'Slice-review'), (5, 'slice_review'), (6, 'reviewer@a@b'),
                          (7, 'abcdef'), (7, 'a' * 41), (7, 'ABCDEF1'),
                          (8, 'owed'), (8, 'pass!'), (9, ''))
        for index, value in invalid_fields:
            words = self.account_words.copy()
            words[index] = value
            with self.subTest(index=index, value=value):
                self.assert_custody_denial({**event, 'tool_input': {'command': shlex.join(words)}})

    def test_own_account_call_preserves_other_custody_checks(self):
        event = self.own_account_event()
        state = Path(os.environ['HOME']) / '.local/state'
        for evidence in (str(state / 'ultraship/text-lint/key'), 'ultraship/text-lint',
                         str(state), str(state / 'ultraship'), str(state / 'ultra*/t*/key'),
                         'text_lint hook', 'import text_lint'):
            words = [*self.account_words[:-1], evidence]
            with self.subTest(evidence=evidence):
                self.assert_custody_denial({**event, 'tool_input': {'command': shlex.join(words)}})
        self.assert_custody_denial({**event, 'cwd': str(state)})

    def test_printf_data_cannot_write_receipt_store(self):
        for caller in ('', 'ship:driver', 'ship:writer--sol'):
            with self.subTest(caller=caller):
                self.assert_custody_denial({
                    'agent_type': caller, 'tool_name': 'Bash',
                    'tool_input': {'command': "printf '%s\\n' 'bash before gh' > " + str(self.store / 'receipt.json')}})

    def test_plain_grep_text_lint_phrases_allow_every_caller(self):
        commands = ("grep -rn 'Only the text_lint hook reads or writes refusal receipts (custody rule).' .",
                    "grep -n 'text_lint.py hook' file.py",
                    "grep -rn 'import text_lint' .",
                    "grep -rn 'text_lint hook' sub")
        for caller in ('', 'ship:driver', 'ship:writer--sol'):
            for command in commands:
                with self.subTest(caller=caller, command=command):
                    output = io.StringIO()
                    with redirect_stdout(output), redirect_stderr(io.StringIO()):
                        self.assertIsNone(ultraship.guarded_pre(
                            {'cwd': str(self.cwd), 'agent_type': caller, 'tool_name': 'Bash',
                             'tool_input': {'command': command}}))
                    self.assertEqual(output.getvalue(), '')

    def test_text_lint_execution_and_nonplain_grep_deny_every_caller(self):
        script = str(self.cwd / 'text_lint.py')
        hook_command = 'python3 ' + script + ' hook'
        grep = 'grep -n "text_lint.py hook" ' + str(self.cwd / 'file.py')
        commands = ['python3 "' + script + '" hook', hook_command, 'python3 -m text_lint hook',
                    'python3 ' + script + ' "ho"ok',
                    'cd ' + str(self.cwd) + ' && python3 text_lint.py hook',
                    'cat payload.json | ' + hook_command,
                    'python3 -c "import runpy; runpy.run_path(\'' + script + '\')"',
                    'grep -n "$(' + hook_command + ')" ' + str(self.cwd),
                    'grep -n "`' + hook_command + '`" ' + str(self.cwd),
                    grep + ' > ' + str(self.cwd / 'output'),
                    'sh -c ' + shlex.quote(grep),
                    'rg --pre ' + shlex.quote(hook_command) + ' x',
                    'git grep -O' + shlex.quote(hook_command) + ' x',
                    'grep ' + shlex.quote('--filter=json:' + hook_command) + ' x p.json',
                    'grep --filter ' + shlex.quote('json:' + hook_command) + ' x p.json',
                    "grep 'text_lint hook' . --filter=x",
                    "grep --save-config=out -e 'text_lint hook' .",
                    "grep -Q 'text_lint hook' .", "grep -z 'text_lint hook' .",
                    'grep -n "text_lint.py hook" file.py',
                    'cd sub && python3 text_lint.py hook',
                    'find . -name x && ' + hook_command,
                    'find . -name x -exec python3 text_lint.py hook +',
                    "find . -fprint out -name 'text_lint hook'",
                    "cd sub && grep -rn 'text_lint hook' .",
                    "find . -name x && grep -rn 'text_lint hook' .",
                    "grep -rn 'text_lint hook' . && ls .",
                    "grep -rn 'a && b text_lint hook' .",
                    'ls text_lint.py hook',
                    "find . -name 'text_lint hook'",
                    'grep\xa0/usr/bin/python3 ' + script + ' hook',
                    "grep\xa0-rn 'text_lint hook' .",
                    "grep -rn 'text_lint hook'\N{IDEOGRAPHIC SPACE}.",
                    "grep -rn 'text_lint hook' .\r"]
        commands.extend(prefix + grep for prefix in ('env ', 'command '))
        commands.extend(grep.replace('grep', program, 1) for program in ('egrep', '/usr/bin/grep'))
        commands.extend(grep + before + separator + after + hook_command
                        for separator in (';', '&&', '|', '\n')
                        for before, after in (('', ''), (' ', ' ')))
        for caller in ('', 'ship:driver', 'ship:writer--sol'):
            for command in commands:
                with self.subTest(caller=caller, command=command):
                    self.assert_custody_denial({'agent_type': caller, 'tool_name': 'Bash',
                                               'tool_input': {'command': command}})

    def test_plain_grep_preserves_other_custody_checks(self):
        grep = "grep -rn 'text_lint.py hook' "
        commands = (grep + str(self.store / 'key'), grep + str(self.state),
                    grep + shlex.quote(str(self.state / 'ultra*/t*/key')),
                    grep + shlex.quote('${XDG_STATE_HOME}/row-review'),
                    grep + shlex.quote('$HOME/.local/s*'),
                    'ls ' + str(self.state) + '/ultra*/t*/key text_lint.py hook',
                    'ls ' + str(self.cwd / '.local') + '/s* text_lint.py hook',
                    grep + str(self.cwd))
        for caller in ('', 'ship:driver', 'ship:writer--sol'):
            for command in commands:
                cwd = self.state if command == commands[-1] else self.cwd
                with self.subTest(caller=caller, command=command, cwd=cwd):
                    self.assert_custody_denial({'cwd': str(cwd), 'agent_type': caller, 'tool_name': 'Bash',
                                               'tool_input': {'command': command}})

    def test_bash_store_glob_prefixes_deny_every_caller(self):
        patterns = ('ultra*/t*/pending/[0-9a-f]*',
                    'ultra*/t*/receipts/' + '?' * 32 + '.json',
                    'ultra*/text-*/key')
        for caller in ('ship:writer--sol', 'ship:driver', ''):
            for pattern in patterns:
                with self.subTest(caller=caller, pattern=pattern):
                    self.assert_custody_denial({'agent_type': caller, 'tool_name': 'Bash',
                                               'tool_input': {'command': 'cat ' + str(self.state / pattern)}})

    def test_bash_state_shortcuts_deny_every_caller(self):
        for caller in ('ship:writer--sol', 'ship:driver', ''):
            for command in ('cd ~/.local/state/ultraship && cat text-lint/key',
                            'cd ~/.local/sta*', 'ls $HOME/.local/s*',
                            'pushd ~/.local/state/ultraship',
                            'cat ~/.local/state/ultraship/text-lint/key') + tuple(
                                'ls $HOME/.local/' + suffix
                                for suffix in ('staging', 's*', 's?', 's[', 's{', '*', '?', '[', '{', '$', '')):
                with self.subTest(caller=caller, command=command):
                    self.assert_custody_denial({'agent_type': caller, 'tool_name': 'Bash',
                                               'tool_input': {'command': command}})

    def test_bash_state_ancestors_deny_every_caller(self):
        for caller in ('ship:writer--sol', 'ship:driver', ''):
            for command in ('rm -rf ' + str(self.state / 'ultraship'),
                            'rm -rf ' + str(self.state),
                            'grep -r . ' + str(self.state / 'ultraship')):
                with self.subTest(caller=caller, command=command):
                    self.assert_custody_denial({'agent_type': caller, 'tool_name': 'Bash',
                                               'tool_input': {'command': command}})

    def test_bash_ordinary_paths_allow_every_caller(self):
        for caller in ('ship:writer--sol', 'ship:driver', ''):
            for command in ('PATH="/home/miguel/.local/share/uv-0.12/bin:$PATH" make openapi api-types preview-mask-sql',
                            'PATH="${HOME}/.local/bin:${PATH}" make -r test',
                            'ls ' + str(self.state / 'ultraship/owed/x.tsv'),
                            'ls ' + os.environ['HOME'], 'ls /'):
                with self.subTest(caller=caller, command=command):
                    output = io.StringIO()
                    with redirect_stdout(output), redirect_stderr(io.StringIO()):
                        self.assertIsNone(ultraship.guarded_pre({'cwd': str(self.cwd), 'agent_type': caller,
                                                              'tool_name': 'Bash',
                                                              'tool_input': {'command': command}}))
                    self.assertEqual(output.getvalue(), '')

    def test_ordinary_calls_allow_every_caller(self):
        """Catch custody checks that deny ordinary calls for a writer, driver or main session."""
        inputs = (('Edit', {'file_path': str(self.cwd / 'file.py'), 'old_string': 'old', 'new_string': 'new'}),
                  ('Write', {'file_path': str(self.cwd / 'file.py'), 'content': 'new'}),
                  ('NotebookEdit', {'notebook_path': str(self.cwd / 'file.ipynb'), 'new_source': 'print(1)'}),
                  ('Agent', {'subagent_type': 'ship:writer--sol', 'description': 'Check file',
                             'prompt': 'Check the file.'}),
                  ('WebSearch', {'query': 'Python documentation'}),
                  ('SendMessage', {'type': 'message', 'recipient': 'main', 'content': 'Ready.'}))
        for caller in ('ship:writer--sol', 'ship:driver', ''):
            for tool, tool_input in inputs:
                with self.subTest(caller=caller, tool=tool):
                    output = io.StringIO()
                    with redirect_stdout(output), redirect_stderr(io.StringIO()):
                        self.assertIsNone(ultraship.guarded_pre({'cwd': str(self.cwd), 'agent_type': caller,
                                                              'tool_name': tool, 'tool_input': tool_input}))
                    self.assertEqual(output.getvalue(), '')

    def test_pre_error_denies_non_read_tools_for_every_caller(self):
        """Catch tool calls escaping a pre failure outside receipt custody or reviewer checks."""
        inputs = (('Bash', {'command': 'ls'}),
                  ('Edit', {'file_path': str(self.cwd / 'file.py'), 'old_string': 'old', 'new_string': 'new'}),
                  ('Write', {'file_path': str(self.cwd / 'file.py'), 'content': 'new'}),
                  ('NotebookEdit', {'notebook_path': str(self.cwd / 'file.ipynb'), 'new_source': 'print(1)'}),
                  ('Agent', {'subagent_type': 'ship:writer--sol', 'description': 'Check file',
                             'prompt': 'Check the file.'}),
                  ('WebSearch', {'query': 'Python documentation'}))
        for caller in ('ship:writer--sol', 'ship:driver', ''):
            for tool, tool_input in inputs:
                output, errors = io.StringIO(), io.StringIO()
                with self.subTest(caller=caller, tool=tool), \
                        patch.object(ultraship, 'pre', side_effect=RuntimeError('pre failed')):
                    with redirect_stdout(output), redirect_stderr(errors), self.assertRaises(SystemExit) as exit:
                        ultraship.guarded_pre({'cwd': str(self.cwd), 'agent_type': caller,
                                              'tool_name': tool, 'tool_input': tool_input})
                    self.assertEqual(exit.exception.code, 0)
                    result = json.loads(output.getvalue())['hookSpecificOutput']
                    self.assertEqual(result['permissionDecision'], 'deny')
                    self.assertEqual(result['permissionDecisionReason'],
                                     'The ship hook failed, so it denies every tool call. Its traceback is on stderr. '
                                     'Report the blocked scope to the driver.')
                    self.assertIn('Traceback (most recent call last):', errors.getvalue())
                    self.assertIn('RuntimeError: pre failed', errors.getvalue())

    def test_pre_error_denies_malformed_tool_names(self):
        """Catch malformed tool names escaping denial through an error in the custody fallback."""
        for tool in (None, 1, ['Read'], {'name': 'Read'}):
            with self.subTest(tool=tool), patch.object(ultraship, 'pre', side_effect=RuntimeError('pre failed')):
                self.assert_custody_denial(
                    {'tool_name': tool, 'tool_input': {}},
                    'The ship hook failed, so it denies every tool call. Its traceback is on stderr. '
                    'Report the blocked scope to the driver.')

    def test_custody_error_denies_every_tool_for_every_caller(self):
        """A failed custody check cannot permit any tool for a writer, driver or main session."""
        inputs = (('Bash', {'command': 'ls'}),
                  ('Edit', {'file_path': str(self.cwd / 'file.py'), 'old_string': 'old', 'new_string': 'new'}),
                  ('Write', {'file_path': str(self.cwd / 'file.py'), 'content': 'new'}),
                  ('NotebookEdit', {'notebook_path': str(self.cwd / 'file.ipynb'), 'new_source': 'print(1)'}),
                  ('Agent', {'subagent_type': 'ship:writer--sol', 'description': 'Check file',
                             'prompt': 'Check the file.'}),
                  ('SendMessage', {'type': 'message', 'recipient': 'main', 'content': 'Ready.'}))
        for caller in ('ship:writer--sol', 'ship:driver', ''):
            for tool, tool_input in inputs:
                with self.subTest(caller=caller, tool=tool), \
                        patch.object(ultraship, 'receipt_custody', side_effect=OSError('custody failed')):
                    self.assert_custody_denial(
                        {'agent_type': caller, 'tool_name': tool, 'tool_input': tool_input},
                        'The ship hook could not check refusal-receipt custody, so it denies this call. '
                        'Report the blocked scope to the driver.')

    def test_role_failure_keeps_writer_read_custody_closed(self):
        with patch.object(ultraship, 'role', side_effect=RuntimeError('role failed')):
            self.assert_custody_denial({'agent_type': 'ship:writer--sol', 'tool_name': 'Read',
                                       'tool_input': {'file_path': str(self.store / 'key')}})

    def test_custody_failure_denies_read_and_search_for_every_caller(self):
        for caller in ('ship:writer--sol', 'ship:driver', ''):
            for tool in ('Read', 'Grep', 'Glob', 'LSP', 'mcp__fff__grep', 'mcp__fff__multi_grep'):
                with self.subTest(caller=caller, tool=tool), \
                        patch.object(ultraship, 'pre', side_effect=RuntimeError('pre failed')), \
                        patch.object(ultraship, 'receipt_custody', side_effect=OSError('custody failed')):
                    self.assert_custody_denial({'agent_type': caller, 'tool_name': tool, 'tool_input': {}})


class WorkspaceRowAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.workspace = self.root / 'workspace'
        self.cwd = self.workspace / 'repo/nested'
        self.cwd.mkdir(parents=True)
        self.row = self.workspace / 'repo/tests/mutation/example.toml'
        self.row.parent.mkdir(parents=True)
        self.row.write_text('')
        self.record = self.workspace / '.scratch/ultraship/row-review/r1.json'
        self.record.parent.mkdir(parents=True)
        self.env = {**os.environ, 'HOME': str(self.root), 'XDG_STATE_HOME': str(self.root / 'state')}
        self.payload = {'agent_type': 'ship:reviewer--sol', 'agent_id': 'r1', 'cwd': str(self.cwd),
                        'tool_name': 'Read', 'tool_input': {'file_path': str(self.row)}}
        self.fields = {'pr': 'https://github.com/example/repo/pull/1', 'agent_id': 'r1',
                       'row_files': [str(self.row)],
                       'expires_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() + 3600))}

    def write_record(self, path=None, **fields):
        path = path or self.record
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**self.fields, **fields}))
        path.chmod(0o600)

    def test_valid_workspace_record_uses_nearest_workspace(self):
        self.write_record(self.root / '.scratch/ultraship/row-review/r1.json')
        self.assertTrue(denied(hook('pre', self.payload, self.env)))
        self.write_record()
        for cwd in (self.workspace, self.cwd):
            for tool, inputs in (('Read', {'file_path': str(self.row)}),
                                 ('Grep', {'path': str(self.row), 'pattern': 'id'})):
                with self.subTest(cwd=cwd, tool=tool):
                    self.assertFalse(denied(hook('pre', {**self.payload, 'cwd': str(cwd),
                                                        'tool_name': tool, 'tool_input': inputs}, self.env)))
        self.record.unlink()
        self.write_record(self.root / 'state/ultraship/row-review/r1.json')
        self.assertFalse(denied(hook('pre', self.payload, self.env)))

    def test_workspace_record_symlink_is_denied(self):
        target = self.root / 'record.json'
        self.write_record(target)
        self.record.symlink_to(target)
        result = hook('pre', self.payload, self.env)
        self.assertTrue(denied(result))
        self.assertIn('the record is missing or is a link', result['hookSpecificOutput']['permissionDecisionReason'])

    def test_workspace_record_symlinked_parent_is_denied(self):
        self.write_record()
        for parent in (self.workspace / '.scratch', self.record.parent.parent, self.record.parent):
            with self.subTest(parent=parent):
                target = self.root / 'unprotected-records'
                parent.rename(target)
                parent.symlink_to(target, target_is_directory=True)
                try:
                    result = hook('pre', self.payload, self.env)
                    self.assertTrue(denied(result))
                    self.assertIn('the record parent has no symlink components',
                                  result['hookSpecificOutput']['permissionDecisionReason'])
                finally:
                    parent.unlink()
                    target.rename(parent)

    def test_workspace_record_world_writable_is_denied(self):
        self.write_record()
        self.record.chmod(0o606)
        result = hook('pre', self.payload, self.env)
        self.assertTrue(denied(result))
        self.assertIn('not group or world writable', result['hookSpecificOutput']['permissionDecisionReason'])

    def test_workspace_record_expiry_is_denied(self):
        self.write_record(expires_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - 60)))
        result = hook('pre', self.payload, self.env)
        self.assertTrue(denied(result))
        self.assertIn('later than now and at most 4 hours ahead', result['hookSpecificOutput']['permissionDecisionReason'])

    def test_workspace_record_for_another_agent_is_denied(self):
        self.write_record(agent_id='r2')
        result = hook('pre', self.payload, self.env)
        self.assertTrue(denied(result))
        self.assertIn('`agent_id` equals your agent ID', result['hookSpecificOutput']['permissionDecisionReason'])

    def assert_workspace_record_write_denied(self, tool):
        alias = self.root / 'record-folder'
        alias.symlink_to(self.record.parent, target_is_directory=True)
        targets = (self.record,) if tool == 'Bash' else (self.record, alias / self.record.name)
        for target in targets:
            inputs = ({'command': f'echo invalid > {target}'} if tool == 'Bash' else
                      {'notebook_path' if tool == 'NotebookEdit' else 'file_path': str(target)})
            for agent in ('ship:writer--sol', 'ship:reviewer--sol', 'Explore'):
                with self.subTest(tool=tool, target=target, agent=agent):
                    result = hook('pre', {**self.payload, 'agent_type': agent,
                                          'tool_name': tool, 'tool_input': inputs}, self.env)
                    self.assertTrue(denied(result))
                    self.assertIn('Only the driver and the main session',
                                  result['hookSpecificOutput']['permissionDecisionReason'])
            for agent in ('ship:driver', ''):
                with self.subTest(tool=tool, target=target, agent=agent):
                    self.assertFalse(denied(hook('pre', {**self.payload, 'agent_type': agent,
                                                        'tool_name': tool, 'tool_input': inputs}, self.env)))

    def test_workspace_record_write_through_symlinked_parent_is_denied(self):
        target = self.root / 'unprotected-records'
        self.record.parent.rename(target)
        self.record.parent.symlink_to(target, target_is_directory=True)
        for tool in ('Edit', 'Write', 'NotebookEdit'):
            with self.subTest(tool=tool):
                inputs = {'notebook_path' if tool == 'NotebookEdit' else 'file_path': str(self.record)}
                result = hook('pre', {**self.payload, 'agent_type': 'ship:writer--sol',
                                      'tool_name': tool, 'tool_input': inputs}, self.env)
                self.assertTrue(denied(result))
                self.assertIn('Only the driver and the main session',
                              result['hookSpecificOutput']['permissionDecisionReason'])

    def test_workspace_record_edit_is_denied(self):
        self.assert_workspace_record_write_denied('Edit')

    def test_workspace_record_write_is_denied(self):
        self.assert_workspace_record_write_denied('Write')

    def test_workspace_record_notebook_edit_is_denied(self):
        self.assert_workspace_record_write_denied('NotebookEdit')

    def test_workspace_record_bash_write_is_denied(self):
        self.assert_workspace_record_write_denied('Bash')


class PythonHeredocGuardTests(unittest.TestCase):
    def test_writer_named_process_heredoc_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, 'XDG_STATE_HOME': tmp, 'HOME': tmp}
            command = "echo ready\npython3 - <<'PY'\nimport subprocess\nsubprocess.run(['git', 'pu' + 'sh'])\nPY\n"
            result = hook('pre', {'agent_type': 'ship:writer--sol', 'tool_name': 'Bash',
                                  'tool_input': {'command': command}}, env)
            self.assertTrue(denied(result))
            self.assertIn('process-capable heredoc rule', result['hookSpecificOutput']['permissionDecisionReason'])

    def test_python_heredoc_executable_remainder_is_refused(self):
        cases = (
            ('import subprocess', 'wt switch --create lane', True),
            ('import subprocess', 'cat receipt.txt', False),
            ('pass', 'wt switch --create lane', False),
        )
        for body, remainder, expected in cases:
            with self.subTest(body=body, remainder=remainder):
                command = f"set -e && python3 -I - <<'PY'\n{body}\nPY\n{remainder}\n"
                self.assertEqual(ultraship.runs_heredoc_output(command), expected)

    def test_isolated_computed_path_reads_are_inert(self):
        reads = ("import hashlib\nfrom pathlib import Path\nroot = Path('/repo')\nfor name in ['a', 'b']:\n"
                 "    print(hashlib.sha256((root / name).read_bytes()).hexdigest())")
        writes = "from pathlib import Path\nroot = Path('/repo')\n(root / 'x.sh').write_text('x')"
        # Columns: interpreter, body, remainder, heredoc-then-run verdict, isolated inert verdict (None: not pinned).
        cases = (
            ('python3 -I -', reads, 'git add a b && git commit -m fix', False, True),
            ('python3 -', reads, 'git add a b && git commit -m fix', True, None),
            ('python3 -I -', writes, 'sh /repo/x.sh', True, None),
            ('python3 -I -', "from pathlib import Path\nroot = Path('/repo')\n(root / 'x.sh').chmod(0o755)",
             'sh /repo/x.sh', True, None),
            ('python3 -I -', "from pathlib import Path\nPath.open('t', 'w').write('x')", 'sh t', True, False),
            ('python3 -I -', "from pathlib import Path\nk = Path\nk.open('t', 'w').write('x')", 'sh t', True, False),
            ('python3 -I -', "import pathlib\npathlib.Path.open('t', 'w').write('x')", 'sh t', True, False),
            ('python3 -I -', "from pathlib import Path\ntype(Path('/repo')).open('t', 'w').write('x')", 'sh t', True, False),
            ('python3 -I -', "from pathlib import Path\nk = Path\nk.replace(Path('/w/x.txt'), '/w/traceback.py')",
             'sh t', True, False),
        )
        for interpreter, body, remainder, expected, isolated_inert in cases:
            with self.subTest(interpreter=interpreter, body=body, remainder=remainder):
                command = f"cd /repo && {interpreter} <<'PY'\n{body}\nPY\n{remainder}\n"
                self.assertEqual(ultraship.runs_heredoc_output(command), expected)
                if isolated_inert is not None:
                    self.assertEqual(ultraship.inert_python(body, isolated=True), isolated_inert)


class WriterGitHubGuardTests(unittest.TestCase):
    def test_writer_main_refused_data_shapes_remain_denied(self):
        for command in ("gh pr view 1 '--jq=[{title: .title}]'",
                        "gh pr view 1 '--template={{.title}}'", "gh api -X GET search/issues -f 'ref=*'"):
            with self.subTest(command=command):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_comment_continuation_cannot_hide_next_command(self):
        command = 'gh pr view 1 # comment ' + '\\' + '\n' + 'gh repo sync o/r'
        result = hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)
        self.assertTrue(denied(result))
        self.assertIn('Writers may run only read-only gh commands.',
                      result['hookSpecificOutput']['permissionDecisionReason'])

    def test_writer_heredoc_quote_cannot_hide_following_command_in_data(self):
        command = "tee <<EOF\ngh pr view 1 -q '\nEOF\ngh issue close 1 # '\n"
        result = hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)
        self.assertTrue(denied(result))
        self.assertIn('Writers may run only read-only gh commands.',
                      result['hookSpecificOutput']['permissionDecisionReason'])

    def test_writer_redirect_data_and_nested_git_words_cannot_hide_commands(self):
        for command in ('gh pr view 1 & >-q gh issue close 1',
                        "flock git --command 'gh issue close 1'",
                        "parallel git ';gh issue close 1 #' ::: x"):
            with self.subTest(command=command):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_final_control_path_shapes_are_denied(self):
        for command in ('echo {x,.git/config}', 'echo {a/b,c}', "bash -c 'cat .git/config'",
                        'echo a,.git,b', 'custom-write -xo.git/x', 'cat ~/.gitconfig',
                        'echo x >> ~/.config/git/config', 'cp a /srv/r.git/hooks/pre-commit',
                        'git init --template=/tmp/t',
                        'git clone --separate-git-dir=/tmp/g https://example.com/o/r.git',
                        'git-config alias.x log', 'git-commit -e', 'export GIT_EDITOR',
                        'read GIT_EDITOR', 'printf -v EDITOR %s x', 'declare PAGER',
                        'git --git-dir=/tmp/x status', 'git --git-dir . status',
                        'git --work-tree=/tmp/w status', 'git --work-tree=./ status',
                        "env -S 'a\\_b'", "env -S '${HOME}/x'", "env -S 'ls #x'",
                        "env -iS'ls #x'", "env --spl='a\\_b'", "env -0S'${HOME}/x'"):
            with self.subTest(command=command):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_native_external_config_and_sequencer_paths_are_denied(self):
        for target in ('~/.gitconfig', '~/.config/git/config', '/srv/r.git/config',
                       '.git/rebase-merge/git-rebase-todo', '.git/rebase-apply/patch', '.git/sequencer/todo'):
            for tool in ('Edit', 'Write', 'NotebookEdit'):
                key = 'notebook_path' if tool == 'NotebookEdit' else 'file_path'
                with self.subTest(target=target, tool=tool):
                    self.assertTrue(denied(hook('pre', {**self.writer, 'tool_name': tool,
                                                      'cwd': str(self.repo), 'tool_input': {key: target}}, self.env)))

    def test_writer_control_path_symlinks_use_input_cwd(self):
        (self.repo / '.git').mkdir()
        (self.repo / 'control-link').symlink_to(self.repo / '.git', target_is_directory=True)
        result = hook('pre', {**self.writer, 'cwd': str(self.repo),
                              'tool_input': {'command': 'cat control-link/config'}}, self.env)
        self.assertTrue(denied(result))

    def test_writer_final_shape_plain_controls_are_admitted(self):
        for command in ('ls .gitignore', 'cat .github/workflows/validate.yml', 'ls /repo/*',
                        'git --work-tree=. status',
                        'git clone --config core.pager=cat https://example.com/o/r.git',
                        'git rev-parse --git-dir', 'ls r.git', "echo '{a/b,c}'"):
            with self.subTest(command=command):
                self.assertFalse(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_git_component_shapes_are_denied(self):
        for command in ('git status; git arbitrary-write .git/config',
                        'custom-write --output=.git/config', 'custom-write -o.git/x',
                        'git diff --output .git/config', 'git diff --output=.git/hooks/pre-commit',
                        'git log -o.git/x', 'git config --file .git/config --get user.name',
                        'git config --bool --get core.bare',
                        'custom-write .g?t/config', 'pushd .git', 'env -C .git ls',
                        "cat .G''IT/config", 'ls .g*/config', 'echo {.g,x}it',
                        'echo .g{i,x}t', 'cat .git/config', 'head .git/config', 'ls .git/hooks',
                        'git --git-dir=.git status', 'git --git-dir .git status'):
            with self.subTest(command=command):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_noncontrol_dot_paths_and_globs_are_admitted(self):
        for command in ('ls .gitignore', 'cat .github/workflows/validate.yml', 'ls /repo/*',
                        'ls ?git', "ls '.g?t/config'", 'ls .gift/config'):
            with self.subTest(command=command):
                self.assertFalse(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_quote_identity_and_all_data_method_flags_are_denied(self):
        for command in ("echo '*'; gh pr view 1 -q *", "echo '[x]'; gh pr view 1 --jq [x]",
                        "gh pr view 1 -q 'ref=-X POST'", "gh pr view 1 -H 'ref=--method POST'",
                        "gh pr view 1 --template='-XPOST'", "gh pr view 1 --jq=--method=POST"):
            with self.subTest(command=command):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_parsed_git_control_operands_are_denied(self):
        commands = (
            "echo x > .g''it/config", 'echo x > .git/config', 'echo x 2> .git/config',
            'echo x &> .git/hooks/pre-commit', 'echo x >|.git/config', 'echo x >>.git/config',
            'echo x 2>.git/config', 'echo x &>.git/hooks/pre-commit',
            'cd .git', 'cd .git/hooks', 'echo x > .git/modules/sub/config',
            'echo x > .git/modules/sub/nested/config.worktree',
            'echo x > .git/modules/sub/commondir', 'echo x > .git/modules/sub/gitdir',
            'echo x > .git/modules/sub/hooks/pre-commit', 'echo x > .GIT/CONFIG',
            'echo x > .git', 'custom-write .git/config', 'custom-write .git/modules/sub/config',
            'git --git-dir=/other/repo/.git status', 'git --work-tree=/other/repo status',
            'git --git-dir /other/repo/.git status', 'git --work-tree /other/repo status',
            'git --git-dir="$G" status', 'git --work-tree="$W" status',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))
        for target in ('.git', '.GIT/CONFIG', '.git/modules/sub/config', '.git/modules/sub/config.worktree',
                       '.git/modules/sub/commondir', '.git/modules/sub/gitdir',
                       '.git/modules/sub/hooks/pre-commit'):
            for tool in ('Edit', 'Write', 'NotebookEdit'):
                key = 'notebook_path' if tool == 'NotebookEdit' else 'file_path'
                with self.subTest(target=target, tool=tool):
                    self.assertTrue(denied(hook('pre', {**self.writer, 'tool_name': tool,
                                                      'cwd': str(self.repo), 'tool_input': {key: target}}, self.env)))

    def test_writer_current_worktree_selectors_are_admitted(self):
        for command in ('git --work-tree=. status', 'git --work-tree . status'):
            with self.subTest(command=command):
                self.assertFalse(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_attached_quoted_command_operands_are_denied(self):
        for command in ("env -S'gh pr merge 1'", "env -iS'gh pr merge 1'",
                        "env -vS'gh pr merge 1'", "env -0S'gh pr merge 1'",
                        '\"g\"\"h\" pr merge 1', "sh -c'gh pr merge 1'",
                        "bash -c'gh pr merge 1'", "env --split-string='gh pr merge 1'",
                        "env -S'\"g\"\"h\" pr merge 1'"):
            with self.subTest(command=command):
                result = hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)
                self.assertTrue(denied(result))
                self.assertIn('Rule:', result['hookSpecificOutput']['permissionDecisionReason'])
                self.assertIn('driver', result['hookSpecificOutput']['permissionDecisionReason'])

    def test_writer_env_zero_split_and_post_filter_globs_are_denied(self):
        for command in ("env '-0SGIT_EDITOR=vim git status'", "env '-0iSGIT_EDITOR=vim git status'",
                        "gh pr view 1 -q .x 'a*'"):
            with self.subTest(command=command):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_global_git_values_cannot_hide_config(self):
        for option, value in (('--git-dir', '/repo/.git'), ('--work-tree', '/repo'),
                              ('--namespace', 'lane'), ('--super-prefix', 'prefix'),
                              ('--attr-source', 'HEAD')):
            command = f'git {option} {value} -c core.editor=/tools/editor-helper commit'
            with self.subTest(command=command):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_exclude_flags_and_attached_data_are_admitted(self):
        for command in ("git ls-files --others -e '*.lock'", "git clean -n -e '*.lock'",
                        'gh api -X GET repos/o/r/contents/env --field=ref=gh',
                        'gh api -X GET repos/o/r/contents/env -fref=gh',
                        'gh api -X GET repos/o/r/contents/env --raw-field=ref=gh',
                        'gh pr view 1 -q.title', "gh pr view 1 '--header=ref=gh'"):
            with self.subTest(command=command):
                self.assertFalse(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_attached_expansions_and_editor_long_options_are_denied(self):
        for command in ('gh api -X GET repos/o/r/issues --field={ref=main,-X,POST}',
                        'gh api -X GET repos/o/r/issues -f{ref=main,-X,POST}',
                        'gh api -X GET repos/o/r/issues --field=ref=-XPOST',
                        'gh pr view 1 --jq=[{title:.title}]',
                        'git grep --edit pattern', 'git ls-files --edit', 'git clean --edit',
                        'git grep --fixup=amend:HEAD', 'git clean --fixup=reword:HEAD'):
            with self.subTest(command=command):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_field_expansions_and_method_values_are_denied(self):
        commands = (
            'gh api -X GET repos/o/r/issues -f {ref=main,-X,POST}',
            'gh api -X GET repos/o/r/issues -f *',
            "gh api -X GET repos/o/r/issues -f 'ref=-X POST'",
            "gh api -X GET repos/o/r/issues -f 'ref=--method POST'",
            'gh api -X GET repos/o/r/issues --field=ref=-XPOST',
            'gh api -X GET repos/o/r/issues --raw-field=ref=--method=POST',
            'gh pr view 1 -q [{title:.title}]',
            'gh pr view 1 -H *',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_stored_git_configuration_writes_are_denied(self):
        commands = (
            'git clone --config core.editor=vim https://example.com/o/r.git',
            'git clone --config=core.editor=vim https://example.com/o/r.git',
            'git config core.editor vim', 'git config --add core.pager less',
            'git config --replace-all core.pager less', 'git config --unset core.pager',
            'git config --unset-all core.pager', 'git config set core.editor vim',
            'git config --global core.editor vim', 'git config --rename-section core old',
            'git config --remove-section core', 'git config --edit',
            'git config core.hooksPath /tools', 'git -c core.hooksPath=/tools status',
            'git clone --config core.hooksPath=/tools https://example.com/o/r.git',
            'git config --get core.pager --add',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_git_control_file_writes_are_denied(self):
        for target in ('.git/config', '.git/config.worktree', '.git/hooks/pre-commit',
                       '.git/worktrees/lane/config', '.git/worktrees/lane/config.worktree',
                       '.git/worktrees/lane/hooks/pre-commit'):
            for tool in ('Edit', 'Write', 'NotebookEdit'):
                key = 'notebook_path' if tool == 'NotebookEdit' else 'file_path'
                with self.subTest(target=target, tool=tool):
                    self.assertTrue(denied(hook('pre', {**self.writer, 'tool_name': tool,
                                                      'cwd': str(self.repo), 'tool_input': {key: target}}, self.env)))
            for command in (f'echo value > {target}', f'printf value >> "{target}"',
                            f'cat <<\'EOF\' > {target}\nvalue\nEOF\n',
                            f'printf value | tee {target}', f'cp source {target}',
                            f'mv source {target}', f'install source {target}',
                            f'touch {target}', f'truncate -s 0 {target}', f'dd if=source of={target}',
                            f"sed -i 's/a/b/' {target}"):
                with self.subTest(target=target, command=command):
                    self.assertTrue(denied(hook('pre', {**self.writer,
                                                      'tool_input': {'command': command}}, self.env)))

    def test_writer_git_config_reads_and_quoted_filters_are_admitted(self):
        for command in ('git config --get user.name', 'git config --get-all core.pager',
                        'git config --list', 'git config -l',
                        "gh pr view 1 --jq '.[].title'",
                        "gh pr view 1 -q '[{title: .title}]'",
                        'git clone --config core.pager=cat https://example.com/o/r.git'):
            with self.subTest(command=command):
                self.assertFalse(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_hidden_value_routes_are_denied(self):
        commands = (
            "GIT_EDITOR='gh pr merge 1' git commit -e -m x",
            "git -c core.editor='gh pr merge 1' commit -e -m x",
            'GIT_EDITOR=gh git commit -e -m x',
            "env GIT_EDITOR='gh pr merge 1' git commit -e -m x",
            "export GIT_EDITOR='gh pr merge 1'; git commit -e -m x",
            "git -c core.pager='gh pr merge 1' log",
            "git -ccore.editor='gh pr merge 1' commit -e -m x",
            "GIT_EDITOR+='gh issue close 1' git commit -e -m x",
            "command git -c core.editor='gh issue close 1' commit -e -m x",
            "timeout 9 git -c core.editor='gh issue close 1' commit -e -m x",
            'env -u VISUAL GIT_EDITOR=gh git commit -e -m x',
            "env -C /repo GIT_EDITOR='gh issue close 1' git commit -e -m x",
            'env \'-SGIT_EDITOR="gh issue close 1" git commit -e -m x\'',
            'env \'--split-string=GIT_EDITOR="gh issue close 1" git commit -e -m x\'',
            "git -c credential.helper='!gh issue close 1' fetch",
            "GIT_EDITOR='!gh issue close 1' git commit -e -m x",
            'env -iS\'GIT_EDITOR="gh issue close 1" git commit -e -m x\'',
            'env \'--spl=GIT_EDITOR="gh issue close 1" git commit -e -m x\'',
            'nice env \'-SGIT_EDITOR="gh issue close 1" git commit -e -m x\'',
            'command env -u VISUAL GIT_EDITOR=gh git commit -e -m x',
            'env \'-vSGIT_EDITOR="gh issue close 1" git commit -e -m x\'',
            'env \'--split=GIT_EDITOR="gh issue close 1" git commit -e -m x\'',
            'git submodule foreach gh pr view 1 \'; GIT_EDITOR="gh issue close 1" git commit -e -m x\'',
            "GH_PAGER='gh issue close 1' gh pr view 1",
            'env \'-SGIT_EDITOR="g""h issue close 1" git commit -e -m x\'',
            'env \'-iSGIT_EDITOR="g""h issue close 1" git commit -e -m x\'',
            'env \'--split-string=GIT_EDITOR="g""h issue close 1" git commit -e -m x\'',
            'env \'--s=GIT_EDITOR="g""h issue close 1" git commit -e -m x\'',
            'GIT_CONFIG_PARAMETERS="\'core.editor=gh issue close 1\'" git commit --allow-empty -e -m x',
            'GIT_CONFIG_PARAMETERS="\'core.editor\'=\'gh issue close 1\'" git commit --allow-empty -e -m x',
            "GIT_EDITOR='gh>x issue close 1' git commit --allow-empty -e -m x",
            "GH_PAGER='gh>x issue close 1' gh pr diff 1",
            'GIT_CONFIG_PARAMETERS="\'credential.helper=!gh issue close 1\'" git fetch',
            "git -c protocol.ext.allow=always -c remote.x.url='ext::gh issue close 1' fetch x",
            'GIT_CONFIG_PARAMETERS="\'protocol.ext.allow=always\' \'remote.x.url=ext::gh issue close 1\'" git fetch x',
            "GIT_ALLOW_PROTOCOL=ext git ls-remote 'ext::gh issue close 1'",
            'gh>x issue close 1',
            "git rebase --exec='gh issue close 1' HEAD~1",
            "git fetch --upload-pack='gh issue close 1' /repo",
            '=gh issue close 1',
            "git add *(e:'gh issue close 1':)",
            "git clone -c core.editor='gh issue close 1' https://example.com/o/r.git r && git -C r commit --allow-empty -e -m x",
        )
        for command in commands:
            with self.subTest(command=command):
                result = hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)
                self.assertTrue(denied(result))
                reason = result['hookSpecificOutput']['permissionDecisionReason']
                self.assertIn('Rule:', reason)
                self.assertIn('driver', reason)

    def test_writer_value_shapes_are_denied_without_command_names(self):
        commands = (
            'GIT_EDITOR=vim git status', 'EDITOR=vim git status', 'VISUAL=vim git status',
            'PAGER=cat git status', 'export GIT_OPTIONAL_LOCKS=1; git status',
            'env --s=GIT_EDITOR=vim git status', "env '-iSGIT_EDITOR=vim git status'",
            'git -c core.editor=vim status', 'git -ccore.pager=less status',
            'git --config-env=core.editor=EDITOR status', 'git --config-env core.editor=EDITOR status',
            'git --exec-path=/tools status', 'git --exec-path /tools status',
            "git ls-remote 'ext::cat /repo'", 'git commit -e -m x', 'git commit --edit -m x',
            "git commit '--edit' -m x", 'git commit -em x', 'git commit --fixup=amend:HEAD',
            'git commit --fixup=reword:HEAD', 'sh -c "GIT_EDITOR=vim git status"',
            'git -c alias.other=log other', 'git -c remote.origin.url=https://example.com/o/r.git fetch',
            'git -c core.pager=less log', 'GIT_CONFIG_COUNT=2 git log',
            'GIT_CONFIG_VALUE_0=less git log', 'GIT_OPTIONAL_LOCKS=1 git status',
            "echo -f 'ref=gh'", "git -c remote.origin.url=ext::cat fetch",
            "git -c alias.lg=gh lg", "GIT_OPTIONAL_LOCKS+=0 git status",
        )
        for command in commands:
            with self.subTest(command=command):
                result = hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)
                self.assertTrue(denied(result))
                self.assertIn('Rule:', result['hookSpecificOutput']['permissionDecisionReason'])
                self.assertIn('driver', result['hookSpecificOutput']['permissionDecisionReason'])

    def test_writer_plain_git_steps_are_admitted(self):
        commands = (
            'git status', 'git diff', 'git add src/example.py', "git commit -m 'fix: plain value'",
            'git -C /repo log',
            "cd /repo && git add src/example.py && git commit -m 'fix: plain value'",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertFalse(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        self.env.update(HOME=str(self.repo), XDG_STATE_HOME=str(self.repo),
                        GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        self.writer = {'agent_type': 'ship:writer--sol', 'tool_name': 'Bash'}

    def test_writer_plain_commit_message_text_is_admitted(self):
        commands = (
            "git commit -m 'fix: no gh calls'",
            "cd /repo && git add a.py && git commit -m 'fix: no gh calls'",
            'git -C /repo commit -m "fix: no gh calls"',
            "git commit --message 'no gh calls'",
            "git commit --message='no gh calls'",
            "git commit -m 'fix: message\nno gh calls'",
            "git commit -m 'docs: explain `gh api` reads'",
            "gh api -X GET search/issues -f 'q=gh in:title'",
            "gh api -X GET search/code -f 'q=label:gh-pages is:open'",
            'git -c remote.origin.url=https://github.com/o/gh-tools.git fetch',
            "command gh api -X GET search/issues -f 'q=gh in:title'",
            "env gh api -X GET search/issues -f 'q=gh in:title'",
            "timeout 60 gh api -X GET search/issues -f 'q=gh in:title'",
            "env GH_PAGER=cat gh api -X GET search/issues -f 'q=gh in:title'",
            'gh api -X GET repos/o/r/contents/env -f ref=gh',
            'GH_PAGER=cat gh pr view 1',
            "git commit -am 'fix: no gh calls'",
            "git add a.py && git commit -m 'fix: no gh calls' -m 'second gh paragraph'",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertFalse(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_executable_commit_message_shapes_are_denied(self):
        commands = (
            'git commit -m "$(gh api repos/o/r)"',
            'git commit -m x; gh issue close 1',
            'git commit -m x && gh issue close 1',
            'git commit -m x || gh issue close 1',
            'git commit -m x & gh issue close 1',
            'git commit -m x | gh issue close 1',
            'git commit -m x\ngh issue close 1',
            "git commit -m 'x; gh pr merge 1' | sh",
            'git commit -m "`gh pr merge 1`"',
            "sh -c \"git commit -m 'gh pr comment 1 --body y'\"",
            "git commit -m 'gh calls' && sh -c x",
            "x='gh issue close 1'; GIT_EDITOR=$x git commit -e -m x",
            "git -c alias.x='!gh issue close 1' x",
            "env -iS 'gh issue close 1'",
            "GIT_EDITOR='command gh api repos/o/r/pulls/1/merge' git config --file=-XPUT --edit",
            "git commit -e -m 'gh issue close 1'",
            "git commit -em 'gh issue close 1'",
            "git commit --edit -m 'gh issue close 1'",
            "git commit -c HEAD -m 'gh issue close 1'",
            "git commit -t tpl -m 'gh issue close 1'",
            "GIT_EDITOR=vim git commit -m 'gh issue close 1'",
            "git -c core.editor=vim commit -m 'gh issue close 1'",
            "git commit -m 'gh issue close 1' > out.txt",
            "git add 'gh issue close 1' && git commit -m x",
            "git commit -m x 'gh issue close 1'",
            "git commit 'x -m '; gh issue close 1; ' y'",
            'git commit "x -m "; gh issue close 1; " y"',
            'git commit -m "prefix -m \'$(gh issue close 1)\'"',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_gh_reads_are_admitted(self):
        for command in ('gh api repos/x/y/pulls/1', 'gh api -X GET repos/x/y/pulls/1',
                        'gh api --method=GET repos/x/y/pulls/1', 'gh pr view 1', 'gh pr checks 1', 'gh run view 1'):
            with self.subTest(command=command):
                self.assertEqual(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env), '')

    def test_writer_gh_reads_are_admitted_independently_of_rewrite(self):
        commands = (
            "gh api repos/x/y/pulls --paginate --jq '.[].title'",
            "gh api repos/x/y/pulls/1 -H 'Accept: application/vnd.github.diff'",
            'gh api repos/x/y/pulls/1 | grep -F x', 'gh api repos/x/y/pulls/1 | cut -f1',
            'gh api repos/x/y/pulls/1 && rm -f p.json', 'gh api repos/x/y/pulls/1 | awk -F,',
            'gh pr view 1 --json reviews --jq .reviews', 'gh run view 1 --log-failed',
            'gh api -X HEAD repos/x/y/pulls/1', 'gh api --method=HEAD repos/x/y/pulls/1',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertFalse(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))
        for option in ('-f q=value', '-F q=value', '--field q=value', '--raw-field q=value',
                       '--input payload.json', '-fq=value', '-Fq=value', '--field=q=value',
                       '--raw-field=q=value', '--input=payload.json'):
            command = f'gh api -X GET search/issues {option}'
            with self.subTest(command=command):
                self.assertFalse(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_gh_writes_remain_denied(self):
        commands = ['gh repo sync x/y', 'cd /repo && gh repo sync x/y']
        for method in ('POST', 'PUT', 'PATCH', 'DELETE', 'post', 'pAtCh', 'OPTIONS', 'TRACE', 'CONNECT', 'CUSTOM', ''):
            for option in (f'-X {shlex.quote(method)}', f'--method {shlex.quote(method)}',
                           f'-X{method}', f'--method={method}', f'-X={method}', f'-X "{method}"', f'-iX{method}'):
                commands.extend((f'gh api {option} repos/x/y/pulls/1',
                                 f'gh api repos/x/y/pulls/1 {option}',
                                 f'/usr/bin/gh api {option} repos/x/y/pulls/1',
                                 'gh api \\\n' + f' {option} repos/x/y/pulls/1'))
        for option in ('-f title=value', '-F title=value', '--field title=value', '--raw-field title=value',
                       '--input payload.json', '-ftitle=value', '-Ftitle=value', '--field=title=value',
                       '--raw-field=title=value', '--input=payload.json'):
            commands.extend((f'gh api {option} repos/x/y/pulls/1',
                             f'gh api repos/x/y/pulls/1 {option}'))
        commands.append('gh api -X GET --method POST repos/x/y/pulls/1')
        for command in commands:
            with self.subTest(command=command):
                result = hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)
                self.assertTrue(denied(result), command)

    def test_writer_nested_and_quoted_gh_writes_are_denied(self):
        commands = ('bash -c "gh api -X POST repos/o/r/issues"', "sh -c 'gh repo sync'",
                    'eval "gh api --method PATCH repos/o/r"', "'gh' api -X POST repos/o/r",
                    'g""h api -X DELETE repos/o/r', 'zsh -c "x=1; gh api -XPUT repos/o/r"')
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_gh_alias_and_extension_mutations_are_denied(self):
        for command in ('gh alias set write api', 'gh alias import aliases.yml',
                        'gh extension install owner/tool', 'gh extension upgrade tool', 'gh extension exec tool'):
            with self.subTest(command=command):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_gh_extension_alias_forms_are_denied(self):
        for group in ('extension', 'extensions', 'ext', 'alias'):
            for action in ('remove', 'create', 'custom'):
                for suffix in ('', " '"):
                    command = f'gh {group} {action} tool{suffix}'
                    with self.subTest(command=command):
                        self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))
        for group, actions in (('extension', ('list', 'search', 'browse')),
                               ('extensions', ('list', 'search', 'browse')),
                               ('ext', ('list', 'search', 'browse')), ('alias', ('list',))):
            for action in actions:
                command = f'gh {group} {action}'
                with self.subTest(command=command):
                    self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_gh_configuration_edits_are_denied(self):
        custom = self.repo / 'custom-gh'
        self.env['GH_CONFIG_DIR'] = str(custom)
        for root in (self.repo / '.config/gh', custom):
            for tool in ('Edit', 'Write', 'NotebookEdit'):
                key = 'notebook_path' if tool == 'NotebookEdit' else 'file_path'
                target = str(root / 'hosts.yml')
                with self.subTest(tool=tool, target=target):
                    self.assertTrue(denied(hook('pre', {**self.writer, 'tool_name': tool,
                                                      'tool_input': {key: target}}, self.env)))
        for target in (self.repo / '.config/gh-other/hosts.yml', self.repo / 'custom-gh-other/hosts.yml'):
            self.assertFalse(denied(hook('pre', {**self.writer, 'tool_name': 'Write',
                                                'tool_input': {'file_path': str(target)}}, self.env)))

    def test_writer_gh_auth_and_config_writes_are_denied(self):
        for command in ('gh auth token', 'gh auth login --with-token', 'gh auth setup-git',
                        'gh config set editor vim', 'gh config clear-cache'):
            for suffix in ('', " '"):
                with self.subTest(command=command, suffix=suffix):
                    self.assertTrue(denied(hook('pre', {**self.writer,
                                                      'tool_input': {'command': command + suffix}}, self.env)))
        for command in ('gh auth status', 'gh config get git_protocol', 'gh config list'):
            with self.subTest(command=command):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_gh_non_read_commands_are_denied(self):
        commands = (
            'gh issue comment 1 -b x', 'gh issue create -t x -b y',
            'gh pr update-branch 12 --rebase', 'gh pr reopen 1', 'gh run rerun 1',
            'gh secret set X -b y', 'gh label delete x', 'gh repo archive -y', 'gh repo rename x',
            'gh gist create f --public', 'gh ext install o/t', 'gh extensions exec t',
            'gh --help=false api -X POST repos/o/r/issues -f title=t',
            'gh alias --clobber=true set w api', 'gh w -XPOST -ftitle=t repos/o/r/issues',
            'gh auth status --show-token', 'gh auth status -t', 'gh config get oauth_token -h github.com',
        )
        for command in commands:
            for suffix in ('', " '"):
                with self.subTest(command=command, suffix=suffix):
                    self.assertTrue(denied(hook('pre', {**self.writer,
                                                      'tool_input': {'command': command + suffix}}, self.env)))

    def test_writer_gh_shell_expansion_and_redirection_writes_are_denied(self):
        commands = (
            'echo a#b; gh api -X POST repos/o/r/issues -f title=t',
            'b=${ref#refs/heads/}; gh api -X POST repos/o/r/issues -f title=t',
            'gh api repos/$(gh repo view --json nameWithOwner -q .nameWithOwner)/issues -X POST -f title=t',
            'gh api repos/o/r/issues 2>&1 -X POST -f title=t',
            "F='-XPOST -ftitle=t'; gh api repos/o/r/issues $F",
            "$'gh' api -X POST repos/o/r/issues -f title=t",
            'gh${IFS}api${IFS}-XPOST${IFS}-ftitle=t${IFS}repos/o/r/issues',
            'echo -XPOST -ftitle=t | xargs gh api repos/o/r/issues',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_gh_value_expansion_and_early_flags_are_denied(self):
        commands = ("F='. -XPOST -ftitle=t'; gh api -q $F repos/o/r/issues",
                    'gh issue comment 1 -b "it\'s', 'gh pr -R view comment 1 -b x',
                    'gh --repo=o/r pr view 1', 'gh pr --repo o/r view 1',
                    'gh --help=false pr --help=false view 1')
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))
        for command in ("gh pr view 12 --json title -q '.title'",
                        "gh pr view 12 --json title -q '[{title: .title}]'",
                        'gh pr view 12 -R o/r --json title'):
            with self.subTest(command=command):
                self.assertEqual(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env), '')

    def test_writer_gh_read_allowlist_preserves_reads(self):
        commands = ["gh pr view 12 --json title -q '.title'", "gh api 'repos/o/r/pulls?state=open'",
                    'gh pr view 12 -R o/r --json title', 'gh --version', 'gh --help', 'gh version', 'gh help',
                    'gh search issues x']
        for group, verbs in (('pr', ('view', 'list', 'checks', 'diff', 'status')),
                             ('issue', ('view', 'list', 'status')), ('run', ('view', 'list', 'watch')),
                             ('repo', ('view',)), ('workflow', ('view', 'list'))):
            commands.extend(f'gh {group} {verb}' for verb in verbs)
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env), '')

    def test_writer_xdg_gh_configuration_edits_are_denied(self):
        self.env['XDG_CONFIG_HOME'] = str(self.repo / 'xdg')
        for tool in ('Edit', 'Write', 'NotebookEdit'):
            key = 'notebook_path' if tool == 'NotebookEdit' else 'file_path'
            with self.subTest(tool=tool):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_name': tool,
                    'tool_input': {key: str(self.repo / 'xdg/gh/hosts.yml')}}, self.env)))

    def test_writer_relative_gh_configuration_targets_use_tool_cwd(self):
        self.env['GH_CONFIG_DIR'] = str(self.repo / 'cli')
        for tool in ('Edit', 'Write', 'NotebookEdit'):
            key = 'notebook_path' if tool == 'NotebookEdit' else 'file_path'
            with self.subTest(tool=tool):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_name': tool, 'cwd': str(self.repo),
                    'tool_input': {key: 'cli/hosts.yml'}}, self.env)))

    def test_writer_relative_gh_configuration_targets_use_process_cwd(self):
        self.env['GH_CONFIG_DIR'] = str(self.repo / 'cli')
        for tool in ('Edit', 'Write', 'NotebookEdit'):
            key = 'notebook_path' if tool == 'NotebookEdit' else 'file_path'
            payload = {**self.writer, 'tool_name': tool, 'tool_input': {key: 'cli/hosts.yml'}}
            with self.subTest(tool=tool):
                result = run([sys.executable, str(HOOK), 'pre'], payload, cwd=self.repo, env=self.env, check=True)
                self.assertTrue(denied(json.loads(result.stdout)) if result.stdout.strip() else False)

    def test_writer_preview_graphql_fields_are_denied(self):
        for command in ('gh api -X GET -p x graphql -f query=q',
                        'gh api -X GET --preview x graphql -F query=q',
                        'gh api -X GET repos/o/r graphql -f query=q'):
            with self.subTest(command=command):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))
        command = 'gh api -X GET repos/o/r/pulls -f state=open'
        self.assertFalse(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_deep_gh_commands_fail_closed(self):
        command = 'gh api repos/o/r'
        for _ in range(5):
            command = 'sh -c ' + shlex.quote(command)
        self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_quoted_heredoc_data_with_apostrophe_is_admitted(self):
        for body in ("don't run anything", "don't run gh api"):
            command = f"cat <<'EOF' > receipt.txt\n{body}\nEOF\n"
            with self.subTest(body=body):
                self.assertNotEqual(ultraship.cat_heredoc_data(command), command)
                self.assertFalse(denied(hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)))

    def test_writer_graphql_fields_are_denied_with_rest_guidance(self):
        for option in ("-f query='query { viewer { login } }'", '-F owner=x', '--field owner=x',
                       '--raw-field=owner=x', '--input query.json'):
            for command in (f'gh api graphql {option}', f'gh api -X GET graphql {option}'):
                with self.subTest(command=command):
                    result = hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)
                    self.assertTrue(denied(result), command)
                    self.assertIn('writers cannot send GraphQL requests; use a REST GET with the query in the path',
                                  result['hookSpecificOutput']['permissionDecisionReason'])

    def test_writer_split_gh_write_with_unclosed_braces_is_refused_fast(self):
        command = 'g' + '\\\n' + 'h issue close 1 ' + '{/' * 4500
        started = time.monotonic()
        result = hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)
        elapsed = time.monotonic() - started
        self.assertTrue(denied(result))
        self.assertIn('writer GitHub read-only rule', result['hookSpecificOutput']['permissionDecisionReason'])
        self.assertLess(elapsed, 10)

    def test_writer_git_unclosed_braces_finish_fast(self):
        command = 'echo ' + '{/' * 4500
        started = time.monotonic()
        result = ultraship.writer_git_file_denial(command, str(self.repo))
        elapsed = time.monotonic() - started
        self.assertIsNone(result)
        self.assertLess(elapsed, 10)

    def test_writer_git_brace_slash_answers(self):
        self.assertEqual(ultraship.writer_git_file_denial('echo {a/b,c}', str(self.repo)),
                         'git control path brace slash rule')
        self.assertIsNone(ultraship.writer_git_file_denial('echo {a,b}/c', str(self.repo)))


class ReviewThreadReadTests(unittest.TestCase):
    def test_literal_graphql_reads_with_pagination_and_variables(self):
        # These shell commands are classifier inputs only.
        watcher = HOOK.parents[1] / 'skills/babysit/scripts/threads.sh'
        query = next(line.removeprefix('query=') for line in watcher.read_text().splitlines()
                     if line.startswith('query='))
        watcher_read = ("gh api graphql --paginate -F owner=example-org -F name=example-repo -F pr=456 "
                        f"-f query={query} --jq '.data.repository.pullRequest.reviewThreads.nodes[]'")
        reads = (
            'gh pr view https://github.com/example-org/example-repo/pull/123 '
            "--json headRefOid,statusCheckRollup,body --jq '{head:.headRefOid,body,checks:[.statusCheckRollup[]"
            '|select((.conclusion == "FAILURE") or (.name|test("[Ii]ntegration|Merge Queue|create-preview")))'
            "|{name,status,conclusion,detailsUrl}]}'; gh api graphql --paginate -f query='query($endCursor:String)"
            '{ repository(owner:"example-org",name:"example-repo"){ pullRequest(number:123)'
            '{ reviewThreads(first:50,after:$endCursor){pageInfo{hasNextPage endCursor} nodes{id isResolved '
            "isOutdated path line comments(first:15){nodes{id databaseId body url author{login}}}}}}}}' "
            "--jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved|not)'",
            "gh api graphql --paginate -f query='query($endCursor:String)"
            '{repository(owner:"example-org",name:"example-repo"){pullRequest(number:456){headRefOid '
            'reviewThreads(first:100,after:$endCursor){pageInfo{hasNextPage endCursor} nodes{id isResolved '
            "isOutdated path comments(last:3){nodes{body url databaseId author{login}}}}}}}}' "
            "--jq '.data.repository.pullRequest | {headRefOid,total:(.reviewThreads.nodes|length),"
            "unresolved:[.reviewThreads.nodes[] | select(.isResolved|not)]}'",
            watcher_read,
        )
        self.assertIn('after:$endCursor', query)
        for command in reads:
            with self.subTest(command=command):
                self.assertIsNone(ultraship.review_thread_denial(command))
        for command in (
            watcher_read + ' -F owner=another-org',
            watcher_read + ' -F undeclared=x',
            watcher_read.replace(',$endCursor:String', ''),
            watcher_read.replace('pageInfo{hasNextPage endCursor}', ''),
            watcher_read.replace('pageInfo{hasNextPage endCursor}', 'pageInfo{hasNextPage}'),
            watcher_read.replace('pageInfo{hasNextPage endCursor}nodes{id',
                                 'nodes{id pageInfo{hasNextPage endCursor}'),
            watcher_read.replace('-f query=', '-f= query='),
        ):
            with self.subTest(command=command):
                self.assertEqual(ultraship.review_thread_denial(command), 'gh api write outside the helper')

    def test_paginated_graphql_read_refuses_two_cursor_bound_connections(self):
        threads = 'reviewThreads(first:20,after:$endCursor){pageInfo{hasNextPage endCursor}nodes{id}}'
        command = ("gh api graphql --paginate -f query='query($endCursor:String)"
                   '{repository(owner:"example-org",name:"example-repo"){'
                   f'firstPr:pullRequest(number:1){{{threads}}}'
                   f'secondPr:pullRequest(number:2){{{threads}}}'
                   "}}'")
        self.assertEqual(ultraship.review_thread_denial(command), 'gh api write outside the helper')

    def test_paginated_graphql_read_requires_one_page_info_response_key(self):
        query = ("gh api graphql --paginate -f query='query($endCursor:String)"
                 '{repository(owner:"example-org",name:"example-repo"){pullRequest(number:456){'
                 'reviewThreads(first:20,after:$endCursor){pageInfo{hasNextPage endCursor}nodes{id}}'
                 'comments(first:5){%s}'
                 "}}}'")
        denied = 'gh api write outside the helper'
        for sibling, reason in (
            ('pageInfo{hasNextPage endCursor}', denied),
            ('pageInfo:nodes{id}', denied),
            ('metadata:pageInfo{hasNextPage endCursor}', None),
        ):
            with self.subTest(sibling=sibling):
                self.assertEqual(ultraship.review_thread_denial(query % sibling), reason)

    def test_graphql_read_exception_excludes_writes_and_unproven_fields(self):
        query = ("-f query='query($owner:String!,$endCursor:String)"
                 '{repository(owner:$owner,name:"example-repo"){pullRequest(number:456)'
                 '{reviewThreads(first:20,after:$endCursor){pageInfo{hasNextPage endCursor}nodes{id}}}}}\'')
        owner = '-F owner=example-org'
        read = f'gh api graphql --paginate {query} {owner}'
        self.assertIsNone(ultraship.review_thread_denial(read))
        write = 'gh api write outside the helper'
        for command, reason in (
            ("gh api graphql --paginate -f query='mutation { example { id } }'", write),
            ('gh api repos/o/r/issues -X POST -f title=example', write),
            (f'{read} {query}', write),
            (read.replace(owner, '-F owner=@example.txt'), write),
            (read.replace(owner, '-F owner="{owner}"'), write),
            (read.replace(owner, '-F owner="$OWNER"'), write),
            (f'{read} -X PATCH', write),
            (read.replace('api graphql', 'api graphql/'), write),
            (read.replace('-f query=', '-f= query='), write),
            (f'{read} --input example.json', 'opaque GraphQL query'),
            ('gh api graphql --paginate -f query="$QUERY"', 'opaque GraphQL query'),
        ):
            with self.subTest(command=command):
                self.assertEqual(ultraship.review_thread_denial(command), reason)


if __name__ == '__main__':
    unittest.main()
