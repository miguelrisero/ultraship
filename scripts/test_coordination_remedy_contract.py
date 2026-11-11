"""Pin the Markdown instructions drivers consume; never simulate or replay dispatch."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / 'plugins/ship/skills/ship/references/owner-decisions.md'


class CoordinationRemedyContractTests(unittest.TestCase):
    def setUp(self):
        self.owner = OWNER.read_text()
        section = self.owner.split('## Loaded instructions and refusals\n', 1)[1]
        self.refusals = re.split(r'^ {0,3}#{1,6}(?:[ \t]+|$)|^.+\n {0,3}(?:=+|-+)[ \t]*$',
                                 section, maxsplit=1, flags=re.MULTILINE)[0]

    def test_contract_binds_both_drivers_and_shared_consumers(self):
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

    def test_contract_requires_exact_gate_remedy_and_loaded_agent_scope(self):
        self.assertIn(
            "For the driver's `Agent` dispatch only, allow one resend when the denial explicitly "
            'identifies `Coordination gate error` and an exact text remedy.', self.refusals)
        self.assertIn('Require unambiguous gate identity and remedy and the applicable loaded contract; '
                      'the denial date alone never determines eligibility.', self.refusals)
        self.assertIn('Apply only that remedy; preserve the action, recipient, scope, authority, '
                      'and exact owner-provenance checks.', self.refusals)

    def test_contract_blocks_incomplete_generic_and_broader_edits(self):
        # Each case must occur inside the operative Block sentence, not elsewhere in the document.
        block = self.refusals.split('Block ', 1)[1].split('.', 1)[0]
        for case in ('missing or ambiguous gate identity', 'missing or ambiguous remedy',
                     'generic `Output contract` denials', 'broader edits',
                     'changed action, recipient, scope, or authority'):
            with self.subTest(case=case):
                self.assertIn(case, block)

    def test_contract_keeps_safety_refusals_and_mixed_denials_final(self):
        self.assertIn('Every safety-hook refusal remains final.', self.refusals)
        self.assertIn(
            'Any safety-hook refusal, mixed safety denial, binding tool denial, '
            'or higher-priority restriction blocks the resend.', self.refusals)
        self.assertIn(
            'Preserve applicable higher-priority prohibitions, tool and hook denials, '
            'protected paths, and approval, GO, installation, and publication holds.', self.refusals)

    def test_contract_consumes_one_resend_durably_before_sending(self):
        self.assertIn('Record the denial and consumed resend on the durable run board before sending, '
                      'keyed by the unchanged action, recipient, and scope.', self.refusals)
        self.assertIn('Absent records, consumed attempts, and a failed second attempt '
                      'stay blocked across recovery.', self.refusals)
        self.assertIn('A version, restart, or new session alone lifts nothing; '
                      'never reset an attempt or substitute an executor '
                      'to bypass a still-effective refusal.', self.refusals)

    def test_contract_preserves_all_authority_and_owner_verification_checks(self):
        for requirement in (
            'An explicit owner refusal blocks all routes for that edit until '
            'applicable owner authority resolves it.',
            'Apply your own loaded definition; a checkout, cache entry, or version '
            'supplies zero additional authority.',
            'Keep prospective source changes separate from runtime adoption and action authority.',
            'Repairing missing verification evidence resolves only that evidence gap; '
            'it cannot override a binding prohibition or tool denial.',
            'Recheck current version, status, and answer provenance before the resend.',
            'Other refusals lift only when their cause is actually fixed or applicable authority resolves them.',
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

    def test_contract_keeps_the_refusal_rule_line_budget(self):
        self.assertLessEqual(len([line for line in self.refusals.splitlines() if line.strip()]), 8)
