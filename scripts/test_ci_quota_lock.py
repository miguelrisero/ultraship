"""Ship CI reads preserve quota and check flaky-guard lock occupancy."""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHIP = ROOT / 'plugins/ship'
LOCK_IDLE = SHIP / 'skills/ship/scripts/lock-idle.py'
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
        self.assertIn('--json bucket,name,link', text)
        self.assertIn("printf '%s\\n' \"$rows\"", text)
        for forbidden in ('gh run watch', 'check-runs', 'gh api'):
            self.assertNotIn(forbidden, text)

    def test_completion_prints_names_and_links_with_one_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            gh = directory / 'gh'
            gh.write_text('#!/bin/sh\nprintf "read\\n" >> "$CALLS"\nprintf "%s\\n" "$ROWS"\n')
            gh.chmod(0o755)
            calls = directory / 'calls'
            for bucket, expected in (('pass', 0), ('fail', 1), ('cancel', 1), ('', 2), ('pending', 3)):
                calls.write_text('')
                row = f'{bucket}\tbuild\thttps://github.com/example/repo/actions/runs/123' if bucket else ''
                env = {**os.environ, 'PATH': f'{directory}{os.pathsep}{os.environ["PATH"]}',
                       'CALLS': str(calls), 'ROWS': row}
                result = subprocess.run(
                    ['bash', str(SHIP / 'skills/ship/scripts/watch-checks.sh'), '123', '0', '0'],
                    env=env, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(calls.read_text(), 'read\n')
                if bucket in ('pass', 'fail', 'cancel'):
                    self.assertEqual(result.stdout, row + '\n')

    def test_all_coordinators_carry_quota_and_lock_rules(self):
        reference = SHIP / 'skills/ship/references/ci-and-locks.md'
        text = reference.read_text()
        for phrase in (
            'GraphQL', 'gh pr checks', 'gh pr view',
            'at most once every 5 minutes per PR', 'each polling reader',
            'gh run watch', 'check-runs loop', 'job polling',
            'repeated status comments', 'once per failure',
            'gh run view <run-id> --log-failed', '/mq/queue',
            '/proc/locks', 'zero holders and zero waiters',
            'make test-flaky-patterns', '/var/ops/CoC/gate/locks/flaky-guard.lock',
            'lock-idle.py', "guard's own bound unchanged", "guard's PID namespace",
            'every 60 seconds', 'up to 10 minutes', 'blocker',
            'one CI reader at a time', 'completion-gate reads',
            'skills/ship/SKILL.md', 'exempt',
        ):
            self.assertIn(phrase, text)
        for path in POLICY_PATHS:
            with self.subTest(path=path):
                link = '../ship/references/ci-and-locks.md' if path.name == 'SKILL.md' else '../skills/ship/references/ci-and-locks.md'
                self.assertIn(f']({link})', path.read_text())
        pipeline = (SHIP / 'skills/ship/references/pipeline.md').read_text()
        for step in ('## 3. Slices', '## 9. Push and PR'):
            section = pipeline.split(step, 1)[1].split('\n## ', 1)[0]
            self.assertIn('every writer brief that can run the flaky-pattern guard', section)
            self.assertIn('ci-and-locks.md#flaky-guard-lock', section)
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

    def test_reaped_parent_with_inherited_child_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'guard.lock'
            child_code = 'import sys; print("ready", flush=True); sys.stdin.read()'
            parent_code = (
                'import fcntl, os, subprocess, sys; '
                'fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o600); '
                'fcntl.flock(fd, fcntl.LOCK_EX); '
                'child = subprocess.Popen([sys.executable, "-c", sys.argv[2]], pass_fds=(fd,)); '
                'print(child.pid, flush=True)'
            )
            parent = subprocess.Popen(
                [sys.executable, '-c', parent_code, str(path), child_code],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            )
            try:
                pid = parent.stdout.readline().strip()
                self.assertEqual(parent.stdout.readline().strip(), 'ready')
                parent.wait(timeout=5)
                result = self.probe(path)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('holders=1 waiters=0', result.stdout)
                self.assertIn(f'holder pid={pid}', result.stdout)
            finally:
                parent.stdin.close()
                parent.wait(timeout=5)
                parent.stdout.read()
                parent.stdout.close()

    def test_posix_ofd_and_unparseable_fdinfo_records(self):
        spec = importlib.util.spec_from_file_location('lock_idle', LOCK_IDLE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp)
            (proc / 'locks').write_text('1: POSIX ADVISORY WRITE 123 08:01:42 0 EOF\n')
            fdinfo = proc / '456/fdinfo'
            fdinfo.mkdir(parents=True)
            (fdinfo / '3').write_text(
                'lock:\t1: POSIX ADVISORY WRITE 123 08:01:42 0 EOF\n'
                'lock:\t2: OFDLCK ADVISORY WRITE -1 ff:ff:42 0 EOF\n'
                'lock:\t3: -> OFDLCK ADVISORY WRITE -1 ff:ff:42 1 EOF\n'
                'lock:\t4: FLOCK ADVISORY WRITE 456 <none>:0 0 EOF\n'
            )
            records = module.lock_records(SimpleNamespace(st_dev=os.makedev(8, 1), st_ino=42), proc)
            self.assertEqual(len(records), 3)
            self.assertEqual(sum(key[0] for key in records), 1)
            self.assertIn({'123', '456'}, records.values())
            self.assertIsNone(module.lock_record('1: FLOCK ADVISORY WRITE 1 <none>:0 0 EOF', 0))
            self.assertIsNotNone(module.lock_record('1: OFDLCK ADVISORY WRITE -1 ff:ff:42 0 EOF', 42))

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
                self.assertIn(f'holder pid={holder.pid}', result.stdout)
                self.assertIn(f'waiter pid={waiter.pid}', result.stdout)
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
