"""The watcher requires every configured context, including delayed reports."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WATCH = ROOT / 'plugins/ship/skills/ship/scripts/watch-checks.sh'


class WatchChecksTests(unittest.TestCase):
    def watch(self, classic='build', rules='', rows='pass\tbuild\thttps://example.com/run', ignore=''):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            gh = directory / 'gh'
            gh.write_text('''#!/bin/sh
case "$1 $2" in
  'pr view') printf 'example/repo\\tmain\\n' ;;
  'pr checks') printf '%s\\n' "$ROWS" ;;
  'api repos/example/repo/branches/main/protection/required_status_checks')
    [ "$CLASSIC" != ERROR ] || { echo 'gh: Server Error (HTTP 502)' >&2; exit 1; }
    [ "$CLASSIC" != NOTPROTECTED ] || { echo 'gh: Branch not protected (HTTP 404)' >&2; exit 1; }
    printf '%s\\n' "$CLASSIC" ;;
  'api repos/example/repo/rules/branches/main')
    [ "$RULES" != ERROR ] || { echo 'gh: Server Error (HTTP 502)' >&2; exit 1; }
    [ "$RULES" != NOTPROTECTED ] || { echo 'gh: Branch not protected (HTTP 404)' >&2; exit 1; }
    printf '%s\\n' "$RULES" ;;
  *) echo "unexpected gh call: $*" >&2; exit 99 ;;
esac
''')
            gh.chmod(0o755)
            env = {**os.environ, 'PATH': f'{directory}{os.pathsep}{os.environ["PATH"]}',
                   'CLASSIC': classic, 'RULES': rules, 'ROWS': rows, 'WATCH_CHECKS_IGNORE': ignore}
            return subprocess.run(['bash', str(WATCH), '7349', '0', '0'],
                                  env=env, capture_output=True, text=True, timeout=10)

    def test_missing_required_aggregate_stays_pending(self):
        result = self.watch(classic='build\nci-gate · required aggregate')
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn('ci-gate · required aggregate', result.stdout)

    def test_rules_context_joins_classic_contexts(self):
        result = self.watch(rules='rules-only')
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)

    def test_all_required_contexts_pass(self):
        result = self.watch(rules='rules-only', rows='pass\tbuild\turl\npass\trules-only\turl')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unknown_required_set_fails_closed(self):
        for classic, rules in (('ERROR', 'ERROR'), ('', ''), ('ERROR', ''), ('NOTPROTECTED', ''),
                               ('ERROR', 'build'), ('build', 'ERROR')):
            with self.subTest(classic=classic, rules=rules):
                result = self.watch(classic=classic, rules=rules)
                self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
                self.assertIn('required contexts', result.stdout)

    def test_either_api_can_supply_contexts(self):
        for classic, rules in (('build', ''), ('', 'build'), ('NOTPROTECTED', 'build')):
            with self.subTest(classic=classic, rules=rules):
                result = self.watch(classic=classic, rules=rules)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ignore_uses_exact_newline_separated_names(self):
        required = 'build\nMerge Queue Gate\nother queue'
        result = self.watch(classic=required, ignore='Merge Queue Gate\nother queue')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = self.watch(classic=required, ignore='Merge Queue')
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)

    def test_skipped_required_context_counts_as_done(self):
        result = self.watch(rows='skipping\tbuild\turl')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_nonpassing_required_context_refuses_success(self):
        for bucket, expected in (('fail', 1), ('cancel', 1), ('pending', 3)):
            with self.subTest(bucket=bucket):
                result = self.watch(rows=f'{bucket}\tbuild\turl')
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
