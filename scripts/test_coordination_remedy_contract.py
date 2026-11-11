"""Pin the Markdown instructions drivers consume; never simulate or replay dispatch."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / 'plugins/ship/skills/ship/references/owner-decisions.md'


class CoordinationRemedyContractTests(unittest.TestCase):
    def setUp(self):
        self.owner = OWNER.read_text()
        self.refusals = self.owner.split('## Loaded instructions and refusals\n', 1)[1]

    def test_both_drivers_consume_the_same_narrow_exception(self):
        for name in ('driver.md', 'driver--sol.md'):
            with self.subTest(driver=name):
                driver = (ROOT / 'plugins/ship/agents' / name).read_text()
                self.assertIn(
                    'Apply [Loaded instructions and refusals]'
                    '(../skills/ship/references/owner-decisions.md#loaded-instructions-and-refusals), '
                    'including its once-only exact coordination text remedy; '
                    'every safety-hook refusal remains final.', driver)
        for name in ('plugins/ship/skills/ship/SKILL.md',
                     'plugins/ship/skills/ship/references/pipeline.md'):
            with self.subTest(consumer=name):
                self.assertIn('[Loaded instructions and refusals]', (ROOT / name).read_text())

    def test_eligibility_requires_all_conditions_in_one_permission(self):
        self.assertIn(
            'For driver dispatch only, allow one resend for an unambiguous coordination-gate '
            'denial that explicitly specifies an exact text remedy.', self.refusals)
        self.assertIn('Require the applicable contract to be loaded; '
                      'the denial date alone never determines eligibility.', self.refusals)
        self.assertIn('Apply only that remedy; preserve the action, recipient, scope, authority, '
                      'and exact owner-provenance checks.', self.refusals)

    def test_incomplete_identity_or_remedy_and_broader_edits_stay_blocked(self):
        # Each case must occur inside the operative Block sentence, not elsewhere in the document.
        block = self.refusals.split('Block ', 1)[1].split('.', 1)[0]
        for case in ('missing or ambiguous gate identity', 'missing or ambiguous remedy',
                     'broader edits', 'changed action, recipient, scope, or authority'):
            with self.subTest(case=case):
                self.assertIn(case, block)

    def test_safety_refusals_and_mixed_denials_are_final(self):
        self.assertIn('Every safety-hook refusal remains final.', self.refusals)
        self.assertIn(
            'Any safety-hook refusal, mixed safety denial, binding tool denial, '
            'or higher-priority restriction blocks the resend.', self.refusals)
        self.assertIn(
            'Preserve applicable higher-priority prohibitions, tool and hook denials, '
            'protected paths, and approval, GO, installation, and publication holds.', self.refusals)

    def test_one_resend_is_consumed_before_sending_and_survives_recovery(self):
        self.assertIn('Record the denial and consumed resend before sending; '
                      'a failed second attempt stays blocked.', self.refusals)
        self.assertIn('Never reset the attempt through a version, restart, new session, '
                      'or executor substitution.', self.refusals)
        self.assertIn('never bypass a still-effective refusal.', self.refusals)

    def test_remedy_cannot_supply_authority_or_replace_owner_verification(self):
        for requirement in (
            'An explicit owner refusal blocks all routes for that edit until '
            'applicable owner authority resolves it.',
            'Apply your own loaded definition; source changes, checkouts, cache entries, '
            'and versions grant zero runtime adoption or action authority.',
            'Repairing missing verification evidence resolves only that evidence gap; '
            'it cannot override a binding prohibition or tool denial.',
            'Recheck current version, status, and answer provenance before the resend.',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.refusals)
        consume = self.owner.split('## Consume and finish\n', 1)[1].split('\n## ', 1)[0]
        for requirement in ('event_type=answer_submitted', 'actor_kind=owner_ui',
                            'payload.no_answer_yet=false', 'recorded Input and current version',
                            'Before dispatch or replay, recheck the Input\'s current version, '
                            'status, and answer provenance.',
                            'Keep superseded or cancelled authorization blocked.'):
            with self.subTest(provenance=requirement):
                self.assertIn(requirement, consume)
        self.assertIn('Preserve a direct authoritative mismatch as blocked; '
                      'the fallback supplies verified provenance, never a substitute owner approval.', self.owner)

    def test_refusal_rule_line_budget(self):
        self.assertLessEqual(len([line for line in self.refusals.splitlines() if line.strip()]), 8)
