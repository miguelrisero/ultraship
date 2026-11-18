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
    'After any other hook or permission refusal, retry in another form only when the refusal reason is fixed or the new form meets the rule the refusal names.',
    'A script file, another interpreter, a module flag or a wrapper command is another form; it must meet that rule too.',
    'Otherwise tell the driver about the denial and ask for permission to run the command; the driver may grant it or run the command itself.',
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


if __name__ == '__main__':
    unittest.main()
