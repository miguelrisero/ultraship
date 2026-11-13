"""Writer contract files forbid obtaining a denied result through another process."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    'plugins/ship/agents/writer--sol.md',
    'plugins/ship/agents/writer--sonnet.md',
    'plugins/ship/agents/writer--fable52.md',
    'plugins/ship/skills/ship/references/owner-decisions.md',
)
HEADING = 'Loaded instructions and refusals\n'
SENTENCES = (
    'Except under the owner-decisions method-only rule: after a hook or permission denial, get the denied result through no other process.',
    'This includes script files, other interpreters, module flags and wrapper commands.',
    'Report the denial to the driver and stop the denied step.',
    'Checks that the brief names stay permitted when the hook admits them.',
)


def refusals_section(text):
    start = text.index(HEADING) + len(HEADING)
    end = text.find('\n#', start)
    return text[start:] if end == -1 else text[start:end]


class WriterDeniedProcessTests(unittest.TestCase):
    def test_general_refusals_section_carries_the_denied_process_rule(self):
        for name in FILES:
            with self.subTest(file=name):
                section = refusals_section((ROOT / name).read_text(encoding='utf-8'))
                for sentence in SENTENCES:
                    self.assertIn(sentence, section)


if __name__ == '__main__':
    unittest.main()
