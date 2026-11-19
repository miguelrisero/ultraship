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

    def test_writers_and_shared_reference_keep_final_safety_refusals(self):
        self.check((*WRITER_FILES, REFERENCE_FILE), (
            'Push, merge and protected-write refusals stay final; a retry in another form never bypasses them.',
        ))

    def test_decision_defect_rule_limits_refusal_resolution(self):
        limits = (
            'Defects include a wrong SHA, a wrong path, a stale head, a missing field, or an internal contradiction.',
            'A corrected decision grants nothing beyond what the defective decision grants.',
            'This rule lifts no hook, permission, tool, owner, push, merge, or protected-write refusal.',
            'Follow the retry rule for hook, permission, and tool refusals.',
            'This rule lifts no security, secret, or production gate.',
        )
        resolution = (
            'Only a corrected CoC decision with a new SHA256 can resolve that refusal for that cause.',
            'Require the corrected decision to quote the refusal verbatim and name the defect it corrects.',
            'Verify the corrected decision in full before the next attempt.',
            'Follow every other route requirement.',
        )
        self.check((REFERENCE_FILE,), (' '.join((
            'Decision-defect rule: This rule applies only to an agent\'s own refusal '
            'whose sole stated cause is a defect in a CoC decision.',
            *limits,
            'Quote the refusal and the defect to your superior.',
            'Use the existing superior chain to reach the CoC: writer to driver, driver to chief, chief to CoC.',
            *resolution,
        )),))
        self.check(WRITER_FILES, ('\n'.join((
            'This [decision-defect rule](../skills/ship/references/owner-decisions.md#loaded-instructions-and-refusals) '
            'applies only to your own refusal whose sole stated cause is a defect in a CoC decision.',
            *limits,
            'Quote the refusal and the defect to your driver.',
            *resolution,
        )),))

    def test_chief_relays_decision_defect_refusals_and_corrected_decisions(self):
        chief = (ROOT / 'plugins/chief/skills/run/SKILL.md').read_text(encoding='utf-8')
        self.assertIn(
            'Grant a lane request, or run the refused command yourself, when you consider it appropriate; '
            'record the grant or the run in the lane state file.\n'
            "Relay the lane's quoted refusal and defect to the CoC and the corrected decision to the lane "
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
