"""Writer contract files forbid doing a denied step through another process."""
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
    'Except under the owner-decisions method-only rule: use no other process to do a step that a hook or permission denied.',
    'Script files, other interpreters, module flags and wrapper commands are other processes.',
    'Tell the driver about the denial and stop that step.',
    CHECKS_SENTENCE,
)
REFERENCE_SENTENCES = (
    'Except under the ordinary-file method-only rule below: a writer uses no other process to do a step that a hook or permission denied.',
    'Script files, other interpreters, module flags and wrapper commands are other processes.',
    'The writer tells the driver about the denial and stops that step.',
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

    def test_writer_files_carry_the_denied_process_rule_in_the_refusals_section(self):
        self.check(WRITER_FILES, WRITER_SENTENCES)

    def test_shared_reference_scopes_the_rule_to_writers_in_the_refusals_section(self):
        self.check((REFERENCE_FILE,), REFERENCE_SENTENCES)


if __name__ == '__main__':
    unittest.main()
