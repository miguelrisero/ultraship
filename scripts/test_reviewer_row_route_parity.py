"""Only the admitted reviewer seats carry the lane-owned row review."""
import importlib.util
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_plugins', ROOT / 'scripts/check-plugins.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)
AGENTS = ROOT / 'plugins/ship/agents'
REVIEW = '## Lane-owned row review'
ADMISSION = '## Protected row admission'
REPAIR = '## Standalone main-row repair review'
SOL_ADMISSION = 'Use this admission for lane-owned row review and standalone main-row repair review, as applicable to the brief.'
ASTRA_ADMISSION = 'Use this admission for lane-owned row review, as applicable to the brief.'


def split_body(text):
    body = text.split('\n---\n', 1)[1]
    parts = re.split(r'^(## .+)$', body, flags=re.M)
    return parts[0], {parts[i]: parts[i] + parts[i + 1]
                      for i in range(1, len(parts), 2)}


class ReviewerRowRouteParityTests(unittest.TestCase):
    def setUp(self):
        self.sol = (AGENTS / 'reviewer--sol.md').read_text()
        self.base, self.sections = split_body(self.sol)

    def test_astra_base_and_exact_route_scope(self):
        base, sections = split_body((AGENTS / 'reviewer--astra.md').read_text())
        self.assertEqual(base, self.base)
        self.assertEqual(set(sections), {ADMISSION, REVIEW})
        self.assertIn(SOL_ADMISSION, self.sections[ADMISSION])
        self.assertEqual(sections[ADMISSION], self.sections[ADMISSION].replace(SOL_ADMISSION, ASTRA_ADMISSION))
        self.assertEqual(sections[REVIEW], self.sections[REVIEW])

    def test_only_named_seats_implement_protected_row_review(self):
        for path in sorted(AGENTS.glob('reviewer--*.md')):
            with self.subTest(seat=path.stem):
                text = path.read_text()
                _, sections = split_body(text)
                if path.stem in ('reviewer--sol', 'reviewer--opus'):
                    self.assertEqual(set(sections), {ADMISSION, '## Squash-merge containment', REPAIR, REVIEW})
                    self.assertEqual(text.split('\n---\n', 1)[1], self.sol.split('\n---\n', 1)[1])
                elif path.stem != 'reviewer--astra':
                    self.assertFalse(sections)

    def test_astra_keeps_read_only_tools_and_effort(self):
        fields = checks.frontmatter((AGENTS / 'reviewer--astra.md').read_text())
        self.assertEqual(fields['tools'], 'Read, Grep, Glob, LSP, WebFetch, WebSearch')
        self.assertEqual(fields['effort'], 'xhigh')

    def test_protected_reviewer_stops_only_on_the_hook_admission_refusal(self):
        policy = (ROOT / 'plugins/ship/skills/ship/references/owner-decisions.md').read_text()
        admission = policy.split('## Reviewer admission record for protected row reads\n', 1)[1].split('\n## ', 1)[0]
        self.assertIn('Launch the reviewer in the background.', admission)
        self.assertIn('Continue the same reviewer with SendMessage after the record exists.', admission)
        for text in [admission, *(split_body((AGENTS / f'reviewer--{seat}.md').read_text())[1][ADMISSION]
                                  for seat in ('sol', 'opus', 'astra'))]:
            with self.subTest(text=text):
                self.assertIn('If the hook refuses a protected read because admission is missing or invalid', text)
                self.assertIn('Make no further protected reads.', text)
                self.assertIn('`Verdict: blocked`', text)
                self.assertIn('`Reason: protected admission missing`', text)
                self.assertIn('`Reviewed commit: <the commit named in the brief>`', text)
                self.assertNotIn('first step', text)
                self.assertNotIn('Check the admission record', text)
                self.assertNotIn('Wait for the driver', text)

    def test_dispatch_selects_a_reviewer_with_the_loaded_route(self):
        text = (ROOT / 'plugins/ship/skills/ship/references/owner-decisions.md').read_text()
        admission = text.split('## Reviewer admission record for protected row reads\n', 1)[1].split('\n## ', 1)[0]
        self.assertIn('Dispatch `ship:reviewer--sol`, `ship:reviewer--opus`, or, for lane-owned row review only, `ship:reviewer--astra`.', admission)
        self.assertIn('Send the full reviewer brief at dispatch.', admission)
        self.assertNotIn('`ready`', admission)
        for path in AGENTS.glob('reviewer--*.md'):
            with self.subTest(seat=path.stem):
                text = path.read_text()
                self.assertNotIn('return `ready`', text.casefold())
                if ADMISSION in text:
                    self.assertIn('If the hook refuses a protected read because admission is missing or invalid', text)
