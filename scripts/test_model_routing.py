"""Required review and verifier seats use Opus with their explicit effort."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_plugins', ROOT / 'scripts/check-plugins.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


class ModelRoutingTests(unittest.TestCase):
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
            self.assertNotIn('claude-fable-', checks.frontmatter(path.read_text()).get('model', ''))
        sol = checks.frontmatter((ROOT / 'plugins/ship/agents/reviewer--sol.md').read_text())
        self.assertEqual((sol['model'], sol['effort']), ('gpt-6.1-sol', 'high'))
        self.assertEqual(checks.check('HEAD'), [])
