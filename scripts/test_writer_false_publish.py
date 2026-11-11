"""Writer push decisions for local reads, checksums and merges, and for every real publish form."""
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
            "cd /w/lane && python3 -I - <<'PY'\n" + GIT_HELPER +
            "assert git('rev-parse', 'MERGE_HEAD') == 'ffe8743830889df4a166f63ec743fed30124a889'\n"
            "path = 'docs/screens/onboarding.png'\n"
            "assert git('rev-parse', f':{path}') == git('rev-parse', f'MERGE_HEAD:{path}')\n"
            "print(f'DELTA={git(\"diff\", \"--cached\", \"--name-status\", \"MERGE_HEAD\", \"--\", path) or \"none\"}')\n"
            "PY",
            'git -C "$WT" diff --cached MERGE_HEAD -- docs/screens/onboarding.png',
            'WT=/w/lane; git -C $WT ls-tree MERGE_HEAD -- docs/screens/onboarding.png',
            'WT=/w/lane; git -C $WT cat-file -p MERGE_HEAD:docs/screens/onboarding.png | sha256sum')

    def test_source_read_that_lists_hook_paths_is_admitted(self):
        self.assertAdmitted(
            "git -C /w/lane grep -n -A 17 'function readChatPlatform' -- src/lib/chatPlatform.ts; "
            "git -C /w/lane ls-files '*pre-commit*' '*pre-push*' '*lefthook*' '*husky*' '*hooks*' "
            "':!:tests/mutation/**' ':!:*.toml' | head -35",
            'git -C "$W" ls-files \'*pre-push*\'',
            'git -C "$W" config --get remote.origin.pushurl')

    def test_local_packaging_and_checksum_step_is_admitted(self):
        self.assertAdmitted(
            'cd /w/plugin-wt && PYTHONDONTWRITEBYTECODE=1 python3 scripts/check-plugins.py --base 7498dfd5 '
            '> ../verify/final-packaging.log 2>&1 && git diff --check > ../verify/final-diff-check.log 2>&1 && '
            "PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'\n"
            "import hashlib, json, subprocess\nfrom pathlib import Path\nroot = Path.cwd()\n"
            "def git(*args):\n    return subprocess.check_output(['git', '-C', str(root), *args])\n"
            "diff = git('diff', '--binary', 'HEAD')\n"
            "print(json.dumps({'head': git('rev-parse', 'HEAD').decode().strip(), "
            "'sha256': hashlib.sha256(diff).hexdigest()}))\n"
            "PY",
            "/usr/bin/bash -c 'set -euo pipefail; W=/w/wt; cd \"$W\"; export GIT_OPTIONAL_LOCKS=0; "
            "git -c core.fsmonitor=false -C \"$W\" rev-parse HEAD; sha256sum -- \"$W/.github/a.yml\" \"$W/b.mjs\"; "
            "git -C \"$W\" diff --binary HEAD -- . \":!tests/mutation/\" | sha256sum; "
            "git -C \"$W\" config --get core.hooksPath || test \"$?\" = 1'")

    def test_local_merge_commit_of_main_into_the_lane_branch_is_admitted(self):
        self.assertAdmitted(
            "cd /w/lane && python3 -I - <<'PY'\n" + GIT_HELPER +
            "assert git('branch', '--show-current') == 'mr/lane'\nassert not git('status', '--porcelain')\nPY\n"
            "git -c user.name='Miguel Rasero' -c user.email=m@example.com merge --no-ff origin/main "
            "-m 'merge(frontend): integrate main'",
            'W=/w/lane; git -C $W merge --no-ff -m "merge main" origin/main && git -C $W log -1',
            'W=/w/lane && git -C $W merge --no-edit origin/main',
            'WT=/w/lane; git -C $WT commit --no-edit')

    def test_every_push_form_stays_denied(self):
        self.assertDenied(
            'git push', 'git -C /w push origin HEAD', 'W=/w; git -C $W push', 'W=/w; git -C "$W" push origin HEAD',
            "/usr/bin/bash -c 'W=/w; git -C $W push'", 'git -C $W status', 'git -C $dir show HEAD:a.png',
            "cd /w && python3 - <<'PY'\nprint(1)\nPY\ngit push origin HEAD",
            "python3 - <<'PY'\nimport subprocess\nsubprocess.run(['git', 'push'])\nPY",
            "python3 - <<'PY'\n" + GIT_HELPER + "git('push', 'origin', 'HEAD')\nPY",
            "python3 - <<'PY'\n" + GIT_HELPER + "git('pu' 'sh')\nprint(f'{1}')\nPY\n:; git p{u,}sh",
            '/usr/lib/git-core/git-push origin HEAD', '/usr/lib/git-core/g?t-push origin HEAD',
            '"$G"-push origin HEAD', '${G}-push origin HEAD',
            "sleep 2 && bash f.sh & true && python3 - <<'PY'\nopen('f.sh', 'w').write('git push')\nPY",
            'git -C /w ls-files *push')

    def test_variables_the_scan_cannot_fix_stay_denied(self):
        self.assertDenied(
            'false && W=/w; git -C $W log push', 'W=/w; git -C $W status; W=x', 'W=/w; read W; git -C $W status',
            'W=/w | git -C $W status', 'W=/w; W=. ; git -C $W log push', 'W=. push; git -C $W status',
            "W=/w; sed -n '1e git -C $W log push' f", "W=/w; echo \"it's\"; sed -n '1e git -C $W log push' f",
            "W=/w; bash -c 'git -C $W log push'", 'W=/w; printf -v X %s .; git -C $W log push',
            'W=/w; git -C $W:s/w/push/ status', "_=/w; echo 'a push'; git -C $_ status",
            "PWD=/w; cd 'a push'; git -C $PWD status", 'W=/w; IFS=/; git -C $W log push',
            'W=/w; X=$(printf ". pu%s" sh); git -C $W $X', 'W=/w & git -C $W log push',
            "W=/w; true # it's\nread W <f; true # '\ngit -C $W log push")

    def test_publish_commands_stay_denied(self):
        self.assertDenied('gh pr merge 3 --squash', 'gh pr create --fill', "gh pr comment 3 --body '/merge fix(x): y'",
                          'npm publish', 'vercel --prod', 'wrangler deploy', 'docker push ghcr.io/x/y')

    def test_denial_names_the_driver_route(self):
        self.assertIn('Return this step to your driver; the driver may run it.',
                      self.decision('git push')['permissionDecisionReason'])


if __name__ == '__main__':
    unittest.main()
