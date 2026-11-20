"""Writer contract files let another process retry a denied step only when it meets the named rule."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WRITER_FILES = (
    'plugins/ship/agents/writer--sol.md',
    'plugins/ship/agents/writer--sonnet.md',
    'plugins/ship/agents/writer--fable52.md',
)
REFERENCE_FILE = 'plugins/ship/skills/ship/references/owner-decisions.md'
HEADING = 'Loaded instructions and refusals\n'
CHECKS_SENTENCE = 'Checks that the brief names stay permitted when the hook admits them.'
WRITER_SENTENCES = (
    'After a hook or permission refusal, retry in another form only when the refusal reason is fixed or the new form meets the rule the refusal names.',
    'A script file, another interpreter, a module flag or a wrapper command is another form; it must meet that rule too.',
    'Keep the work pending after a hook refusal.',
    'Ask the driver for permission to run the refused command at any time.',
    'The driver may grant it or run the command within its authority.',
    CHECKS_SENTENCE,
)
REFERENCE_SENTENCES = (
    'Retry rule: after a hook or permission refusal, an agent may retry in another form when the refusal reason is fixed or the new form meets the rule the refusal names.',
    'A script file, another interpreter, a module flag or a wrapper command is another form; it must meet that rule too.',
    'An agent may always ask its superior for permission to run the refused command.',
    'A writer asks its driver, a reviewer asks its coordinator, a driver asks its chief, and a chief asks the CoC.',
    'The superior may grant the request, or run the command itself when it considers that appropriate.',
    'The superior records the grant or the run in the lane state file.',
    'Never ask the owner to paste or run a command.',
    'A retry in another form never bypasses a safety block.',
    CHECKS_SENTENCE,
)
def refusals_section(text):
    start = text.index(HEADING) + len(HEADING)
    end = text.find('\n#', start)
    return text[start:] if end == -1 else text[start:end]


class WriterDeniedProcessTests(unittest.TestCase):
    def check(self, names, sentences):
        for name in names:
            with self.subTest(file=name):
                section = refusals_section((ROOT / name).read_text(encoding='utf-8'))
                for sentence in sentences:
                    self.assertIn(sentence, section)

    def test_writer_files_carry_the_retry_rule_in_the_refusals_section(self):
        self.check(WRITER_FILES, WRITER_SENTENCES)

    def test_shared_reference_carries_the_retry_and_superior_rule(self):
        self.check((REFERENCE_FILE,), REFERENCE_SENTENCES)

    def test_every_agent_copy_carries_the_refusal_rule(self):
        rule = (
            'A refusal never ends the work. '
            'After a refusal, find the cause and retry in a compliant form, or ask your superior how to proceed. '
            'A writer asks its driver, a driver asks its chief, and a chief asks the CoC. '
            'The ask never blocks your other work. '
            'Only the CoC decides whether an owner-only item becomes an owner Input. '
            'With a CoC, decisions reach the owner through the CoC. In a standalone run, an owner-only item becomes a standalone Input. '
            'No agent, the CoC included, sends the owner a refusal, hook or tooling question. '
            'Product, billing, security policy and big architecture decisions still reach the owner through the CoC. '
            'The refused action keeps its gate: push, merge, protected writes, secrets, production and owner-only items '
            'still need a compliant form or the authority they lacked. '
            'A compliant retry never bypasses a hook, uses a different credential, or edits a guard.'
        )
        agents = sorted((ROOT / 'plugins/ship/agents').glob('*.md'))
        for path in (*agents, ROOT / REFERENCE_FILE, ROOT / 'plugins/ship/skills/ship/SKILL.md',
                     ROOT / 'plugins/chief/skills/run/SKILL.md'):
            name = path.relative_to(ROOT).as_posix()
            with self.subTest(file=name):
                text = path.read_text(encoding='utf-8')
                if name in (*WRITER_FILES, REFERENCE_FILE):
                    text = refusals_section(text)
                joined = ' '.join(text.splitlines())
                self.assertIn(rule, joined)
                if path in agents and not path.name.startswith(('writer--', 'driver')):
                    self.assertIn('Ask your coordinator for permission at any time. ' + rule, joined)

    def test_decision_defect_rule_limits_refusal_resolution(self):
        eligibility = (
            'The sole stated cause must be a defect in a CoC decision.',
            'The refusal must come before the refused action writes anything, with zero bytes written and zero commits.',
            'For protected writes, this rule covers only row re-anchor tool attempts.',
            "It covers your refusal before the run and the tool's refusal during the run.",
            'The defect is a wrong SHA, a wrong path, a stale head, a missing field, or an internal contradiction.',
            'A digest, extent or other binding without an exact definition in the decision counts as a missing field or an internal contradiction.',
        )
        resolution = (
            'Only a corrected CoC decision with a new SHA256 can resolve that refusal for that cause.',
            'Require the corrected decision to quote the refusal verbatim, name the defective decision by path and SHA256, '
            'and name the defect it corrects.',
            'A corrected decision grants nothing beyond what the defective decision grants and changes only the defective fields.',
            'Wait for the CoC to freeze the corrected decision.',
            'Before the next attempt, verify the corrected decision in full and compare its actor, action, target and scope '
            "with the defective decision's grant.",
            'Keep the refusal pending when that comparison is inconclusive or shows a wider grant.',
            'Then the refused row-tool attempt counts as zero runs, and the writer gets one new attempt under the corrected decision.',
            'The driver re-dispatches that attempt with a fresh admission record.',
            'Follow every other route requirement, including the independent review.',
            'This rule lifts no hook, permission or owner refusal, and no security, secret or production gate.',
            'It lifts no refusal of a push or a merge, no tool refusal with any other cause, and no protected write that already ran.',
            "Follow the retry rule for hook and permission refusals, and the tool's own rule for a tool refusal with any other cause.",
        )
        reference = ' '.join((
            "Decision-defect rule: it applies only to an agent's own refusal or a refusal from the row re-anchor tool.",
            *eligibility,
            'Quote the refusal and the defect to your superior, who relays them up the superior chain to the CoC.',
            *resolution,
        ))
        writer = '\n'.join((
            'This [decision-defect rule](../skills/ship/references/owner-decisions.md#loaded-instructions-and-refusals) '
            'applies only to your own refusal or a refusal from the row re-anchor tool.',
            *eligibility,
            'Quote the refusal and the defect to your driver.',
            *resolution,
        ))
        self.check((REFERENCE_FILE,), (f'\n{reference}\n',))
        self.check(WRITER_FILES, (f'\n{writer}\n',))

    def test_scope_refusal_rule_limits_refusal_resolution(self):
        eligible = "or an earlier writer's refusal on the same lane, PR and edit."
        cause = 'The sole stated cause must be that a CoC decision asks for an action the writer contract forbids.'
        resolution = (
            'Only a new CoC decision with a new SHA256 can resolve that refusal for that cause.',
            'Require the new decision to quote the refusal verbatim.',
            'Require it to name the earlier decision by path and SHA256.',
            "Require it to name the same lane, PR and edit for an earlier writer's refusal.",
            'Require it to remove the cause so that every action it grants fits the writer contract.',
            'The new decision grants nothing the writer contract forbids, '
            'and widens no read scope, protected row authority or other guard.',
            'Each action it grants still needs its own route and the authority that route names; '
            'this rule grants no authority.',
            'Never run the refused action under either decision.',
            'Verify the new decision in full before the next attempt.',
            'Compare each action it grants with the writer contract and its route before the next attempt.',
            'Keep the refusal pending when that comparison is inconclusive or finds an action the writer contract forbids.',
            'Follow every other route requirement.',
            'This rule lifts no hook, permission, tool or owner refusal, and no security, secret or production gate.',
            'It lifts no refusal of a push or a merge, and an explicit owner refusal still needs applicable owner authority.',
        )
        reference = ' '.join((
            f"Scope-refusal rule: it applies only to an agent's own refusal {eligible}",
            cause,
            'Quote the refusal and its cause to your superior, who relays them up the superior chain to the CoC.',
            *resolution,
        ))
        writer = '\n'.join((
            'This [scope-refusal rule](../skills/ship/references/owner-decisions.md#loaded-instructions-and-refusals) '
            f'applies only to your own refusal {eligible}',
            cause,
            'Quote the refusal and its cause to your driver.',
            *resolution,
        ))
        self.check((REFERENCE_FILE,), (f'\n{reference}\n',))
        self.check(WRITER_FILES, (f'\n{writer}\n',))

    def test_drivers_relay_decision_defect_refusals_and_corrected_decisions(self):
        for name in ('driver.md', 'driver--sol.md'):
            with self.subTest(file=name):
                driver = (ROOT / 'plugins/ship/agents' / name).read_text(encoding='utf-8')
                self.assertIn(
                    "\nRelay a writer's decision-defect refusal and its defect to your chief, "
                    'and the corrected decision to the writer.\n'
                    'Never run the refused step under the defective decision.\n',
                    driver,
                )

    def test_chief_relays_decision_defect_refusals_and_corrected_decisions(self):
        chief = (ROOT / 'plugins/chief/skills/run/SKILL.md').read_text(encoding='utf-8')
        self.assertIn(
            "\nRelay the lane's quoted refusal and defect to the CoC and the corrected decision to the lane "
            "under ship's decision-defect rule.\n",
            chief,
        )

    def test_retired_refusal_accounting_does_not_return(self):
        for name in (*WRITER_FILES, REFERENCE_FILE):
            text = (ROOT / name).read_text(encoding='utf-8')
            for phrase in ('superseded-ruling free', 'attempt record', 'contract-gap refusal'):
                with self.subTest(file=name, phrase=phrase):
                    self.assertNotIn(phrase, text)


if __name__ == '__main__':
    unittest.main()
