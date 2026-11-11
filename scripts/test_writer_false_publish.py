"""Writer push decisions for local reads and merges, and for every real publish form."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ultraship_false_publish', ROOT / 'plugins/ship/hooks/ultraship.py')
ultraship = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ultraship)

GIT_HELPER = ("import subprocess\n\n"
              "def git(*args):\n"
              "    return subprocess.check_output(['git', *args], text=True).strip()\n\n")


FRONTEND_EDIT = ("cd /w/lane/frontend/app/src && python3 - <<'EOF'\n"
                 "p = 'components/__tests__/TeamsStoreWaitingPanel.spec.ts'\n"
                 "open(p, 'w').write(\"it('skips', async () => {\\n  order.push('skip');\\n"
                 "  await router.push('/onboarding/done');\\n});\\n\")\n"
                 "p = 'components/TeamsStoreWaitingPanel.vue'\ns = open(p).read()\n"
                 "old = '<slot name=\"actions\" />'\nassert old in s\n"
                 "open(p, 'w').write(s.replace(old, '<slot name=\"actions\" :skip-pending=\"skipPending\" />'))\n"
                 "EOF\n")


class WriterFalsePublishTests(unittest.TestCase):
    def decision(self, command):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            try:
                ultraship.pre({'agent_type': 'ship:writer--sol', 'tool_name': 'Bash',
                               'tool_input': {'command': command}})
            except SystemExit as error:
                self.assertEqual(error.code, 0)
        text = output.getvalue()
        return json.loads(text)['hookSpecificOutput'] if text else {}

    def assertAdmitted(self, *commands):
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(self.decision(command), {})

    def assertDenied(self, *commands):
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(self.decision(command).get('permissionDecision'), 'deny')

    def test_png_identity_check_during_a_staged_merge_is_admitted(self):
        self.assertAdmitted(
            "cd /w/lane && python3 -I - <<'PY'\nimport subprocess\npath = 'docs/screens/onboarding.png'\n"
            "staged = subprocess.check_output(['git', 'rev-parse', f':{path}'], text=True)\n"
            "incoming = subprocess.check_output(['git', 'rev-parse', f'MERGE_HEAD:{path}'], text=True)\n"
            "print({'same': staged == incoming})\nPY",
            'git -C "$WT" diff --cached MERGE_HEAD -- docs/screens/onboarding.png',
            'WT=/w/lane; git -C $WT ls-tree MERGE_HEAD -- docs/screens/onboarding.png',
            'WT=/w/lane; git -C $WT cat-file -p MERGE_HEAD:docs/screens/onboarding.png | wc -c')

    def test_local_checksum_wrapper_and_merge_commit_are_admitted(self):
        self.assertAdmitted(
            "/usr/bin/bash -c 'W=/w/wt; git -c core.fsmonitor=false -C \"$W\" rev-parse HEAD; "
            "git -C \"$W\" diff --binary HEAD -- . \":!tests/mutation/\" | wc -c; git -C $W status --short'",
            'W=/w/lane; git -C $W merge --no-ff -m "merge main" origin/main && git -C $W log -1',
            'W=/w/lane && git -C $W merge --no-edit origin/main', 'WT=/w/lane; git -C $WT commit --no-edit')

    def test_every_push_form_stays_denied(self):
        self.assertDenied(
            'git push', 'git -C /w push origin HEAD', 'W=/w; git -C $W push', 'W=/w; git -C "$W" push origin HEAD',
            "/usr/bin/bash -c 'W=/w; git -C $W push'",
            "cd /w && python3 - <<'PY'\nprint(1)\nPY\ngit push origin HEAD",
            "python3 - <<'PY'\nimport subprocess\nsubprocess.run(['git', 'push'])\nPY",
            "python3 - <<'PY'\n" + GIT_HELPER + "git('push', 'origin', 'HEAD')\nPY",
            '/usr/lib/git-core/git-push origin HEAD', '"$G"-push origin HEAD', '${G}-push origin HEAD',
            "sleep 2 && bash f.sh & true && python3 - <<'PY'\nopen('f.sh', 'w').write('git push')\nPY",
            'git -C /w ls-files *push', "git -C /w ls-files '*pre-push*'")

    def test_variables_the_scan_cannot_fix_stay_denied(self):
        self.assertDenied(
            'git -C $W status', 'git -C $dir show HEAD:a.png',
            'false && W=/w; git -C $W log push', 'W=/w; git -C $W status; W=x', 'W=/w; read W; git -C $W status',
            'W=/w | git -C $W status', 'W=/w; W=. ; git -C $W log push', 'W=. push; git -C $W status',
            "W=/w; sed -n '1e git -C $W log push' f", "W=/w; echo \"it's\"; sed -n '1e git -C $W log push' f",
            "W=/w; bash -c 'git -C $W log push'", 'W=/w; printf -v X %s .; git -C $W log push',
            'W=/w; git -C $W:s/w/push/ status', "_=/w; echo 'a push'; git -C $_ status",
            "PWD=/w; cd 'a push'; git -C $PWD status", 'W=/w; IFS=/; git -C $W log push',
            'W=/w; X=$(printf ". pu%s" sh); git -C $W $X', 'W=/w & git -C $W log push',
            "W=/w; true # it's\nread W <f; true # '\ngit -C $W log push")

    def test_adjacent_python_literals_after_a_git_helper_stay_denied(self):
        self.assertDenied(*("python3 - <<'PY'\n" + GIT_HELPER + call + "\nPY" for call in (
            "git('pu' 'sh')", "git('pu' 'sh', 'origin', 'HEAD')", "print(f'{1}')\ngit('pu' \"sh\")",
            "git('status')")))

    def test_executable_glob_or_expansion_matching_git_push_stays_denied(self):
        self.assertDenied('/usr/lib/git-core/git-pu* origin HEAD', '/usr/lib/git-core/git-p?sh origin HEAD',
                          '/usr/lib/git-core/g*-push origin HEAD', '/usr/lib/git-core/g?t-push origin HEAD',
                          '/usr/lib/git-core/git-pus[h] origin HEAD', 'cd /w && /usr/lib/git-core/git-pu* x')
        self.assertAdmitted('ls *.py', 'git -C "$W" status')

    def test_globs_in_arguments_are_file_names(self):
        self.assertAdmitted('ls g*', "find . -name 'g*'", 'ls /usr/lib/git-core/git-*', 'ls /usr/lib/git-core/git-pu*',
                            "git -C /w ls-files 'g*'", 'cat g*.txt', 'head -n 1 g?t-*', 'wc -l /usr/lib/git-core/g*')

    def test_send_pack_and_other_remote_ref_writers_stay_denied(self):
        self.assertDenied('git send-pack origin HEAD:main', 'S=send-pack; git $S origin HEAD:main',
                          'S=send-pack && git -C /w $S origin HEAD:main', 'git -C /w send-pack x HEAD:main',
                          'git http-push https://x/y main', '/usr/lib/git-core/git-send-pack x HEAD:main',
                          '/usr/lib/git-core/git-http-push x main', 'g?t send-pack x HEAD:main',
                          '/usr/lib/git-core/git-send-p* x HEAD:main')

    def test_git_config_environment_that_aliases_a_push_stays_denied(self):
        body = "python3 - <<'PY'\nimport subprocess\nsubprocess.run(('git', 'status'))\nPY"
        self.assertDenied(
            'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.status GIT_CONFIG_VALUE_0=push ' + body,
            'cd /w && GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.st GIT_CONFIG_VALUE_0=push ' + body,
            'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.st GIT_CONFIG_VALUE_0=push git st',
            "export GIT_CONFIG_PARAMETERS=\"'alias.st=push'\"; git st",
            'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.st GIT_CONFIG_VALUE_0=send-pack git st')
        self.assertAdmitted('cd /w && PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 ' + body)

    def test_wrapper_runs_its_first_argument_as_the_command_word(self):
        self.assertDenied(*(f'{wrapper} /usr/lib/git-core/git-pu* origin HEAD' for wrapper in (
            'env', 'env -u X Y=1', 'command', 'exec', 'exec -a x', 'nice', 'nice -n 10', 'nohup', 'timeout 5',
            'timeout -s KILL 5m', 'xargs', 'xargs -I {} -n 1', 'sudo', 'sudo -u root', '/usr/bin/env',
            'sudo env', 'nohup nice -n 5')))
        self.assertAdmitted('timeout 5 ls g*', 'env X=1 ls g*', 'xargs -n 1 grep -l g*', 'nohup cat g*.txt')

    def test_git_alias_that_runs_a_shell_or_a_writer_stays_denied(self):
        self.assertDenied('git -c alias.x=push x', 'git -c alias.x=send-pack x origin HEAD:main',
                          'git -c alias.x=http-push x', "git -c 'alias.x=!sh -c y' x", 'git -c alias.x=!git x',
                          'git -calias.x=push x', 'git -c ALIAS.x=push x', 'git -C /w -c alias.st=push st',
                          'git --config-env alias.x=V x', 'git --config-env=alias.x=V x')
        self.assertAdmitted('git -c alias.lg=log lg', 'git -c core.pager=cat log -1', 'git -c push.default=current status')

    def test_unsplittable_git_text_with_a_writer_or_an_escape_stays_denied(self):
        self.assertDenied('git send-pack x "', 'git http-push x "', 'git $X "', 'git `x` "', 'git \\x "')
        self.assertAdmitted('echo "it\'s"')

    def test_git_config_environment_that_defines_an_alias_stays_denied(self):
        self.assertDenied('GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.st GIT_CONFIG_VALUE_0=$V git st',
                          'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=ALIAS.st GIT_CONFIG_VALUE_0=!x git st',
                          'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=$K GIT_CONFIG_VALUE_0=x git st',
                          "GIT_CONFIG_PARAMETERS=\"'alias.st=log'\" git st",
                          'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=ali\\as.st GIT_CONFIG_VALUE_0=x git st')
        self.assertAdmitted('GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.pager GIT_CONFIG_VALUE_0=cat git log -1')

    def test_only_read_only_commands_keep_a_literal_variable_fixed(self):
        self.assertDenied(*(f'W=/w; {command} x; git -C $W log' for command in (
            'tar -xf a.tar --to-command=sh', 'zip -T -TT sh a.zip', 'unzip', 'cd', 'sha256sum', 'echo', 'cp',
            'python3', 'uv', 'make', 'npm', 'bun', 'node', 'xargs', 'find', 'awk', 'sed', 'set -e',
            'export X=1')))
        self.assertAdmitted(*(f'W=/w; {command} x; git -C $W log' for command in (
            'git', 'ls', 'cat', 'grep', 'rg', 'head', 'tail', 'wc', 'test -f')))

    def test_quoted_pathspec_glob_in_read_only_git_is_admitted(self):
        # The refused Teams-lane source read: `'*pre-push*'` is a quoted pathspec, so the shell never globs it.
        lane = 'git -C /home/miguel/.vk-worktrees/.bettercoding-workspaces/ada6-pati-teams-parit/lanes/teams-credits'
        self.assertAdmitted(
            f"{lane} grep -n -A 17 'function readChatPlatform' -- frontend/app/src/lib/chatPlatform.ts; "
            f"{lane} ls-files '*pre-commit*' '*pre-push*' '*lefthook*' '*husky*' '*hooks*' "
            "':!:backend/api/tests/mutation/**' ':!:*.toml' | head -35",
            "git -C /w ls-files '*pre-push*' && git -C /w status --short")

    def test_quoted_pathspec_glob_beside_a_runner_or_expansion_stays_denied(self):
        self.assertDenied(
            'git ls-files *pre-push*', 'git ls-files \'*pre-push*\' "*push*"', "git ls-files x'*push*'",
            "git ls-files '*pre-push*'; git push origin HEAD", "git ls-files '*pre-push*' | xargs git",
            "git ls-files '*pre-push*' && bash run.sh", "git ls-files '*pre-push*' $X", "eval git 'pu*'",
            "git 'pu*'", "git grep '--open-files-in-pager=*push*' x", "git -c 'core.pager=*push*' log",
            "echo '*push*' | xargs git", "sh -c '*push*'")

    def test_publish_commands_stay_denied(self):
        self.assertDenied('gh pr merge 3 --squash', 'gh pr create --fill', "gh pr comment 3 --body '/merge fix(x): y'",
                          'npm publish', 'vercel --prod', 'wrangler deploy', 'docker push ghcr.io/x/y')

    def test_dated_proof_preparation_in_scratch_is_admitted(self):
        # The refused Teams-lane shape: a timestamp, then a Python patch of a scratch script, then a syntax check.
        self.assertAdmitted(
            "date -u +%FT%TZ && python3 -I - <<'PY'\n"
            "from pathlib import Path\nimport ast, hashlib\n"
            "base = Path('/w/.scratch/battery')\np = base / 'battery-1110.sh'\ns = p.read_text()\n"
            "assert hashlib.sha256(p.read_bytes()).hexdigest() == '0' * 64\n"
            "s = s.replace('rc=0\\n\"$PY\" -I - <<\\'PY\\' || rc=$?\\n', 'exec \"$PY\" -I - <<\\'PY\\'\\n')\n"
            "s = s.replace('done\\n', 'elif test -n \"$DIRTY\"; then\\n    echo DIRTY\\n')\n"
            "body = s.split(\"<<'PY'\\n\", 1)[1].rsplit('\\nPY\\n', 1)[0]\nast.parse(body)\n"
            "dst = base / 'battery-final-1110.sh'\nwith dst.open('x') as fh:\n    fh.write(s)\n"
            "dst.chmod(0o444)\nprint(hashlib.sha256(dst.read_bytes()).hexdigest())\nPY\n"
            "bash -n /w/.scratch/battery/battery-final-1110.sh",
            "date -u +%FT%TZ && cd /w/lane && python3 - <<'PY'\np = 'tests/startup.test.js'\ns = open(p).read()\n"
            "open(p, 'w').write(s + \"order.push('listen')\\n\")\nPY")

    def test_test_append_in_own_worktree_is_admitted(self):
        # The refused photos-lane shape: a heredoc append whose test text calls `order.push`.
        self.assertAdmitted(
            "cd /w/repo.lane && cat >> backend/api/tests/unit/routes/startup.test.js <<'EOF'\n\n"
            "describe('replacement startup contract', () => {\n"
            "    it('listens once', async () => {\n        const order = [];\n"
            "        order.push('listen');\n        expect(order).toEqual(['listen']);\n"
            "        expect(process.exit).toHaveBeenCalledWith(0);\n    });\n});\nEOF")

    def test_frontend_edit_then_read_only_checks_is_admitted(self):
        # The refused frontend shape: write a test file, fix a component slot, then read the result back.
        self.assertAdmitted(
            FRONTEND_EDIT + 'date -u',
            FRONTEND_EDIT + 'grep -n skip-pending components/TeamsStoreWaitingPanel.vue && wc -l components/TeamsStoreWaitingPanel.vue; date -u')

    def test_a_command_that_runs_written_files_after_a_heredoc_stays_denied(self):
        # The script can build a push at run time, so nothing that runs code may follow it.
        built = "'git ' + 'pu' + 'sh origin HEAD'"
        self.assertDenied(
            f"cd /w/lane && python3 - <<'EOF'\nopen('run.sh', 'w').write({built})\nEOF\nbash run.sh",
            f"cd /w/lane && python3 - <<'EOF'\nopen('run.sh', 'w').write({built})\nEOF\nsh -n run.sh && sh run.sh",
            f"date -u && python3 -I - <<'EOF'\nimport ast\nopen('run.sh', 'w').write({built})\nEOF\nbash run.sh",
            f"cd /w/lane && python3 - <<'EOF'\nopen('t.spec.ts', 'w').write({built})\nEOF\nbunx vitest run t.spec.ts",
            FRONTEND_EDIT + 'cd /w/lane/frontend/app && bunx vitest run src/components/__tests__')

    def test_frontend_edit_then_publication_stays_denied(self):
        self.assertDenied(
            FRONTEND_EDIT + 'bun run typecheck && git push origin HEAD', FRONTEND_EDIT + 'gh pr merge 3 --squash',
            FRONTEND_EDIT + "gh pr comment 3 --body '/merge fix(x): y'",
            "cd /w/lane && python3 - <<'EOF'\nopen('run.sh', 'w').write('git push origin HEAD')\nEOF\nbash run.sh",
            "cd /w/lane && python3 - <<'EOF'\nopen('run.sh', 'w').write('gh pr merge 3')\nEOF\nbash run.sh",
            "cd /w/lane && python3 - <<'EOF'\np = 'a.txt'\np = 'traceback.py'\n"
            "open(p, 'w').write('git push origin HEAD')\n1 / 0\nEOF\nbun run test")

    def test_a_shell_glob_on_git_from_a_process_starting_script_stays_denied(self):
        # zsh runs `/usr/bin/git(|)` as git, so `git(` text stays a command when the script can start a process.
        self.assertDenied(*(f"date -u +%FT%TZ && python3 - <<'PY'\n{start}\nPY" for start in (
            "import subprocess\nsubprocess.run('/usr/bin/git(|) send-pack x HEAD:main', shell=True, executable='/bin/zsh')",
            "import os\nos.system(\"zsh -c '/usr/bin/git(.) send-pack x HEAD:main'\")",
            "__import__('os').system(\"zsh -c '/usr/bin/git(N) send-pack x HEAD:main'\")",
            "import pathlib\npathlib.os.system(\"zsh -c '/usr/bin/git(|) send-pack x HEAD:main'\")",
            "from pathlib import os\nos.system(\"zsh -c '/usr/bin/git(|) send-pack x HEAD:main'\")",
            "from pathlib import Path\nPath('.').parser.os.system(\"zsh -c '/usr/bin/git(|) send-pack x HEAD:main'\")")))

    def test_a_script_that_writes_a_loadable_module_keeps_its_git_text_scanned(self):
        # Python imports a module the script wrote, so that module can start a process.
        payload = "import os\\nos.system('zsh -c \"/usr/bin/git(|) send-pack x HEAD:main\"')\\n"
        self.assertDenied(*(f"date -u && python3 - <<'PY'\n{body}\nPY" for body in (
            f"open('difflib.py', 'w').write('{payload}')\nimport difflib\nprint('git(|)')",
            f"from pathlib import Path\nPath('textwrap.py').write_text('{payload}')\nfrom textwrap import dedent\n"
            "print('git(|)')",
            f"from pathlib import Path\nbase = Path('/w')\np = base / 'traceback.py'\nwith p.open('w') as f:\n"
            f"    f.write('{payload}')\nprint('git(|)')\n1 / 0",
            f"o = open\no('difflib.py', 'w').write('{payload}')\nimport difflib\nprint('git(|)')",
            f"from pathlib import Path\nw = Path('difflib.py').write_text\nw('{payload}')\nimport difflib\nprint('git(|)')",
            f"from pathlib import Path\nPath('a.txt').write_text('{payload}')\nPath('a.txt').replace('difflib.py')\n"
            "import difflib\nprint('git(|)')",
            f"p = 'a.txt'\nmatch 'difflib.py':\n    case p:\n        pass\nopen(p, 'w').write('{payload}')\n"
            "import difflib\nprint('git(|)')",
            f"Path = lambda p: 'difflib.py'\nopen(Path('a.txt'), 'w').write('{payload}')\nimport difflib\nprint('git(|)')",
            f"from pathlib import Path\ndef Path(p):\n    return 'difflib.py'\nopen(Path('a.txt'), 'w').write('{payload}')\n"
            "import difflib\nprint('git(|)')")))

    def test_an_interactive_shell_or_a_print_write_before_a_run_stays_denied(self):
        write = "cd /w/lane && python3 - <<'EOF'\nopen('run.sh', 'w').write('x')\nEOF\n"
        self.assertDenied(write + 'bash -n -i run.sh', write + 'sh -n -i', write + 'zsh -n --rcs run.sh',
                          "cd /w/lane && python3 - <<'EOF'\nf = open('run.sh', 'w')\nprint('x', file=f)\nEOF\nbash run.sh")
        self.assertAdmitted(write + 'bash -n run.sh')

    def test_a_run_after_a_heredoc_with_any_lead_stays_denied(self):
        write = "python3 - <<'X'\nopen('run.sh', 'w').write('git pu' + 'sh origin HEAD')\nX\n"
        self.assertDenied('date --file=x && ' + write + 'bash run.sh', 'uv run ' + write + 'sh run.sh',
                          'sleep 2 && bash run.sh & ' + write)
        self.assertAdmitted("cd /w && uv run python3 - <<'X'\nimport subprocess\nsubprocess.run(['git', 'status'])\nX")

    def test_publication_behind_a_date_prefix_stays_denied(self):
        self.assertDenied(
            'date -u +%FT%TZ && git push origin HEAD', 'date -u && cd /w && git -C /w push',
            'date -u +%FT%TZ && gh pr merge 3 --squash',
            "date -u +%FT%TZ && cd /w && gh pr comment 3 --body '/merge fix(x): y'",
            "date -u +%FT%TZ && python3 - <<'PY'\nprint(1)\nPY\ngit push origin HEAD",
            "date -u +%FT%TZ && python3 - <<'PY'\nimport subprocess\nsubprocess.run('gh pr merge 3', shell=True)\nPY",
            "date -u +%FT%TZ && python3 - <<'PY'\n" + GIT_HELPER + "git('status')\nPY",
            "date -u && python3 - <<'PY'\nimport subprocess\n"
            "subprocess.run(\"git() { command git pu''sh; }; git\", shell=True)\nPY",
            "date -u $(git push) && python3 - <<'PY'\nprint(1)\nPY")

    def test_denial_names_the_driver_route(self):
        self.assertIn('Return this step to your driver; the driver may run it.',
                      self.decision('git push')['permissionDecisionReason'])


if __name__ == '__main__':
    unittest.main()
