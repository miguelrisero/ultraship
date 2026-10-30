"""Static push-policy contracts; these tests perform zero remote operations."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ExplicitFeaturePushTests(unittest.TestCase):
    def test_pipeline_requires_explicit_feature_destination_and_upstream_preflight(self):
        text = (ROOT / 'plugins/ship/skills/ship/references/pipeline.md').read_text()
        push = text.split('## 9. Push and PR\n', 1)[1].split('\n## ', 1)[0]
        for requirement in (
            'git push origin HEAD:refs/heads/<feature-branch>',
            'git rev-parse --abbrev-ref @{u}',
            'git branch --show-current',
            'actual default branch',
            '`main`, `origin/main`',
            'block the push and establish feature tracking',
            'A missing upstream permits the explicit first feature push',
            'Never use an abbreviated or default push',
            'Preserve existing push authority, approval holds, merge holds, and verification gates',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, push)
        self.assertNotIn('3. Push. Open one PR', push)

    def test_chief_template_carries_the_same_push_boundary(self):
        text = (ROOT / 'plugins/chief/skills/run/references/dispatch.md').read_text()
        template = text.split('## Brief template\n', 1)[1]
        for requirement in (
            'git push origin HEAD:refs/heads/<feature-branch>',
            'git rev-parse --abbrev-ref @{u}',
            'actual default branch',
            '`main`, `origin/main`',
            'block the push and establish feature tracking',
            'missing upstream permits the explicit first feature push',
            'Never use an abbreviated or default push',
            'Preserve existing push authority, approval holds, merge holds, and verification gates',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, template)
