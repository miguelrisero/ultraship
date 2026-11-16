"""Reviewer seats share exact route contracts and explicit partial-route refusals."""
import importlib.util
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_plugins', ROOT / 'scripts/check-plugins.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)
AGENTS = ROOT / 'plugins/ship/agents'
LIMIT_SECTION = '''## Protected row routes in this definition

Among protected row routes, this definition implements only New lane-owned row review and Draft PR for new lane-owned row review.
Refuse every step of every other protected row route because this loaded definition implements none of it.
This refusal includes row-ID lookup and row reads.
Preserve every existing refusal and affected-session hold.
'''
DISPATCH_STEP = '1. Dispatch a reviewer whose loaded definition implements the selected route. `ship:reviewer--sol` and `ship:reviewer--opus` implement every reviewer row route; `ship:reviewer--astra` implements only the new lane-owned row review route. Make the first message ask it to return `ready` and read nothing.'


def split_body(text):
    body = text.split('\n---\n', 1)[1]
    parts = re.split(r'^(## .+)$', body, flags=re.M)
    return parts[0], {parts[i]: parts[i] + parts[i + 1]
                      for i in range(1, len(parts), 2)}


class ReviewerRowRouteParityTests(unittest.TestCase):
    def setUp(self):
        self.sol_body = (AGENTS / 'reviewer--sol.md').read_text().split('\n---\n', 1)[1]
        base, sections = split_body((AGENTS / 'reviewer--sol.md').read_text())
        draft = sections['## Draft PR for new lane-owned row review']
        self.assertTrue(draft.endswith('\n\n'))
        self.partial_body = (base + sections['## Protected row admission']
                             + LIMIT_SECTION + '\n'
                             + sections['## New lane-owned row review'] + draft[:-1])

    def test_astra_base_and_exact_route_scope(self):
        body = (AGENTS / 'reviewer--astra.md').read_text().split('\n---\n', 1)[1]
        self.assertEqual(body, self.partial_body)

    def test_all_reviewer_bodies_match_sol_or_exact_partial_scope(self):
        for path in sorted(AGENTS.glob('reviewer--*.md')):
            with self.subTest(seat=path.stem):
                text = path.read_text()
                _, sections = split_body(text)
                if sections:
                    self.assertIn(text.split('\n---\n', 1)[1], (self.sol_body, self.partial_body))

    def test_astra_keeps_read_only_tools_and_effort(self):
        fields = checks.frontmatter((AGENTS / 'reviewer--astra.md').read_text())
        self.assertEqual(fields['tools'], 'Read, Grep, Glob, LSP, WebFetch, WebSearch')
        self.assertEqual(fields['effort'], 'xhigh')

    def test_dispatch_selects_a_reviewer_with_the_loaded_route(self):
        text = (ROOT / 'plugins/ship/skills/ship/references/owner-decisions.md').read_text()
        self.assertEqual(text.splitlines().count(DISPATCH_STEP), 1)
