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

    def test_contract_scopes_the_owner_approved_method_only_retry(self):
        for requirement in (
            'Method-only denial (owner Input e6ba1705-42f2-491c-ac0b-43ae191596b6, choice B): '
            'a refusal naming only the method, never the content, permits one native Edit retry.',
            'A fresh writer applies the already-approved edit text exactly once with native Edit; '
            'the commit stays a separate step.',
            'The method ban and every content, scope, protected-access and publication denial stay final.',
            'Consume that single attempt on the canonical durable record before the edit; '
            'a failed attempt stays consumed.',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.refusals)

    def test_contract_keeps_the_refusal_rule_line_budget(self):
        self.assertLessEqual(len([line for line in self.refusals.splitlines() if line.strip()]), 8)

    def test_contract_binds_formatting_resends_to_authenticated_original_calls(self):
        for requirement in (
            'For `Agent` and `SendMessage`, allow one formatting-only resend only after '
            'an authenticated lint refusal with an exact formatting remedy.',
            'Require trusted native tool evidence attributing the complete refusal to the '
            'formatting producer and identifying the original refused tool call.',
            'For `SendMessage`, require authenticated `plugins/ship/hooks/text_lint.py` or '
            'chief-of-chiefs `skills/run/scripts/text_lint.py` producer attribution.',
            'The `Output contract:` prefix alone supplies zero producer authentication.',
            'An authenticated formatting-only refusal qualifies despite that prefix; '
            'generic or unclassified denials remain blocked.',
            'Require every returned finding to be formatting-only and the applicable loaded contract.',
            "The formatting exception covers only the identified formatting producer's refusal "
            "of that handoff's text; other binding tool denials remain final.",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.refusals)
        for name in ('driver.md', 'driver--sol.md'):
            with self.subTest(driver=name):
                driver = (ROOT / 'plugins/ship/agents' / name).read_text()
                self.assertIn('Apply its once-only authenticated formatting-only resend contract '
                              'to `Agent` and `SendMessage`.', driver)

    def test_contract_requires_known_formatting_findings_and_blocks_unknown_evidence(self):
        self.assertIn(
            'Attribute a pathless hook refusal by elimination only when every enabled PreToolUse '
            'hook that matches the tool and can emit each returned finding is a named formatting producer.',
            self.refusals,
        )
        self.assertIn(
            'Require every returned finding to match a known `text_lint.py` formatting message.',
            self.refusals,
            'Every returned finding must match a known text_lint formatting message',
        )
        block = self.refusals.partition('For formatting-only resends, block ')[2].partition('.')[0]
        for case in ('unknown producers', 'unmatched findings'):
            with self.subTest(case=case):
                self.assertIn(case, block, f'The formatting exception must block {case}')

    def test_contract_limits_formatting_remedies_to_supported_prose(self):
        for requirement in (
            'Apply only the exact formatting remedy; preserve the action, recipient, scope, '
            'authority, non-prose fields, owner provenance, and choice identifiers.',
            'A missing `Facts` heading organizes supported existing facts only; '
            'invent zero facts, evidence, approval, or authority.',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.refusals)
        self.assertIn('preserve existing published choice IDs during retries.', self.owner)

    def test_contract_keeps_formatting_route_fail_closed(self):
        block = self.refusals.partition('For formatting-only resends, block ')[2].partition('.')[0]
        for case in (
            'generic prefixes without exact provenance',
            'unknown producers',
            'incomplete refusal evidence',
            'missing or ambiguous formatting remedies',
            'unknown or mixed reasons',
            'safety refusals',
            'affected-operation denials',
            'uncertain delivery',
            'changed action, recipient, scope, authority, non-prose fields, owner provenance, '
            'or choice identifiers',
        ):
            with self.subTest(case=case):
                self.assertIn(case, block)

    def test_contract_requires_canonical_exclusive_durable_consumption(self):
        for requirement in (
            'Use one canonical durable record binding the original refused call and unchanged '
            'action, recipient, and scope.',
            'Require one verified sender with proven exclusive custody before consuming the attempt.',
            'Verify absence of overlapping senders; require explicit custody transfer during replacement.',
            'An existing atomic claim qualifies only when its guarantees cover this same canonical record.',
            'A read followed by an append alone supplies zero exclusivity proof.',
            'Durably consume the single attempt and confirm persistence before sending.',
            'Recovery, replacement, and new sessions use the same record and retain its consumed state.',
            'A failed corrected send stays consumed.',
            'Never use alternate delivery or substitute execution for a still-effective refusal.',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.refusals)
        block = self.refusals.partition('For resend consumption, block ')[2].partition('.')[0]
        for case in (
            'unknown custody',
            'overlapping senders',
            'replacement without explicit custody transfer',
            'uncertain persistence',
            'absent or uncertain records',
            'consumed attempts',
        ):
            with self.subTest(case=case):
                self.assertIn(case, block)

    def test_contract_keeps_formatting_source_delivery_prospective(self):
        self.assertIn('Prospective source delivery supplies zero runtime-adoption '
                      'or affected-retry authority.', self.refusals)
        self.assertIn('Preserve existing loaded-session restrictions and affected-session holds.',
                      self.refusals)
        self.assertIn('Recheck current version, status, and answer provenance before the resend.',
                      self.refusals)
        self.assertIn('Preserve actual owner Input event delivery and all answer-verification '
                      'steps below.', self.owner)
        self.assertIn('Only the CoC publishes canonical owner decisions and results '
                      'in CoC workspace Inputs.', self.owner)
        self.assertIn('Never use BetterCoding `send_workspace_message`, `run_session_prompt`, '
                      'or simulated user input for peer coordination, including fallback delivery.',
                      self.owner)
