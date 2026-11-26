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

    def test_protected_reviewer_checks_admission_without_a_second_message(self):
        policy = (ROOT / 'plugins/ship/skills/ship/references/owner-decisions.md').read_text()
        admission = policy.split('## Reviewer admission record for protected row reads\n', 1)[1].split('\n## ', 1)[0]
        self.assertIn('In the brief, name the admission record and the reviewed commit.', admission)
        self.assertIn("Make the admission check the reviewer's first step.", admission)
        self.assertIn('require zero protected reads and the single finding `protected admission missing`', admission)
        self.assertIn('`Verdict: findings` and `Reviewed commit: <the commit named in the brief>`', admission)
        self.assertNotIn('SendMessage', admission)
        self.assertNotIn('until the driver confirms', admission)
        for path in AGENTS.glob('reviewer--*.md'):
            _, sections = split_body(path.read_text())
            if ADMISSION in sections:
                with self.subTest(seat=path.stem):
                    text = sections[ADMISSION]
                    self.assertIn('Check the admission record named in the brief as your first step.', text)
                    self.assertIn('If the record is missing or invalid, read nothing protected.', text)
                    self.assertIn('protected admission missing', text)
                    self.assertIn('`Verdict: findings`', text)
                    self.assertIn('`Reviewed commit: <the commit named in the brief>`', text)
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
                    self.assertIn('Check the admission record named in the brief as your first step.', text)
