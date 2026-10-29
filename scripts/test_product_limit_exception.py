"""Static instruction contracts; these checks do not execute agent behavior."""
from pathlib import Path
import unittest

from test_guard_exception import guard_blocks

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_LIMIT_EXCEPTION = (
    'Exception: an owner-requested product-limit change is a feature '
    '(owner rule, Input 2b7e497e-a794-4ab2-a62c-0f1748396967, owner_ui event 485, a_allow). '
    'The writer implements only the specifically requested product limit, including when '
    'that limit exists on origin/main. Add boundary tests that accept the new limit and '
    'refuse the limit plus one unit; for byte limits, refuse one additional byte '
    '(for example, accept 536870912 bytes and refuse 536870913 bytes). '
    'For every bound the owner did not ask to change, preserve the stop-and-report rule '
    'and fix the consumer side, subject to the existing branch-only and same-guarantee '
    'test-edit exceptions below. This product-limit exception grants no authority to '
    'change unrelated safety, security, resource, budget, or timeout bounds or to weaken '
    'other guarantees. Preserve normal review, CI, and applicable consent requirements. '
    'Record the owner request and its exact scope in the brief and PR body. '
    'This product-limit exception applies independently of the two exceptions below.'
)


class ProductLimitInstructionTests(unittest.TestCase):
    def test_every_guard_block_includes_the_scoped_product_limit_exception(self):
        blocks = guard_blocks()
        self.assertTrue({
            'plugins/ship/agents/writer--sol.md',
            'plugins/ship/agents/writer--sonnet.md',
            'plugins/ship/skills/ship/SKILL.md',
            'plugins/chief/skills/run/SKILL.md',
        }.issubset(blocks))
        for path, block in blocks.items():
            with self.subTest(path=path):
                self.assertIn(PRODUCT_LIMIT_EXCEPTION, block)

    def test_readme_states_the_owner_requested_feature_and_preserved_guards(self):
        readme = (ROOT / 'README.md').read_text()
        self.assertIn(
            'An owner-requested product-limit change is a feature, including limits on main. '
            'The writer implements that exact limit and tests acceptance at the limit and '
            'refusal one unit above it (one byte for byte limits).',
            readme,
        )
        self.assertIn(
            'Every unrequested bound retains the stop-and-report and consumer-side rule, '
            'subject to the branch-only and same-guarantee test-edit exceptions. '
            'Unrelated safety, security, resource, budget, and timeout bounds and other '
            'guarantees keep their protection. Review, CI, and applicable consent requirements apply.',
            readme,
        )


if __name__ == '__main__':
    unittest.main()
