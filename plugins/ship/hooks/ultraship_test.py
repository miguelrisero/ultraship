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
    ledger = lambda *a: run(['python3', str(LEDGER), *a], cwd=repo)

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


class WriterPushEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        self.env = {**os.environ, 'HOME': str(self.repo), 'XDG_STATE_HOME': str(self.repo),
                    'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}
        self.writer = {'agent_type': 'ship:writer--sol', 'tool_name': 'Bash'}

    def rewritten(self, command):
        original = {'command': command, 'description': 'Check writer permissions',
                    'timeout': 120000, 'run_in_background': False}
        result = hook('pre', {**self.writer, 'tool_input': original}, self.env)
        self.assertIsInstance(result, dict, 'writer Bash must return a push-refusing updatedInput')
        output = result['hookSpecificOutput']
        self.assertEqual(output['hookEventName'], 'PreToolUse')
        self.assertNotIn('permissionDecision', output, 'the rewrite must retain normal permission evaluation')
        updated = output['updatedInput']
        self.assertEqual({key: value for key, value in updated.items() if key != 'command'},
                         {key: value for key, value in original.items() if key != 'command'})
        self.assertNotEqual(updated['command'], command)
        return updated['command']

    def git(self, *args):
        return run(['git', *args], cwd=self.repo, env=self.env, check=True).stdout.strip()

    def test_writer_script_git_push_destination_is_refused_by_inherited_env(self):
        self.git('init', '-q')
        remotes = ('https://github.com/example/project.git', 'ssh://git@github.com/example/project.git',
                   'git@github.com:example/project.git')
        for index, remote in enumerate(remotes):
            self.git('remote', 'add', f'remote{index}', remote)
        tools = self.repo / 'tools'
        tools.mkdir()
        # Only URL resolution runs. No Git transport or push command executes.
        (tools / 'run.py').write_text(
            'import json, os, subprocess\n'
            'print(json.dumps({"count": os.environ.get("GIT_CONFIG_COUNT"), "urls": [\n'
            '    subprocess.check_output(["git", "remote", "get-url", "--push", name], text=True).strip()\n'
            '    for name in ("remote0", "remote1", "remote2")],\n'
            '    "protocols": subprocess.check_output(["git", "config", "--get-regexp",\n'
            '        r"^protocol\\..*\\.allow$"], text=True)}))\n')
        shell = tools / 'run-task'
        shell.write_text('#!/bin/sh\nexec python3 tools/run.py\n')
        shell.chmod(0o755)
        (tools / 'linked-task').symlink_to(shell)
        for command in ('python3 tools/run.py', 'sh tools/run-task', './tools/linked-task',
                        'PATH="$PWD/tools:$PATH" run-task'):
            with self.subTest(command=command):
                rewritten = self.rewritten(command)
                probe = run(['bash', '-c', rewritten], cwd=self.repo, env=self.env, check=True)
                observed = json.loads(probe.stdout)
                self.assertGreater(int(observed['count']), 0)
                self.assertEqual(len(observed['urls']), len(remotes))
                protocols = dict(line.split(None, 1) for line in observed['protocols'].splitlines())
                for destination in observed['urls']:
                    self.assertRegex(destination, r'^[A-Za-z][A-Za-z0-9+.-]*://[^/]*\.invalid(?:/|$)')
                    scheme = destination.split(':', 1)[0]
                    self.assertEqual(protocols.get(f'protocol.{scheme}.allow'), 'never')

    def test_writer_git_fetch_and_commit_still_work_with_push_refusing_env(self):
        source = self.repo / 'source.git'
        self.git('init', '-q', '--bare', str(source))
        self.git('init', '-q', '-b', 'writer-work')
        self.git('-c', 'user.name=Writer', '-c', 'user.email=writer@example.invalid',
                 'commit', '-q', '--allow-empty', '-m', 'initial')
        initial = self.git('rev-parse', 'HEAD')
        self.git('--git-dir', str(source), 'fetch', str(self.repo), 'HEAD:refs/heads/source')
        self.git('remote', 'add', 'origin', str(source))
        command = ('git fetch origin && git -c user.name=Writer -c user.email=writer@example.invalid '
                   'commit -q --allow-empty -m checkpoint')
        rewritten = self.rewritten(command)
        run(['bash', '-c', rewritten], cwd=self.repo, env=self.env, check=True)
        self.assertNotEqual(self.git('rev-parse', 'HEAD'), initial)
        self.assertEqual(self.git('log', '-1', '--format=%s'), 'checkpoint')
        self.assertEqual(self.git('rev-parse', 'refs/remotes/origin/source'), initial)
        self.assertEqual(self.git('remote', 'get-url', 'origin'), str(source))

    def test_writer_gh_reads_keep_authentication_with_push_refusing_env(self):
        tokens = {name: 'test-read-credential' for name in
                  ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN')}
        self.env.update(tokens)
        binary = self.repo / 'bin'
        binary.mkdir()
        gh = binary / 'gh'
        # This stand-in observes argv and credential inheritance without contacting GitHub.
        gh.write_text(f'#!{os.sys.executable}\nimport json, os, sys\n'
                      'print(json.dumps({"args": sys.argv[1:], "tokens": '
                      '{k: os.environ.get(k) for k in ' + repr(tuple(tokens)) + '}}))\n')
        gh.chmod(0o755)
        self.env['PATH'] = str(binary) + os.pathsep + self.env['PATH']
        commands = ('gh api repos/x/y/pulls/1', 'gh api -X GET repos/x/y/pulls/1',
                    'gh api --method=GET repos/x/y/pulls/1', 'gh pr view 1', 'gh pr checks 1', 'gh run view 1')
        for command in commands:
            with self.subTest(command=command):
                rewritten = self.rewritten(command)
                observed = json.loads(run(['bash', '-c', rewritten], cwd=self.repo,
                                          env=self.env, check=True).stdout)
                self.assertEqual(observed['args'], command.split()[1:])
                self.assertEqual(observed['tokens'], tokens)

    def test_writer_gh_writes_remain_denied(self):
        commands = ['gh pr merge 1 --squash', 'gh repo sync x/y', 'cd /repo && gh repo sync x/y']
        for method in ('POST', 'PUT', 'PATCH', 'DELETE', 'post', 'pAtCh'):
            for option in (f'-X {method}', f'--method {method}', f'-X{method}', f'--method={method}'):
                commands.extend((f'gh api {option} repos/x/y/pulls/1',
                                 f'gh api repos/x/y/pulls/1 {option}'))
        for option in ('-f title=value', '-F title=value', '--field title=value', '--raw-field title=value',
                       '--input payload.json', '-ftitle=value', '-Ftitle=value', '--field=title=value',
                       '--raw-field=title=value', '--input=payload.json'):
            commands.extend((f'gh api {option} repos/x/y/pulls/1',
                             f'gh api repos/x/y/pulls/1 {option}',
                             f'gh api -X GET repos/x/y/pulls/1 {option}'))
        for command in commands:
            with self.subTest(command=command):
                result = hook('pre', {**self.writer, 'tool_input': {'command': command}}, self.env)
                self.assertTrue(denied(result), command)


if __name__ == '__main__':
    unittest.main()
