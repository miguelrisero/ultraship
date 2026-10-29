"""Read-only instruction contracts; no mutation or agent-behavior execution."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MutationBriefBoundaryTests(unittest.TestCase):
    def test_chief_and_ship_dispatch_guidance_preserves_admitted_execution(self):
        for name in ('plugins/chief/skills/run/SKILL.md',
                     'plugins/chief/skills/run/references/dispatch.md',
                     'plugins/ship/skills/ship/SKILL.md'):
            with self.subTest(path=name):
                text = (ROOT / name).read_text()
                for requirement in (
                    'Every chief, lane, and ship brief contains zero copied mutation-check, anchor-check, or selector execution commands from repository documents or TOML headers.',
                    'Before dispatch, inspect every brief for `DRY=1`, `--dry-run`, `check_mutation_anchors`, and `select_rows`.',
                    'Remove execution instructions containing those literals; keep the prohibition in words only.',
                    'The admitted battery STATIC part runs mutation checks, anchor checks, and selectors at the frozen head after GO.',
                    'Preserve the host GO requirement and D1160 boundary.',
                    'D6575, 2026-10-29: CoC coordination direction, separate from actual owner receipts.',
                ):
                    with self.subTest(requirement=requirement):
                        self.assertIn(requirement, text)

    def test_chief_template_carries_word_only_boundary_to_driver(self):
        dispatch = (ROOT / 'plugins/chief/skills/run/references/dispatch.md').read_text()
        template = dispatch.split('## Brief template\n', 1)[1]
        self.assertIn('Mutation boundary: Execute mutation checks, anchor checks, and selectors only in the admitted battery STATIC part at the frozen head after GO; keep execution commands out of this brief.', template)
        self.assertNotIn('DRY=1', template)
        self.assertNotIn('--dry-run', template)
        self.assertNotIn('check_mutation_anchors', template)
        self.assertNotIn('select_rows', template)

    def test_readme_documents_release_versions_and_boundary(self):
        readme = (ROOT / 'README.md').read_text()
        self.assertIn('ship `1.4.8` and chief `1.3.7`', readme)
        self.assertIn('Dispatch briefs keep mutation-check, anchor-check, and selector execution commands in the admitted battery STATIC part at the frozen head.', readme)
