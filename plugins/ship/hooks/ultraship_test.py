#!/usr/bin/env python3
"""Self-check for hooks/ultraship.py and skills/ship/scripts/ledger.py. Run with a workspace-local TMPDIR."""
import importlib.util
import json
import time
import os
import re
import subprocess
import tempfile
import uuid
import unittest
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

    assert denied(hook('pre', {'tool_name': 'Agent', 'tool_input': {'subagent_type': 'ship:reviewer--sol', 'model': 'opus'}}, env))
    assert not denied(hook('pre', {'tool_name': 'Agent', 'tool_input': {'subagent_type': 'ship:reviewer--sol'}}, env))
    assert not denied(hook('pre', {'tool_name': 'Agent', 'tool_input': {'subagent_type': 'Explore', 'model': 'haiku'}}, env))

    for agent in ['ship:writer--sol', 'ship:writer--sonnet']:
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
                    'git -C "$W" status', 'git -C "${W}" log --oneline -3', 'git --git-dir "$G" status',
                    'git --work-tree "$W" diff --stat', "printf 'HEAD %s\\n' x; git -C \"$W\" status"]:
            assert not denied(hook('pre', {**writer, 'agent_type': agent, 'tool_input': {'command': cmd}}, env)), (agent, cmd)
    assert not denied(hook('pre', {'agent_type': 'ship:driver', 'tool_name': 'Bash', 'tool_input': {'command': 'git push'}}, env))
    assert denied(hook('pre', {**writer, 'tool_name': 'Write', 'tool_input': {'file_path': '/r/.claude/settings.local.json'}}, env))
    assert denied(hook('pre', {**writer, 'tool_name': 'Edit', 'tool_input': {'file_path': f'{tmp}/.claude/CLAUDE.md'}}, env))
    assert not denied(hook('pre', {**writer, 'tool_name': 'Edit', 'tool_input': {'file_path': '/r/src/app.py'}}, env))

    matcher = json.loads(HOOK.with_name('hooks.json').read_text())['hooks']['PreToolUse'][0]['matcher']
    for action in ['create_input', 'update_input', 'set_input_status']:
        tool = f'mcp__bettercoding__{action}'
        assert re.fullmatch(matcher, tool), tool
        for agent in ['ship:writer--sol', 'ship:writer--sonnet']:
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
    assert set(result) == {'id', 'ledger', 'run', *provenance}
    assert not Path(provenance['agent_transcript_path']).exists()
    hook('subagent-stop', {**session, 'agent_type': 'ship:writer--sol'}, env)
    blocked = hook('stop', session, env)
    assert blocked['decision'] == 'block' and 'reviewer--sol' in blocked['reason']
    assert hook('stop', session, env)['decision'] == 'block'
    assert ledger('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode == 0
    assert hook('stop', session, env) == ''

    metadata_cases = [({}, {}), *[({key: value}, {key: value}) for key, value in provenance.items()]]
    metadata_cases.extend(({'agent_id': value, 'agent_transcript_path': value}, {})
                          for value in (None, '', ' \t\n', 7, False, [], {}))
    for metadata, expected in metadata_cases:
        hook('subagent-stop', {**session, 'agent_type': 'ship:reviewer--sol', **metadata}, env)
        result = json.loads(owed.read_text().split('\t')[3])
        assert {key: result[key] for key in provenance if key in result} == expected, metadata
        assert set(result) == {'id', 'ledger', 'run', *expected}, metadata
        assert result['run'] is not None
        assert hook('stop', session, env)['decision'] == 'block'
        assert ledger('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode == 0
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


class WriterGitHubGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        self.env.update(HOME=str(self.repo), XDG_STATE_HOME=str(self.repo),
                        GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        self.writer = {'agent_type': 'ship:writer--sol', 'tool_name': 'Bash'}

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


class IsolatedPythonFileEditTests(unittest.TestCase):
    setUp = WriterGitHubGuardTests.setUp
    body = ("from pathlib import Path\n"
            "p = Path('tests/test_old.py')\np.unlink()\n"
            "p = Path('tests/test_example.py')\n"
            "s = p.read_text().replace('old', 'new')\n"
            "p.write_text(s + '''\ndef test_git():\n"
            "    from package import __main__\n"
            "    data = {'command': 'git push'}\n"
            "    raise FileNotFoundError(\"git\")\n''')\n")

    def command(self, body, header="cd /repo && python3 -I - <<'PY'", remainder="sed -n '1,5p' tests/test_example.py"):
        return f'{header}\n{body}\nPY\n{remainder}\n'

    def test_isolated_literal_file_edits_are_admitted(self):
        bodies = (self.body,
                  self.body.replace('from pathlib import Path', 'import pathlib').replace('Path(', 'pathlib.Path('),
                  "from pathlib import Path as P\nP('tests/test_example.py').write_text('git push __main__')",
                  "from pathlib import Path\nPath('/repo/tests/test_example.py').unlink()\nprint('git push')",
                  "p = 'tests/test_example.py'\nopen(p, 'w').write('git push __main__')",
                  "from pathlib import Path\np = Path('tests/test_example.py')\nopen(p, 'w').write('git push')",
                  "from pathlib import Path\np = Path('tests/test_example.py')\np.open('w').write('git push')",
                  "text = 'git push'\nopen('tests/test_example.py', 'w').write(text.replace('old', 'new'))",
                  "from pathlib import Path\np = Path('tests/test_example.py')\ntext = p.read_text()\n"
                  "p.write_text(text.replace('old', 'git push').replace('before', 'after'))")
        for body in bodies:
            with self.subTest(body=body):
                self.assertFalse(denied(hook('pre', {**self.writer, 'tool_input': {
                    'command': self.command(body)}}, self.env)))

    def test_isolation_and_quoted_delimiter_are_required_for_file_edits(self):
        for header in ("cd /repo && python3 - <<'PY'", 'cd /repo && python3 -I - <<PY'):
            with self.subTest(header=header):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {
                    'command': self.command(self.body, header=header)}}, self.env)))

    def test_isolated_unsafe_targets_keep_the_push_scan(self):
        for target in ('x.pth', 'x.so', 'x.pyc', 'x.pyd', 'x.pyo', 'x.pyw', 'x.pyi',
                       'site-packages/x.py', 'dist-packages/x.py', '.git/config', '.venv/x.py',
                       'tests/../x.py', '/outside/x.py', '/repo-other/x.py',
                       'sitecustomize.py', 'pkg/usercustomize/__init__.py'):
            for operation in (f'Path({target!r}).write_text("git push")',
                              f'Path({target!r}).unlink()\nprint("git push")',
                              f'open({target!r}, "w").write("git push")'):
                with self.subTest(target=target, operation=operation):
                    body = 'from pathlib import Path\n' + operation
                    self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {
                        'command': self.command(body)}}, self.env)))

    def test_isolated_moves_and_nonliteral_paths_keep_the_push_scan(self):
        operations = (
            "Path('source.py').parent.replace('destination.py')",
            "(Path('folder') / 'source.py').replace('destination.py')",
            "Path('source.py').with_suffix('.txt').replace('destination.py')",
            "paths[0].replace('destination.py')",
            "p = Path('source.py')\np = 'text'\np.replace('old', 'new')",
            "Path('folder/' + name).write_text('text')",
            "(Path('folder') / name).write_text('text')",
            "Path(f'{name}.py').write_text('text')",
        ) + tuple(f"Path('source.py').{method}('destination.py')" for method in (
            'rename', 'symlink_to', 'hardlink_to', 'link_to', 'touch', 'mkdir', 'chmod', 'write_bytes'))
        for operation in operations:
            with self.subTest(operation=operation):
                body = 'from pathlib import Path\n' + operation + "\nprint('git push')"
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {
                    'command': self.command(body)}}, self.env)))

    def test_isolated_unsafe_working_directories_keep_the_push_scan(self):
        for cwd in ('/repo/.git', '/repo/.venv', '/repo/site-packages', '/repo/dist-packages',
                    '/repo/../outside', '/repo/sitecustomize', '/repo/usercustomize.py', '/repo/x.pth'):
            for target in ('x.py', cwd + '/x.py'):
                with self.subTest(cwd=cwd, target=target):
                    body = f"from pathlib import Path\nPath({target!r}).write_text('git push')"
                    self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {
                        'command': self.command(body, header=f"cd {cwd} && python3 -I - <<'PY'")}}, self.env)))

    def test_isolated_case_variant_targets_keep_the_push_scan(self):
        for target in ('.GIT/config', '.VENV/x.py', 'Site-Packages/x.py', 'Dist-Packages/x.py',
                       'SiteCustomize.py', 'pkg/UserCustomize/__init__.py', 'X.PTH', 'X.SO', 'X.PYC'):
            for operation in (f'Path({target!r}).write_text("git push")',
                              f'Path({target!r}).unlink()\nprint("git push")',
                              f'open({target!r}, "w").write("git push")'):
                with self.subTest(target=target, operation=operation):
                    body = 'from pathlib import Path\n' + operation
                    self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {
                        'command': self.command(body)}}, self.env)))
            with self.subTest(cwd=target):
                body = "from pathlib import Path\nPath('x.py').write_text('git push')"
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {
                    'command': self.command(body, header=f"cd /repo/{target} && python3 -I - <<'PY'")}}, self.env)))

    def test_subprocess_import_cannot_qualify_as_inert_file_text(self):
        self.assertFalse(ultraship.inert_python("import subprocess\nprint('file text')", isolated=True))

    def test_isolated_dynamic_targets_and_execution_keep_the_push_scan(self):
        bodies = (
            "from pathlib import Path\nPath(name_from_input).write_text('git push')",
            "from pathlib import Path\np = Path('x.py')\np = Path(name_from_input)\np.write_text('git push')",
            "from pathlib import Path\np = Path('x.py')\nif True:\n    p = Path(name_from_input)\np.unlink()\nprint('git push')",
            "from pathlib import Path\nfor p in paths:\n    p.write_text('git push')",
            "from pathlib import Path\np = Path('x.py')\np += other\np.write_text('git push')",
            "from pathlib import Path\np = Path('x.py')\nf = p.write_text\nf('git push')",
            "from pathlib import Path\nPath('x.py').replace('.git/config')\nprint('git push')",
            "from pathlib import Path\nPath = factory\nPath('x.py').write_text('git push')",
            "open(name_from_input, 'w').write('git push')",
            "p = 'x.py'\np = name_from_input\nopen(p, 'w').write('git push')",
            "import subprocess\nsubprocess.run(['git', 'push'])",
            "from pathlib import Path\n__target = Path('x.py')\n__target.write_text('git push')",
        )
        for body in bodies:
            with self.subTest(body=body):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {
                    'command': self.command(body)}}, self.env)))

    def test_isolated_file_edits_require_a_read_only_remainder(self):
        for remainder in ('; git push', 'python3 tests/test_example.py', "sed -i '1d' tests/test_example.py"):
            with self.subTest(remainder=remainder):
                self.assertTrue(denied(hook('pre', {**self.writer, 'tool_input': {
                    'command': self.command(self.body + "\nprint('git push')", remainder=remainder)}}, self.env)))


if __name__ == '__main__':
    unittest.main()
