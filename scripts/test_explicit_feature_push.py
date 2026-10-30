"""Push-policy source contracts and a CI-only synthetic bare-remote regression."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PUSH = 'git push origin HEAD:refs/heads/<feature-branch>'
PREFLIGHT = 'git push --dry-run --porcelain origin HEAD:refs/heads/<feature-branch>'


class ExplicitFeaturePushTests(unittest.TestCase):
    def test_pipeline_requires_explicit_feature_destination_and_upstream_preflight(self):
        text = (ROOT / 'plugins/ship/skills/ship/references/pipeline.md').read_text()
        push = text.split('## 9. Push and PR\n', 1)[1].split('\n## ', 1)[0]
        for requirement in (
            PUSH,
            PREFLIGHT,
            'Before every authorized feature push, including retries and later pushes',
            'git rev-parse --show-toplevel',
            'git remote get-url --push --all origin',
            'git branch --show-current',
            'git rev-parse HEAD',
            'git ls-remote --symref <push-url> HEAD',
            'actual default branch',
            'detached HEAD',
            'git rev-parse --abbrev-ref @{u}',
            '`main`, `origin/main`',
            'block the push and establish feature tracking',
            'A missing upstream permits the explicit first feature push',
            'Inherited upstream and `push.default` are risk context, not resolved destination evidence',
            '`pushurl`, `insteadOf`, and `pushInsteadOf` resolution',
            'Inspect every `To` endpoint and every porcelain status row',
            'sole approved endpoint',
            'exactly one destination row',
            'extra refs, tags, deletions, forced updates',
            'denied, unavailable, unsuccessful, empty, or unparseable',
            'same repository, HEAD SHA, current branch, remote, and literal refspec',
            'remove only `--dry-run --porcelain`',
            'Never use an abbreviated or default push',
            'Preserve existing push authority, approval holds, merge holds, and verification gates',
            'Writers prepare repository, branch, and command evidence only',
            'writers retain zero push authority, including push dry-runs',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, push)
        self.assertNotIn('Before the first push', push)
        self.assertNotIn('3. Push. Open one PR', push)

    def test_chief_template_carries_the_same_push_boundary(self):
        text = (ROOT / 'plugins/chief/skills/run/references/dispatch.md').read_text()
        template = text.split('## Brief template\n', 1)[1]
        for requirement in (
            PUSH,
            'Before every authorized feature push',
            'repository, remote, current branch, and actual default branch',
            'resolved destination preflight',
            'installed ship plugin',
            'skills/ship/references/pipeline.md',
            'step 9',
            'permitted dry-run',
            'every advertised endpoint and destination ref',
            'same remote and literal refspec',
            'main, the actual default branch, detached HEAD, and extra refs',
            'denied, unavailable, or unparseable',
            'Preserve existing push authority, approval holds, merge holds, and verification gates',
            'Writers prepare evidence only',
            'writers retain zero push authority, including push dry-runs',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, template)
        # The mutation-command boundary keeps execution literals out of briefs.
        self.assertNotIn('--dry-run', template)
        self.assertNotIn('Before the first push', template)

    def test_ci_discovers_push_and_model_regressions(self):
        workflow = (ROOT / '.github/workflows/validate.yml').read_text()
        self.assertIn("python3 -m unittest discover -s scripts -p 'test_*.py' -v", workflow)
        self.assertIn('TMPDIR="$PWD/.scratch"', workflow)

    def test_both_drivers_use_the_shared_preflight_without_writer_authority(self):
        for name in ('driver', 'driver--sol'):
            with self.subTest(driver=name):
                text = (ROOT / f'plugins/ship/agents/{name}.md').read_text()
                for requirement in (
                    'Before every authorized feature push',
                    '../skills/ship/references/pipeline.md#9-push-and-pr',
                    'resolved destination preflight',
                    'including retries and later pushes',
                    'Writers prepare evidence only',
                    'writers retain zero push authority, including push dry-runs',
                ):
                    self.assertIn(requirement, text)
        for name in ('writer--sol', 'writer--sonnet'):
            text = (ROOT / f'plugins/ship/agents/{name}.md').read_text()
            self.assertIn('Never push, merge, deploy, publish, or release.', text)


@unittest.skipUnless(os.environ.get('CI') == 'true', 'Synthetic push regression runs only in CI')
class ExplicitFeaturePushRemoteTests(unittest.TestCase):
    def test_every_explicit_push_targets_feature_with_main_upstream(self):
        # All Git state and transport stay inside the CI scratch directory.
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
            root = Path(directory)
            local, remote = root / 'local', root / 'remote.git'
            env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_AUTHOR_NAME='Push contract', GIT_AUTHOR_EMAIL='push@example.invalid',
                       GIT_COMMITTER_NAME='Push contract', GIT_COMMITTER_EMAIL='push@example.invalid',
                       GIT_TERMINAL_PROMPT='0', LC_ALL='C')

            def git(cwd, *args):
                return subprocess.run(['git', *args], cwd=cwd, env=env, check=True,
                                      capture_output=True, text=True).stdout.strip('\n')

            git(root, 'init', '--initial-branch=main', str(local))
            git(local, 'commit', '--allow-empty', '-m', 'Seed main')
            main = git(local, 'rev-parse', 'HEAD')
            git(root, 'clone', '--bare', str(local), str(remote))
            git(local, 'remote', 'add', 'origin', str(remote))
            git(local, 'fetch', 'origin')
            feature = 'feature/push-destination'
            refspec = f'HEAD:refs/heads/{feature}'
            git(local, 'switch', '-c', feature)
            git(local, 'branch', '--set-upstream-to=origin/main', feature)
            git(local, 'config', 'push.default', 'upstream')
            for attempt in range(2):
                with self.subTest(attempt=attempt):
                    git(local, 'commit', '--allow-empty', '-m', f'Feature {attempt}')
                    head = git(local, 'rev-parse', 'HEAD')
                    self.assertEqual(git(local, 'branch', '--show-current'), feature)
                    self.assertEqual(git(local, 'rev-parse', '--abbrev-ref', '@{u}'), 'origin/main')
                    self.assertEqual(git(local, 'config', 'push.default'), 'upstream')
                    self.assertEqual(git(local, 'remote', 'get-url', '--push', '--all', 'origin'), str(remote))
                    self.assertIn('ref: refs/heads/main\tHEAD',
                                  git(local, 'ls-remote', '--symref', str(remote), 'HEAD'))
                    before = git(remote, 'show-ref')
                    output = git(local, 'push', '--dry-run', '--porcelain', 'origin', refspec)
                    lines = output.splitlines()
                    self.assertEqual([line for line in lines if line.startswith('To ')], [f'To {remote}'])
                    rows = [line.split('\t') for line in lines if '\t' in line]
                    self.assertEqual(len(rows), 1, output)
                    self.assertEqual(len(rows[0]), 3, output)
                    self.assertIn(rows[0][0], (' ', '*', '='))
                    self.assertEqual(rows[0][1], refspec)
                    self.assertEqual(git(remote, 'show-ref'), before)
                    # Exercise the exact remote/refspec, without changing upstream tracking.
                    git(local, 'push', 'origin', refspec)
                    self.assertEqual(git(remote, 'rev-parse', f'refs/heads/{feature}'), head)
                    self.assertEqual(git(remote, 'rev-parse', 'refs/heads/main'), main)
                    self.assertEqual(set(git(remote, 'for-each-ref', '--format=%(refname)').splitlines()),
                                     {'refs/heads/main', f'refs/heads/{feature}'})
