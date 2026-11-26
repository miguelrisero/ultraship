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
from threading import Barrier, Thread
from types import SimpleNamespace
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
    build = ('cd /workspace/service-walkthroughs && npm run build'
             ' && node --test scripts/test-service-examples.mjs')
    build_payload = {'cwd': '/workspace/repo', 'tool_name': 'Bash'}
    for command, expected_reason in (
            (build, None),
            (build + ' && true', None),
            (build.rsplit(' ', 1)[0], custody),
            (build + ' scripts/other.test.mjs', custody),
            (build + f' && cat {shlex.quote(str(receipt_store / "key"))}', custody),
            (build + f' > {shlex.quote(str(receipt_store / "key"))}', custody)):
        result = hook('pre', {**build_payload, 'tool_input': {'command': command}}, env)
        actual_reason = result['hookSpecificOutput']['permissionDecisionReason'].split('\n', 1)[0] if denied(result) else None
        assert actual_reason == expected_reason, (command, result)

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
            assert result['hookSpecificOutput']['permissionDecisionReason'].split('\n', 1)[0] == custody
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
                assert result['hookSpecificOutput']['permissionDecisionReason'].split('\n', 1)[0] == custody
    receipt_alias = Path(tmp) / 'ReceiptAlias'
    receipt_store.mkdir(parents=True)
    receipt_alias.symlink_to(receipt_store, target_is_directory=True)
    for caller in ({'agent_type': 'ship:writer--sol'}, {'agent_type': 'ship:driver'}, {}):
        for tool in ('Edit', 'Read', 'Write'):
            result = hook('pre', {**caller, 'tool_name': tool,
                                  'tool_input': {'file_path': str(receipt_alias / 'key')}}, env)
            assert denied(result), (caller, tool)
            assert result['hookSpecificOutput']['permissionDecisionReason'].split('\n', 1)[0] == custody
        for command, state_root in (
                ('cat ~/.local/sta[t]e/ultraship/*/key', str(Path(tmp) / '.local/state')),
                ('cat $HOME/.local/sta[t]e/ultraship/*/key', str(Path(tmp) / '.local/state')),
                ('cat ${HOME}/.local/sta[t]e/ultraship/*/key', str(Path(tmp) / '.local/state')),
                ('cat $XDG_STATE_HOME/ultra*/t*/key', tmp),
                ('cat ${XDG_STATE_HOME}/ultra*/t*/key', tmp)):
            result = hook('pre', {**caller, 'tool_name': 'Bash', 'tool_input': {'command': command}},
                          {**env, 'XDG_STATE_HOME': state_root})
            assert denied(result), (caller, command)
            assert result['hookSpecificOutput']['permissionDecisionReason'].split('\n', 1)[0] == custody
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
    def test_bash_pre_hook_blocks_process_failure(self):
        config = json.loads(HOOK.with_name('hooks.json').read_text())
        hooks = [hook for entry in config['hooks']['PreToolUse']
                 if re.fullmatch(entry['matcher'], 'Bash') for hook in entry['hooks']]
        self.assertTrue(any(
            hook.get('type') == 'command'
            and hook.get('command') == 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/ultraship.py" pre'
            and hook.get('onFailure') == 'block'
            for hook in hooks
        ))
        self.assertTrue(all(hook.get('onFailure') == 'block' for hook in hooks))

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
                    reason, _, retry = output['permissionDecisionReason'].partition('\n')
                    self.assertEqual(reason, (
                        'The ship hook could not read its input as a JSON object, so it denies this call. '
                        'Report the blocked scope to the driver.'))
                    self.assertIn('Keep the work pending.', retry)
                    self.assertIn('Retry only after you meet the rule above.', retry)
                    self.assertIn('report the blocked step, the rule, and the next permitted action', retry)


class CompoundReadHookTests(unittest.TestCase):
    search = ('''ls /workspace/reports; grep -rl "sample notices" /workspace/reports --include="*.py" '''
              '''2>/dev/null | grep -v "/tests/" | awk -F/ '{print $7"/"$8"/"$9" :: "$NF}' | sort -u | tail -15''')
    metadata = 'gh pr view 235 --repo sample/project --json number,headRefOid,mergeStateStatus'
    custody = 'Only the text_lint hook reads or writes refusal receipts (custody rule).'
    thread_guard = 'Ship replies to and resolves review threads only through'

    def setUp(self):
        home = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.state = home / 'state'
        self.cwd = home / 'repo'
        self.cwd.mkdir()
        self.enterContext(patch.dict(os.environ, {'HOME': str(home), 'XDG_STATE_HOME': str(self.state)}))
        self.enterContext(patch.object(ultraship.pwd, 'getpwuid', return_value=SimpleNamespace(pw_dir=str(home))))
        self.enterContext(patch.object(ultraship, 'STATE', self.state / 'ultraship'))
        self.enterContext(patch.object(ultraship.subprocess, 'run', side_effect=AssertionError('fixture ran a process')))

    def pre(self, command):
        event = {'cwd': str(self.cwd), 'tool_name': 'Bash', 'tool_input': {'command': command}}
        output = io.StringIO()
        with redirect_stdout(output):
            try:
                ultraship.guarded_pre(event)
            except SystemExit as error:
                self.assertEqual(error.code, 0)
        return json.loads(output.getvalue() or '{}').get('hookSpecificOutput', {})

    def assert_refused(self, command, reason):
        result = self.pre(command)
        self.assertEqual(result.get('permissionDecision'), 'deny', result)
        self.assertIn(reason, result['permissionDecisionReason'])

    def test_compound_metadata_read(self):
        for pattern in ('bash', "'bash'"):
            inspection = f'grep -n {pattern} /workspace/reports/notes.txt'
            for command in (f'{inspection} && {self.metadata}', f'{self.metadata}; {inspection}'):
                with self.subTest(command=command):
                    self.assertEqual(self.pre(command), {})

    def test_compound_metadata_keeps_thread_guards(self):
        write = 'gh api repos/sample/project/pulls/235/comments -X POST -f body=sample'
        self.assert_refused(f'git diff -- . && {write}', 'gh api write outside the helper')
        self.assert_refused(f'sh -c {shlex.quote(self.metadata)}', 'shell runner names gh')
        self.assert_refused('git diff -- . && gh "$subcommand"', self.thread_guard)

    def test_compound_search_field_separator(self):
        for command in (self.search, self.search.replace('awk -F/', 'awk -F:')):
            with self.subTest(command=command):
                self.assertEqual(self.pre(command), {})

    def test_report_probe_keeps_interpreter_protection(self):
        report = r'''python3 -c "import re; from pathlib import Path; h=Path('report.html').read_text(); print(len(re.findall(r'data:[^\"\')]+', h)))"'''
        self.assert_refused(report, self.custody)

    def test_compound_search_keeps_path_redirect_and_program_checks(self):
        receipt = shlex.quote(str(self.state / 'ultraship/text-lint/fixture.txt'))
        for command in (self.search.replace('2>/dev/null', f'2>{receipt}'),
                        self.search.replace('awk -F/', f'awk -F/ -f {receipt}'),
                        self.search.replace('awk -F/', 'awk -F/ /'),
                        self.search + ' | "$program"'):
            with self.subTest(command=command):
                self.assert_refused(command, self.custody)


class LiteralCustodyTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.cwd = self.home / 'repo'
        self.cwd.mkdir()
        self.scratch = self.home / '.scratch'
        self.scratch.mkdir()
        self.state = self.home / 'state'
        self.enterContext(patch.dict(os.environ, {'HOME': str(self.home), 'XDG_STATE_HOME': str(self.state),
                                                   'CLAUDE_CONFIG_DIR': str(self.cwd / '.claude')}))
        for name in ('P', 'COC_CONFIG', 'CHILD'):
            os.environ.pop(name, None)
        self.enterContext(patch.object(ultraship.pwd, 'getpwuid', return_value=SimpleNamespace(pw_dir=str(self.home))))
        self.enterContext(patch.object(ultraship, 'STATE', self.state / 'ultraship'))
        self.enterContext(patch.object(ultraship.subprocess, 'run', side_effect=AssertionError('fixture ran a process')))

    def pre(self, command, caller='ship:writer--sol'):
        event = {'cwd': str(self.cwd), 'tool_name': 'Bash', 'agent_type': caller,
                 'tool_input': {'command': command}}
        with redirect_stdout(io.StringIO()) as output:
            try:
                ultraship.guarded_pre(event)
            except SystemExit as error:
                self.assertEqual(error.code, 0)
        return json.loads(output.getvalue() or '{}').get('hookSpecificOutput', {})

    def assert_allowed(self, command, caller='ship:writer--sol'):
        decision = self.pre(command, caller)
        self.assertEqual(decision, {}, decision.get('permissionDecisionReason', decision))

    def assert_denied(self, command, reason, caller='ship:writer--sol'):
        decision = self.pre(command, caller)
        self.assertEqual(decision.get('permissionDecision'), 'deny', decision)
        self.assertIn(reason, decision['permissionDecisionReason'])

    def test_literal_oxlint_with_scratch_output(self):
        command = ('node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON node_modules/oxlint/bin/oxlint '
                   '-c oxlint.config.ts --threads=1 ../lanes/synthetic/.github/scripts/dashboard.test.mjs')
        self.assert_allowed(command + ' > ../.scratch/dashboard-oxlint.log 2>&1', caller='')

    def test_literal_node_check_in_repository(self):
        for source in ('.github/scripts/dashboard.test.mjs', '../lanes/synthetic/.github/scripts/dashboard.test.mjs'):
            with self.subTest(source=source):
                self.assert_allowed(f'node --check {source}', caller='')

    def test_node_script_parent_traversal_stays_denied(self):
        self.assert_denied('node --check ../lanes/synthetic/.github/scripts/dashboard.test.mjs',
                           'inline interpreter code rule')

    def test_literal_scratch_redirect(self):
        (self.cwd / 'data').symlink_to(self.state / 'ultraship/text-lint', target_is_directory=True)
        command = r"printf '%s\n' 'Example: ${XDG_STATE_HOME}/sample [text]'"
        self.assert_allowed(command + ' >> ../.scratch/example.log 2>&1')

    def test_inert_scratch_heredoc(self):
        command = "cat > ../.scratch/example.md <<'END'\nExample: ${XDG_STATE_HOME}/sample [text]\nEND\n"
        self.assert_allowed(command)

    def test_literal_grep_on_clone_and_packaged_source(self):
        (self.cwd / 'clone/.git').mkdir(parents=True)
        (self.cwd / 'data').symlink_to(self.state / 'ultraship/text-lint', target_is_directory=True)
        for source in ('clone/plugins/ship/hooks/ultraship.py',
                       '.claude/plugins/cache/ultraship/ship/0.0.0/hooks/ultraship.py'):
            target = self.cwd / source
            target.parent.mkdir(parents=True)
            target.write_text('Synthetic source.\n')
            command = f'grep -nE "XDG_STATE_HOME|text_lint.py hook|issue_account_grant" {source}'
            with self.subTest(source=source):
                self.assert_allowed(command)

    def test_literal_data_preserves_protected_path_checks(self):
        store = self.state / 'ultraship/text-lint'
        grants = self.home / '.local/state/ultraship/account-grants'
        store.mkdir(parents=True)
        grants.mkdir(parents=True)
        (self.scratch / 'fixture-link').symlink_to(store, target_is_directory=True)
        note = r"printf '%s\n' 'Example: ${XDG_STATE_HOME}/sample [text]'"
        for command in (f'{note} > {store}/fixture.log 2>&1',
                        f'{note} > {grants}/fixture.log 2>&1',
                        f'{note} > ../.scratch/fixture-link/fixture.log 2>&1',
                        f"cat > ../.scratch/../state/ultraship/text-lint/fixture.log <<'END'\nExample.\nEND\n",
                        'grep -rnE "XDG_STATE_HOME|text_lint.py hook" ../.scratch/../state',
                        'grep -nE "XDG_STATE_HOME|text_lint.py hook" ../.scratch/fixture-link/fixture.log',
                        'grep -n "$(python3 text_lint.py hook)" example.py'):
            with self.subTest(command=command):
                self.assert_denied(command, ultraship.RECEIPT_CUSTODY)
        self.assert_denied('node --unknown-option example.mjs', 'inline interpreter code rule')

    def test_exact_custody_forms_allow_both_callers(self):
        repo = str(self.cwd)
        writer = HOOK.with_name('text_lint.py')
        for name in ('promises.py', 'slack_post.py'):
            (self.cwd / name).touch()
        commands = (
            "git grep -n 'text_lint hook' -- plugins/ship/hooks/ultraship.py"
            " && git grep -i -w -F -l -e 'example' -- README.md docs/",
            f'cd {repo} && python3 tools/ledger_answers.py "00000000-0000-4000-8000-000000000001=x"; '
            f'P={repo}/promises.py; export COC_CONFIG={repo}/config.json; '
            'python3 $P add --promise "x" --due 2026-11-27T10:00Z --driver "y" | grep \'"id"\'',
            f'cd {repo} && printf \'%s\\n\' "x" > slack-x.txt && P={repo}/slack_post.py '
            f'&& COC_CONFIG={repo}/config.json python3 $P --channel D0 --text-file {repo}/slack-x.txt | tail -c 120',
            f'P={repo}/promises.py; python3 "$P" "$P"',
            *(f'python3 {writer} {kind} < draft.txt' for kind in ('peer', 'decision', 'result')),
        )
        for caller in ('', 'ship:driver--sol'):
            for command in commands:
                with self.subTest(caller=caller, command=command):
                    decision = self.pre(command, caller)
                    self.assertNotEqual(decision.get('permissionDecision'), 'deny', decision)

    def test_exact_custody_forms_check_public_paths_and_keep_main_denials(self):
        store = self.home / '.local/state/ultraship/account-grants'
        store.mkdir(parents=True)
        (store / 'fixture.py').touch()
        (self.cwd / 'fixture-alias').symlink_to(store, target_is_directory=True)
        writer = HOOK.with_name('text_lint.py')
        search = "git grep -n 'text_lint hook' -- README.md"
        for caller in ('', 'ship:driver--sol'):
            for command in (
                    search.replace('-n', '-O'), search.replace('-n', '--open-files-in-pager'),
                    search.replace('-n', '--output=out.txt'), search + ' > out.txt', search + '; true',
                    search + ' | cat', search + '\ntrue', search.replace('hook', 'hook $X'),
                    search.replace('hook', 'hook `pwd`'), search.replace('README.md', 'fixture-alias/fixture.py'),
                    f'python3 {writer} hook < draft.txt', f'python3 {writer} peer < fixture-alias/fixture.py',
                    f'P={self.cwd}/fixture-alias/fixture.py; python3 $P',
                    f'P={self.cwd}/$CHILD; python3 $P', 'python3 $P', "python3 -c 'import text_lint'"):
                with self.subTest(caller=caller, command=command):
                    self.assert_denied(command, ultraship.RECEIPT_CUSTODY, caller)
        for command in (
                f'P={self.cwd}/a.py; P={self.cwd}/b.py; python3 $P',
                f'P={self.cwd}/a.py; python3 ${{P}}', f'P={self.cwd}/a.py; python3 $P:h',
                f'P={self.cwd}/a.py; python3 "$(cat $P)"', f'P={self.cwd}/a.py; python3 "$P" `pwd`',
                f'P={self.cwd}/$CHILD; python3 $P', f'P={self.cwd}/a.py; python3 $P > out.txt'):
            with self.subTest(command=command):
                self.assertIsNone(ultraship.custody_bound_command(command))

    def test_bound_command_refuses_relative_and_parent_directory_operands(self):
        grant = self.home / '.local/state/ultraship/account-grants/fixture.json'
        grant.parent.mkdir(parents=True)
        grant.touch()
        logical = self.cwd / 'logical'
        logical.mkdir()
        physical = self.scratch / 'physical/child'
        physical.mkdir(parents=True)
        (logical / 'link').symlink_to(physical, target_is_directory=True)
        (logical / 'draft.txt').symlink_to(grant)
        script = self.cwd / 'helper.py'
        script.touch()
        tail = (f"printf '%s\\n' x > draft.txt && P={script} "
                f'&& COC_CONFIG={self.cwd}/config.json python3 $P | tail -c 120')
        for directory in (logical / 'link/..', 'logical'):
            command = f'cd {directory} && {tail}'
            with self.subTest(directory=directory):
                self.assertIsNone(ultraship.custody_bound_command(command))
                for caller in ('', 'ship:driver--sol'):
                    self.assert_denied(command, ultraship.RECEIPT_CUSTODY, caller)

    def test_bound_command_with_literal_cdpath_keeps_the_original_custody_verdict(self):
        grant = self.home / '.local/state/ultraship/account-grants/fixture.json'
        grant.parent.mkdir(parents=True)
        grant.touch()
        directory = self.cwd / 'entered'
        directory.mkdir()
        (directory / 'draft.txt').symlink_to(grant)
        script = self.cwd / 'helper.py'
        script.touch()
        for draft in ('ordinary.txt', 'draft.txt'):
            command = (f'cd {directory} && printf \'%s\\n\' "cdpath" > {draft} && P={script} '
                       f'&& COC_CONFIG={self.cwd}/config.json python3 $P | tail -c 120')
            expanded, _, _ = ultraship.custody_bound_command(command)
            event = {'cwd': str(self.cwd), 'tool_name': 'Bash', 'tool_input': {'command': expanded}}
            with self.subTest(draft=draft):
                if draft == 'draft.txt':
                    with redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit):
                        ultraship.receipt_custody(event, exact_forms=False, verified_cd=str(directory))
                    self.assertIn('Rule: store-operand.', output.getvalue())
                else:
                    self.assertEqual(ultraship.receipt_custody(event, exact_forms=False, verified_cd=str(directory)), 'soft')
                for caller in ('', 'ship:driver--sol'):
                    self.assert_denied(command, 'Rule: custody-scope.', caller)

    def test_clean_custody_rescan_discards_warning_and_emitted_decision(self):
        def warning(*args, **kwargs):
            ultraship.warn('S2', 'fixture warning')

        def ask(*args, **kwargs):
            print('{"hookSpecificOutput": {"permissionDecision": "ask"}}')

        with patch.object(ultraship, 'WARNINGS', ['existing warning']), redirect_stdout(io.StringIO()) as output:
            for scan in (warning, ask):
                with self.subTest(scan=scan.__name__), patch.object(ultraship, 'receipt_custody', side_effect=scan):
                    self.assertFalse(ultraship.clean_custody_rescan({'tool_name': 'Bash'}, None))
                    self.assertEqual(ultraship.WARNINGS, ['existing warning'])
            self.assertEqual(output.getvalue(), '')

    def test_main_custody_gaps_receive_no_allowance(self):
        writer = HOOK.with_name('text_lint.py')
        commands = (
            f"git grep -n 'text_lint hook' -- README.md && git diff --output={writer} -- README.md",
            f"sed --in-pl -e 's/a/b/' {writer}", f'cat {writer} | python3 -',
            'd=/fixture; ((\n  1 << 2\n)); cat "$d/fixture.json"\n2\n',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertFalse(ultraship.custody_grep_paths(command))
                self.assertIsNone(ultraship.custody_bound_command(command))
                self.assertIsNone(ultraship.CUSTODY_LINT.fullmatch(command))

    def test_literal_node_keeps_custody_checks(self):
        store = self.state / 'ultraship/text-lint'
        store.mkdir(parents=True)
        (self.cwd / 'fixture-link').symlink_to(store, target_is_directory=True)
        (self.scratch / 'result.log').symlink_to(store / 'example.log')
        for command in ('node --check fixture-link/example.mjs',
                        'node --unknown-option example.mjs',
                        'node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON node_modules/oxlint/bin/oxlint '
                        '-c oxlint.config.ts --threads=1 example.mjs > ../.scratch/result.log 2>&1'):
            with self.subTest(command=command):
                self.assert_denied(command, ultraship.RECEIPT_CUSTODY, caller='')


class ReceiptCustodyTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.state = Path(temporary).resolve() / 'custom-state'
        self.cwd = Path(temporary).resolve() / 'repo'
        self.cwd.mkdir()
        self.enterContext(patch.dict(os.environ, {'HOME': temporary, 'XDG_STATE_HOME': str(self.state)}))
        self.store = self.state / 'ultraship' / 'text-lint'
        self.enterContext(patch.object(ultraship.pwd, 'getpwuid', return_value=SimpleNamespace(pw_dir=temporary)))
        self.ledger = ultraship.load_ledger()
        self.enterContext(patch.object(ultraship, 'load_ledger', return_value=self.ledger))

    def assert_custody_denial(self, event, reason=(
            'Only the text_lint hook reads or writes refusal receipts (custody rule). '
            'Report the blocked scope to the driver.')):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit:
            ultraship.guarded_pre({'cwd': str(self.cwd), **event})
        self.assertEqual(exit.exception.code, 0)
        result = json.loads(output.getvalue())['hookSpecificOutput']
        self.assertEqual(result['permissionDecision'], 'deny')
        self.assertEqual(result['permissionDecisionReason'].split('\n', 1)[0], reason)

    def assert_custody_warning(self, event):
        """The call proceeds with an advisory S2 warning and no permission decision."""
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            try:
                ultraship.guarded_pre({'cwd': str(self.cwd), **event})
            except SystemExit:
                self.fail(output.getvalue())
        result = json.loads(output.getvalue())['hookSpecificOutput']
        self.assertNotIn('permissionDecision', result)
        self.assertTrue(result['additionalContext'].startswith('S2: '), result)

    def test_parser_refusal_preserves_literal_retry(self):
        caller = 'ship:writer--sol'
        event = {'cwd': str(self.cwd), 'tool_name': 'Bash', 'agent_type': caller,
                 'tool_input': {'command': 'pwd "-P'}}
        with redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit):
            ultraship.guarded_pre(event)
        decision = json.loads(output.getvalue())['hookSpecificOutput']
        self.assertEqual(decision['permissionDecision'], 'deny')
        self.assertIn('unparsed shell syntax rule: unfinished shell quote', decision['permissionDecisionReason'])
        self.assert_account_command_allowed('pwd -P', caller=caller)

    def test_literal_cwd_query_keeps_custody_and_hook_failure_blocks(self):
        event = {'tool_name': 'Bash', 'agent_type': 'ship:writer--sol', 'tool_input': {'command': 'pwd -P'}}
        self.assert_custody_denial({**event, 'cwd': str(self.store)})
        with patch.object(ultraship, 'pre_output', side_effect=RuntimeError):
            self.assert_custody_denial(event, ultraship.PRE_FAILED)

    def prepare_owed(self, event):
        pending = ultraship.owed_file(event)
        pending.parent.mkdir(parents=True, exist_ok=True)
        pending.touch(exist_ok=True)
        return pending

    def consume(self, words):
        with self.ledger.consume_grant(words[1], words[2:]):
            pass

    def own_account_event(self):
        os.environ.pop('XDG_STATE_HOME', None)
        state = Path(os.environ['HOME']) / '.local/state/ultraship'
        self.enterContext(patch.object(ultraship, 'STATE', state))
        self.prepare_owed({'session_id': 'session-context'})
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
                    self.consume(shlex.split(command))

        for evidence in ('"reviewed context, [P2] nit"', r"'Reviewer'\''s [P2] context'"):
            command = shlex.join(self.account_words[:-1]) + ' ' + evidence
            with self.subTest(evidence=evidence):
                output = io.StringIO()
                with redirect_stdout(output), redirect_stderr(io.StringIO()):
                    self.assertIsNone(ultraship.guarded_pre(
                        {'cwd': str(self.cwd), **event, 'tool_input': {'command': command}}))
                self.assertEqual(output.getvalue(), '')
                self.consume(shlex.split(command))

    def test_own_account_call_allows_literal_hook_name_in_evidence(self):
        event = self.own_account_event()
        words = [*self.account_words[:-1], "Reviewer's finding in ultraship.py: $HOME/hooks/*"]
        self.assert_account_command_allowed(shlex.join(words), session_id=event['session_id'])
        self.consume(words)

    def test_grant_issuance_failure_removes_temporary_record(self):
        event = self.own_account_event()
        with patch.object(self.ledger.os, 'fsync', side_effect=OSError):
            self.assert_custody_denial(event, 'The ship hook could not issue a fresh accounting grant. '
                                     'Run the exact command again.')
        self.assertFalse(any(self.ledger.grant_store().iterdir()))
        with self.assertRaisesRegex(ValueError, 'requires a fresh grant'):
            self.consume(self.account_words)

    def test_grant_refuses_mismatch_expiry_replay_and_failed_consume(self):
        event = self.own_account_event()
        words = self.account_words
        with patch.object(self.ledger.time, 'time_ns', return_value=10_000_000_000) as clock:
            self.assert_account_command_allowed(shlex.join(words), session_id=event['session_id'])
            with self.assertRaisesRegex(ValueError, 'requires a fresh grant'):
                self.consume([*words[:-1], 'different evidence'])
            with patch.object(self.ledger.os, 'unlink', side_effect=PermissionError):
                with self.assertRaisesRegex(ValueError, 'requires a fresh grant'):
                    self.consume(words)
            clock.return_value += 899_999_999_999
            self.consume(words)
            with self.assertRaisesRegex(ValueError, 'requires a fresh grant'):
                self.consume(words)
            self.assert_account_command_allowed(shlex.join(words), session_id=event['session_id'])
            clock.return_value += 900_000_000_000
            with self.assertRaisesRegex(ValueError, 'requires a fresh grant'):
                self.consume(words)
            self.assert_account_command_allowed(shlex.join(words), session_id=event['session_id'])
            self.consume(words)

    def test_grant_refuses_replacement_and_second_claimant(self):
        event = self.own_account_event()
        words = self.account_words
        refusal = 'The ship hook could not issue a fresh accounting grant. Run the exact command again.'
        with patch.object(self.ledger.time, 'time_ns', return_value=10_000_000_000) as clock:
            self.assert_account_command_allowed(shlex.join(words), session_id=event['session_id'])
            record, = self.ledger.grant_store().iterdir()
            issued = record.read_bytes()
            clock.return_value += 899_999_999_999
            self.assert_account_command_allowed(shlex.join(words), session_id=event['session_id'])
            self.assertEqual(record.read_bytes(), issued)
            self.assert_custody_denial({**event, 'tool_input': {'command': shlex.join(
                [*words[:-1], 'different evidence'])}}, refusal)
            barrier = Barrier(2, timeout=5)
            outcomes = []

            def claim():
                barrier.wait()
                try:
                    self.consume(words)
                    outcomes.append('consumed')
                except ValueError:
                    outcomes.append('refused')

            claimants = [Thread(target=claim) for _ in range(2)]
            for claimant in claimants:
                claimant.start()
            for claimant in claimants:
                claimant.join()
            self.assertEqual(sorted(outcomes), ['consumed', 'refused'])
            with self.assertRaisesRegex(ValueError, 'requires a fresh grant'):
                self.consume(words)

    def test_grant_refuses_malformed_and_linked_records(self):
        event = self.own_account_event()
        words = self.account_words
        self.assert_account_command_allowed(shlex.join(words), session_id=event['session_id'])
        record, = self.ledger.grant_store().iterdir()
        retained = record.with_suffix('.retained')
        os.link(record, retained)
        with self.assertRaisesRegex(ValueError, 'requires a fresh grant'):
            self.consume(words)
        record.unlink()
        record.symlink_to(retained)
        with self.assertRaisesRegex(ValueError, 'requires a fresh grant'):
            self.consume(words)
        record.unlink()
        retained.rename(record)
        record.write_bytes(b'{broken')
        with self.assertRaisesRegex(ValueError, 'requires a fresh grant'):
            self.consume(words)

    def test_grant_refuses_a_symlinked_store_component(self):
        event = self.own_account_event()
        words = self.account_words
        self.assert_account_command_allowed(shlex.join(words), session_id=event['session_id'])
        store = self.ledger.grant_store()
        retained = store.rename(store.with_name('retained'))
        store.symlink_to(retained, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'requires a fresh grant'):
            self.consume(words)
        self.assert_custody_denial(event, 'The ship hook could not issue a fresh accounting grant. Run the exact command again.')

    def test_denied_hook_emits_no_grant(self):
        event = self.own_account_event()
        self.assert_custody_denial({**event, 'agent_type': 'ship:writer--sol'})
        with self.assertRaisesRegex(ValueError, 'requires a fresh grant'):
            self.consume(self.account_words)
        with patch.object(ultraship, 'pre_output', side_effect=RuntimeError):
            self.assert_custody_denial(event, ultraship.PRE_FAILED)
        with self.assertRaisesRegex(ValueError, 'requires a fresh grant'):
            self.consume(self.account_words)

    def test_grant_store_custody_guards_paths_aliases_and_hook_entry(self):
        path = self.ledger.grant_store()
        path.mkdir(mode=0o700, parents=True)
        alias = self.cwd / 'alias to store'
        alias.symlink_to(path, target_is_directory=True)
        hook_alias = self.cwd / 'hook-alias'
        hook_alias.symlink_to(HOOK)
        for command in (f'cat {shlex.quote(str(path / "example"))}', "cat 'alias to store/example'",
                        f'ls {path.parent}/acc*/*',
                        f'python3 {shlex.quote(str(HOOK))} pre', 'python3 ./hook-alias pre'):
            with self.subTest(command=command):
                self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': command}})
        # Listing a parent folder of the store reads no store file.
        self.assert_account_command_allowed(f'ls {path.parent}', caller='')
        for tool, key, value in (('Read', 'file_path', str(alias / 'example')),
                                 ('Write', 'file_path', str(alias / 'example')),
                                 ('Grep', 'path', str(path.parent)),
                                 ('Glob', 'pattern', str(path.parent / '*/*.json'))):
            with self.subTest(tool=tool):
                self.assert_custody_denial({'tool_name': tool, 'tool_input': {key: value}})

    def test_grant_custody_refuses_store_and_ancestor_changes(self):
        store = self.ledger.grant_store()
        for target in (store, store.parent.parent.parent):
            path = shlex.quote(str(target))
            for command in (f'rm -rf {path}', f'mv {path} saved', f'cp -r fixture {path}',
                            f'printf data > {path}', f'printf data >> {path}', f'find {path} -delete',
                            f'find {path} -fprint output', f'find {path} -fprint0 output',
                            f'rsync -a --delete empty/ {path}/',
                            f'tar -xf fixture.tar -C {path}', f'printf fixture | xargs rm {path}',
                            f"python3 -c 'pass' {path}"):
                with self.subTest(command=command):
                    self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': command}})
            for tool in ('Edit', 'Write'):
                with self.subTest(tool=tool, target=target):
                    self.assert_custody_denial({'tool_name': tool, 'tool_input': {'file_path': str(target)}})

    def test_grant_custody_denies_attached_ancestor_paths(self):
        ancestor = shlex.quote(str(self.ledger.grant_store().parent.parent.parent))
        for command in (f'tar -xf fixture.tar --directory={ancestor}',
                        f'tar -xf fixture.tar -C{ancestor}', f'tar -xC{ancestor} -f fixture.tar',
                        f'VAR={ancestor} tar -tf fixture.tar'):
            with self.subTest(command=command):
                self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': command}})

    def test_grant_custody_denies_gh_api_redirect_to_grant_store(self):
        destination = shlex.quote(str(self.ledger.grant_store() / 'output'))
        self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {
            'command': f'gh api user > {destination}'}})

    def test_grant_custody_denies_hook_execution_forms(self):
        installed = shlex.quote(str(HOOK))
        relative = os.path.relpath(HOOK, self.cwd)
        alias = self.cwd / 'named-entry'
        alias.symlink_to(HOOK)
        copy = self.cwd / HOOK.name
        copy.touch()
        for form, command in (
                ('installed path without mode', f'python3 {installed}'),
                ('variable mode with redirect', f'python3 {installed} "$MODE" < input.json'),
                ('relative installed path', f'python3 {shlex.quote(relative)} stop'),
                ('alias with interpreter path', 'env /usr/bin/python3 ./named-entry stop'),
                ('alias as a command', './named-entry'),
                ('alias in a nested shell', "sh -c 'python3 ./named-entry stop'"),
                ('repository file as a command', './ultraship.py'),
                ('repository file via interpreter', '/usr/bin/python3 ./ultraship.py stop'),
                ('pipeline into repository file', 'cat input.json | python3 ./ultraship.py stop'),
                ('module', 'python3 -m plugins.ship.hooks.ultraship stop'),
                ('attached module', 'python3 -multraship stop'),
                ('grouped module flag', 'python3 -Im plugins.ship.hooks.ultraship stop'),
                ('grouped attached module', 'python3 -Implugins.ship.hooks.ultraship stop'),
                ('inline import', 'python3 -c "import ultraship"'),
                ('standard input import', "python3 - <<'EOF'\nfrom plugins.ship.hooks import ultraship\nEOF"),
                ('runpy target', "python3 -c 'import runpy; runpy.run_module(\"ultraship\")'"),
                ('import target', "python3 -c 'import importlib; importlib.import_module(\"ultraship\")'"),
                ('issuer symbol', 'python3 -c "print(issue_account_grant)"'),
                ('grant writer symbol', 'python3 -c "print(_issue_grant)"'),
        ):
            with self.subTest(form=form):
                self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': command}})
        # A pure text read of the hook runs no hook code; any other command that names it stays refused.
        self.assert_account_command_allowed(f'cat < {installed}', caller='')
        self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': f'printf %s {installed}'}})
        self.assert_custody_warning({'tool_name': 'Bash', 'tool_input': {'command': "echo ultraship 'unfinished"}})
        with patch.object(ultraship, 'nested_work_exceeded', return_value=True):
            self.assert_custody_warning({'tool_name': 'Bash', 'tool_input': {'command': 'echo ultraship'}})
            self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {
                'command': f'python3 {installed} pre'}})

    def test_grant_custody_denies_hook_path_expansions(self):
        installed = Path.home() / 'plugin with spaces/hooks/ultraship.py'
        with patch.object(ultraship, '__file__', str(installed)):
            for form, command in (
                    ('file glob', f'python3 {shlex.quote(str(installed.parent))}/ultra*.py'),
                    ('folder glob', f'python3 {shlex.quote(str(installed.parent.parent))}/hoo?s/*.py'),
                    ('home and file expansion', 'python3 "$HOME/plugin with spaces/hooks/ultra${SUFFIX}"'),
                    ('unquoted backtick expansion', f'python3 {shlex.quote(str(installed.parent))}/ultra`printf suffix`'),
                    ('hook name with no path prefix', 'python3 "${ROOT}/hooks/${SCRIPT}"'),
            ):
                with self.subTest(form=form):
                    self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': command}})

    def test_grant_custody_denies_hook_folder_brace_expansion(self):
        installed = Path.home() / 'plugin/hooks/ultraship.py'
        with patch.object(ultraship, '__file__', str(installed)):
            self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {
                'command': f'python3 {shlex.quote(str(installed.parent.parent))}/{{hooks,docs}}/{{ultra,other}}ship.py'}})

    def test_grant_custody_warns_on_glob_in_noninterpreter_argument(self):
        installed = Path.home() / 'plugin/hooks/ultraship.py'
        with patch.object(ultraship, '__file__', str(installed)):
            self.assert_custody_warning({'tool_name': 'Bash', 'tool_input': {
                'command': f'ls {shlex.quote(str(installed.parent.parent))}/hoo?s/ultra*.py'}})

    def test_grant_custody_warns_on_braces_in_noninterpreter_argument(self):
        self.assert_custody_warning({'tool_name': 'Bash', 'tool_input': {
            'command': 'ls ./plugin/{hooks,docs}/{ultra,other}ship.py'}})

    def test_grant_custody_warns_on_cwd_relative_hook_glob(self):
        plugin = self.cwd / 'plugin'
        with patch.object(ultraship, '__file__', str(plugin / 'hooks/ultraship.py')):
            self.assert_custody_warning({'cwd': str(plugin), 'tool_name': 'Bash',
                                       'tool_input': {'command': 'ls [h]ooks/ultra*.py'}})

    def test_grant_custody_warns_on_hook_glob_without_literal_prefix(self):
        plugin = self.cwd / 'plugin'
        with patch.object(ultraship, '__file__', str(plugin / 'hooks/ultraship.py')):
            self.assert_custody_warning({'cwd': str(plugin), 'tool_name': 'Bash',
                                       'tool_input': {'command': 'ls */ultra*.py'}})

    def test_grant_custody_denies_literal_hook_after_directory_change(self):
        self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {
            'command': f'cd {shlex.quote(str(HOOK.parent))} && python3 ultraship.py'}})

    def test_grant_custody_allows_ordinary_shell_and_exact_stop_commands(self):
        event = self.own_account_event()
        for command in ('ls *.py', 'df -h /', 'ls ~', 'find . -name x',
                        f'cd {shlex.quote(str(self.cwd))} && git status',
                        f'cd {shlex.quote(str(self.cwd))} && uv run pytest'):
            with self.subTest(command=command):
                self.assert_account_command_allowed(command, caller='')
        words = [*self.account_words[:2], 'account-auto', self.account_words[3]]
        self.assert_account_command_allowed(shlex.join(words), session_id=event['session_id'])
        self.consume(words)

    def test_grant_custody_admits_ordinary_calls_when_the_account_has_no_passwd_entry(self):
        with patch.object(ultraship.pwd, 'getpwuid', side_effect=KeyError('getpwuid(): uid not found')):
            self.assert_account_command_allowed('ls *.py', caller='')
            self.assert_account_command_allowed('ls *.py')
            with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
                ultraship.guarded_pre({'cwd': str(self.cwd), 'agent_type': '', 'tool_name': 'Read',
                                       'tool_input': {'file_path': str(self.cwd / 'file.py')}})
            self.assertEqual(output.getvalue(), '')
            self.assert_custody_denial({'tool_name': 'Read', 'tool_input': {'file_path': str(self.store / 'key')}})

    def test_own_account_call_is_denied_when_the_account_has_no_passwd_entry(self):
        event = self.own_account_event()
        with patch.object(ultraship.pwd, 'getpwuid', side_effect=KeyError('getpwuid(): uid not found')):
            self.assert_custody_denial(event, 'The ship hook could not issue a fresh accounting grant. '
                                     'Run the exact command again.')

    def test_grant_custody_admits_literal_indexed_array_assignment(self):
        self.assert_account_command_allowed('items=([0]=alpha [1]=beta)', caller='ship:writer--sol')

    def test_grant_custody_admits_literal_pr_comment_body(self):
        self.assert_account_command_allowed(r"gh pr comment 7 --body $'first\nsecond `example`'", caller='')

    def test_grant_custody_treats_find_name_as_data(self):
        self.assert_account_command_allowed("find ./scripts -name 'uv' -print", caller='ship:writer--sol')

    def test_grant_custody_warns_on_uncertain_commands_without_custody_words(self):
        self.assert_custody_warning({'tool_name': 'Bash', 'tool_input': {'command': "echo 'unfinished"}})
        with patch.object(ultraship, 'nested_work_exceeded', return_value=True):
            self.assert_custody_warning({'tool_name': 'Bash', 'tool_input': {'command': 'echo ordinary'}})

    def test_grant_custody_warns_on_unclosed_group(self):
        self.assert_custody_warning({'tool_name': 'Bash', 'tool_input': {'command': '(echo ordinary'}})

    def test_grant_custody_warns_on_unterminated_heredoc(self):
        self.assert_custody_warning({'tool_name': 'Bash', 'tool_input': {'command': "cat <<'EOF'\nordinary\n"}})

    def test_grant_custody_warns_on_open_braces_and_empty_delimiter_heredoc(self):
        for command in ('{ echo ordinary;', "cat <<''\nordinary\n", 'cat <<""\nordinary\n'):
            with self.subTest(command=command):
                self.assert_custody_warning({'tool_name': 'Bash', 'tool_input': {'command': command}})

    def test_grant_custody_allows_plain_repository_source_commands(self):
        source = 'plugins/ship/hooks/ultraship.py'
        for command in (f'git diff -- {source}', f'git add -- {source}', f'git show HEAD:{source}',
                        f"grep -n 'issue_account_grant' {source}", f'diff -u saved.py {source}'):
            with self.subTest(command=command):
                self.assert_account_command_allowed(command, caller='ship:writer--sol')

    def clone_source(self):
        """Make the working directory a Git work tree that holds a copy of the hook source."""
        source = 'plugins/ship/hooks/ultraship.py'
        (self.cwd / '.git').mkdir()
        (self.cwd / source).parent.mkdir(parents=True)
        (self.cwd / source).write_text('print(1)\n')
        return source

    def test_grant_custody_allows_a_line_range_read_of_hook_source_in_a_clone(self):
        source = self.clone_source()
        for caller in ('', 'general-purpose', 'ship:writer--sol'):
            for command in (f'sed -n 6231,6300p {source}', f"sed -n '6231,6300p' {source}", f'sed -n 5145p {source}',
                            f'sed -n 1p {source} {source}',
                            f'cd {shlex.quote(str(self.cwd))} && sed -n 6231,6300p {source}',
                            'cd plugins/ship && sed -n 6231,6300p hooks/ultraship.py',
                            f'cd ~/repo && sed -n 6231,6300p {source}',
                            f'git -C /repo diff --stat fa85be3 edf0871 -- {source}'):
                with self.subTest(caller=caller, command=command):
                    self.assert_account_command_allowed(command, caller=caller)

    def test_grant_custody_reads_hook_source_by_line_range_only_from_a_file_in_a_git_work_tree(self):
        source = self.clone_source()
        outside = Path(os.environ['HOME']) / 'plain/ultraship.py'
        outside.parent.mkdir()
        outside.write_text('print(1)\n')
        (self.cwd / 'outside-alias.py').symlink_to(outside)
        (self.cwd / 'plugin-alias').symlink_to(HOOK.parents[1])
        # A repository at the home folder itself, such as one for dotfiles, makes no file below it a clone.
        (Path(os.environ['HOME']) / '.git').mkdir()
        installed = Path(os.environ['HOME']) / '.claude/plugins/marketplaces/ultraship'
        (installed / '.git').mkdir(parents=True)
        (installed / 'ultraship.py').write_text('print(1)\n')
        for command in (f'sed -n 1p {shlex.quote(str(outside))}', f'sed -n 1p {source} outside-alias.py',
                        f'cd {shlex.quote(str(outside.parent))} && sed -n 1p ultraship.py',
                        'sed -n 1p ~/.claude/plugins/marketplaces/ultraship/ultraship.py',
                        f'sed -n 1p {source} plugins/ship/hooks', 'sed -n 1p plugins/ship/hooks/missing/ultraship.py',
                        f'sed -n 1p {source} plugin-alias/hooks/ultraship.py',
                        'cd plugin-alias/hooks && sed -n 1p ultraship.py',
                        # `diff` opens a file of the same name inside a folder operand, so it takes no `cd` prefix.
                        f'cd {shlex.quote(str(self.cwd))} && diff -u saved.py {source}',
                        'cd plugins/ship && diff -u hooks/ultraship.py ../..'):
            with self.subTest(command=command):
                self.assert_custody_denial({'agent_type': 'general-purpose', 'tool_name': 'Bash',
                                            'tool_input': {'command': command}})

    def test_grant_custody_allows_a_search_of_found_ledger_copies_in_a_clone(self):
        for caller in ('', 'general-purpose'):
            for command in ('find plugins -name "ledger.py"',
                            'grep -n "def grant_store" $(find plugins -name "ledger.py")',
                            'find plugins -name "ledger.py" && grep -n "consume_grant" $(find plugins -name "ledger.py")'):
                with self.subTest(caller=caller, command=command):
                    self.assert_account_command_allowed(command, caller=caller)
            # The accounting word and a hook symbol keep their refusals when the file list comes from a substitution.
            for command in ('grep -n "account-auto" $(find plugins -name "ledger.py")',
                            'grep -n "_issue_grant" $(find plugins -name "ledger.py")'):
                with self.subTest(caller=caller, command=command):
                    self.assert_custody_denial({'agent_type': caller, 'tool_name': 'Bash',
                                                'tool_input': {'command': command}})

    def test_grant_custody_allows_a_marketplace_update_and_plain_reads_of_the_marketplace_list(self):
        listing = '~/.claude/plugins/known_marketplaces.json'
        for caller in ('', 'ship:driver--sol', 'general-purpose'):
            for command in ('claude plugin marketplace update ultraship', 'claude plugin marketplace update',
                            'claude plugin update ship@ultraship', f'cat {listing}', f"jq '.ultraship' {listing}",
                            f'python3 -m json.tool {listing}',
                            f'python3 -c "import json,os; print(list(json.load(open(os.path.expanduser(\'{listing}\')))))"'):
                with self.subTest(caller=caller, command=command):
                    self.assert_account_command_allowed(command, caller=caller)
            # A quoted module name in interpreter code could be an import target, so it keeps its refusal.
            for command in (f'python3 -c "import json,os; print(json.load(open(os.path.expanduser(\'{listing}\')))[\'ultraship\'])"',
                            f"python3 -c 'import json,os; print(json.load(open(os.path.expanduser(\"{listing}\"))).get(\"ultraship\"))'"):
                with self.subTest(caller=caller, command=command):
                    self.assert_custody_denial({'agent_type': caller, 'tool_name': 'Bash',
                                                'tool_input': {'command': command}})

    def test_grant_custody_denies_other_sed_forms_and_directory_changes_with_the_hook_name(self):
        source = self.clone_source()
        installed = shlex.quote(str(HOOK))
        repo = shlex.quote(str(self.cwd))
        (self.cwd / 'hook-alias').symlink_to(HOOK)
        (self.cwd / 'print.sed').write_text('1,5p\n')
        for command in (f'sed -i 1d {source}', f"sed -n '1,5p;w out' {source}", f"sed -n '1e id' {source}",
                        f'sed -n 1,5p {source} -i', f"sed -n -e 1,5p -e 'w out' {source}", f"sed -n '$p' {source}",
                        f"sed -n '/def pre/,/^def /p' {source}", f'sed 1,5p {source}',
                        f'sed --file print.sed {source}', f'sed -n --file=print.sed {source}',
                        f'sed -n 1,5p --file print.sed {source}', f'sed -n -f print.sed {source}',
                        # The shell keeps a backslash and newline inside single quotes, so it opens another file name.
                        "sed -n 1,5p 'plugins/ship/hooks/ultra\\\nship.py'",
                        f"cd {repo} && sed -n 1,5p 'plugins/ship/hooks/ultra\\\nship.py'",
                        f'sed -n 1,5p {source} | python3 - pre', f'sed -n 1,5p {source} && python3 {source} pre',
                        f'sed -n 1,5p $(echo {source})', f'sed -n 1,5p {source} > {shlex.quote(str(self.store / "key"))}',
                        f'sed -n 1,5p {shlex.quote(str(self.store / "key"))}',
                        f'sed -n 1,5p {installed}', 'sed -n 1,5p ./hook-alias',
                        f'cd {shlex.quote(str(HOOK.parent))} && sed -n 1,5p ultraship.py',
                        f'cd {repo} && python3 {source} pre', f'cd $(pwd) && sed -n 1,5p {source}',
                        f'cd - && sed -n 1,5p {source}', f'cd {repo} & & sed -n 1,5p {source}',
                        f'cd {repo} && cd {shlex.quote(str(HOOK.parent))} && sed -n 1,5p ultraship.py',
                        # A repository can configure a program for git, so git takes its folder only through `-C`.
                        f'cd {repo} && git diff --stat fa85be3 edf0871 -- {source}', f'cd {repo} && git show HEAD:{source}',
                        f'cd {repo} && git diff -- {source} | python3 - pre'):
            with self.subTest(command=command):
                self.assert_custody_denial({'agent_type': 'general-purpose', 'tool_name': 'Bash',
                                            'tool_input': {'command': command}})

    def test_grant_custody_allows_literal_search_chain_with_hook_name(self):
        self.assert_account_command_allowed(
            "cd /repo && find . -name README.md && grep -n 'def pre' plugins/ship/hooks/ultraship.py && ls .")

    def test_grant_custody_allows_path_prefix_above_home(self):
        home = Path.home()
        command = f'echo {shlex.quote(str(home.parent))}/$(date)'
        with patch.object(ultraship, '__file__', str(home / 'plugin/hooks/ultraship.py')):
            self.assert_account_command_allowed(command)

    def test_grant_custody_allows_home_and_working_paths_that_hold_hook_folder_names(self):
        home = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve() / 'ultraship' / 'hooks' / 'home'
        self.cwd = home / 'repo'
        self.cwd.mkdir(parents=True)
        self.enterContext(patch.dict(os.environ, {'HOME': str(home)}))
        self.enterContext(patch.object(ultraship.pwd, 'getpwuid', return_value=SimpleNamespace(pw_dir=str(home))))
        self.enterContext(patch.object(ultraship, '__file__', str(home / 'plugin/hooks/ultraship.py')))
        for command in ('PATH="${HOME}/.local/bin:${PATH}" make -r test', f'echo {shlex.quote(str(home.parent))}/$(date)',
                        f'ls {shlex.quote(str(self.cwd))}/*.py'):
            with self.subTest(command=command):
                self.assert_account_command_allowed(command)

    def test_grant_custody_handles_hook_names_after_an_unresolved_path_segment(self):
        self.assert_custody_warning({'tool_name': 'Bash', 'tool_input': {
            'command': 'ls ~/.claude/plugins/cache/*/ship/*/hooks/u*.py'}})
        # The hook name appears, so the unresolved word stays fail-closed.
        self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': 'cat ./hoo$x/ultraship.py'}})

    def test_grant_custody_allows_complete_brace_group_and_literal_shell_code(self):
        for command in ('{ echo a; echo b; }', "bash -c 'label=sample; echo \"$label\"'"):
            with self.subTest(command=command):
                self.assert_account_command_allowed(command)

    def test_grant_custody_treats_program_running_reader_options_as_writes(self):
        ancestor = shlex.quote(str(self.ledger.grant_store().parent.parent.parent))
        for command in (f'rg --pre=cat text {ancestor}', f'rg --pre-glob=*.txt text {ancestor}',
                        f'sort --compress-program=cat {ancestor}'):
            with self.subTest(command=command):
                self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': command}})

    def test_grant_custody_denies_interpreter_operands_after_value_options(self):
        # An unresolved interpreter operand or an unknown interpreter option could run the hook.
        for command in ('bash -o pipefail -c "$BODY"', 'uv run --with sample "$SCRIPT"',
                        'bash --unknown-option sample.sh', 'uv run --unknown-option sample.py'):
            with self.subTest(command=command):
                self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': command}})

    def test_grant_custody_admits_ancestor_operands_of_df_and_read_only_git(self):
        ancestor = shlex.quote(str(self.ledger.grant_store().parent.parent.parent))
        probe = ('env -i PATH="$PATH" HOME="$HOME" GIT_ASKPASS= GIT_TERMINAL_PROMPT=0 '
                 f'git -C {ancestor} -c credential.helper= ls-remote --symref origin HEAD')
        for command in (f'{probe} | wc -l; touch result', f'git -C {ancestor} status --porcelain; touch result',
                        f'df -h {ancestor}; touch result',
                        f'disk=$(df --output=pcent {ancestor} | tail -n 1); touch result'):
            with self.subTest(command=command):
                self.assert_account_command_allowed(command, caller='')
        for command in (f'git -C {ancestor} clean -fdx', f'git -C {ancestor} ls-remote --upload-pack=true origin',
                        f'git -C {ancestor} -c core.pager=true status', f'git -C {ancestor} status > output',
                        f'df -h {ancestor} > output', f'df -h {ancestor}; rm -rf {ancestor}'):
            with self.subTest(command=command):
                self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': command}})

    def test_grant_custody_denies_ls_remote_upload_pack_short_forms(self):
        ancestor = shlex.quote(str(self.ledger.grant_store().parent.parent.parent))
        for option in ('-u true', '-utrue', '-qu true'):
            with self.subTest(option=option):
                self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {
                    'command': f'git -C {ancestor} ls-remote {option} origin; touch result'}})

    def test_grant_custody_denies_ls_remote_options_that_a_shell_expansion_supplies(self):
        ancestor = shlex.quote(str(self.ledger.grant_store().parent.parent.parent))
        for command in (f"opt=-u; git -C {ancestor} ls-remote $opt 'cmd' /some/repo",
                        f"git -C {ancestor} ls-remote {{-u,'cmd'}} /some/repo",
                        f"git -C {ancestor} ls-remote $(printf -- -u) 'cmd' /some/repo",
                        f"git -C {ancestor} ls-remote `printf -- -u` 'cmd' /some/repo"):
            with self.subTest(command=command):
                self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': command}})

    def test_grant_custody_admits_the_short_status_option_u_after_an_ancestor(self):
        ancestor = shlex.quote(str(self.ledger.grant_store().parent.parent.parent))
        self.assert_account_command_allowed(f'git -C {ancestor} status -uno; touch result', caller='')

    def test_grant_custody_admits_a_single_quoted_dollar_in_git_log(self):
        ancestor = shlex.quote(str(self.ledger.grant_store().parent.parent.parent))
        self.assert_account_command_allowed(f"git -C {ancestor} log -- '$notes'; touch result", caller='')

    def test_grant_custody_denies_abbreviated_git_program_and_output_options(self):
        ancestor = shlex.quote(str(self.ledger.grant_store().parent.parent.parent))
        for option in ('--upl=true', '--u=true', '--rec=true', '--ex=true', '--e=true', '--out=file', '--o=file'):
            with self.subTest(option=option):
                self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {
                    'command': f'git -C {ancestor} ls-remote {option} origin; touch result'}})

    def test_grant_custody_drops_the_git_read_exception_for_a_quoted_rebinding(self):
        binding = 'status=$(git -C "$worktree" status --porcelain); '
        self.assert_account_command_allowed(binding + '$status', caller='')
        for rebinding in ('printf -v sta"tus" %s x; ', r'read st\atus; '):
            with self.subTest(rebinding=rebinding):
                self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': binding + rebinding + '$status'}})

    def test_grant_custody_denies_a_git_binding_to_a_name_the_shell_sets(self):
        for name in ('_', 'REPLY', 'reply', 'argv', '1', 'match', 'mbegin', 'mend'):
            with self.subTest(name=name):
                self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {
                    'command': f'{name}=$(git -C "$worktree" status --porcelain); ${name}'}})

    def test_grant_custody_admits_read_only_commands_that_name_the_hook_by_alias(self):
        (self.cwd / 'hook-alias').symlink_to(HOOK)
        self.assert_account_command_allowed('cat ./hook-alias', caller='')
        for command in ('python3 ./hook-alias pre', 'cat ./hook-alias | python3 - pre'):
            with self.subTest(command=command):
                self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': command}})

    def test_grant_custody_treats_an_inert_quoted_script_as_file_text(self):
        body = "from pathlib import Path\nprint(Path('plugins/ship/hooks/ultraship.py').read_text().count('def'))\n"
        self.assert_account_command_allowed(f"python3 - <<'EOF'\n{body}EOF\n", caller='')
        runner = ("import subprocess\nsubprocess.run(['python3', 'plugins/ship/hooks/ultraship.py', 'pre'])\n")
        self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': f"python3 - <<'EOF'\n{runner}EOF\n"}})

    def test_grant_custody_treats_unresolved_words_after_a_search_pattern_as_data(self):
        self.assert_account_command_allowed('grep -rn eval "$DIR"', caller='')
        self.assert_account_command_allowed('grep -rn eval src/*.py | head', caller='')
        self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': 'eval "$DIR"'}})
        self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': 'grep -rn x eval "$DIR" ; eval "$DIR"'}})

    def test_stop_account_diagnostic_admits_quoted_paths(self):
        event = self.own_account_event()
        home = Path(os.environ['HOME']) / 'home with text'
        state = home / '.local/state/ultraship'
        script = self.cwd / 'plugin with space/ledger.py'
        script.parent.mkdir()
        script.touch()
        with patch.dict(os.environ, {'HOME': str(home)}), \
                patch.object(ultraship, 'STATE', state), \
                patch.object(ultraship, 'ledger_script', return_value=script), \
                patch.object(self.ledger, '__file__', str(script)), \
                patch.object(ultraship, 'account', side_effect=ValueError('synthetic missing review')):
            pending = self.prepare_owed(event)
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

            self.consume(shlex.split(command))
            self.assertNotIn(' account-auto ', diagnostic['reason'])
            auto = shlex.join(['python3', str(script), 'account-auto', str(pending)])
            for caller in ('', 'ship:driver--sol'):
                with self.subTest(caller=caller):
                    output = io.StringIO()
                    with redirect_stdout(output), redirect_stderr(io.StringIO()):
                        ultraship.guarded_pre({'cwd': str(self.cwd), **event, 'agent_type': caller,
                                               'tool_input': {'command': auto}})
                    self.assertEqual(output.getvalue(), '')
                    self.consume(shlex.split(auto))
            for invalid in (auto + ' extra', auto + ' && echo done', auto.replace('session-context', 'sibling')):
                with self.subTest(command=invalid):
                    self.assert_custody_denial({**event, 'tool_input': {'command': invalid}})
            self.assert_custody_denial({**event, 'agent_type': 'ship:writer--sol', 'tool_input': {'command': auto}})

    def test_plain_account_auto_requires_own_driver_call(self):
        event = self.own_account_event()
        event['session_id'] = 's1'
        command = shlex.join([*self.account_words[:2], 'account-auto', str(self.prepare_owed(event))])
        driver = {**event, 'agent_type': 'ship:driver--sol', 'tool_input': {'command': command}}
        with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
            self.assertIsNone(ultraship.guarded_pre({'cwd': str(self.cwd), **driver}))
        self.assertEqual(output.getvalue(), '')
        with self.subTest('writer'):
            self.assert_custody_denial({**driver, 'agent_type': 'ship:writer--sol'})
        with self.subTest('sibling'):
            sibling = command.replace('s1.tsv', 'sibling.tsv')
            self.assert_custody_denial({**driver, 'tool_input': {'command': sibling}})

    def test_stop_account_auto_line_passes_and_a_refusal_names_the_difference(self):
        event = self.own_account_event()
        event['session_id'] = '67a62f05-978d-412a-97db-3073378bcd29'
        line = shlex.join(['python3', str(ultraship.ledger_script()), 'account-auto', str(self.prepare_owed(event))])
        for caller in ('', 'ship:driver', 'ship:driver--sol'):
            with self.subTest(caller=caller):
                self.assert_account_command_allowed(line, caller=caller, session_id=event['session_id'])
                self.consume(shlex.split(line))

        def refusal(command=line, **changes):
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                ultraship.guarded_pre({'cwd': str(self.cwd), **event, 'tool_input': {'command': command}, **changes})
            lines = json.loads(output.getvalue())['hookSpecificOutput']['permissionDecisionReason'].split('\n')
            self.assertEqual(lines[0], ultraship.RECEIPT_CUSTODY)
            return lines[1]

        self.assertIn("agent type 'coordinator'", refusal(agent_type='coordinator'))
        self.assertIn('session ID', refusal(session_id=None))
        for command in (line + ' ', line + '\n', line + ' 2>&1', f'cd {shlex.quote(str(self.cwd))} && {line}',
                        line.replace('67a62f05', '00000000')):
            with self.subTest(command=command):
                self.assertIn(f'`{line}`', refusal(command))

    def test_fail_unparsed_requires_exact_own_driver_call(self):
        event = self.own_account_event()
        driver = {**event, 'agent_type': 'ship:driver--sol'}
        prefix = [*self.account_words[:2], 'account-auto']
        owed = str(ultraship.owed_file(driver))
        words = [*prefix, '--fail-unparsed', owed]
        command = shlex.join(words)
        with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
            self.assertIsNone(ultraship.guarded_pre(
                {'cwd': str(self.cwd), **driver, 'tool_input': {'command': command}}))
        self.assertEqual(output.getvalue(), '')
        for invalid in ([*words[:-1], str(Path(owed).with_name('sibling.tsv'))],
                        [*words, 'extra'], [*prefix, owed, '--fail-unparsed'],
                        ['python3', str(self.cwd / 'ledger.py'), *words[2:]]):
            with self.subTest(command=invalid):
                self.assert_custody_denial({**driver, 'tool_input': {'command': shlex.join(invalid)}})
        self.assert_custody_denial({**driver, 'agent_type': 'ship:writer--sol', 'tool_input': {'command': command}})

    def test_correct_binding_requires_exact_own_command(self):
        event = {'session_id': 's1', 'tool_name': 'Bash'}
        self.enterContext(patch.object(ultraship, 'STATE', self.state / 'ultraship'))
        words = ['python3', str(LEDGER), 'correct-binding', str(self.prepare_owed(event)),
                 '12345678-1234-1234-1234-123456789abc', '12', 'review row']
        command = shlex.join(words)
        self.assert_account_command_allowed(command, session_id=event['session_id'])
        self.consume(words)
        for invalid in (command + ' && echo done', command.replace('s1.tsv', 'other.tsv'),
                        shlex.join([*words[:3], *words[4:]])):
            with self.subTest(command=invalid):
                self.assert_custody_denial({**event, 'tool_input': {'command': invalid}}, ultraship.ACCOUNT_CUSTODY)
        self.assert_custody_denial({**event, 'agent_type': 'ship:writer--sol',
                                   'tool_input': {'command': command}}, ultraship.ACCOUNT_CUSTODY)

    def test_account_auto_line_continuations_require_raw_driver_call(self):
        event = self.own_account_event()
        event['session_id'] = 's1'
        command = shlex.join([*self.account_words[:2], 'account-auto', str(ultraship.owed_file(event))])
        for before, after in (('account-', 'auto'), ('ledger.', 'py')):
            split = command.replace(before + after, before + '\\\n' + after, 1)
            for caller in ('ship:writer--sol', 'ship:driver--sol'):
                with self.subTest(token=before + after, caller=caller):
                    self.assert_custody_denial({**event, 'agent_type': caller, 'tool_input': {'command': split}})

    def test_account_auto_denies_a_copy_of_the_ledger(self):
        copy = self.cwd / 'copied-ledger.py'
        copy.write_bytes(LEDGER.read_bytes())
        self.assert_custody_denial({'agent_type': 'ship:writer--sol', 'tool_name': 'Bash',
                                   'tool_input': {'command': 'python3 ./copied-ledger.py account-auto pending.tsv'}})

    def test_writer_cannot_account_with_current_or_cached_ledger(self):
        relative = '.claude/plugins/cache/ultraship/ship/1.11.7/skills/ship/scripts/ledger.py'
        cached = Path.home() / relative
        cached.parent.mkdir(parents=True)
        cached.touch()
        (self.cwd / 'ledger.py').symlink_to(LEDGER)
        paths = (shlex.quote(str(LEDGER)), './ledger.py', f'"$HOME/{relative}"',
                 f'"${{HOME}}/{relative}"', f'~/{relative}')
        commands = [f'python3 {script} account-auto pending.tsv' for script in paths]
        commands.append('bash -c ' + shlex.quote(commands[2]))
        for command in commands:
            with self.subTest(command=command):
                self.assert_custody_denial({'agent_type': 'ship:writer--sol', 'tool_name': 'Bash',
                                           'tool_input': {'command': command}})

    def assert_account_custody_denial(self, command, caller='ship:driver--sol'):
        self.assert_custody_denial(
            {'agent_type': caller, 'tool_name': 'Bash', 'tool_input': {'command': command}},
            'Use the exact Stop command for your session (account custody rule). Report the blocked scope to the driver.')

    def assert_account_command_allowed(self, command, caller='ship:driver--sol', **event):
        with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
            try:
                ultraship.guarded_pre({'cwd': str(self.cwd), **event, 'agent_type': caller,
                                       'tool_name': 'Bash', 'tool_input': {'command': command}})
            except SystemExit:
                self.fail(output.getvalue())
        self.assertEqual(output.getvalue(), '')

    def test_account_custody_allows_commit_message_heredoc(self):
        self.assert_account_command_allowed(
            'git commit -m "$(cat <<\'EOF\'\nfix: check the account\n\nThe ledger\'s label (reviewed).\nEOF\n)"\n',
            caller='ship:writer--sol')

    def test_account_custody_allows_a_long_quoted_argument(self):
        self.assert_account_command_allowed(f'echo "{"a" * 300}" account')

    def test_account_custody_denies_commit_message_with_session_variable(self):
        self.assert_account_custody_denial("git commit -m 'Explain account-auto and CLAUDE_CODE_SESSION_ID'",
                                           caller='ship:writer--sol')

    def test_account_custody_denies_session_override_without_ledger_name(self):
        (self.cwd / 'helper.py').write_bytes(LEDGER.read_bytes())
        self.assert_account_custody_denial('CLAUDE_CODE_SESSION_ID=s1 echo ./helper.py account-auto ./s1.tsv')

    def test_account_custody_allows_own_stop_command_with_session_variable_in_path(self):
        event = self.own_account_event()
        state = ultraship.STATE / 'CLAUDE_CODE_SESSION_ID'
        with patch.object(ultraship, 'STATE', state):
            command = shlex.join([*self.account_words[:2], 'account-auto', str(self.prepare_owed(event))])
            self.assert_account_command_allowed(command, session_id=event['session_id'])

    def test_account_auto_denies_commands_that_name_the_session_variable(self):
        for command in (
            'CLAUDE_CODE_SESSION_ID=s1 echo account-auto ./ledger',
            'export CLAUDE_CODE_SESSION_ID=s1; echo account-auto ./ledger',
            'env CLAUDE_CODE_SESSION_ID=s1 echo account-auto ./ledger',
            'env -u CLAUDE_CODE_SESSION_ID echo account-auto ./ledger',
            'unset CLAUDE_CODE_SESSION_ID; echo account-auto ./missing/ledger',
            'echo account-auto claude_code_session_id ./ledger',
        ):
            with self.subTest(command=command):
                self.assert_account_custody_denial(command)

    def assert_ledger_expansion_denied(self, command):
        for caller in ('ship:driver--sol', 'ship:writer--sol'):
            with self.subTest(caller=caller):
                self.assert_account_custody_denial(command, caller)

    def test_ledger_custody_blocks_variable_expansion(self):
        self.assert_ledger_expansion_denied(f'word=account; echo {shlex.quote(str(LEDGER))} "$word-sample"')

    def test_ledger_custody_blocks_ansi_c_quoting(self):
        self.assert_ledger_expansion_denied(f"echo {shlex.quote(str(LEDGER))} $'account\\x2dsample'")

    def test_ledger_custody_blocks_command_substitution(self):
        self.assert_ledger_expansion_denied(f'echo {shlex.quote(str(LEDGER))} "$(printf account)"')

    def test_account_custody_resolves_installed_ledger_paths(self):
        os.environ.pop('CLAUDE_CONFIG_DIR', None)
        cached = Path.home() / '.claude/plugins/cache/ultraship/ship/1.11.7/skills/ship/scripts/ledger.py'
        cached.parent.mkdir(parents=True)
        cached.touch()
        command = f'word=account; echo {shlex.quote(str(cached))} "$word-sample"'
        for fixture in (command, 'bash -c ' + shlex.quote(command)):
            with self.subTest(fixture=fixture):
                self.assert_account_custody_denial(fixture)
        (self.cwd / 'helper').symlink_to(cached)
        self.assert_account_custody_denial('echo ./helper account-auto')

    def test_account_custody_recognizes_a_symlinked_installation(self):
        os.environ.pop('CLAUDE_CONFIG_DIR', None)
        cached = Path.home() / '.claude/plugins/cache/ultraship/ship/1.11.7/skills/ship/scripts/ledger.py'
        cached.parent.mkdir(parents=True)
        target = self.cwd / 'placeholder.py'
        target.touch()
        cached.symlink_to(target)
        self.assert_account_custody_denial(f'echo {shlex.quote(str(cached))} accounting')

    def test_account_custody_recognizes_a_symlinked_installation_with_parent_segment(self):
        os.environ.pop('CLAUDE_CONFIG_DIR', None)
        cached = Path.home() / '.claude/plugins/cache/ultraship/ship/1.11.7/skills/ship/scripts/ledger.py'
        cached.parent.mkdir(parents=True)
        target = self.cwd / 'placeholder.py'
        target.touch()
        cached.symlink_to(target)
        path = cached.parent / '..' / 'scripts' / cached.name
        self.assert_account_custody_denial(f'echo {shlex.quote(str(path))} account')

    def test_account_custody_denies_accounting_after_redirection(self):
        os.environ.pop('CLAUDE_CONFIG_DIR', None)
        cached = Path.home() / '.claude/plugins/cache/ultraship/ship/1.11.7/skills/ship/scripts/ledger.py'
        cached.parent.mkdir(parents=True)
        cached.touch()
        (self.cwd / 'helper').symlink_to(cached)
        self.assert_account_custody_denial('echo ./helper 2>/dev/null account-auto ./other.tsv')

    def test_account_custody_checks_substitution_after_ledger_reference(self):
        self.assert_account_custody_denial(f'echo {shlex.quote(str(LEDGER))} `printf accounting`')

    def test_account_custody_checks_opening_parenthesis_after_ledger_reference(self):
        self.assert_account_custody_denial(f'echo account {shlex.quote(str(LEDGER))} <(printf sample)')

    def test_account_custody_stops_at_command_separator(self):
        self.assert_account_command_allowed(f'echo {shlex.quote(str(LEDGER))}; echo account')

    def test_account_custody_denies_parse_error_with_ledger(self):
        self.assert_account_custody_denial("echo ledger 'account")

    def test_account_auto_denies_ledger_path_resolution_error(self):
        (self.cwd / 'loop').symlink_to('loop')
        self.assert_account_custody_denial('echo ./loop account')

    def test_ledger_append_allows_account_in_a_literal_note(self):
        command = (f'python3 {shlex.quote(str(LEDGER))} append slices driver {"a" * 40}'
                   " pass 'Review of the account completed'")
        self.assert_account_command_allowed(command)

    def test_ledger_run_start_allows_account_in_board_path(self):
        command = f'python3 {shlex.quote(str(LEDGER))} run-start light lane ./account-board.md'
        self.assert_account_command_allowed(command)

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

    def test_own_account_call_admits_patch_accounting_with_an_absolute_patch(self):
        event = self.own_account_event()
        words = ['python3', str(LEDGER), 'account-patch', self.account_words[3], self.account_words[4],
                 str(self.cwd / 'frozen.patch')]
        self.assert_account_command_allowed(shlex.join(words), session_id=event['session_id'])
        self.consume(words)
        linked = self.cwd / 'linked'
        linked.symlink_to(self.cwd)
        loop = self.cwd / 'loop.patch'
        loop.symlink_to(loop)
        for index, value in ((4, 'invalid'), (5, 'frozen.patch'), (5, str(self.cwd / '../frozen.patch')),
                             (5, str(self.cwd) + '//frozen.patch'), (5, '/' + str(self.cwd / 'frozen.patch')),
                             (5, str(linked / 'frozen.patch')), (5, str(loop)), (5, '')):
            invalid = words.copy()
            invalid[index] = value
            with self.subTest(index=index, value=value):
                self.assert_custody_denial({**event, 'tool_input': {'command': shlex.join(invalid)}})
        for invalid in (words[:-1], [*words, 'extra']):
            with self.subTest(words=invalid):
                self.assert_custody_denial({**event, 'tool_input': {'command': shlex.join(invalid)}})

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
                    "grep -rn 'text_lint hook' sub",
                    "grep -rn 'a && b text_lint hook' .",
                    "grep -rln 'text_lint hook' ~/.claude/plugins/cache 2>/dev/null | head -20")
        for caller in ('', 'ship:driver', 'ship:writer--sol'):
            for command in commands:
                with self.subTest(caller=caller, command=command):
                    output = io.StringIO()
                    with redirect_stdout(output), redirect_stderr(io.StringIO()):
                        self.assertIsNone(ultraship.guarded_pre(
                            {'cwd': str(self.cwd), 'agent_type': caller, 'tool_name': 'Bash',
                             'tool_input': {'command': command}}))
                    self.assertEqual(output.getvalue(), '')

    def test_lane_commands_with_custody_words_and_literal_variables_are_allowed(self):
        receipts = '.scratch/coc/receipts'
        # A binding resolves only to an absolute path; `$PWD` gives one.
        bound = '$PWD/.scratch/coc/receipts'
        commands = (
            f"grep -rln {shlex.quote(ultraship.RECEIPT_CUSTODY)} ~/.claude/plugins/cache 2>/dev/null | head -20",
            f'L={bound}/teams-scoped-tests.sh; bash -n "$L" && sha256sum "$L"',
            'UV="$PWD/.scratch/uv-0.12.7/bin/uv"; python3 -m pip install --target .scratch/uv-0.12.7'
            ' .scratch/wheels/uv-0.12.7-py3-none-manylinux_2_17_x86_64.whl && "$UV" --version',
            f'LAUNCH={bound}/credit-replay.sh\nbash -n "$LAUNCH" && bash "$LAUNCH" 2>&1 | tail -20',
            f'H="{bound}/format_recovery.py"\npython3 "$H" {receipts}/recovery.json',
            f'tail -20 {receipts}/ledger.py-account-auto.txt',
        )
        for caller in ('', 'ship:driver--sol'):
            for command in commands:
                with self.subTest(caller=caller, command=command):
                    self.assert_account_command_allowed(command, caller=caller)

    def test_literal_variables_keep_store_ledger_and_hook_refusals(self):
        (self.cwd / 'hook-alias').symlink_to(HOOK)
        (self.cwd / 'ledger.py').symlink_to(LEDGER)
        store = shlex.quote(str(self.store))
        grants = shlex.quote(str(self.ledger.grant_store().parent.parent.parent))
        for command in (f'S={store}; cat "$S"/key', f'S={store}; echo forged > "$S/key"',
                        'L="$PWD/ledger.py"; python3 "$L" account-auto pending.tsv',
                        'H=./hook-alias; python3 "$H" pre', 'H="$PWD/hook-alias"; python3 "$H" pre',
                        'H="$PWD/hook-alias"; "$H" pre', 'H=./hook-alias; env -C . python3 "$H" pre',
                        'A=./hook-; B=alias; python3 "$A$B" pre',
                        f'D={grants}; rm -rf "$D"', 'D=~/.local; rm -rf "$D"'):
            with self.subTest(command=command):
                self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': command}})
        self.assert_account_custody_denial('L="$PWD/ledger.py"; python3 "$L" account pending.tsv x')

    def test_only_a_binding_that_always_runs_first_resolves_a_variable(self):
        for command in ('true && H=./x.py; python3 "$H"', 'true ||\nH=./x.py; python3 "$H"', 'python3 "$H"; H=./x.py',
                        'H=./x.py python3 "$H"', 'H=./a.py; H=./b.py; python3 "$H"', 'H=./x.py & python3 "$H"',
                        'H=./x.py | python3 "$H"', 'H=$(echo ./x.py); python3 "$H"', 'H=./x*.py; python3 "$H"',
                        'IFS=/; python3 "$IFS"', 'if true; then H=./x.py; fi; python3 "$H"',
                        'export H=./x.py; python3 "$H"', "cat <<'EOF'\nH=./x.py\nEOF\npython3 \"$H\"",
                        'H=./x.py; python3 "${H:-y}"', 'H=./x.py; python3 $H', 'H=./x.py; python3 "$H[1,-2]"',
                        'H=./x.py; python3 "$H:h"', 'H=./x.py; cd sub; python3 "$H"',
                        "H=./x.py; c'd' sub; python3 \"$H\"", 'HOME=/tmp; H=~/x.py; python3 "$H"',
                        'H="${PWD}-x/a.py"; python3 "$H"', '. ./env.sh; H=./x.py; python3 "$H"',
                        'source ./env.sh; H=./x.py; python3 "$H"',
                        'PWD=/tmp; H="$PWD/a.py"; python3 "$H"', 'H=alias; "$H" x',
                        'chdir /tmp; H="$PWD/a.py"; python3 "$H"', 'H=/a.py; python3 "$$H"',
                        'a=F; FO=/ok.py; declare "${a}O=/x.py"; python3 "$FO"', 'repeat 0 { H=/a.py; }; python3 "$H"',
                        'H=/a.py; python3 "${${H}:t}"', 'H=/a.py\x0b; python3 "$H"', 'H=/a.py; bash -c "cat $H"',
                        'RANDOM=/a.py; python3 "$RANDOM"', 'H=/a.py # note\npython3 "$H"',
                        'for f in ./a.sh; do bash "$f"; done', 'bash -n "$f"'):
            with self.subTest(command=command):
                self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': command}})

    def batch_script(self):
        """Make the regular `.py` file that a batch binds to a variable."""
        helper = self.cwd / 'skills/babysit/scripts/thread_reply.py'
        helper.parent.mkdir(parents=True)
        helper.write_text('print(1)\n')
        return shlex.quote(str(helper))

    def test_thread_reply_batches_are_allowed_for_main_and_subagent_callers(self):
        helper = self.batch_script()
        pull = 'https://github.com/acme/widgets/pull/2891'
        commands = (
            f'python3 {helper} resolve {pull} PRRT_kwDOabc123 && python3 {helper} resolve {pull} PRRT_kwDOabc456',
            f'python3 {helper} reply {pull} PRRT_kwDOabc123 .scratch/r1.md\npython3 {helper} resolve {pull} PRRT_kwDOabc123\n',
            f'for t in PRRT_kwDOabc123 PRRT_kwDOabc456; do python3 {helper} resolve {pull} "$t"; done',
            # The script path sits in a variable, inside a loop or beside another variable.
            f'TR={helper}; for t in PRRT_kwDOabc123 PRRT_kwDOabc456; do python3 "$TR" resolve {pull} "$t"; done',
            f'TR={helper}\nPR={pull}\npython3 "$TR" reply "$PR" PRRT_kwDOabc123 .scratch/r1.md'
            ' && python3 "$TR" resolve "$PR" PRRT_kwDOabc123\npython3 "$TR" resolve "$PR" PRRT_kwDOabc456\n',
            f'TR={helper}\nPR={pull}\nfor t in PRRT_kwDOabc123 PRRT_kwDOabc456; do\n'
            '  python3 "${TR}" resolve "$PR" "${t}" 2>&1 | tail -2\ndone\n',
        )
        for caller in ('', 'general-purpose', 'ship:driver'):
            for command in commands:
                with self.subTest(caller=caller, command=command):
                    self.assert_account_command_allowed(command, caller=caller)

    def test_a_variable_script_in_a_batch_keeps_hook_store_and_rebinding_refusals(self):
        (self.cwd / 'hook-alias').symlink_to(HOOK)
        helper = self.batch_script()
        folder = shlex.quote(str(self.cwd))
        installed = shlex.quote(str(HOOK))
        store = shlex.quote(str(self.store / 'key'))
        # Python runs `__main__.py` of a folder and any file whatever its name; a copy keeps the name of its source.
        (self.cwd / 'package').mkdir()
        for name in ('package/__main__.py', 'tool', 'ledger.py', 'text_lint.py', 'TEXT_LINT.py'):
            (self.cwd / name).write_text('print(1)\n')
        (self.cwd / 'link.py').symlink_to(self.cwd / 'tool')
        script_refusals = [f'TR={folder}/{name}; for t in a; do python3 "$TR" "$t"; done'
                           for name in ('package', 'tool', 'missing.py', 'ledger.py', 'text_lint.py', 'TEXT_LINT.py',
                                        'link.py')]
        # A loop sets its name with no assignment word, so only a lower-case name that no shell reads is a loop name.
        loop_refusals = [f'TR={helper}; for {name} in /opt/example/venv/bin; do python3 "$TR"; done'
                         for name in ('PATH', 'IFS', 'ENV', 'BASH_ENV', 'HOME', 'PYTHONPATH', 'PYTHONSTARTUP',
                                      'LD_PRELOAD', 'Item', 'path', 'fpath')]
        for command in (*script_refusals, *loop_refusals,
                        # The interpreter is the word `python3`, and the script is one whole quoted variable.
                        f'TR={helper}; for t in a; do python "$TR" "$t"; done',
                        f'TR={helper}; for t in a; do /usr/bin/python3 "$TR" "$t"; done',
                        f'P={folder}/skills/babysit/scripts; F=/thread_reply.py; for t in a; do python "$P$F" "$t"; done',
                        f'P={folder}/skills/babysit/scripts; F=/thread_reply.py; for t in a; do python3 "$P$F" "$t"; done',
                        f'P={folder}/skills/babysit; for t in a; do python3 "$P/scripts/thread_reply.py" "$t"; done',
                        f'TR={helper}; for t in a; do python3 prefix"$TR" "$t"; done',
                        f'TR={helper}; for t in a; do python3 "$TR""$t"; done',
                        f'TR={installed}; for t in a; do python3 "$TR" pre; done',
                        'TR="$PWD/hook-alias"; for t in a; do python3 "$TR" pre; done',
                        f'TR={helper}; for t in a b; do python3 "$TR" "$t"; TR=./hook-alias; done',
                        f'TR={helper}; for TR in ./hook-alias; do python3 "$TR" pre; done',
                        f'TR={helper}; for t in a; do TR=./hook-alias python3 "$TR" pre; done',
                        'for t in ./hook-alias; do python3 "$t" pre; done',
                        f'TR={helper}; x=TR; for t in a; do declare "$x=./hook-alias"; python3 "$TR" pre; done',
                        f'TR={helper}; x=TR; printf -v "$x" %s ./hook-alias; python3 "$TR" pre "$x"',
                        f'TR={helper}; x=TR; : $(( $x = 1 )); python3 "$TR" pre "$x"',
                        f'TR={helper}; for t in a; do read TR < names; python3 "$TR" pre; done',
                        f'TR={helper}; for t in a; do . ./env.sh; python3 "$TR" "$t"; done',
                        f'TR={helper}; eval "$x"; python3 "$TR" pre "$y"',
                        f'TR={helper}; for t in a; do python3 "$TR[1,-2]" "$t"; done',
                        f'TR={helper}; for t in a; do python3 "$TR:h" "$t"; done',
                        f'TR={helper}; for t in a; do python3 "${{TR%/*}}/x.py" "$t"; done',
                        f'TR={helper}; for t in a; do python3 $TR "$t"; done',
                        # An empty expansion before the script would make Python run the next word.
                        f'TR={helper}; python3 -W $E "$TR" ./hook-alias pre',
                        f'TR={helper}; for t in a; do python3 -X $E "$TR" ./hook-alias "$t"; done',
                        f'TR={helper}; python3 -W"$E" "$TR" ./hook-alias pre',
                        f'TR={helper}; python3 -W "$E" "$TR" ./hook-alias pre',
                        # A background list keeps its binding in another shell.
                        f'TR={helper} && true & for t in a; do python3 "$TR" "$t"; done',
                        # A prefix assignment, or one to a name the shell reads, can change the program that starts.
                        f'TR={helper}; for t in a; do PATH=/opt/other python3 "$TR" "$t"; done',
                        f'TR={helper}; PATH=/opt/other; for t in a; do python3 "$TR" "$t"; done',
                        f'TR={helper}; for t in a; do X=1 python3 "$TR" "$t"; done',
                        f'TR={helper}; python3 "$TRé" x "$y"',
                        f'TR={helper}; if true; then TR=./hook-alias; fi; python3 "$TR" pre "$t"',
                        f'TR={helper}; while read t; do python3 "$TR" "$t"; done < names',
                        f'false && TR={helper}; for t in a; do python3 "$TR" "$t"; done',
                        f'TR={helper}; P=python3; for t in a; do "$P" "$TR" "$t"; done',
                        f'TR={helper}; for t in a; do python3 "$TR" "$t"; done; python3 "$OTHER" pre',
                        'D=/opt/ship/hooks; S=ultra; python3 "$D/${S}ship.py" pre "$t"',
                        'D=/opt/ship; for t in ultraship; do python3 "$D/hooks/$t.py" pre; done',
                        f'S={store}; for t in a; do python3 "$S" "$t"; done',
                        'S=/opt/x.sh; for t in a; do bash "$S" "$t"; done'):
            with self.subTest(command=command):
                self.assert_custody_denial({'agent_type': 'general-purpose', 'tool_name': 'Bash',
                                            'tool_input': {'command': command}})
        self.assert_account_custody_denial(
            f'L={shlex.quote(str(LEDGER))}; for t in a; do python3 "$L" account "$t"; done')

    def test_text_lint_and_ledger_words_reach_a_program_only_through_readers(self):
        for command in ("grep 'text_lint hook' notes.md | sh", "grep 'text_lint hook' notes.md | xargs python3",
                        "rg --pre=python3 'text_lint hook' .", "rg {--pre=python3,x} 'text_lint hook' .",
                        "grep 'text_lint hook' *", 'grep -rn "text_lint hook $(date)" .',
                        "printf -v 'a[1]' 'text_lint hook'", "grep 'text_lint hook' x >'./out'/dev/null",
                        "cat ledger.py-account-auto.txt | python3 -", "echo 'import text_lint' | python3 -",
                        "LD_PRELOAD=./x.so grep 'text_lint hook' .", "grep 'text_lint hook' . || python3 -",
                        "grep -R 'text_lint hook' .", "grep -rR 'text_lint hook' .",
                        "grep x notes.md # note \\\npython3 text_lint.py hook", "grep 'x' notes.md #text_lint hook"):
            with self.subTest(command=command):
                self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': command}})

    def test_scratch_append_with_custody_message(self):
        self.assert_account_command_allowed(
            f"echo {shlex.quote(ultraship.RECEIPT_CUSTODY)} >> .scratch/coc/state-owed.md", caller='')

    def test_recursive_cache_search_keeps_its_refusal(self):
        (Path.home() / '.claude/plugins/cache/ultraship/ship/1.15.20/hooks').mkdir(parents=True)
        self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {
            'command': f'grep -rl "{ultraship.RECEIPT_CUSTODY}" ~/.claude/plugins/cache/*/*/*/'}})

    def test_cache_listing_refuses_a_protected_alias(self):
        cache = Path.home() / '.claude/plugins/cache/ultraship/ship'
        cache.mkdir(parents=True)
        self.store.mkdir(parents=True)
        (cache / '1.15.20').symlink_to(self.store, target_is_directory=True)
        self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {
            'command': 'ls -d ~/.claude/plugins/cache/ultraship/ship/*'}})

    def test_printf_with_custody_message(self):
        self.assert_account_command_allowed(
            f"printf '%s\\n' {shlex.quote(ultraship.RECEIPT_CUSTODY)}", caller='')

    def test_list_ship_cache_versions(self):
        installed = Path.home() / '.claude/plugins/cache/ultraship/ship/1.15.20/hooks/ultraship.py'
        installed.parent.mkdir(parents=True)
        with patch.object(ultraship, '__file__', str(installed)):
            self.assert_account_command_allowed('ls -d ~/.claude/plugins/cache/ultraship/ship/*', caller='')

    def test_reader_in_a_folder_that_holds_a_store_keeps_its_refusal(self):
        self.store.mkdir(parents=True)
        for command in ("grep -rn 'text_lint hook' | head", "grep -rn 'text_lint hook' ."):
            with self.subTest(command=command):
                self.assert_custody_denial({'cwd': str(self.store.parent.parent), 'tool_name': 'Bash',
                                            'tool_input': {'command': command}})

    def test_a_binding_under_a_working_directory_with_spaces_resolves(self):
        spaced = self.cwd / 'with spaces'
        spaced.mkdir()
        (spaced / 'hook-alias').symlink_to(HOOK)
        command = 'L="$PWD/.scratch/coc/receipts/teams-scoped-tests.sh"; bash -n "$L" && sha256sum "$L"'
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertIsNone(ultraship.guarded_pre({'cwd': str(spaced), 'agent_type': '', 'tool_name': 'Bash',
                                                     'tool_input': {'command': command}}))
        self.assertEqual(output.getvalue(), '')
        self.assert_custody_denial({'cwd': str(spaced), 'tool_name': 'Bash',
                                    'tool_input': {'command': 'H="$PWD/hook-alias"; python3 "$H" pre'}})

    def test_print_state_root(self):
        self.assert_account_command_allowed("printf '%s\\n' \"${XDG_STATE_HOME:-$HOME/.local/state}\"", caller='')

    def test_custody_message_cannot_be_written_to_receipt(self):
        target = self.store / 'receipts' / ('a' * 32 + '.json')
        self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {
            'command': f"printf '%s\\n' {shlex.quote(ultraship.RECEIPT_CUSTODY)} > {shlex.quote(str(target))}"}})

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

    def test_state_folder_triggers_name_their_own_rule(self):
        folder = '~/.local/state/ultraship/row-reanchor'
        record = ('{\n  "pr": "https://github.com/acme/widgets/pull/7",\n  "agent_id": "a1b2c3",\n'
                  '  "row_id": "row-17",\n  "expires_at": "2026-01-01T00:00:00Z"\n}\n')
        absolute = str(Path.home() / '.local/state/ultraship/row-reanchor/a1b2c3.json')
        commands = (f'ls -t {folder}/*.json | head -5', 'ls -la "$HOME/.local/state/ultraship/row-reanchor/"',
                    'ls "${XDG_STATE_HOME:-$HOME/.local/state}/ultraship/row-reanchor"',
                    f"""python3 -c 'import json; print(json.load(open("{absolute}"))["pr"])'""",
                    f"grep -l '\"pr\"' {folder}/*.json",
                    f"cat > {folder}/a1b2c3.json <<'EOF'\n{record}EOF\n",
                    f'mkdir -p {folder} && cd {folder} && ls',
                    f'grep -n text {folder}/a1b2c3.json',
                    'wc -l ~/.local/state/ultraship/owed/*.tsv',
                    'ls -la ~/.local/state/ultraship/owed/ && wc -l ~/.local/state/ultraship/owed/*')
        for caller in ('', 'ship:driver', 'general-purpose'):
            for command in commands:
                with self.subTest(caller=caller, command=command):
                    self.assert_custody_denial({'agent_type': caller, 'tool_name': 'Bash',
                                                'tool_input': {'command': command}}, ultraship.STATE_FOLDER_CUSTODY)
        reason = ultraship.STATE_FOLDER_CUSTODY
        for part in ('`$`', '`{`', '`}`', '`*`', '`?`', '`[`', '`]`', 'backtick', '`cd`', '`pushd`', '`text`',
                     'Read and Write tools', 'literal path'):
            with self.subTest(part=part):
                self.assertIn(part, reason)

    def test_state_folder_literal_paths_follow_the_caller_rule(self):
        folder = '~/.local/state/ultraship/row-reanchor'
        literal = (f'ls -la {folder}/', f'cat {folder}/a1b2c3.json', f'chmod 600 {folder}/a1b2c3.json',
                   f'grep -n expires_at {folder}/a1b2c3.json', f'grep -n context {folder}/a1b2c3.json',
                   f'rm {folder}/a1b2c3.json')
        for caller in ('', 'ship:driver'):
            for command in literal:
                with self.subTest(caller=caller, command=command):
                    self.assert_account_command_allowed(command, caller=caller)
        # A helper agent stays under the admission record rule, which names its own folder.
        for command in literal:
            with self.subTest(caller='general-purpose', command=command):
                self.assert_custody_denial(
                    {'agent_type': 'general-purpose', 'tool_name': 'Bash', 'tool_input': {'command': command}},
                    'Only the driver and the main session touch row-reanchor admission records (custody rule). '
                    'Report the blocked scope to the driver.')
        for caller in ('', 'general-purpose'):
            for command in ('ls ~/.local/state/ultraship/owed/', 'wc -l ~/.local/state/ultraship/owed/session-1.tsv'):
                with self.subTest(caller=caller, command=command):
                    self.assert_account_command_allowed(command, caller=caller)

    def test_state_folder_triggers_keep_the_receipt_text_for_store_commands(self):
        owed = '~/.local/state/ultraship/owed'
        for caller in ('', 'ship:driver', 'general-purpose'):
            for command in ('cat ~/.local/state/ultraship/text-lint/key',
                            'cat ~/.local/state/ultraship/account-grants/*',
                            'cat ${XDG_STATE_HOME:-~/.local/state}/ultraship/*',
                            'ls $HOME/.local/state/ultraship/', 'cat ~/.local/state/ultraship/*/key',
                            'cd ~/.local/state/ultraship && cat text-lint/key',
                            f'cat {owed}/../account-grants/x', f'S={owed}; cat $S/../account-grants/x',
                            f'ln -s ../text-lint {owed}/link', f'ln -s ../account-grants/x {owed}/x.tsv; cat {owed}/*',
                            "grep -rn 'text_lint.py hook' '${XDG_STATE_HOME}/row-review'"):
                with self.subTest(caller=caller, command=command):
                    self.assert_custody_denial({'agent_type': caller, 'tool_name': 'Bash',
                                                'tool_input': {'command': command}})
        # A trigger still refuses a path to a store that the command builds from pieces.
        for command in (f'D=te; cat {owed}/../${{D}}xt-lint/key', f'S=$(echo {owed}); cat $S/../acc*/x'):
            with self.subTest(command=command):
                self.assert_custody_denial({'tool_name': 'Bash', 'tool_input': {'command': command}},
                                           ultraship.STATE_FOLDER_CUSTODY)

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
                        patch.object(ultraship, 'pre_output', side_effect=RuntimeError('pre failed')):
                    with redirect_stdout(output), redirect_stderr(errors), self.assertRaises(SystemExit) as exit:
                        ultraship.guarded_pre({'cwd': str(self.cwd), 'agent_type': caller,
                                              'tool_name': tool, 'tool_input': tool_input})
                    self.assertEqual(exit.exception.code, 0)
                    result = json.loads(output.getvalue())['hookSpecificOutput']
                    self.assertEqual(result['permissionDecision'], 'deny')
                    self.assertEqual(result['permissionDecisionReason'].split('\n', 1)[0],
                                     'The ship hook failed, so it denies every tool call. Its traceback is on stderr. '
                                     'Report the blocked scope to the driver.')
                    self.assertIn('Traceback (most recent call last):', errors.getvalue())
                    self.assertIn('RuntimeError: pre failed', errors.getvalue())

    def test_pre_error_denies_malformed_tool_names(self):
        """Catch malformed tool names escaping denial through an error in the custody fallback."""
        for tool in (None, 1, ['Read'], {'name': 'Read'}):
            with self.subTest(tool=tool), patch.object(ultraship, 'pre_output', side_effect=RuntimeError('pre failed')):
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
                        patch.object(ultraship, 'pre_output', side_effect=RuntimeError('pre failed')), \
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

    def test_missing_record_guides_workspace_admission(self):
        result = hook('pre', self.payload, self.env)
        self.assertTrue(denied(result))
        reason = result['hookSpecificOutput']['permissionDecisionReason']
        self.assertIn(str(self.root / 'state/ultraship/row-review/r1.json'), reason)
        self.assertIn(str(self.record), reason)

        for agent in ('ship:driver', ''):
            with self.subTest(agent=agent):
                self.assertFalse(denied(hook('pre', {**self.payload, 'agent_type': agent,
                                                    'tool_name': 'Write',
                                                    'tool_input': {'file_path': str(self.record)}}, self.env)))

        self.write_record()
        self.assertFalse(denied(hook('pre', self.payload, self.env)))
        self.assertFalse(denied(hook('pre', {**self.payload, 'tool_name': 'Grep',
                                            'tool_input': {'path': str(self.row), 'pattern': 'id'}}, self.env)))

    def test_missing_record_without_workspace_names_scratch_requirement(self):
        with (patch.object(ultraship, 'STATE', self.root / 'state'),
              patch.object(ultraship.Path, 'is_dir', return_value=False)):
            fields, reason = ultraship.row_record({**self.payload, 'cwd': '/'}, 'row-review', workspace_fallback=True)
        self.assertIsNone(fields)
        self.assertIn('needs a `.scratch` folder', reason)

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

    def test_paginated_graphql_read_refuses_connection_under_pull_request_list(self):
        command = ("gh api graphql --paginate -f query='query($endCursor:String)"
                   '{repository(owner:"example-org",name:"example-repo"){pullRequests(first:2){nodes{'
                   'reviewThreads(first:20,after:$endCursor){pageInfo{hasNextPage endCursor}nodes{id}}'
                   "}}}}'")
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
