"""Every guard copy allows branch-only bounds, council-approved and Chief-checked test edits."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUARD = 'Never widen, raise, or relax'
EXCEPTIONS = (
    'This rule covers limits that exist on origin/main. Exception: a limit, cap, timeout, budget, '
    'or bound that only this PR branch added is the lane\'s design choice (owner rule, Input '
    '6e43dda9-a1b8-4b0e-a8c8-f3525a67a5e9). Run `git fetch origin main` first and record the '
    '`origin/main` SHA; when the fetch fails, the exception does not apply. Compare the behavior '
    'the bound constrains, not its path or name: `git grep` main\'s whole tree and read the branch '
    'diff (`git diff origin/main...HEAD`) for the same invariant, including replacements, '
    'duplicates, validators, test baselines, fixtures, and goldens. A missing path on main is not '
    'enough evidence. When main has no such bound, change or remove it without an owner question, '
    'and record the reason and the main SHA in the PR body. Every bound already on main keeps '
    'this rule, also when the branch moves, renames, replaces, or changes it. Exception: a test, '
    'fixture, mutation row, census or register edit is allowed without an owner question after '
    'one council round (no Fable or cf-* models) agrees that the guard keeps its guarantee (owner '
    'grant 2026-10-26: "ok I give you from now onwards full power to change tests, no need to '
    'check with me, just do one council round to analyze it makes sense and is appropiate, and do '
    'it."). Weakening a test to hide a real regression stays forbidden. Record the council '
    'verdict and the owner words in the PR body. Exception: no step waits for a human to apply '
    'an edit. When the executor is certain and its Chief or the CoC checked the change, that '
    'check replaces the council round, and an agent applies it (owner order 2026-10-30: "if '
    'agent is certain that its ok and he checked with his CoC or Chief ALL GOOD remove that '
    'blocker everywhere"). Record that check in the PR body.'
)


def guard_blocks():
    """Map each plugin file to the normalized paragraph or fenced block that holds the guard."""
    blocks = {}
    for path in (ROOT / 'plugins').rglob('*'):
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        for chunk in text.split('\n\n'):
            if GUARD in chunk:
                blocks[path.relative_to(ROOT).as_posix()] = ' '.join(chunk.replace('```', ' ').split())
    return blocks


class GuardExceptionTests(unittest.TestCase):
    def test_every_guard_block_ends_with_both_exceptions(self):
        blocks = guard_blocks()
        self.assertTrue({
            'plugins/ship/agents/writer--sol.md',
            'plugins/ship/agents/writer--sonnet.md',
            'plugins/ship/skills/ship/SKILL.md',
            'plugins/chief/skills/run/SKILL.md',
        }.issubset(blocks))
        for path, block in blocks.items():
            with self.subTest(path=path):
                self.assertTrue(block.endswith(EXCEPTIONS), block[-300:])


if __name__ == '__main__':
    unittest.main()
