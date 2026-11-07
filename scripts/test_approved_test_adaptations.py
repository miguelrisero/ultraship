"""Static instruction contracts only; these checks do not execute agent behavior."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INPUT_ID = '32c223a4-6bd9-43d1-b049-19a3990d2379'
WORKSPACE_ID = 'b8fed386-cf11-40fe-b14f-425e6331ee41'
EVENT_ID = '1c2e4bf5-10c2-4cb2-9abc-ab86ba945fc8'


class ApprovedTestAdaptationsTests(unittest.TestCase):
    def test_writers_require_verified_authority_and_preserve_controls(self):
        for name in ('writer--sol.md', 'writer--sonnet.md'):
            text = (ROOT / 'plugins/ship/agents' / name).read_text()
            for phrase in (
                INPUT_ID, WORKSPACE_ID, EVENT_ID, 'get_input', 'owner_ui',
                'Outside the exceptions in the guard paragraph above, never make a test, pin, census, register, or bound edit on your own initiative.',
                'approved that exact edit and cites this owner rule',
                'Then apply the edit with no council round and no owner question.',
                'stop and report to the driver',
                '`answer_submitted`', 'choice `plugin_rule`',
                'Record the approver, the exact edit, and the Input ID in the PR body.',
                'Never loosen an assertion, widen a bound, or delete a check',
                'zero writer push authority',
                'Verify the owner event yourself when you have a `get_input` tool',
                'Verifier fallback: when you have no `get_input` tool, or the call fails with an auth or tool error, the driver or the CoC runs `get_input`',
                'the full Input UUID, workspace UUID, event id, event hash, `actor_kind`, choice id, and verifier name',
                'Check that the recorded Input UUID, workspace UUID, event id, and choice id equal the values quoted in this definition',
                'On a match, apply the exact approved edit.',
                'Fail closed: when your own `get_input` call returns an event that does not match, when `get_input` fails and the brief has no verified event record, when any recorded field is missing or differs from the values in this definition, or when the brief does not name the exact edit, make no edit; stop and report to the driver.',
            ):
                with self.subTest(path=name, phrase=phrase):
                    self.assertIn(phrase, text)
            for number, phrase in enumerate((
                'EXPECTED_GROUPS', 'census digest',
                'tests.race_helpers.wait_for_task', 'setup-only fixture',
            ), 1):
                with self.subTest(path=name, case=number):
                    self.assertTrue(any(
                        line.startswith(f'  {number}. ') and phrase in line
                        for line in text.splitlines()
                    ))

    def test_drivers_supply_owner_event_coordinates(self):
        for name in ('driver.md', 'driver--sol.md'):
            text = (ROOT / 'plugins/ship/agents' / name).read_text()
            for phrase in (
                INPUT_ID, WORKSPACE_ID, EVENT_ID, 'get_input',
                'Outside the exceptions in the writer guard paragraph, never ask a writer for a test, pin, census, register, or bound edit that the CoC or the topic Chief did not approve.',
                'the exact edit and file, the approver and the approval time, the owner rule citation, the Input ID, and the workspace ID',
                'Loosened assertions, widened bounds, and deleted checks stay forbidden.',
                'A writer without a `get_input` tool depends on your record',
                'the full Input UUID, workspace UUID, event id, event hash, `actor_kind`, choice id, and verifier name',
                'Record only values read from a `get_input` result.',
            ):
                with self.subTest(path=name, phrase=phrase):
                    self.assertIn(phrase, text)

    def test_skill_cites_owner_rule(self):
        text = (ROOT / 'plugins/ship/skills/ship/SKILL.md').read_text()
        self.assertIn(INPUT_ID, text)
        self.assertIn('the writer stops on any mismatch with its definition', text)


if __name__ == '__main__':
    unittest.main()
