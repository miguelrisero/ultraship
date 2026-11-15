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
        self.assertIn('Recovery, replacement, and new sessions use the same record '
                      'and retain its consumed state; absent records, consumed attempts, '
                      'a failed second attempt, and a recorded final corrected brief stay blocked across recovery, '
                      'except one eligible final corrected brief not yet recorded.', self.refusals)
        self.assertIn('A failed corrected send stays consumed.', self.refusals)
        block = self.refusals.partition('For resend consumption, block ')[2].partition('.')[0]
        for case in ('absent or uncertain records', 'consumed attempts'):
            with self.subTest(case=case):
                self.assertIn(case, block)
        self.assertIn('A version, restart, or new session alone lifts nothing; '
                      'never reset an attempt or substitute an executor '
                      'to bypass a still-effective refusal.', self.refusals)

    def test_contract_preserves_all_authority_and_owner_verification_checks(self):
        for requirement in (
            'An explicit owner refusal blocks all routes for that edit until '
            'applicable owner authority resolves it.',
            'Apply your own loaded definition; a checkout, cache entry, or version '
            'supplies zero additional authority.',
            'Prospective source changes and their delivery supply zero runtime-adoption, '
            'affected-retry, or action authority.',
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
            'The method-only rule applies only to ordinary files and to the granted protected-row re-anchor below; '
            'it never covers any other protected-row operation.',
            'A fresh writer applies the already-approved edit text exactly once with native Edit; '
            'the commit stays a separate step.',
            'The method ban and every content, scope, protected-access and publication denial stay final.',
            'Consume that single attempt on the canonical durable record before the edit; '
            'a failed attempt stays consumed.',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.refusals)

    def test_protected_row_method_only_retry_admits_one_native_edit_on_the_named_row(self):
        for requirement in (
            "When that re-anchor is on the explicit-pair or lane-derived route that its verified owner grant covers, "
            "one fresh writer applies that route's approved edit once with native Edit and `replace_all=false`.",
            'The brief names the CI-named row file and the unique row ID.',
            "The edit changes only that row's paired `old` and `new` fields with the identical mutant edit: "
            "the CoC-approved pair on the explicit-pair route, or the subject's new source text on the lane-derived route.",
            "Require that route's independent not-weaker review before the push.",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.refusals)

    def test_protected_row_method_only_retry_refuses_wider_or_repeated_edits(self):
        refusal = self.refusals.split(
            'Refuse a native Edit outside the named file, row or paired fields', 1
        )[1].split('.', 1)[0]
        for case in ('a second attempt', 'a denial of the native Edit itself',
                     'every content, scope or protected-access denial'):
            with self.subTest(case=case):
                self.assertIn(case, refusal)

    def test_reviewer_form_admits_one_fresh_reviewer_for_the_same_frozen_subject(self):
        for requirement in (
            'Reviewer form: the fresh-brief and final corrected brief routes also admit one fresh reviewer '
            'as their one new recipient, of the same reviewer agent type, for the same frozen subject SHA, '
            'review step and scope.',
            'That reviewer gets the same brief content, changed only in format, under the same receipt, '
            'consumed-attempt record, exclusive custody and run-board rules.',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.refusals)

    def test_reviewer_form_refuses_non_formatting_refusals_and_a_second_reviewer(self):
        self.assertIn(
            'Refuse the reviewer form after any non-formatting, mixed or ambiguous refusal, '
            'and refuse a second fresh reviewer for the same original call.', self.refusals)

    def test_receiptless_form_admits_one_fresh_brief_and_keeps_its_refusal_final(self):
        for requirement in (
            "Receiptless form: when the loaded hook version's `text_lint.py` writes no receipt "
            '(ship 1.10.37 to 1.10.47), the coordinator may use the fresh-brief route once if every finding '
            'in the recorded refusal text matches a known `text_lint.py` formatting message.',
            'Record the full refusal text and the hook version on the run board in place of the receipt id; '
            'on this form only, they stand in for the receipt.',
            'A refusal of that fresh brief is final; the receiptless form admits no resend and no final corrected brief.',
            'A hook version that writes receipts still requires its receipt.',
            'No form resets a consumed attempt.',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.refusals)

    def test_lane_derived_route_names_the_granted_re_anchor_exception(self):
        for name in (
            'plugins/ship/agents/writer--sol.md', 'plugins/ship/agents/writer--sonnet.md',
            'plugins/ship/agents/writer--fable52.md', 'plugins/ship/agents/driver.md',
            'plugins/ship/agents/driver--sol.md', 'plugins/ship/skills/ship/SKILL.md',
        ):
            text = (ROOT / name).read_text()
            _, heading, after = text.partition('#### Lane-derived route\n')
            route = re.split(r'^ {0,3}#{1,6}(?:[ \t]+|$)', after,
                             maxsplit=1, flags=re.MULTILINE)[0]
            with self.subTest(path=name):
                self.assertTrue(heading)
                self.assertIn(
                    "After a hook denies only the method of this route's row edit, apply the owner-decisions "
                    'granted protected-row re-anchor; it is the one exception to the alternate-form sentence below.',
                    route,
                )

    def test_contract_scopes_message_format_refusals_and_fresh_instructions(self):
        for requirement in (
            'Examples include glued words, sentence or word limits, and a missing `Facts` heading.',
            'The sender rewrites the same content once in short plain sentences.',
            'Put long identifiers in backticks or in a file and send its path.',
            'After a message-format refusal, a coordinator may give a fresh writer a new brief '
            'for the same approved scope.',
            'This fresh brief is a new instruction, not a resend.',
            'It records the receipt id on the run board; the hook refuses a receipt marker in an `Agent` or `Task` prompt.',
            'Preserve the consumed-attempt record across fresh briefs.',
            'Only for the fresh-brief route, permit a new writer recipient and dispatch action '
            'despite the unchanged-identity requirements below.',
            'Bind the shared attempt to the original refused call and its original action, recipient, '
            'and scope; record the new writer and dispatch separately.',
            'Preserve approved scope, authority, provenance, choice identifiers, exclusive custody, '
            'and all unrelated non-prose fields.',
            'Both the wording rewrite and fresh brief require matching formatting findings, '
            'exact remedies, original-call evidence, and canonical exclusive custody below.',
            "Share that original call's single attempt across both routes, the rewrite, and the fresh brief; "
            'durably consume it before either action.',
            "Deny every other action on a consumed attempt; that brief's refusal and every content, safety, "
            'protected-path, non-formatting hook, mixed, or ambiguous denial stay final.',
            'Keep actors outside that lane refused, hook-denied commands refused in every form, '
            'and every content, protected-path, and publication denial final.',
            'Except under the ordinary-file method-only rule or the fresh message-format instruction:',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.refusals)

    def test_contract_allows_one_final_corrected_brief_after_a_consumed_format_refusal(self):
        allowance = (
            'After the consumed rewrite or fresh brief draws another formatting-only refusal, '
            'the coordinator may dispatch one final corrected brief to one fresh writer for the same slice.'
        )
        self.assertIn(allowance, self.refusals)
        self.assertIn(
            "That brief keeps the same action, scope, authority, and content, passes the refused call's "
            '`text_lint.py` check, and is recorded as consumed on the same canonical run-board record before sending.',
            self.refusals,
        )

    def test_contract_keeps_the_refusal_rule_line_budget(self):
        self.assertLessEqual(len([line for line in self.refusals.splitlines() if line.strip()]), 8)

    def test_contract_binds_formatting_resends_to_known_findings(self):
        for requirement in (
            'For `Agent` and `SendMessage`, every returned finding matching a known `text_lint.py` '
            'formatting message suffices to establish a formatting-only refusal.',
            'Require every returned finding to match a known `text_lint.py` formatting message.',
            'Require the applicable loaded contract.',
            'A formatting-only resend after a `text_lint.py` refusal also requires the hook receipt that refusal names.',
            'Cite it as `<!-- ultraship-receipt:ID -->` in the resent prose.',
            "The hook verifies the receipt's session, tool, recipient and non-prose fields, then consumes it once.",
            'Refusal prefix text without a verified receipt supplies zero producer evidence.',
            'Only the hook writes receipt state; agents never read, write or reset the receipt store.',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.refusals)
        for name in ('driver.md', 'driver--sol.md'):
            with self.subTest(driver=name):
                driver = (ROOT / 'plugins/ship/agents' / name).read_text()
                self.assertIn('Apply its once-only formatting contract to `Agent` and `SendMessage` '
                              'when every returned finding matches a known `text_lint.py` formatting message '
                              'and, for a `text_lint.py` refusal, a resend cites its hook receipt '
                              'and a fresh brief records it on the run board.', driver)

    def test_contract_requires_known_formatting_findings_and_blocks_unknown_evidence(self):
        for removed in ('authenticated', 'producer attribution', 'producer authentication', 'by elimination'):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, self.refusals)
        self.assertIn(
            'Require every returned finding to match a known `text_lint.py` formatting message.',
            self.refusals,
            'Every returned finding must match a known text_lint formatting message',
        )
        block = self.refusals.partition('For formatting-only resends, block ')[2].partition('.')[0]
        for case in ('unmatched findings', 'absent, invalid, expired or consumed hook receipts'):
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
            'incomplete original-call evidence',
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
            'Recovery, replacement, and new sessions use the same record and retain its consumed state;',
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
        self.assertIn('Prospective source changes and their delivery supply zero runtime-adoption, '
                      'affected-retry, or action authority.', self.refusals)
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
