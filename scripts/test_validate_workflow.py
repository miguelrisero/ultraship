"""Exercise the validation workflow with synthetic suites."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/validate.yml'
SUITES = ('rules', 'ledger', 'teardown', 'shell')
SHELL_FIXTURE = 'plugins/ship/skills/test/scripts/check.sh'
SUITE = """import os
from pathlib import Path
tmpdir = Path(os.environ['TMPDIR']).resolve(strict=True)
if not tmpdir.is_dir():
    raise NotADirectoryError(tmpdir)
Path('{name}.tmpdir').write_text(str(tmpdir))
"""
FIXTURES = {
    'scripts/check-plugins.py': 'pass\n',
    'scripts/test_synthetic.py': SUITE.format(name='rules') + """
import time
import unittest

class SyntheticTest(unittest.TestCase):
    def test_rules(self):
        if os.environ['SYNTHETIC_FAIL'] in ('rules', 'both'):
            self.fail('synthetic rules failure')
        if os.environ['SYNTHETIC_WAIT']:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if 'synthetic ledger failure' in Path('workflow.out').read_text():
                    print('synthetic rules resumed')
                    return
                time.sleep(0.02)
            self.fail('ledger output unavailable while rules waited')
""",
    'plugins/ship/hooks/ultraship_test.py': SUITE.format(name='ledger') + """
if os.environ['SYNTHETIC_FAIL'] in ('ledger', 'both'):
    raise SystemExit('synthetic ledger failure')
""",
    'plugins/chief/skills/run/scripts/lane-teardown.test.sh': '''
(cd -- "$TMPDIR" && pwd -P) > teardown.tmpdir || exit 1
if [ "$SYNTHETIC_FAIL" = teardown ]; then
    echo 'synthetic teardown failure' >&2
    exit 7
fi
''',
    SHELL_FIXTURE: ':\n',
    'bin/bash': '''#!/bin/sh
if [ "$1" = -n ]; then
    (cd -- "$TMPDIR" && pwd -P) > shell.tmpdir || exit 1
fi
exec "$REAL_BASH" "$@"
''',
}


class ValidateWorkflowTests(unittest.TestCase):
    def run_workflow(self, root, fail='', wait=False):
        steps = re.findall(r'^        run: (.+)\n((?:^          [^\n]*\n)*)',
                           WORKFLOW.read_text(), re.MULTILINE)
        self.assertTrue(steps)
        for name, text in FIXTURES.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('if true; then\n' if fail == 'shell' and name == SHELL_FIXTURE else text)
        (root / 'bin/bash').chmod(0o755)

        bash = shutil.which('bash')
        self.assertIsNotNone(bash)
        env = {**os.environ, 'BASE': '', 'GITHUB_WORKSPACE': str(root),
               'REAL_BASH': bash,
               'PATH': f'{root / "bin"}{os.pathsep}{os.environ["PATH"]}',
               'SYNTHETIC_FAIL': fail, 'SYNTHETIC_WAIT': '1' if wait else ''}
        log = root / 'workflow.out'
        with log.open('w') as output:
            for inline, block in steps:
                command = textwrap.dedent(block) if inline == '|' else inline
                result = subprocess.run([bash, '-e', '-o', 'pipefail', '-c', command],
                                        cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT,
                                        timeout=10)
                if result.returncode:
                    break
        return result.returncode, log.read_text()

    def test_success_reports_every_suite_with_its_own_workspace_tmpdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            code, output = self.run_workflow(root)
            self.assertEqual(code, 0, output)
            dirs = set()
            scratch = (root / '.scratch').resolve(strict=True)
            for suite in SUITES:
                self.assertIn(f'{suite}: exit 0', output.splitlines())
                directory = Path((root / f'{suite}.tmpdir').read_text().strip())
                self.assertTrue(directory.is_relative_to(scratch), directory)
                self.assertNotEqual(directory, scratch)
                dirs.add(directory)
            self.assertEqual(len(dirs), len(SUITES), output)

    def test_each_suite_failure_fails_the_aggregate(self):
        for suite, status, detail in (
            ('rules', 1, 'synthetic rules failure'),
            ('ledger', 1, 'synthetic ledger failure'),
            ('teardown', 7, 'synthetic teardown failure'),
            ('shell', 2, 'syntax error'),
        ):
            with self.subTest(suite=suite), tempfile.TemporaryDirectory() as tmp:
                code, output = self.run_workflow(Path(tmp).resolve(), fail=suite)
                self.assertNotEqual(code, 0, output)
                self.assertIn(detail, output)
                for name in SUITES:
                    self.assertIn(f'{name}: exit {status if name == suite else 0}', output.splitlines())

    def test_multiple_suite_failures_keep_both_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = self.run_workflow(Path(tmp).resolve(), fail='both')
            self.assertNotEqual(code, 0, output)
            self.assertIn('synthetic rules failure', output)
            self.assertIn('synthetic ledger failure', output)
            self.assertIn('teardown: exit 0', output.splitlines())
            self.assertIn('shell: exit 0', output.splitlines())

    def test_completed_suite_output_is_available_while_another_suite_waits(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = self.run_workflow(Path(tmp).resolve(), fail='ledger', wait=True)
            self.assertNotEqual(code, 0, output)
            self.assertIn('synthetic rules resumed', output)
            self.assertIn('rules: exit 0', output.splitlines())
            self.assertIn('ledger: exit 1', output.splitlines())


if __name__ == '__main__':
    unittest.main()
