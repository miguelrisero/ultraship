"""Every guard copy allows branch-only bounds without an owner question."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GuardExceptionTests(unittest.TestCase):
    def test_all_guard_copies_allow_branch_only_bounds(self):
        copies = {}
        for path in (ROOT / 'plugins').rglob('*'):
            if path.is_file():
                try:
                    text = path.read_text()
                except UnicodeDecodeError:
                    continue
                if 'Never widen, raise, or relax' in text:
                    copies[path.relative_to(ROOT).as_posix()] = ' '.join(text.split())
        self.assertTrue({
            'plugins/ship/agents/writer--sol.md',
            'plugins/ship/agents/writer--sonnet.md',
            'plugins/ship/skills/ship/SKILL.md',
            'plugins/chief/skills/run/SKILL.md',
        }.issubset(copies))
        for path, text in copies.items():
            with self.subTest(path=path):
                for phrase in (
                    'This rule covers limits that exist on origin/main',
                    'Input 6e43dda9-a1b8-4b0e-a8c8-f3525a67a5e9',
                    'without an owner question',
                    'record the reason and the main SHA in the PR body',
                    'git fetch origin main',
                    'A missing path on main is not enough evidence',
                ):
                    self.assertIn(phrase, text)
                self.assertNotIn('the brief says so', text)
