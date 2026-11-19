"""Pin the Markdown instructions drivers consume; never simulate or replay dispatch."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / 'plugins/ship/skills/ship/references/owner-decisions.md'
LINK = '(../skills/ship/references/owner-decisions.md#loaded-instructions-and-refusals)'


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
                self.assertIn('Apply [Loaded instructions and refusals]' + LINK
                              + ', including its retry rule, its coordination text remedy and its safety blocks.', driver)
                self.assertIn('When a writer or reviewer asks for permission to run a refused command, '
                              'grant it or run the command yourself when you consider it appropriate.', driver)
                self.assertIn('Record the grant or the run in the lane state file; '
                              'ask your chief when the command is outside your authority.', driver)
        for name in ('plugins/ship/skills/ship/SKILL.md',
                     'plugins/ship/skills/ship/references/pipeline.md'):
            with self.subTest(consumer=name):
                self.assertIn('[Loaded instructions and refusals]', (ROOT / name).read_text())

    def test_retry_rule_permits_a_rule_meeting_form_and_asking_the_superior(self):
        for requirement in (
            'Retry rule: after a hook or permission refusal, an agent may retry in another form '
            'when the refusal reason is fixed or the new form meets the rule the refusal names.',
            'An agent may always ask its superior for permission to run the refused command.',
            'A writer asks its driver, a reviewer asks its coordinator, a driver asks its chief, and a chief asks the CoC.',
            'The CoC asks the owner only for product, billing, security policy or big architecture.',
            'The superior may grant the request, or run the command itself when it considers that appropriate.',
            'The superior records the grant or the run in the lane state file.',
            'Never ask the owner to paste or run a command.',
            'A version, restart, or new session alone lifts nothing.',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.refusals)

    def test_safety_blocks_stay(self):
        for requirement in (
            'Safety blocks: keep destructive actions, secrets, production data writes, flag flips, deploys, '
            'customer-data deletion, protected paths, and approval, GO, installation, and publication holds '
            'blocked as their own rules say.',
            'A retry in another form never bypasses a safety block.',
            'A superior grants or runs a command only within its own authority, and its own hooks and permissions apply.',
            'Protected mutation-row edits use only the [lane-owned row route](../SKILL.md#lane-owned-row-route) and its tools.',
            'Push, merge and protected-write refusals stay final; a retry in another form never bypasses them.',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.refusals)

    def test_contract_requires_exact_gate_remedy_and_loaded_agent_scope(self):
        self.assertIn(
            "Coordination gate: for the driver's `Agent` dispatch, resend when the denial explicitly "
            'identifies `Coordination gate error` and an exact text remedy.', self.refusals)
        self.assertIn('Require unambiguous gate identity and remedy and the applicable loaded contract; '
                      'the denial date alone never determines eligibility.', self.refusals)
        self.assertIn('Apply only that remedy; preserve the action, recipient, scope, authority, '
                      'and exact owner-provenance checks.', self.refusals)
        self.assertIn('Recheck current version, status, and answer provenance before the resend.', self.refusals)

    def test_contract_preserves_all_authority_and_owner_verification_checks(self):
        for requirement in (
            'An explicit owner refusal blocks all routes for that edit until '
            'applicable owner authority resolves it.',
            'Apply your own loaded definition; a checkout, cache entry, or version '
            'supplies zero additional authority.',
            'Prospective source changes and their delivery supply zero runtime-adoption, '
            'affected-retry, or action authority.',
            'Preserve existing loaded-session restrictions and affected-session holds.',
            'Repairing missing verification evidence resolves only that evidence gap; '
            'it cannot override a binding prohibition or tool denial.',
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

    def test_hook_refusal_keeps_work_pending(self):
        self.assertIn('A hook refusal never drops work: keep the task pending, then retry in a fixed form or ask the superior.',
                      self.refusals)
        ship = (ROOT / 'plugins/ship/skills/ship/SKILL.md').read_text()
        self.assertIn('Pause a refused tool step and keep the work pending.', ship)
        self.assertIn('Retry under the refusal rule or ask your superior.', ship)

    def test_message_warnings_and_receipt_refusals_keep_existing_authority(self):
        for requirement in (
            'Message-format rule: `text_lint.py` warns about prose formatting and lets the call proceed.',
            'Examples include glued words, sentence or word limits, and a missing `Facts` heading.',
            'Preserve the action, recipient, scope, authority, non-prose fields, owner provenance, and choice identifiers.',
            'A missing `Facts` heading organizes supported existing facts only; '
            'invent zero facts, evidence, approval, or authority.',
            'Keep the Input classification requirement and receipt validation in force.',
            'After a receipt citation refusal, remove the receipt marker and resend with the same action, recipient and scope.',
            'Only the hook writes receipt state; agents never read, write or reset the receipt store.',
            'Keep receipt markers out of `Agent` and `Task` prompts.',
            'For a content refusal, fix the content to meet the named rule or ask the superior for permission within existing authority.',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.refusals)
        self.assertIn('preserve existing published choice IDs during retries.', self.owner)

    def test_contract_drops_final_and_once_only_wording(self):
        for removed in ('remains final', 'stays refused', 'once-only', 'in every form',
                        'superseded-ruling free', 'contract-gap refusal', 'ends the attempt',
                        'substitute actor', 'substitute an executor', 'no resend', 'final corrected brief'):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, self.refusals)
        for name in ('driver.md', 'driver--sol.md', 'writer--sol.md', 'writer--sonnet.md', 'writer--fable52.md'):
            text = (ROOT / 'plugins/ship/agents' / name).read_text()
            for removed in ('once-only', 'remains final', 'substitute an executor', 'Never replay a denied command'):
                with self.subTest(carrier=name, removed=removed):
                    self.assertNotIn(removed, text)

    def test_contract_keeps_the_refusal_rule_line_budget(self):
        self.assertLessEqual(len([line for line in self.refusals.splitlines() if line.strip()]), 8)

    def test_contract_keeps_formatting_source_delivery_prospective(self):
        self.assertIn('Preserve actual owner Input event delivery and all answer-verification '
                      'steps below.', self.owner)
        self.assertIn('Only the CoC publishes canonical owner decisions and results '
                      'in CoC workspace Inputs.', self.owner)
        self.assertIn('Never use BetterCoding `send_workspace_message`, `run_session_prompt`, '
                      'or simulated user input for peer coordination, including fallback delivery.',
                      self.owner)


if __name__ == '__main__':
    unittest.main()
