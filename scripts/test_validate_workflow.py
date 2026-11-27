"""Exercise the validation workflow with synthetic suites."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/validate.yml'
SUITE = """import os
from pathlib import Path
Path('{name}.tmpdir').write_text(os.environ['TMPDIR'])
"""
FIXTURES = {
    'scripts/check-plugins.py': 'pass\n',
    'scripts/test_synthetic.py': SUITE.format(name='rules') + """
import unittest

class SyntheticTest(unittest.TestCase):
    def test_rules(self):
        if os.environ['SYNTHETIC_FAIL']:
            self.fail('synthetic rules failure')
""",
    'plugins/ship/hooks/ultraship_test.py': SUITE.format(name='ledger') + """
if os.environ['SYNTHETIC_FAIL']:
    raise SystemExit('synthetic ledger failure')
""",
    'plugins/chief/skills/run/scripts/lane-teardown.test.sh': 'printf "%s\\n" "$TMPDIR" > teardown.tmpdir\n',
    'plugins/ship/skills/test/scripts/check.sh': ':\n',
}


class ValidateWorkflowTests(unittest.TestCase):
    def test_aggregate_keeps_every_suite_result(self):
        steps = re.findall(r'^        run: (.+)\n((?:^          [^\n]*\n)*)',
                           WORKFLOW.read_text(), re.MULTILINE)
        self.assertTrue(steps)
        for fail in ('1', ''):
            with self.subTest(fail=bool(fail)), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                for name, text in FIXTURES.items():
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text)

                env = {**os.environ, 'BASE': '', 'GITHUB_WORKSPACE': str(root), 'SYNTHETIC_FAIL': fail}
                output = ''
                for inline, block in steps:
                    command = textwrap.dedent(block) if inline == '|' else inline
                    result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', command],
                                            cwd=root, env=env, capture_output=True, text=True, timeout=10)
                    output += result.stdout + result.stderr
                    if result.returncode:
                        break

                self.assertEqual(result.returncode != 0, bool(fail), output)
                if fail:
                    self.assertIn('synthetic rules failure', output)
                    self.assertIn('synthetic ledger failure', output)
                dirs = {Path((root / f'{name}.tmpdir').read_text().strip())
                        for name in ('rules', 'ledger', 'teardown')}
                self.assertEqual(len(dirs), 3, output)
                for directory in dirs:
                    self.assertTrue(directory.is_relative_to(root), directory)


if __name__ == '__main__':
    unittest.main()
