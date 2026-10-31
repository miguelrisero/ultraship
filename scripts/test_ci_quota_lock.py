"""Ship CI reads preserve quota and check flaky-guard lock occupancy."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHIP = ROOT / 'plugins/ship'
LOCK_IDLE = SHIP / 'skills/ship/scripts/lock-idle.sh'
POLICY_PATHS = (
    SHIP / 'agents/driver.md',
    SHIP / 'agents/driver--sol.md',
    SHIP / 'skills/babysit/SKILL.md',
)


class CIQuotaTests(unittest.TestCase):
    def test_watch_checks_uses_five_minute_graphql_reads(self):
        text = (SHIP / 'skills/ship/scripts/watch-checks.sh').read_text()
        self.assertRegex(text, r'(?m)^interval=300$')
        self.assertIn('start_timeout="${2:-600}"', text)
        self.assertIn('timeout="${3:-5400}"', text)
        self.assertEqual(text.count('gh pr checks'), 1)
        for forbidden in ('gh run watch', 'check-runs', 'gh api'):
            self.assertNotIn(forbidden, text)

    def test_all_coordinators_carry_quota_and_lock_rules(self):
        for path in POLICY_PATHS:
            with self.subTest(path=path):
                text = path.read_text()
                for phrase in (
                    'GraphQL', 'gh pr checks', 'gh pr view',
                    'at most once every 5 minutes per PR',
                    'gh run watch', 'check-runs loop', 'job polling',
                    'repeated status comments', 'once per failure',
                    'gh run view <run-id> --log-failed', '/mq/queue',
                    '/proc/locks', 'zero holders and zero waiters',
                    'make test-flaky-patterns', '/var/ops/CoC/gate/locks/flaky-guard.lock',
                    'lock-idle.sh', "guard's own bound unchanged",
                ):
                    self.assertIn(phrase, text)
        drivers = [path.read_text().split('\n---\n', 1)[1] for path in POLICY_PATHS[:2]]
        self.assertEqual(*drivers)
        babysit = POLICY_PATHS[2].read_text().split('## One round', 1)[1]
        self.assertIn('gh pr view --json statusCheckRollup', babysit)


@unittest.skipUnless(sys.platform == 'linux' and shutil.which('flock'), 'requires Linux and flock')
class LockIdleTests(unittest.TestCase):
    def probe(self, path):
        return subprocess.run([str(LOCK_IDLE), str(path)], capture_output=True, text=True, check=False)

    def test_usage(self):
        for args in ([], ['a', 'b']):
            result = subprocess.run([str(LOCK_IDLE), *args], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)

    def test_missing_and_idle_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'guard.lock'
            result = self.probe(path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('missing', result.stdout)
            path.touch()
            self.assertEqual(self.probe(path).returncode, 0)
            self.assertEqual(path.read_bytes(), b'')

    def test_holder_and_waiter_are_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'guard.lock'
            other = Path(tmp) / 'other.lock'
            other.touch()
            processes = []
            try:
                holder = subprocess.Popen(
                    ['flock', str(path), sys.executable, '-c',
                     'import sys; print("ready", flush=True); sys.stdin.read()'],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                )
                processes.append(holder)
                self.assertEqual(holder.stdout.readline().strip(), 'ready')
                result = self.probe(path)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('holders=1 waiters=0', result.stdout)
                self.assertEqual(self.probe(other).returncode, 0)
                waiter = subprocess.Popen(
                    ['flock', str(path), sys.executable, '-c', 'import sys; sys.stdin.read()'],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                )
                processes.append(waiter)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    result = self.probe(path)
                    if 'holders=1 waiters=1' in result.stdout:
                        break
                    time.sleep(0.01)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('holders=1 waiters=1', result.stdout)
            finally:
                # Closing input lets each flock command and its child exit normally.
                for process in processes:
                    process.stdin.close()
                for process in processes:
                    process.wait(timeout=5)
                    process.stdout.close()
            self.assertEqual(self.probe(path).returncode, 0)
            self.assertTrue(path.exists())


if __name__ == '__main__':
    unittest.main()
