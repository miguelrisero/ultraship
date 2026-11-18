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
SUPERSEDED_RULING_SENTENCES = (
    'A superseded-ruling free is the one exception to every rule that keeps a used protected-row attempt, or its record, consumed.',
    'Only a fresh CoC row decision file with a new SHA256 grants it, for exactly one further attempt on one named row.',
    'That file names the repository, PR, row file and row ID, and quotes each earlier refusal on that row verbatim.',
    'It records that every earlier attempt on that row made zero protected reads, zero edits and zero commits.',
    'It records that the first refusal named only a chief or CoC ruling, never the row content.',
    'It records that each later refusal named only that first refusal or the attempt it used.',
    'It supersedes that ruling by name, and it resolves the quoted refusals for that row only.',
    'Refuse the free when the file lacks any of these records.',
    'A row gets at most one free, whatever the decision file or head SHA; refuse a second free.',
    "Record the free on the row's attempt record, with the decision file and its SHA256, before the freed attempt starts.",
    'Content refusals, method bans, `REFUSED` tool results, and every hook, permission or tool denial stay final; no decision frees their attempts.',
    'The freed attempt keeps every other route requirement, authority, independent review and publication hold.',
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

    def test_writers_carry_the_superseded_ruling_rule_once(self):
        block = '\n'.join(SUPERSEDED_RULING_SENTENCES)
        for name in WRITER_FILES:
            with self.subTest(file=name):
                section = refusals_section((ROOT / name).read_text(encoding='utf-8'))
                self.assertEqual(section.count(block), 1)

    def test_reference_carries_the_superseded_ruling_rule_once(self):
        paragraph = ' '.join(SUPERSEDED_RULING_SENTENCES)
        section = refusals_section((ROOT / REFERENCE_FILE).read_text(encoding='utf-8'))
        self.assertEqual(section.count(paragraph), 1)

    def test_one_free_frees_exactly_one_further_attempt(self):
        self.check((*WRITER_FILES, REFERENCE_FILE), tuple(SUPERSEDED_RULING_SENTENCES[i] for i in (0, 1, 9)))

    def test_second_free_for_the_same_row_refuses(self):
        self.check((*WRITER_FILES, REFERENCE_FILE), (SUPERSEDED_RULING_SENTENCES[8],))

    def test_free_without_the_zero_read_record_refuses(self):
        self.check((*WRITER_FILES, REFERENCE_FILE), tuple(SUPERSEDED_RULING_SENTENCES[i] for i in (3, 7)))

    def test_content_refusal_stays_final(self):
        self.check((*WRITER_FILES, REFERENCE_FILE), tuple(SUPERSEDED_RULING_SENTENCES[i] for i in (4, 10)))


if __name__ == '__main__':
    unittest.main()
