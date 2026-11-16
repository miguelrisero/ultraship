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
LIMIT_HEADING = '## Protected row routes in this definition'
LIMIT_SECTION = '''## Protected row routes in this definition

Among protected row routes, this definition implements only New lane-owned row review and Draft PR for new lane-owned row review.
Refuse every step of every other protected row route because this loaded definition implements none of it.
This refusal includes row-ID lookup and row reads.
Preserve every existing refusal and affected-session hold.
'''
SHARED_HEADINGS = (
    '## Protected row admission',
    '## New lane-owned row review',
    '## Draft PR for new lane-owned row review',
)


def split_body(text):
    body = text.split('\n---\n', 1)[1]
    parts = re.split(r'^(## .+)$', body, flags=re.M)
    return parts[0], [(parts[i], parts[i] + parts[i + 1].rstrip('\n') + '\n')
                      for i in range(1, len(parts), 2)]


class ReviewerRowRouteParityTests(unittest.TestCase):
    def test_astra_base_and_exact_route_scope(self):
        astra_base, astra_sections = split_body((AGENTS / 'reviewer--astra.md').read_text())
        sol_base, _ = split_body((AGENTS / 'reviewer--sol.md').read_text())
        self.assertEqual(astra_base, sol_base)
        self.assertEqual([heading for heading, _ in astra_sections], [
            SHARED_HEADINGS[0], LIMIT_HEADING, *SHARED_HEADINGS[1:],
        ])
        self.assertEqual(dict(astra_sections)[LIMIT_HEADING], LIMIT_SECTION)

    def test_astra_shared_sections_match_sol_and_opus(self):
        _, astra_sections = split_body((AGENTS / 'reviewer--astra.md').read_text())
        astra = dict(astra_sections)
        for seat in ('reviewer--sol', 'reviewer--opus'):
            _, sections = split_body((AGENTS / (seat + '.md')).read_text())
            for heading in SHARED_HEADINGS:
                with self.subTest(seat=seat, heading=heading):
                    self.assertEqual(astra[heading], dict(sections)[heading])

    def test_astra_keeps_read_only_tools_model_and_effort(self):
        fields = checks.frontmatter((AGENTS / 'reviewer--astra.md').read_text())
        self.assertEqual(fields['tools'], 'Read, Grep, Glob, LSP, WebFetch, WebSearch')
        self.assertEqual(fields['model'], 'gpt-6-astra')
        self.assertEqual(fields['effort'], 'xhigh')

    def test_all_reviewer_sections_match_sol_or_explicit_partial_scope(self):
        _, sol_sections = split_body((AGENTS / 'reviewer--sol.md').read_text())
        sol = dict(sol_sections)
        for path in sorted(AGENTS.glob('reviewer--*.md')):
            with self.subTest(seat=path.stem):
                _, sections = split_body(path.read_text())
                headings = {heading for heading, _ in sections}
                self.assertEqual(len(headings), len(sections))
                self.assertLessEqual(headings, sol.keys() | {LIMIT_HEADING})
                for heading, section in sections:
                    self.assertEqual(section, LIMIT_SECTION if heading == LIMIT_HEADING else sol[heading])
                shared = headings & sol.keys()
                if shared and shared != sol.keys():
                    self.assertEqual(dict(sections).get(LIMIT_HEADING), LIMIT_SECTION)
