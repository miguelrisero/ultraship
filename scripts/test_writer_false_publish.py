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

    def test_publish_commands_stay_denied(self):
        self.assertDenied('gh pr merge 3 --squash', 'gh pr create --fill', "gh pr comment 3 --body '/merge fix(x): y'",
                          'npm publish', 'vercel --prod', 'wrangler deploy', 'docker push ghcr.io/x/y')

    def test_denial_names_the_driver_route(self):
        self.assertIn('Return this step to your driver; the driver may run it.',
                      self.decision('git push')['permissionDecisionReason'])


if __name__ == '__main__':
    unittest.main()
