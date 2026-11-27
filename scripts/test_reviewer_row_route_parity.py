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
EVIDENCE_LINK = '[lane-owned row evidence record](../skills/ship/references/owner-decisions.md#lane-owned-row-evidence-record)'
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
        policy = (ROOT / 'plugins/ship/skills/ship/references/owner-decisions.md').read_text()
        self.evidence = policy.partition('## Lane-owned row evidence record\n')[2].split('\n## ', 1)[0]

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

    def test_row_evidence_requires_the_exact_lane_identity(self):
        self.assertIn('Each record requires `repository`, `pr`, `row_id`, `row_file`, `worktree` and `head`.', self.evidence)
        for definition in (
            "`repository`: the repository's `owner/name`.",
            '`pr`: the verified URL of the authorized draft PR.',
            '`row_id`: the exact row ID.',
            '`row_file`: the exact repository-relative path of the protected row file.',
            '`worktree`: the canonical absolute path of the lane worktree that holds the frozen head.',
            '`head`: the full frozen head commit SHA.',
        ):
            with self.subTest(definition=definition):
                self.assertIn(f'- {definition}', self.evidence)
        self.assertIn('Match every identity field to the verified lane scope.', self.evidence)
        self.assertIn('Keep the row pending if the record or any identity field is missing or mismatched.', self.evidence)

    def test_row_evidence_keeps_separate_admissions_and_gives_zero_authority_or_retry_credit(self):
        self.assertIn('Keep reviewer admission, tool admission and execution admission separate.', self.evidence)
        self.assertIn('The record grants zero authority.', self.evidence)
        self.assertIn('The record authorizes zero retries and gives zero retry credit.', self.evidence)

    def test_drivers_supply_the_record_for_all_four_row_actions(self):
        self.assertIn('Keep one content-free record per authorized lane-owned protected row change at the frozen head.',
                      self.evidence)
        self.assertIn('Include every changed, added, retired or restored protected row.', self.evidence)
        for name in ('driver.md', 'driver--sol.md'):
            with self.subTest(driver=name):
                self.assertIn(f'Include the {EVIDENCE_LINK} in the reviewer brief for each changed, added, retired or restored row.',
                              (AGENTS / name).read_text())

    def test_lane_owned_review_checks_identity_and_keeps_separate_admission(self):
        review = self.sections[REVIEW]
        self.assertIn(f'Require exactly one {EVIDENCE_LINK} in the brief for each changed, added, retired or restored row.',
                      review)
        self.assertIn('Match every identity field to the scope in the brief.', review)
        self.assertIn('Block approval if the record or any identity field is missing or mismatched.', review)
        self.assertIn("Read rows only under the driver's reviewer admission record.", review)
        self.assertIn('The evidence record grants zero protected access.', review)

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
