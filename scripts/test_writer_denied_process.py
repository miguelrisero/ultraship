"""Writer agent files forbid obtaining a denied result through another process."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WRITERS = ('writer--sol.md', 'writer--sonnet.md', 'writer--fable52.md')
RULE = (
    'After a hook or permission denial, run no process that obtains the denied result another way.\n'
    'Script files, other interpreters, module flags and wrapper commands count.\n'
    'Return the denial to the driver and stop that step.\n'
)
ANCHOR = 'Never replay a denied command, equivalent operation or substitute actor while its refusal remains effective.\n'


class WriterDeniedProcessTests(unittest.TestCase):
    def test_every_writer_carries_the_denied_process_rule_after_the_replay_rule(self):
        for name in WRITERS:
            with self.subTest(writer=name):
                text = (ROOT / 'plugins/ship/agents' / name).read_text(encoding='utf-8')
                self.assertIn(ANCHOR + RULE, text)


if __name__ == '__main__':
    unittest.main()
