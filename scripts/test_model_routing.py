"""Required review and verifier seats use Opus with their explicit effort."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_plugins', ROOT / 'scripts/check-plugins.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


class ModelRoutingTests(unittest.TestCase):
    def test_astra_and_luna_reviewer_names_pin_their_declared_models(self):
        for seat, model in (('reviewer--astra', 'gpt-6-astra'),
                            ('reviewer--luna', 'gpt-6-luna')):
            with self.subTest(seat=seat):
                path = ROOT / 'plugins/ship/agents' / (seat + '.md')
                fields = checks.frontmatter(path.read_text())
                self.assertEqual(fields['name'], seat)
                self.assertEqual(fields['model'], model)
                self.assertEqual(checks.inspect_text(path.read_text(), path), [])

    def test_required_seats_keep_read_only_tools_effort_and_fallbacks(self):
        for seat in ('reviewer--fable', 'verifier--fable'):
            path = ROOT / 'plugins/ship/agents' / (seat + '.md')
            fields = checks.frontmatter(path.read_text())
            self.assertEqual(fields['model'], 'claude-opus-5-5')
            self.assertEqual(fields['effort'], 'xhigh')
            self.assertEqual(checks.inspect_text(path.read_text(), path), [])
            self.assertNotIn('Bash', fields['tools'])
            self.assertNotIn('Edit', fields['tools'])
        roster = (ROOT / 'plugins/ship/skills/ship/references/roster.md').read_text()
        self.assertIn('| `ship:reviewer--fable` | `claude-opus-5-5` | xhigh |', roster)
        self.assertIn('| `ship:verifier--fable` | `claude-opus-5-5` | xhigh |', roster)
        panels = (ROOT / 'plugins/ship/skills/panel/references/panels.md').read_text()
        self.assertIn('`reviewer--fable`, `reviewer--kimi`', panels)
        self.assertIn('`reviewer--astra` takes the seat', panels)
        for path in (ROOT / 'plugins/ship/agents').glob('*.md'):
            if path.stem.endswith('--fable52'):
                continue
            self.assertNotIn('claude-fable-', checks.frontmatter(path.read_text()).get('model', ''))
        sol = checks.frontmatter((ROOT / 'plugins/ship/agents/reviewer--sol.md').read_text())
        self.assertEqual((sol['model'], sol['effort']), ('gpt-6.1-sol', 'high'))
        driver = checks.frontmatter((ROOT / 'plugins/ship/agents/driver.md').read_text())
        self.assertEqual((driver['model'], driver['effort']), ('claude-opus-5-5', 'xhigh'))
        low = checks.frontmatter((ROOT / 'plugins/ship/agents/driver--sol.md').read_text())
        self.assertEqual((low['model'], low['effort']), ('gpt-6.1-sol', 'high'))
        self.assertIn('low', low['description'])
        for path in (ROOT / 'plugins/ship/agents').glob('*.md'):
            self.assertNotEqual(checks.frontmatter(path.read_text()).get('model', 'inherit'), 'inherit', path.name)
        self.assertEqual(checks.check('HEAD'), [])

    def test_fable52_seats_pin_fable_and_copy_their_base_seat_body(self):
        for seat, base, effort in (('writer--fable52', 'writer--sol', 'high'),
                                   ('reviewer--fable52', 'reviewer--fable', 'xhigh')):
            with self.subTest(seat=seat):
                path = ROOT / 'plugins/ship/agents' / (seat + '.md')
                text = path.read_text()
                fields = checks.frontmatter(text)
                self.assertEqual((fields['name'], fields['model'], fields['effort']), (seat, 'claude-fable-5-2', effort))
                self.assertEqual(checks.inspect_text(text, path), [])
                base_text = (ROOT / 'plugins/ship/agents' / (base + '.md')).read_text()
                self.assertEqual(text.split('\n---\n', 1)[1], base_text.split('\n---\n', 1)[1])
        reviewer = checks.frontmatter((ROOT / 'plugins/ship/agents/reviewer--fable52.md').read_text())
        self.assertNotIn('Bash', reviewer['tools'])
        self.assertNotIn('Edit', reviewer['tools'])
