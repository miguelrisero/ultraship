"""Pin draft PRs, mutation row updates, driver reports, auto-formatting, and hourly review fixes."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHIP = ROOT / 'plugins/ship/skills/ship'
WRITERS = {
    'plugins/ship/agents/writer--sol.md',
    'plugins/ship/agents/writer--sonnet.md',
    'plugins/ship/agents/writer--fable52.md',
}


class PRSpeedDefaultsTests(unittest.TestCase):
    def test_first_commit_opens_a_draft_pr(self):
        pipeline = (SHIP / 'references/pipeline.md').read_text()
        slices = pipeline.split('## 3. Slices', 1)[1].split('## 4.', 1)[0]
        self.assertIn('open a draft PR at once, so CI and review run while the lane builds', slices)

    def test_ready_follows_the_last_code_commit_and_row_update(self):
        pipeline = (SHIP / 'references/pipeline.md').read_text()
        push = pipeline.split('## 9. Push and PR', 1)[1].split('## 10.', 1)[0]
        self.assertIn('Mark it ready after the last code commit and any row update', push)
        self.assertNotIn('Open one PR at the first push', pipeline)

    def test_driver_reports_have_a_bounded_wake(self):
        skill = (SHIP / 'SKILL.md').read_text()
        self.assertIn('report to the parent every 15 minutes, day and night', skill)
        self.assertIn('`--max-seconds 900`', skill)

    def test_row_updates_preserve_proof_after_merge(self):
        skill = (SHIP / 'SKILL.md').read_text()
        proof = skill.split('## Proof after merge', 1)[1].split('## Boundaries', 1)[0]
        self.assertIn("Re-anchor the PR's own mutation rows once", proof)
        self.assertIn('Mutation proof runs after merge', proof)

    def test_review_fixes_have_an_hourly_batch(self):
        babysit = (ROOT / 'plugins/ship/skills/babysit/SKILL.md').read_text()
        self.assertIn('as one batch within 1 hour of the review', babysit)
        self.assertIn('Target 6 pushes or fewer per PR after it is marked ready', babysit)

    def test_all_writers_auto_format_before_every_commit(self):
        for path in sorted(WRITERS):
            with self.subTest(path=path):
                self.assertIn('Before every commit, auto-format the changed files',
                              (ROOT / path).read_text())

    def test_chief_replaces_a_silent_driver_on_the_same_lane(self):
        chief = (ROOT / 'plugins/chief/skills/run/SKILL.md').read_text()
        self.assertIn('Replace a PR driver that sends no report for 15 minutes', chief)
        self.assertIn('dispatch `ship:driver` on the same lane', chief)
        self.assertNotIn('The driver opens the PR before any proof work', chief)

    def test_each_rule_has_one_owning_place(self):
        owners = {
            'every 15 minutes': {'plugins/ship/skills/ship/SKILL.md'},
            'within 1 hour of the review': {'plugins/ship/skills/babysit/SKILL.md'},
            'open a draft PR': {'plugins/ship/skills/ship/references/pipeline.md'},
            "Re-anchor the PR's own mutation rows": {'plugins/ship/skills/ship/SKILL.md'},
            'auto-format the changed files': WRITERS,
            'no report for 15 minutes': {'plugins/chief/skills/run/SKILL.md'},
        }
        found = {phrase: set() for phrase in owners}
        for path in (ROOT / 'plugins').rglob('*.md'):
            text = path.read_text()
            for phrase in owners:
                if phrase in text:
                    found[phrase].add(path.relative_to(ROOT).as_posix())
        for phrase, paths in owners.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(paths, found[phrase])


if __name__ == '__main__':
    unittest.main()
