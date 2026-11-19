"""Synthetic linked-worktree ledger and hook regressions."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import importlib.util
import json
import os
import shutil
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / 'plugins/ship/skills/ship/scripts/ledger.py'
HOOK = ROOT / 'plugins/ship/hooks/ultraship.py'
spec = importlib.util.spec_from_file_location('ledger', LEDGER)
ledger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger)


class LedgerDirTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT.parent / '.scratch'
        scratch.mkdir(exist_ok=True)
        self.base = Path(tempfile.mkdtemp(prefix='ship-ledger-regression-', dir=scratch))
        self.addCleanup(shutil.rmtree, self.base)
        self.env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'CLAUDE_CODE_SESSION_ID': 's1',
                    'XDG_STATE_HOME': str(self.base / 'state'), 'HOME': str(self.base)}
        self.env.pop('SHIP_LEDGER_DIR', None)
        self.common = self.base / 'external'
        self.workspace = self.base / 'workspace'
        self.workspace.mkdir()
        (self.workspace / '.scratch').mkdir()
        self.checkout = self.workspace / 'checkout'
        self.git(self.base, 'init', '-q', '-b', 'main', str(self.common))
        self.git(self.common, '-c', 'user.name=t', '-c', 'user.email=t@t',
                 'commit', '-q', '--allow-empty', '-m', 'init')
        self.git(self.common, 'worktree', 'add', '-q', '-b', 'feat/nested/x', str(self.checkout))
        self.legacy = self.common / '.git/ship/ledger/feat__nested__x.tsv'
        self.legacy.parent.mkdir(parents=True)
        self.history = (b'1\trun-start\tlight\tsha\topen\trun-1 /board\n'
                        b'2\tslices\twriter\tsha\tpass\tall evidence\n'
                        b'3\tdeep-review\treviewer\tsha\towed\tkeep this\n')
        self.legacy.write_bytes(self.history)

    def git(self, cwd, *args):
        return subprocess.run(['git', '-C', str(cwd), *args], env=self.env,
                              capture_output=True, text=True, check=True).stdout.strip()

    def cli(self, *args, env=None, cwd=None):
        return subprocess.run([sys.executable, str(LEDGER), *args], cwd=cwd or self.checkout,
                              env=env or self.env, capture_output=True, text=True)

    def resolve(self):
        with mock.patch.dict(os.environ, self.env, clear=True):
            return ledger.ledger_path(self.checkout)

    def hook(self, mode, env=None, **extra):
        payload = {'session_id': 's1', 'cwd': str(self.checkout), **extra}
        return subprocess.run([sys.executable, str(HOOK), mode], input=json.dumps(payload),
                              cwd=self.checkout, env=env or self.env, capture_output=True,
                              text=True, check=True).stdout

    def test_import_and_open_run_continue_locally_once(self):
        local = self.resolve()
        self.assertTrue(local.is_relative_to(self.workspace / '.scratch/ship-ledgers'))
        self.assertFalse(local.is_relative_to(self.checkout))
        self.assertEqual(local.name, 'feat__nested__x.tsv')
        self.assertEqual(local.read_bytes(), self.history)
        provenance = local.with_suffix('.import.json').read_bytes()
        self.assertEqual(json.loads(provenance), {
            'legacy_path': str(self.legacy.resolve()),
            'sha256': hashlib.sha256(self.history).hexdigest(),
        })
        self.assertEqual(ledger.open_run(local)[0][5], 'run-1 /board')
        self.assertEqual(self.cli('append', 'simplify', 'reviewer', 'new-sha', 'pass').returncode, 0)
        continued = local.read_bytes()
        self.assertEqual(continued.count(b'run-start'), 1)
        self.assertTrue(continued.startswith(self.history))
        self.assertEqual(self.legacy.read_bytes(), self.history)
        self.legacy.write_bytes(b'malformed later legacy change\n')
        self.assertEqual(self.resolve(), local)
        self.assertEqual(local.read_bytes(), continued)
        self.assertEqual(local.with_suffix('.import.json').read_bytes(), provenance)
        self.assertEqual(self.legacy.read_bytes(), b'malformed later legacy change\n')
        self.assertIn('run-1 /board', self.cli('status').stdout)
        self.assertIn('run-1 /board', self.hook('compact'))

    def test_cooperating_first_users_publish_one_snapshot(self):
        users = [subprocess.Popen([sys.executable, str(LEDGER), 'path'], cwd=self.checkout,
                                  env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True) for _ in range(4)]
        paths = []
        for user in users:
            stdout, stderr = user.communicate(timeout=10)
            self.assertEqual(user.returncode, 0, stderr)
            paths.append(stdout.strip())
        self.assertEqual(len(set(paths)), 1)
        self.assertEqual(Path(paths[0]).read_bytes(), self.history)
        self.assertEqual(self.legacy.read_bytes(), self.history)

    def test_override_and_full_checkout_compatibility(self):
        override = self.base / 'override'
        env = {**self.env, 'SHIP_LEDGER_DIR': str(override)}
        self.assertEqual(self.cli('path', env=env).stdout.strip(), str(override / self.legacy.name))
        self.assertFalse(override.exists())
        self.assertFalse((self.workspace / '.scratch/ship-ledgers').exists())
        for value in ('relative/ledger', ''):
            result = self.cli('path', env={**self.env, 'SHIP_LEDGER_DIR': value})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('absolute path', result.stderr)
        self.assertEqual(self.cli('path', cwd=self.common).stdout.strip(),
                         str(self.common / '.git/ship/ledger/main.tsv'))
        self.assertEqual(self.legacy.read_bytes(), self.history)

    def test_ambiguous_layout_and_symlink_escape_fail(self):
        ambiguous = self.base / 'ambiguous'
        self.git(self.common, 'worktree', 'add', '-q', '-b', 'other', str(ambiguous))
        result = self.cli('path', cwd=ambiguous)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHIP_LEDGER_DIR', result.stderr)
        (self.workspace / '.scratch/ship-ledgers').symlink_to(self.base, target_is_directory=True)
        result = self.cli('path')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('escapes workspace', result.stderr)
        self.assertEqual(self.legacy.read_bytes(), self.history)

    def test_contained_common_git_directory_keeps_existing_default(self):
        linked = self.common / 'linked'
        (self.common / '.scratch').mkdir()
        self.git(self.common, 'worktree', 'add', '-q', '-b', 'contained', str(linked))
        self.assertEqual(self.cli('path', cwd=linked).stdout.strip(),
                         str(self.common / '.git/ship/ledger/contained.tsv'))
        self.assertFalse((self.common / '.scratch/ship-ledgers').exists())

    def test_import_without_final_newline_preserves_then_separates_rows(self):
        history = self.history.rstrip(b'\n')
        self.legacy.write_bytes(history)
        local = self.resolve()
        self.assertEqual(local.read_bytes(), history)
        self.assertEqual(self.cli('append', 'simplify', 'reviewer', 'sha', 'pass').returncode, 0)
        self.assertEqual(len(ledger.rows(local)), 4)
        self.assertEqual(ledger.rows(local)[2][5], 'keep this')
        self.assertEqual(self.legacy.read_bytes(), history)

    def test_repository_and_branch_isolation(self):
        local = self.resolve()
        sibling = self.workspace / 'sibling'
        self.git(self.common, 'worktree', 'add', '-q', '--detach', str(sibling))
        with mock.patch.dict(os.environ, self.env, clear=True):
            sibling_path = ledger.ledger_path(sibling)
        self.assertNotEqual(local.parent, sibling_path.parent)
        self.git(self.checkout, 'checkout', '-q', '-b', 'second')
        second = self.resolve()
        self.assertEqual(local.parent, second.parent)
        self.assertNotEqual(local, second)
        self.assertEqual(local.read_bytes(), self.history)
        self.assertEqual(second.read_bytes(), b'')

    def test_failed_import_preserves_source_and_error(self):
        self.legacy.write_bytes(b'broken\trow\n')
        with self.assertRaisesRegex(ValueError, 'Malformed legacy ledger'):
            self.resolve()
        self.assertEqual(self.legacy.read_bytes(), b'broken\trow\n')
        self.assertEqual(list((self.workspace / '.scratch').rglob('*.tsv')), [])
        self.legacy.write_bytes(self.history)
        with mock.patch.object(Path, 'read_bytes', side_effect=PermissionError('source unreadable')):
            with self.assertRaisesRegex(PermissionError, 'source unreadable'):
                self.resolve()
        self.assertEqual(self.legacy.read_bytes(), self.history)

    def test_partial_publication_fails_closed_without_reimport(self):
        replace = os.replace

        def fail_tsv(source, target):
            if target.suffix == '.tsv':
                raise PermissionError('snapshot publication denied')
            replace(source, target)

        with mock.patch.object(ledger.os, 'replace', side_effect=fail_tsv):
            with self.assertRaisesRegex(PermissionError, 'snapshot publication denied'):
                self.resolve()
        self.assertEqual(self.legacy.read_bytes(), self.history)
        self.legacy.write_bytes(b'later source must stay unread\n')
        with self.assertRaisesRegex(ValueError, 'Local ledger missing after import'):
            self.resolve()
        snapshots = list((self.workspace / '.scratch').rglob('*.tsv.*'))
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].read_bytes(), self.history)

    def finish_run(self):
        for step in ledger.REQUIRED['light']:
            self.assertEqual(self.cli('append', step, 'driver', 'sha', 'pass').returncode, 0)
        self.assertEqual(self.cli('run-end').returncode, 0)

    def fallback_fixture(self):
        self.env['GIT_CEILING_DIRECTORIES'] = str(self.base)
        agent = 'ship:reviewer--sol'
        self.hook('subagent-stop', cwd=str(self.workspace), agent_type=agent, agent_id='reviewer')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        pending = b'10\t' + owed.read_bytes().split(b'\t', 1)[1]
        result = json.loads(pending.split(b'\t')[3])
        self.assertNotIn('ledger', result)
        owed.write_bytes(pending)
        return owed, pending, json.dumps([str(owed), str(self.workspace), result['id']])

    def fallback_hook(self, owed):
        spec = importlib.util.spec_from_file_location('stop_hook', HOOK)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, self.env, clear=True):
            spec.loader.exec_module(module)
        self.assertEqual(module.owed_file({'session_id': 's1'}), owed)
        return module

    def test_stop_non_git_exact_match(self):
        owed, pending, key = self.fallback_fixture()
        home = self.resolve()
        child = self.workspace / 'repo/.git/ship/ledger/child.tsv'
        child.parent.mkdir(parents=True)
        start = b'1\trun-start\tlight\tsha\topen\trun-1\n'
        row = b'10\tdeep-review\tship:reviewer--sol@reviewer\tsha\tpass\t\n'
        receipts = owed.parent.parent / 'accounted.json'
        for count in (0, 2, 1):
            with self.subTest(count=count):
                owed.write_bytes(pending)
                owed.with_suffix('.stop-state').unlink(missing_ok=True)
                home.write_bytes(start + (row if count else row.replace(b'@reviewer', b'@other')))
                child.write_bytes(start + (row.replace(b'\tpass\t', b'\towed\t') if count == 2 else b''))
                output = self.hook('stop')
                if count != 1:
                    self.assertIn(f'Found {count} ledger rows', json.loads(output)['reason'])
                    self.assertEqual(owed.read_bytes(), pending)
                    self.assertFalse(receipts.exists())
                    continue
                self.assertEqual(output, '')
                self.assertEqual(owed.read_bytes(), b'')
                self.assertEqual(json.loads(receipts.read_bytes()), {key: [str(home),
                    *[[i, hashlib.sha256(json.dumps(line.decode().rstrip('\n').split('\t')).encode()).hexdigest()]
                      for i, line in enumerate((start, row))]]})

    def test_stop_non_git_preserves_main(self):
        owed, pending, _ = self.fallback_fixture()
        home = self.resolve()
        receipts = owed.parent.parent / 'accounted.json'
        row = b'10\tdeep-review\tship:reviewer--sol@reviewer\tsha\tpass\t\n'
        home.write_bytes(self.history + row)
        fields = pending.decode().rstrip('\n').split('\t')
        result = json.loads(fields[3])
        run = ledger.run_identity(0, ledger.rows(home)[0])
        for mode in ('git', 'broken', 'recorded', 'legacy'):
            with self.subTest(mode=mode):
                cwd = str(self.checkout) if mode in ('git', 'legacy') else str(self.workspace)
                home.write_bytes(self.history + (row.replace(b'@reviewer', b'') if mode == 'legacy' else row))
                data = {**result, 'ledger': str(home), 'run': run} if mode == 'recorded' else result
                line = '\t'.join(['10', fields[1], cwd] + ([] if mode == 'legacy' else [json.dumps(data)])) + '\n'
                owed.write_text(line)
                receipts.unlink(missing_ok=True)
                if mode == 'broken':
                    (self.workspace / '.git').mkdir()
                output = self.hook('stop')
                if mode == 'broken':
                    block = json.loads(output)
                    self.assertEqual(block['decision'], 'block')
                    self.assertIn("'--abbrev-ref', 'HEAD']' returned non-zero exit status 128", block['reason'])
                    self.assertEqual(owed.read_bytes(), line.encode())
                    self.assertFalse(receipts.exists())
                    continue
                self.assertEqual(output, '')
                self.assertEqual(owed.read_bytes(), b'')
                identifier = result['id']
                if mode == 'legacy':
                    identifier = 'legacy:' + hashlib.sha256(json.dumps([str(owed), line.rstrip('\n'), 0]).encode()).hexdigest()
                key = json.dumps([str(owed), cwd, identifier])
                expected = {key: [str(home), run, ledger.run_identity(3, ledger.rows(home)[3])]}
                self.assertEqual(receipts.read_bytes(), json.dumps(expected).encode())

    def test_stop_non_git_window(self):
        owed, pending, _ = self.fallback_fixture()
        home = self.resolve()
        receipts = owed.parent.parent / 'accounted.json'
        start = b'10\trun-start\tlight\tsha\topen\trun-1\n'
        row = b'18\tdeep-review\tship:reviewer--sol@reviewer\tsha\tpass\t\n'
        closed = b'20\trun-end\t\tsha\tclosed\trun-1\n'
        next_run = b'20\trun-start\tlight\tsha\topen\trun-2\n'
        for when, tail, passes in ((10, closed, True), (20, closed, True), (9, closed, False),
                                   (21, closed, False), (20, next_run, False), (20, closed + next_run, False)):
            with self.subTest(when=when, tail=tail):
                evidence = str(when).encode() + b'\t' + pending.split(b'\t', 1)[1]
                owed.write_bytes(evidence)
                receipts.unlink(missing_ok=True)
                owed.with_suffix('.stop-state').unlink(missing_ok=True)
                home.write_bytes(start + row + tail)
                output = self.hook('stop')
                if passes:
                    self.assertEqual(output, '')
                    self.assertEqual(owed.read_bytes(), b'')
                else:
                    self.assertEqual(json.loads(output)['decision'], 'block')
                    self.assertEqual(owed.read_bytes(), evidence)
                    self.assertFalse(receipts.exists())

    def test_stop_non_git_io(self):
        owed, pending, _ = self.fallback_fixture()
        hook = self.fallback_hook(owed)
        home = self.workspace / 'repo/.git/ship/ledger/live.tsv'
        home.parent.mkdir(parents=True)
        history = self.history + b'10\tdeep-review\tship:reviewer--sol@reviewer\tsha\tpass\t\n'
        home.write_bytes(history)
        bad = home.with_name('other.tsv')
        real_list, real_open, real_fork = os.scandir, os.open, os.fork

        def stop():
            output = io.StringIO()
            with mock.patch.dict(os.environ, self.env, clear=True), redirect_stdout(output):
                hook.stop({'session_id': 's1'})
            return output.getvalue()

        def blocked():
            owed.with_suffix('.stop-state').unlink(missing_ok=True)
            self.assertEqual(json.loads(stop())['decision'], 'block')
            self.assertEqual(owed.read_bytes(), pending)

        output = stop()
        self.assertEqual(output, '', output)
        self.assertEqual(owed.read_bytes(), b'')
        receipts = owed.parent.parent / 'accounted.json'
        receipts.unlink()
        owed.write_bytes(pending)
        bad.touch()

        def deny_listing(path):
            if path == home.parent:
                raise PermissionError('denied enumeration')
            return real_list(path)

        def vanish(path, *args, **kwargs):
            if path == bad:
                raise FileNotFoundError('vanished ledger')
            return real_open(path, *args, **kwargs)

        with mock.patch.object(os, 'scandir', side_effect=deny_listing):
            blocked()
        with mock.patch.object(os, 'open', side_effect=vanish):
            blocked()
        bad.unlink()
        for make in (lambda: bad.symlink_to(home), lambda: os.mkfifo(bad),
                     lambda: bad.write_text('bad\trow\n'), lambda: bad.write_bytes(b' ' * (1024 * 1024 + 1))):
            make()
            blocked()
            bad.unlink()
        for suffix, count in (('.tsv', 64), ('.txt', 128)):
            with tempfile.TemporaryDirectory(dir=self.base) as directory:
                override = Path(directory)
                for i in range(count):
                    (override / f'{i}{suffix}').touch()
                (override / 'live.tsv').write_bytes(history)
                with mock.patch.dict(self.env, SHIP_LEDGER_DIR=str(override)):
                    blocked()

        children = []

        def track_fork():
            pid = real_fork()
            if pid:
                children.append(pid)
            return pid

        def stall(path):
            time.sleep(30)
            return real_list(path)

        try:
            owed.write_bytes(pending * 2)
            owed.with_suffix('.stop-state').unlink(missing_ok=True)
            started = time.monotonic()
            with mock.patch.object(os, 'fork', side_effect=track_fork), mock.patch.object(os, 'scandir', side_effect=stall):
                output = stop()
            self.assertEqual(json.loads(output)['decision'], 'block')
            self.assertIn('timed out', output)
            self.assertLess(time.monotonic() - started, 12)
            self.assertEqual(len(children), 1)
            self.assertEqual(owed.read_bytes(), pending * 2)
            with self.assertRaises(ChildProcessError):
                os.waitpid(children[0], os.WNOHANG)
        finally:
            for pid in children:
                try:
                    if os.waitpid(pid, os.WNOHANG)[0] == 0:
                        os.kill(pid, signal.SIGTERM)
                        os.waitpid(pid, 0)
                except ChildProcessError:
                    pass

    def test_stop_non_git_replay(self):
        owed, pending, key = self.fallback_fixture()
        hook = self.fallback_hook(owed)
        home = self.resolve()
        row = b'10\tdeep-review\tship:reviewer--sol@reviewer\tsha\tpass\t\n'
        home.write_bytes(self.history + row)
        self.assertEqual(self.hook('stop'), '')
        receipts = owed.parent.parent / 'accounted.json'
        before = receipts.read_bytes()
        valid = json.loads(before)[key]
        with home.open('ab') as stream:
            stream.write(row)
        owed.write_bytes(pending)
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(owed.read_bytes(), b'')
        self.assertEqual(receipts.read_bytes(), before)
        with home.open('ab') as stream:
            stream.write(row.replace(b'@reviewer', b'@other'))
        other = json.loads(pending.split(b'\t')[3])
        other.update(id='other-result', agent_id='other')
        batch = b'\t'.join(pending.split(b'\t')[:3] + [json.dumps(other).encode()]) + b'\n' + pending
        for saved in (None, [[], *valid[1:]], [valid[0], [True, valid[1][1]], valid[2]],
                      [str(self.base / 'elsewhere.tsv'), *valid[1:]], [*valid[:2], [3, 'bad token']]):
            with self.subTest(saved=saved), mock.patch.dict(os.environ, self.env, clear=True):
                evidence = json.dumps({key: saved}).encode()
                receipts.write_bytes(evidence)
                owed.write_bytes(batch)
                owed.with_suffix('.stop-state').unlink(missing_ok=True)
                with self.assertRaises(hook.ReceiptIntegrityError):
                    hook.account(ledger, [line.split('\t') for line in batch.decode().splitlines()],
                                 {key: saved}, str(owed))
                self.assertEqual(json.loads(self.hook('stop'))['decision'], 'block')
                self.assertEqual(receipts.read_bytes(), evidence)
                self.assertEqual(owed.read_bytes(), batch)

    def test_stop_accounts_closed_run_and_refuses_next_run_evidence(self):
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode, 0)
        self.assertEqual(self.hook('stop'), '')
        self.hook('subagent-stop', agent_type='ship:reviewer--opus')
        self.finish_run()
        # The notification names the closed first run, even after another run starts.
        self.assertEqual(self.cli('run-start', 'light', 'run-2').returncode, 0)
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--opus', 'sha', 'pass').returncode, 0)
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        evidence = owed.read_bytes()
        self.assertEqual(json.loads(self.hook('stop'))['decision'], 'block')
        self.assertEqual(owed.read_bytes(), evidence)

    def test_stop_accounts_original_closed_run_with_new_run_open(self):
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode, 0)
        self.finish_run()
        self.assertEqual(self.cli('run-start', 'light', 'run-2').returncode, 0)
        self.assertEqual(self.hook('stop'), '')
        self.assertIn('run-2', self.cli('status').stdout)

    def test_stop_cycles_consume_distinct_rows_and_preserve_repeat_notifications(self):
        self.hook('subagent-stop', agent_type='ship:reviewer--sol', agent_id='same-agent')
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol@same-agent', 'sha', 'pass').returncode, 0)
        self.assertEqual(self.hook('stop'), '')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        receipts = self.base / 'state/ultraship/accounted.json'
        committed = receipts.read_bytes()
        self.hook('subagent-stop', agent_type='ship:reviewer--sol', agent_id='same-agent')
        fields = owed.read_text().rstrip('\n').split('\t')
        # Keep the historical five-second tolerance in play across separate Stops.
        row_epoch = next(r[0] for r in ledger.rows(self.resolve()) if r[2] == 'ship:reviewer--sol@same-agent')
        fields[0] = str(int(row_epoch) + 4)
        owed.write_text('\t'.join(fields) + '\n')
        evidence = owed.read_bytes()
        self.assertEqual(json.loads(self.hook('stop'))['decision'], 'block')
        self.assertEqual(owed.read_bytes(), evidence)
        self.assertEqual(receipts.read_bytes(), committed)
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol@same-agent', 'sha', 'pass').returncode, 0)
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(len(json.loads(receipts.read_bytes())), 2)
        self.hook('subagent-stop', agent_type='ship:reviewer--sol', agent_id='same-agent')
        evidence = owed.read_bytes()
        self.assertEqual(json.loads(self.hook('stop'))['decision'], 'block')
        self.assertEqual(owed.read_bytes(), evidence)

    def test_receipt_publication_failure_retains_pending_and_retry_consumes_once(self):
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode, 0)
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        evidence = owed.read_bytes()
        receipts = self.base / 'state/ultraship/accounted.json'
        receipts.mkdir()
        self.assertEqual(json.loads(self.hook('stop'))['decision'], 'block')
        self.assertEqual(owed.read_bytes(), evidence)
        receipts.rename(receipts.with_name('retained-receipt-obstruction'))
        self.assertEqual(self.hook('stop'), '')
        # Replaying an already accounted notification also models a crash before clearing.
        owed.write_bytes(evidence)
        committed = receipts.read_bytes()
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(receipts.read_bytes(), committed)
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        evidence = owed.read_bytes()
        self.assertEqual(json.loads(self.hook('stop'))['decision'], 'block')
        self.assertEqual(owed.read_bytes(), evidence)

    def test_legacy_notification_uses_unambiguous_closed_run(self):
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        owed.write_text('\t'.join(owed.read_text().rstrip('\n').split('\t')[:3]) + '\n')
        evidence = owed.read_bytes()
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode, 0)
        self.finish_run()
        self.assertEqual(self.hook('stop'), '')
        receipts = self.base / 'state/ultraship/accounted.json'
        committed = receipts.read_bytes()
        self.assertEqual(len(json.loads(committed)), 1)
        owed.write_bytes(evidence)
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(receipts.read_bytes(), committed)
        self.assertEqual(owed.read_bytes(), b'')

    def test_duplicate_legacy_lines_have_distinct_stable_receipts(self):
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        line = '\t'.join(owed.read_text().rstrip('\n').split('\t')[:3]) + '\n'
        owed.write_text(line * 2)
        evidence = owed.read_bytes()
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode, 0)
        self.assertEqual(json.loads(self.hook('stop'))['decision'], 'block')
        self.assertEqual(owed.read_bytes(), evidence)
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode, 0)
        self.assertEqual(self.hook('stop'), '')
        receipts = self.base / 'state/ultraship/accounted.json'
        committed = receipts.read_bytes()
        self.assertEqual(len(json.loads(committed)), 2)
        owed.write_bytes(evidence)
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(receipts.read_bytes(), committed)
        self.assertEqual(owed.read_bytes(), b'')

    def test_actual_hooks_retain_exact_evidence_until_accounted(self):
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        evidence = owed.read_bytes()
        result_ids = [json.loads(line.split('\t')[3])['id'] for line in evidence.decode().splitlines()]
        self.assertNotEqual(result_ids[0], result_ids[1])
        bad_env = {**self.env, 'SHIP_LEDGER_DIR': 'relative'}
        blocked = json.loads(self.hook('stop', env=bad_env))
        self.assertEqual(blocked['decision'], 'block')
        self.assertIn('no unused ledger row', blocked['reason'])
        self.assertEqual(owed.read_bytes(), evidence)
        self.assertIn('Ledger resolution failed', self.hook('compact', env=bad_env))
        self.assertEqual(owed.read_bytes(), evidence)
        self.assertEqual(self.hook('stop', env=bad_env, stop_hook_active=True), '')
        self.assertEqual(owed.read_bytes(), evidence)
        empty_env = {**self.env, 'SHIP_LEDGER_DIR': str(self.base / 'empty')}
        self.assertEqual(self.hook('stop', env=empty_env), '')
        self.assertEqual(owed.read_bytes(), evidence)
        # A failed CLI append leaves the pending evidence intact.
        obstruction = self.base / 'file-not-directory'
        obstruction.write_text('keep')
        failed_env = {**self.env, 'SHIP_LEDGER_DIR': str(obstruction)}
        self.assertNotEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha',
                                     'pass', env=failed_env).returncode, 0)
        self.assertEqual(self.hook('stop', env=failed_env), '')
        self.assertEqual(owed.read_bytes(), evidence)
        local = self.resolve()
        local.chmod(0o400)
        try:
            if os.geteuid() != 0:
                failed = self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass')
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn('PermissionError', failed.stderr)
                self.assertEqual(self.hook('stop'), '')
                self.assertEqual(owed.read_bytes(), evidence)
        finally:
            local.chmod(0o600)
        self.assertEqual(self.cli('append', 'deep-review', 'unrelated', 'sha', 'pass').returncode, 0)
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(owed.read_bytes(), evidence)
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'owed').returncode, 0)
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(owed.read_bytes(), evidence)
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode, 0)
        receipts = self.base / 'state/ultraship/accounted.json'
        blocked = json.loads(self.hook('stop'))
        self.assertIn(result_ids[1], blocked['reason'])
        self.assertNotIn(result_ids[0], blocked['reason'])
        committed = receipts.read_bytes()
        self.assertEqual({json.loads(key)[2] for key in json.loads(committed)}, {result_ids[0]})
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(owed.read_bytes(), evidence)
        self.assertEqual(receipts.read_bytes(), committed)
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode, 0)
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(owed.read_bytes(), b'')
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(self.legacy.read_bytes(), self.history)


    def test_stop_accounts_two_branch_ledgers_for_one_checkout(self):
        first = self.resolve()
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode, 0)
        self.finish_run()
        closed = first.read_bytes()
        self.git(self.checkout, 'checkout', '-q', '-b', 'second')
        self.assertEqual(self.cli('run-start', 'light', 'run-2').returncode, 0)
        second = self.resolve()
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode, 0)
        active = second.read_bytes()
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        pending = owed.read_bytes()
        self.assertEqual(self.hook('stop'), '')
        receipts = self.base / 'state/ultraship/accounted.json'
        saved = receipts.read_bytes()
        self.assertEqual({r[0] for r in json.loads(saved).values()}, {str(first), str(second)})
        self.assertEqual(first.read_bytes(), closed)
        self.assertEqual(second.read_bytes(), active)
        owed.write_bytes(pending)  # a crash after publishing receipts must replay without a second charge
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(receipts.read_bytes(), saved)
        self.assertEqual(owed.read_bytes(), b'')

    def test_explicit_accounting_records_a_late_result_for_its_closed_run(self):
        first = self.resolve()
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        pending = owed.read_bytes()
        result = json.loads(pending.decode().rstrip().split('\t')[3])
        self.finish_run()
        closed = first.read_bytes()
        self.git(self.checkout, 'checkout', '-q', '-b', 'second')
        self.assertEqual(self.cli('run-start', 'light', 'run-2').returncode, 0)
        second = self.resolve()
        active = second.read_bytes()
        self.assertEqual(json.loads(self.hook('stop'))['decision'], 'block')
        self.assertEqual(owed.read_bytes(), pending)
        recorded = self.cli('account', str(owed), result['id'], 'deep-review', 'ship:reviewer--sol',
                            'reviewed-sha', 'pass', 'Completed review at evidence/report.md')
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        self.assertTrue(first.read_bytes().startswith(closed))
        self.assertEqual(second.read_bytes(), active)
        after = first.read_bytes()
        self.assertEqual(self.cli('account', str(owed), result['id'], 'deep-review', 'ship:reviewer--sol',
                         'reviewed-sha', 'pass', 'Completed review at evidence/report.md').returncode, 0)
        self.assertEqual(first.read_bytes(), after)  # an exact retry appends nothing
        self.assertEqual(self.hook('stop'), '')
        receipts = self.base / 'state/ultraship/accounted.json'
        saved = receipts.read_bytes()
        owed.write_bytes(pending)
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(receipts.read_bytes(), saved)
        self.assertEqual(first.read_bytes(), after)
        self.assertEqual(second.read_bytes(), active)

    def test_explicit_accounting_rejects_wrong_result_or_agent_and_owed_verdict(self):
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        pending = owed.read_bytes()
        result = json.loads(pending.decode().rstrip().split('\t')[3])
        self.finish_run()
        home = self.resolve()
        closed = home.read_bytes()
        for identifier, agent, verdict in (('absent', 'ship:reviewer--sol', 'pass'),
                                           (result['id'], 'ship:reviewer--opus', 'pass'),
                                           (result['id'], 'ship:reviewer--sol', 'owed')):
            with self.subTest(identifier=identifier, agent=agent, verdict=verdict):
                attempt = self.cli('account', str(owed), identifier, 'deep-review', agent, 'sha', verdict, 'report.md')
                self.assertNotEqual(attempt.returncode, 0)
                self.assertEqual(home.read_bytes(), closed)
                self.assertEqual(owed.read_bytes(), pending)


    def test_closed_run_accounting_cannot_cover_another_result(self):
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        pending = owed.read_bytes()
        result = json.loads(pending.decode().splitlines()[0].split('\t')[3])
        self.finish_run()
        recorded = self.cli('account', str(owed), result['id'], 'deep-review', 'ship:reviewer--sol',
                            'sha', 'pass', 'Completed review at evidence/report.md')
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        self.assertEqual(json.loads(self.hook('stop'))['decision'], 'block')
        self.assertEqual(owed.read_bytes(), pending)
        receipts = json.loads((owed.parent.parent / 'accounted.json').read_text())
        self.assertEqual({json.loads(key)[2] for key in receipts}, {result['id']})

    def test_correct_binding_finds_receipt_while_other_evidence_stays_pending(self):
        self.hook('subagent-stop', agent_type='ship:reviewer--sol', agent_id='missing')
        self.hook('subagent-stop', agent_type='ship:reviewer--sol', agent_id='complete')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        pending = owed.read_bytes()
        missing, complete = (json.loads(row.split(b'\t')[3])['id'] for row in pending.splitlines())
        receipts = owed.parent.parent / 'accounted.json'
        receipts.write_text('{}')
        self.finish_run()
        recorded = self.cli('account', str(owed), complete, 'review', 'ship:reviewer--sol',
                            'sha', 'pass', 'Completed review')
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        home = self.resolve()
        explicit = str(len(ledger.rows(home)))
        blocked = json.loads(self.hook('stop'))
        self.assertIn(missing, blocked['reason'])
        self.assertEqual({json.loads(k)[2] for k in json.loads(receipts.read_text())}, {complete})
        fixed = self.cli('correct-binding', complete, explicit, 'keep')
        self.assertEqual(fixed.returncode, 0, fixed.stderr)
        self.assertNotIn(complete, blocked['reason'])
        refused = self.cli('correct-binding', missing, explicit, 'keep')
        self.assertIn('has no Stop receipt', refused.stderr)
        self.assertIn('run Stop to publish its receipt', refused.stderr)
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(owed.read_bytes(), pending)

    def test_correct_binding_moves_credit_to_its_own_explicit_row(self):
        self.hook('subagent-stop', agent_type='ship:reviewer--sol', agent_id='complete')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        pending = owed.read_bytes()
        result = json.loads(pending.split(b'\t')[3])
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol@complete',
                                  'sha', 'pass').returncode, 0)
        self.assertEqual(self.hook('stop'), '')
        self.finish_run()
        owed.write_bytes(pending)
        self.assertEqual(self.cli('account', str(owed), result['id'], 'review', 'ship:reviewer--sol',
                                  'sha', 'pass', 'Completed review').returncode, 0)
        home = self.resolve()
        explicit = str(len(ledger.rows(home)))
        fixed = self.cli('correct-binding', result['id'], explicit, 'bind exact result')
        self.assertEqual(fixed.returncode, 0, fixed.stderr)
        self.assertEqual(json.loads(self.bound()[result['id']])['step'], 'review')
        self.assertEqual(self.hook('stop'), '')

    def auto_owed(self, entries):
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        transcript = self.base / 's1/subagents/agent-reviewer.jsonl'
        transcript.parent.mkdir(parents=True, exist_ok=True)
        self.hook('subagent-stop', agent_type='ship:reviewer--sol', agent_id='reviewer',
                  **({'agent_transcript_path': str(transcript)} if entries is not None else {}))
        epoch, _, _, raw = owed.read_text().splitlines()[-1].split('\t')
        result = json.loads(raw)
        if entries is not None:
            lines = []
            for offset, role, content in entries:
                timestamp = datetime.fromtimestamp(int(epoch) + offset, timezone.utc).isoformat()
                if isinstance(content, str) and role == 'assistant':
                    content = [{'type': 'text', 'text': content}]
                lines.append(json.dumps({'timestamp': timestamp, 'type': role,
                                         'message': {'content': content}}))
            transcript.write_text(''.join(line + '\n' for line in lines))
        return owed, transcript, result, int(epoch)

    def assert_account_auto_refuses_session(self, session):
        sha = 'ab' * 20
        owed, _, _, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Verdict: PASS {sha}')])
        home = self.resolve()
        receipts = self.base / 'state/ultraship/accounted.json'
        receipts.write_bytes(b'{}\n')
        paths = (home, receipts, owed)
        before = [path.read_bytes() for path in paths]
        env = self.env.copy()
        if session is None:
            del env['CLAUDE_CODE_SESSION_ID']
        else:
            env['CLAUDE_CODE_SESSION_ID'] = session
        refused = self.cli('account-auto', str(owed), env=env)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(refused.stdout, '')
        self.assertEqual(refused.stderr.splitlines(), [
            'account-auto requires CLAUDE_CODE_SESSION_ID to match the owed file session.'])
        self.assertEqual([path.read_bytes() for path in paths], before)
        allowed = self.cli('account-auto', str(owed))
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertIn('1 accounted, 0 pending\n', allowed.stdout)
        self.assertNotEqual(home.read_bytes(), before[0])

    def test_account_auto_refuses_foreign_session(self):
        self.assert_account_auto_refuses_session('s2')

    def test_account_auto_refuses_missing_session(self):
        self.assert_account_auto_refuses_session(None)

    def test_account_auto_refuses_empty_session(self):
        self.assert_account_auto_refuses_session('')

    def test_account_auto_refuses_a_symlinked_owed_file(self):
        owed, _, _, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Verdict: PASS {"ab" * 20}')])
        target = owed.rename(owed.with_name('retained.tsv'))
        owed.symlink_to(target)
        home = self.resolve()
        receipts = self.base / 'state/ultraship/accounted.json'
        receipts.write_bytes(b'{}\n')
        paths = (home, receipts, target)
        before = [path.read_bytes() for path in paths]
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(Path, 'read_text', side_effect=AssertionError('unexpected read')):
            with self.assertRaisesRegex(SystemExit, 'account-auto refuses a symlinked owed file'):
                ledger.account_auto(owed)
        self.assertTrue(owed.is_symlink())
        self.assertEqual([path.read_bytes() for path in paths], before)

    def test_account_auto_reads_the_owed_file_once(self):
        owed, _, _, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Verdict: PASS {"ab" * 20}')])
        home = self.resolve()
        output = io.StringIO()
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(ledger, 'STATE', self.base / 'state/ultraship'), \
                mock.patch.object(ledger.os, 'open', wraps=os.open) as fd_open, \
                mock.patch.object(Path, 'open', autospec=True, side_effect=Path.open) as path_open, \
                mock.patch('sys.stdout', output):
            ledger.account_auto(owed)
        reads = [call for spy in (fd_open, path_open) for call in spy.call_args_list
                 if call.args[0] == owed]
        self.assertEqual(len(reads), 1)
        self.assertIn('1 accounted, 0 pending\n', output.getvalue())
        self.assertEqual(ledger.rows(home)[-1][1], 'account-result')

    def test_account_auto_uses_own_final_text_and_skips_existing_accounting(self):
        sha = 'ab' * 20
        owed, transcript, result, epoch = self.auto_owed([
            (-5, 'user', 'Review the patch.'),
            (-4, 'assistant', 'FAIL ' + 'cd' * 20),
            (-3, 'assistant', [{'type': 'text', 'text': 'FAIL'}, {'type': 'tool_use'}]),
            (-2, 'user', [{'type': 'tool_result', 'content': 'FAIL'}]),
            (-1, 'assistant', 'Other findings; reviewed ' + sha),
            (1, 'assistant', '**OVERALL:** PASS ' + sha.upper()),
            (2, 'user', [{'type': 'text', 'text': 'Review another commit.'}]),
            (3, 'assistant', 'Verdict: FAIL ' + 'ef' * 20),
        ])
        expected = f"accounted {result['id']} ship:reviewer--sol@reviewer {sha} pass\n1 accounted, 0 pending\n"
        home = self.resolve()
        auto = self.cli('account-auto', str(owed))
        self.assertEqual(auto.returncode, 0, auto.stderr)
        self.assertEqual(auto.stdout, expected)
        row = ledger.rows(home)[-1]
        self.assertEqual(row[1:5], ['account-result', 'ship:reviewer--sol@reviewer', sha, 'pass'])
        note = json.loads(row[5])
        self.assertEqual(note['step'], 'review')
        self.assertEqual(note['evidence'], f'{transcript} at {datetime.fromtimestamp(epoch, timezone.utc).isoformat()}: pass')
        transcript.unlink()
        saved = home.read_bytes()
        self.assertEqual(self.cli('account-auto', str(owed)).stdout, expected)
        pending = owed.read_bytes()
        self.assertEqual(self.hook('stop'), '')
        owed.write_bytes(pending)
        self.assertEqual(self.cli('account-auto', str(owed)).stdout, expected)
        self.assertEqual(home.read_bytes(), saved)

    def test_account_auto_requires_own_canonical_transcript_path(self):
        sha = 'ab' * 20
        for case, relative in (
            ('wrong agent', 's1/subagents/agent-other.jsonl'),
            ('wrong directory', 's1/reviews/agent-reviewer.jsonl'),
            ('wrong session', 's2/subagents/agent-reviewer.jsonl'),
            ('relative', None),
            ('symlink', None),
        ):
            with self.subTest(case=case):
                owed, transcript, result, _ = self.auto_owed([
                    (-2, 'user', 'Review.'), (-1, 'assistant', f'Verdict: PASS {sha}')])
                if relative:
                    source = self.base / relative
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_bytes(transcript.read_bytes())
                elif case == 'relative':
                    source = Path(os.path.relpath(transcript, self.checkout))
                else:
                    source = transcript
                    target = transcript.with_name('target.jsonl')
                    transcript.replace(target)
                    transcript.symlink_to(target)
                fields = owed.read_text().rstrip('\n').split('\t')
                fields[-1] = json.dumps({**result, 'agent_transcript_path': str(source)})
                owed.write_text('\t'.join(fields) + '\n')
                auto = self.cli('account-auto', str(owed))
                owed.write_text('')
                self.assertEqual(auto.returncode, 0, auto.stderr)
                self.assertEqual(auto.stdout.splitlines(), [
                    f"pending {result['id']} transcript path does not match the recorded agent and session",
                    '0 accounted, 1 pending'])

    def test_account_auto_refuses_noncanonical_transcript_spelling(self):
        sha = 'ab' * 20
        for segment in ('/./', '//', '/s1/../'):
            with self.subTest(segment=segment):
                owed, transcript, result, _ = self.auto_owed([
                    (-2, 'user', 'Review.'), (-1, 'assistant', f'Verdict: PASS {sha}')])
                source = f'{self.base}{segment}{transcript.relative_to(self.base)}'
                fields = owed.read_text().rstrip('\n').split('\t')
                fields[-1] = json.dumps({**result, 'agent_transcript_path': source})
                owed.write_text('\t'.join(fields) + '\n')
                home = self.resolve()
                before = (owed.read_bytes(), home.read_bytes())
                auto = self.cli('account-auto', str(owed))
                self.assertEqual((owed.read_bytes(), home.read_bytes()), before)
                self.assertEqual(auto.returncode, 0, auto.stderr)
                self.assertEqual(auto.stdout.splitlines(), [
                    f"pending {result['id']} transcript path does not match the recorded agent and session",
                    '0 accounted, 1 pending'])
                owed.write_text('')

    def test_final_turn_text_refuses_a_transcript_symlink(self):
        _, transcript, _, epoch = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', 'Verdict: PASS ' + 'ab' * 20)])
        target = transcript.with_name('target.jsonl')
        transcript.replace(target)
        transcript.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'transcript unavailable'):
            ledger.final_turn_text(transcript, epoch, {})

    def test_account_auto_excludes_turn_after_image_prompt_in_grace_second(self):
        sha = 'ab' * 20
        owed, _, result, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', 'No result yet.'),
            (0.5, 'user', [{'type': 'image'}]), (1, 'assistant', f'Verdict: PASS {sha}'),
        ])
        auto = self.cli('account-auto', str(owed))
        self.assertEqual(auto.returncode, 0, auto.stderr)
        self.assertEqual(auto.stdout.splitlines(), [f"pending {result['id']} no final turn text",
                                                   '0 accounted, 1 pending'])

    def test_account_auto_checks_the_first_verdict_word_and_rejects_negated_pass(self):
        sha = 'ab' * 20
        for label, verdict in (
            ('Verdict: did not pass', None),
            ('OVERALL: not pass', None),
            ('Verdict: checks PASS', None),
            ('Verdict: PASS but not complete', None),
            ('Verdict: PASS, no evidence', None),
            ('Verdict: PASS, never verified', None),
            ('Verdict: PASS without evidence', None),
            ("Verdict: PASS but didn't verify", None),
            ('Verdict: PASS but wasn’t verified', None),
            ('Verdict: PASS, PASS', None),
            ('OVERALL: FAIL and pass', None),
            ('**OVERALL:** PASS', 'pass'),
            ('Verdict: `_PASS_`', 'pass'),
            ('OVERALL: FAIL', 'fail'),
        ):
            with self.subTest(label=label):
                owed, _, result, _ = self.auto_owed([
                    (-2, 'user', 'Review.'), (-1, 'assistant', f'{label} {sha}')])
                auto = self.cli('account-auto', str(owed))
                owed.write_text('')
                self.assertEqual(auto.returncode, 0, auto.stderr)
                if verdict:
                    expected = [f"accounted {result['id']} ship:reviewer--sol@reviewer {sha} {verdict}",
                                '1 accounted, 0 pending']
                else:
                    expected = [f"pending {result['id']} expected one verdict", '0 accounted, 1 pending']
                self.assertEqual(auto.stdout.splitlines(), expected)

    def test_account_auto_normalizes_labeled_verdicts(self):
        sha = 'ab' * 20
        for label, verdict in (
            ('Verdict: PASS', 'pass'),
            ('OVERALL: FAIL', 'fail'),
            ('verdict: findings', 'findings'),
            ('verdict: pass', 'pass'),
            ('Verdict: PASS checks', 'pass'),
            ('Verdict: failed', 'fail'),
            ('Verdict: fails', 'fail'),
            ('Verdict: Failing', 'fail'),
            ('Verdict: FAILURE', 'fail'),
            ('  > - **Verdict:** FAIL and Findings', 'findings'),
        ):
            with self.subTest(label=label):
                owed, _, result, _ = self.auto_owed([(-2, 'user', 'Review.'), (-1, 'assistant', f'{label} {sha}')])
                auto = self.cli('account-auto', str(owed))
                self.assertEqual(auto.returncode, 0, auto.stderr)
                self.assertEqual(auto.stdout, f"accounted {result['id']} ship:reviewer--sol@reviewer {sha} {verdict}\n"
                                              '1 accounted, 0 pending\n')
                self.assertEqual(ledger.rows(self.resolve())[-1][4], verdict)
                owed.write_text('')

    def test_account_auto_leaves_unclear_results_pending(self):
        sha = 'ab' * 20
        prompt = (-5, 'user', [{'type': 'text', 'text': 'Review this commit.'}])
        for case, entries, reason in (
            ('no transcript', None, 'no transcript'),
            ('missing file', [prompt], 'no transcript'),
            ('no turn', [(-1, 'assistant', f'PASS {sha}')], 'no final turn text'),
            ('later verdict', [(-8, 'user', 'Earlier review.'), (-7, 'assistant', f'PASS {sha}'),
                               prompt, (-1, 'assistant', 'No result yet.'),
                               (3, 'user', 'Later review.'), (4, 'assistant', f'PASS {sha}')], 'expected one commit'),
            ('later turn in grace second', [prompt, (-1, 'assistant', 'No result yet.'),
                                           (0.5, 'user', 'Later review.'),
                                           (1, 'assistant', f'PASS {sha}')], 'no final turn text'),
            ('last tool', [prompt, (-2, 'assistant', f'PASS {sha}'),
                           (-1, 'assistant', [{'type': 'tool_use'}])], 'no final turn text'),
            ('no commit', [prompt, (-1, 'assistant', 'PASS abcd1234')], 'expected one commit'),
            ('several commits', [prompt, (-1, 'assistant', 'PASS ' + sha + ' ' + 'cd' * 20)], 'expected one commit'),
            ('no verdict', [prompt, (-1, 'assistant', f'bypass PASSING {sha}')], 'expected one verdict'),
            ('several verdicts', [prompt, (-1, 'assistant', f'PASS followed by findings {sha}')], 'expected one verdict'),
            ('conflicting labels', [prompt, (-1, 'assistant', f'OVERALL: PASS\nVerdict: FAIL {sha}')], 'expected one verdict'),
            ('repeated label', [prompt, (-1, 'assistant', f'OVERALL: PASS\nVerdict: PASS {sha}')], 'expected one verdict'),
            ('unclear label', [prompt, (-1, 'assistant', f'Verdict: bypass PASSING {sha}')], 'expected one verdict'),
            ('verdict on next line', [prompt, (-1, 'assistant', f'Verdict:\nPASS {sha}')], 'expected one verdict'),
            ('pass and fail', [prompt, (-1, 'assistant', f'Verdict: PASS and fail {sha}')], 'expected one verdict'),
            ('pass and failed', [prompt, (-1, 'assistant', f'Verdict: pass, 2 FAILED {sha}')], 'expected one verdict'),
            ('pass and fails', [prompt, (-1, 'assistant', f'Verdict: pass, one fails {sha}')], 'expected one verdict'),
            ('pass and findings', [prompt, (-1, 'assistant', f'Verdict: pass with FINDINGS {sha}')], 'expected one verdict'),
            ('pass without label', [prompt, (-1, 'assistant', f'tests pass {sha}')], 'expected one verdict'),
            ('failure without label', [prompt, (-1, 'assistant', f'tests pass, 2 failed {sha}')], 'expected one verdict'),
            ('inline label', [prompt, (-1, 'assistant', f'my verdict: pass {sha}')], 'expected one verdict'),
            ('parse error', [prompt], 'transcript parse error'),
        ):
            with self.subTest(case=case):
                owed, transcript, result, _ = self.auto_owed(entries)
                if case == 'missing file':
                    transcript.unlink()
                if case == 'parse error':
                    transcript.write_text('{bad json\n')
                before = (owed.read_bytes(), self.resolve().read_bytes())
                auto = self.cli('account-auto', str(owed))
                self.assertEqual(auto.returncode, 0, auto.stderr)
                self.assertEqual(auto.stdout, f"pending {result['id']} {reason}\n0 accounted, 1 pending\n")
                self.assertEqual((owed.read_bytes(), self.resolve().read_bytes()), before)
                owed.write_text('')

    def test_account_auto_counts_underscored_and_backticked_commits(self):
        sha, other = 'ab' * 20, 'cd' * 20
        owed, _, result, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Verdict: PASS _{sha}_ {other}')])
        auto = self.cli('account-auto', str(owed))
        self.assertEqual(auto.returncode, 0, auto.stderr)
        self.assertEqual(auto.stdout.splitlines(), [f"pending {result['id']} expected one commit",
                                                   '0 accounted, 1 pending'])
        owed.write_text('')
        _, _, result, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Verdict: PASS _{sha}_ `{sha.upper()}`')])
        auto = self.cli('account-auto', str(owed))
        self.assertEqual(auto.returncode, 0, auto.stderr)
        self.assertEqual(auto.stdout.splitlines(), [
            f"accounted {result['id']} ship:reviewer--sol@reviewer {sha} pass", '1 accounted, 0 pending'])

    def test_account_auto_preserves_account_run_refusal_and_continues(self):
        sha = 'ab' * 20
        owed, _, invalid, _ = self.auto_owed([(-2, 'user', 'Review.'), (-1, 'assistant', f'Verdict: FAIL {sha}')])
        fields = owed.read_text().rstrip('\n').split('\t')
        invalid['run'] = [0, 'wrong']
        fields[-1] = json.dumps(invalid)
        owed.write_text('\t'.join(fields) + '\n')
        _, _, valid, _ = self.auto_owed([(-2, 'user', 'Review.'), (-1, 'assistant', f'Verdict: FAIL {sha}')])
        auto = self.cli('account-auto', str(owed))
        self.assertEqual(auto.returncode, 0, auto.stderr)
        self.assertEqual(auto.stdout.splitlines(), [f"pending {invalid['id']} recorded run is missing or differs",
                         f"accounted {valid['id']} ship:reviewer--sol@reviewer {sha} fail", '1 accounted, 1 pending'])

    def test_account_auto_reads_the_tail_in_bounded_chunks(self):
        sha = 'ab' * 20
        owed, transcript, result, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Verdict: findings {sha}' + ' ' * (128 * 1024))])
        prefix = transcript.read_bytes()
        cap = 64 * 1024 * 1024
        with transcript.open('wb') as fh:
            fh.seek(cap * 2)
            fh.write(b'\n' + prefix)
        auto = self.cli('account-auto', str(owed))
        self.assertEqual(auto.returncode, 0, auto.stderr)
        self.assertIn(f"accounted {result['id']} ship:reviewer--sol@reviewer {sha} findings", auto.stdout)
        owed, transcript, result, _ = self.auto_owed([(-2, 'user', 'Review.'), (-1, 'assistant', f'pass {sha}')])
        # The last line crosses the scan bound without a delimiter.
        with transcript.open('r+b') as fh:
            fh.seek(cap * 2, io.SEEK_END)
            fh.write(b'\n')
        auto = self.cli('account-auto', str(owed))
        self.assertEqual(auto.returncode, 0, auto.stderr)
        self.assertIn(f"pending {result['id']} transcript scan limit reached", auto.stdout)

    def test_account_auto_shortcuts_require_the_recorded_run_start(self):
        owed, _, result, _ = self.auto_owed(None)
        pending = owed.read_bytes()
        record = self.cli('account', str(owed), result['id'], 'review', 'ship:reviewer--sol',
                          'ab' * 20, 'pass', 'Completed review')
        self.assertEqual(record.returncode, 0, record.stderr)
        self.assertEqual(self.hook('stop'), '')
        owed.write_bytes(pending)
        home = self.resolve()
        home.write_text(home.read_text().replace('run-1 /board', 'different-run /board'))
        receipts = owed.parent.parent / 'accounted.json'
        for shortcut in ('receipt', 'account-result'):
            with self.subTest(shortcut=shortcut):
                auto = self.cli('account-auto', str(owed))
                self.assertEqual(auto.returncode, 0, auto.stderr)
                self.assertEqual(auto.stdout.splitlines(), [
                    f"pending {result['id']} recorded run is missing or differs", '0 accounted, 1 pending'])
            receipts.unlink(missing_ok=True)

    def test_account_auto_requires_the_receipts_ledger_and_run_to_match(self):
        owed, _, result, _ = self.auto_owed(None)
        pending = owed.read_bytes()
        record = self.cli('account', str(owed), result['id'], 'review', 'ship:reviewer--sol',
                          'ab' * 20, 'pass', 'Completed review')
        self.assertEqual(record.returncode, 0, record.stderr)
        self.assertEqual(self.hook('stop'), '')
        owed.write_bytes(pending)
        receipts = owed.parent.parent / 'accounted.json'
        saved = receipts.read_text()
        other = self.base / 'other.tsv'
        other.write_bytes(self.resolve().read_bytes())
        for index, wrong in ((0, str(other)), (1, [0, 'other-run'])):
            with self.subTest(field=index):
                data = json.loads(saved)
                next(iter(data.values()))[index] = wrong
                receipts.write_text(json.dumps(data))
                auto = self.cli('account-auto', str(owed))
                self.assertEqual(auto.returncode, 0, auto.stderr)
                self.assertEqual(auto.stdout.splitlines(), [
                    f"pending {result['id']} Stop receipt names a different ledger or run", '0 accounted, 1 pending'])

    def test_account_auto_refuses_a_receipt_row_outside_its_run(self):
        owed, _, result, _ = self.auto_owed(None)
        self.finish_run()
        self.assertEqual(self.cli('run-start', 'light', 'run-2').returncode, 0)
        agent = 'ship:reviewer--sol'
        self.assertEqual(self.cli('append', 'deep-review', agent + '@reviewer', 'sha', 'pass').returncode, 0)
        home = self.resolve()
        history = ledger.rows(home)
        key = json.dumps([str(owed), str(self.checkout), result['id']])
        receipts = owed.parent.parent / 'accounted.json'
        identity = ledger.run_identity(len(history) - 1, history[-1])
        receipts.write_text(json.dumps({key: [str(home), result['run'], identity]}))
        auto = self.cli('account-auto', str(owed))
        self.assertEqual(auto.returncode, 0, auto.stderr)
        self.assertEqual(auto.stdout.splitlines(), [
            f"pending {result['id']} Stop receipt row belongs to another run", '0 accounted, 1 pending'])

    def test_stop_publishes_no_receipt_when_a_saved_receipt_has_invalid_shape(self):
        owed, _, first, _ = self.auto_owed(None)
        record = self.cli('account', str(owed), first['id'], 'review', 'ship:reviewer--sol',
                          'ab' * 20, 'pass', 'Completed review')
        self.assertEqual(record.returncode, 0, record.stderr)
        _, _, corrupt, _ = self.auto_owed(None)
        pending = owed.read_bytes()
        key = json.dumps([str(owed), str(self.checkout), corrupt['id']])
        receipts = owed.parent.parent / 'accounted.json'
        saved = json.dumps({key: [corrupt['ledger'], corrupt['run'], []]}).encode()
        receipts.write_bytes(saved)
        blocked = json.loads(self.hook('stop'))
        self.assertEqual(blocked['decision'], 'block')
        self.assertIn('Accounting receipt has an invalid shape', blocked['reason'])
        self.assertEqual(receipts.read_bytes(), saved)
        self.assertEqual(owed.read_bytes(), pending)

    def test_stop_publishes_no_receipt_when_a_receipted_row_changes(self):
        agent = 'ship:reviewer--sol'
        self.hook('subagent-stop', agent_type=agent, agent_id='reviewer')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        first = owed.read_bytes()
        self.assertEqual(self.cli('append', 'deep-review', agent + '@reviewer', 'sha', 'pass').returncode, 0)
        self.assertEqual(self.hook('stop'), '')
        receipts = owed.parent.parent / 'accounted.json'
        saved = receipts.read_bytes()
        home = self.resolve()
        home.write_text(home.read_text().replace('\tsha\tpass\t\n', '\tnew-sha\tpass\t\n'))
        self.hook('subagent-stop', agent_type=agent, agent_id='reviewer')
        pending = first + owed.read_bytes()
        owed.write_bytes(pending)
        blocked = json.loads(self.hook('stop'))
        self.assertEqual(blocked['decision'], 'block')
        self.assertIn('Accounting receipt row is missing or differs', blocked['reason'])
        self.assertEqual(receipts.read_bytes(), saved)
        self.assertEqual(owed.read_bytes(), pending)

    def test_account_auto_skill_describes_evidence_requirements(self):
        skill = (LEDGER.parent.parent / 'SKILL.md').read_text()
        guidance = skill.split('Use the Stop diagnostic\'s `account-auto` command', 1)[1].split('`correct-binding`', 1)[0]
        for phrase in ('`<session>/subagents/agent-<agent-id>.jsonl`', 'The first word must be a verdict word.',
                       'exactly one `run-start` row', 'The receipt must name the same ledger and run.'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, guidance)

    def test_account_auto_skill_describes_path_row_and_commit_boundaries(self):
        skill = (LEDGER.parent.parent / 'SKILL.md').read_text()
        guidance = skill.split('Use the Stop diagnostic\'s `account-auto` command', 1)[1].split('`correct-binding`', 1)[0]
        for phrase in ('match its normalized and resolved forms', '`..` segments or repeated slashes',
                       'The first `run-end` or next `run-start`', 'outside that range',
                       'exactly one distinct 40-digit hexadecimal commit SHA', 'underscores or backticks'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, guidance)

    def test_accounting_refuses_a_changed_bound_run(self):
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        result = json.loads(owed.read_text().splitlines()[0].split('\t')[3])
        self.finish_run()
        home = self.resolve()
        home.write_text(home.read_text().replace('run-1 /board', 'other-run /board'))
        changed = home.read_bytes()
        recorded = self.cli('account', str(owed), result['id'], 'deep-review', 'ship:reviewer--sol',
                            'sha', 'pass', 'Completed review at evidence/report.md')
        self.assertNotEqual(recorded.returncode, 0)
        self.assertIn('recorded run is missing or differs', recorded.stderr)
        self.assertEqual(home.read_bytes(), changed)


    def test_exact_result_record_keeps_the_ordinary_row_for_its_sibling(self):
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        pending = owed.read_bytes()
        first = json.loads(pending.decode().splitlines()[0].split('\t')[3])
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode, 0)
        self.finish_run()
        recorded = self.cli('account', str(owed), first['id'], 'deep-review', 'ship:reviewer--sol',
                            'sha', 'pass', 'First result report.md')
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        self.assertEqual(self.hook('stop'), '')
        receipts = json.loads((self.base / 'state/ultraship/accounted.json').read_text())
        self.assertEqual(len(receipts), 2)
        history = ledger.rows(self.resolve())
        first_receipt = next(v for k, v in receipts.items() if json.loads(k)[2] == first['id'])
        self.assertEqual(history[first_receipt[2][0]][1], 'account-result')
        owed.write_bytes(pending)
        self.assertEqual(self.hook('stop'), '')

    def test_explicit_accounting_keeps_symlinked_state_path_receipt_identity(self):
        real = self.base / 'state-real'
        real.mkdir()
        link = self.base / 'state-link'
        link.symlink_to(real, target_is_directory=True)
        self.env['XDG_STATE_HOME'] = str(link)
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        owed = link / 'ultraship/owed/s1.tsv'
        pending = owed.read_bytes()
        result = json.loads(pending.decode().splitlines()[0].split('\t')[3])
        self.finish_run()
        recorded = self.cli('account', str(owed), result['id'], 'deep-review', 'ship:reviewer--sol',
                            'sha', 'pass', 'Completed report.md')
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        self.assertEqual(self.hook('stop'), '')
        receipt_path = link / 'ultraship/accounted.json'
        receipts = receipt_path.read_bytes()
        self.assertEqual(json.loads(next(iter(json.loads(receipts))))[0], str(owed))
        owed.write_bytes(pending)
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(receipt_path.read_bytes(), receipts)

    def test_close_results_bind_only_to_their_own_agent_rows(self):
        # Two reviews of one agent type finish seconds apart; each result binds to its own agent's row.
        self.hook('subagent-stop', agent_type='ship:reviewer--sol', agent_id='capacity-40bf7a98')
        self.hook('subagent-stop', agent_type='ship:reviewer--sol', agent_id='scrub-4a111b8e')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        ids = {json.loads(line.split('\t')[3])['agent_id']: json.loads(line.split('\t')[3])['id']
               for line in owed.read_text().splitlines()}
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol@scrub-4a111b8e',
                                  'sha', 'findings').returncode, 0)
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol@capacity-40bf7a98',
                                  'sha', 'pass').returncode, 0)
        self.assertEqual(self.hook('stop'), '')
        receipts = json.loads((self.base / 'state/ultraship/accounted.json').read_text())
        history = ledger.rows(self.resolve())
        bound = {json.loads(k)[2]: history[v[2][0]] for k, v in receipts.items()}
        self.assertEqual(bound[ids['capacity-40bf7a98']][2:5], ['ship:reviewer--sol@capacity-40bf7a98', 'sha', 'pass'])
        self.assertEqual(bound[ids['scrub-4a111b8e']][2:5], ['ship:reviewer--sol@scrub-4a111b8e', 'sha', 'findings'])
        # A result never binds to a row without its agent ID or with another agent's ID.
        self.hook('subagent-stop', agent_type='ship:reviewer--sol', agent_id='other')
        evidence = owed.read_bytes()
        blocked = json.loads(self.hook('stop'))
        self.assertIn('ship:reviewer--sol@other', blocked['reason'])
        for agent in ('ship:reviewer--sol', 'ship:reviewer--sol@capacity-40bf7a98'):
            self.assertEqual(self.cli('append', 'deep-review', agent, 'sha', 'pass').returncode, 0)
            self.assertEqual(self.hook('stop'), '')
            self.assertEqual(owed.read_bytes(), evidence)

    def swapped_pair(self):
        """Two legacy results with no agent ID take each other's rows; return their IDs and the pending bytes."""
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        pending = owed.read_bytes()
        scrub, capacity = (json.loads(line.split('\t')[3])['id'] for line in pending.decode().splitlines())
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass', 'capacity').returncode, 0)
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'findings', 'scrub').returncode, 0)
        self.assertEqual(self.hook('stop'), '')
        return scrub, capacity, pending

    def bound(self):
        rows = ledger.rows(self.resolve())
        receipts = json.loads((self.base / 'state/ultraship/accounted.json').read_text())
        return {json.loads(k)[2]: rows[v[2][0]][5] for k, v in receipts.items()}

    def line_of(self, note):
        return str(next(i for i, r in enumerate(ledger.rows(self.resolve())) if r[5:] == [note]) + 1)

    def test_correct_binding_moves_credit_with_an_appended_audit_row(self):
        scrub, capacity, pending = self.swapped_pair()
        receipt_path = self.base / 'state/ultraship/accounted.json'
        home = self.resolve()
        self.assertEqual(self.bound(), {scrub: 'capacity', capacity: 'scrub'})
        before = home.read_bytes()
        self.assertNotEqual(self.cli('correct-binding', scrub, self.line_of('scrub'), ' ').returncode, 0)
        self.assertIn('result ID must match exactly one', self.cli('correct-binding', 'absent', self.line_of('scrub'), 'swap').stderr)
        self.assertEqual(home.read_bytes(), before)
        fixed = self.cli('correct-binding', scrub, self.line_of('scrub'), 'scrub findings bound to the capacity PASS')
        self.assertEqual(fixed.returncode, 0, fixed.stderr)
        self.assertEqual(self.bound(), {scrub: 'scrub', capacity: 'capacity'})
        after = home.read_bytes()
        self.assertTrue(after.startswith(before))
        audit = ledger.rows(home)[-1]
        self.assertEqual(audit[1:5], ['correct-binding', '-', 'sha', 'corrected'])
        note = json.loads(audit[5])
        self.assertEqual((note['agent'], note['reason']), ('ship:reviewer--sol', 'scrub findings bound to the capacity PASS'))
        self.assertEqual(json.loads(note['swap'])[2], capacity)
        saved = receipt_path.read_bytes()
        self.assertEqual(len(json.loads(saved)[next(iter(json.loads(saved)))]), 3)
        self.assertEqual(self.cli('correct-binding', scrub, self.line_of('scrub'), 'retry').returncode, 0)
        self.assertEqual((home.read_bytes(), receipt_path.read_bytes()), (after, saved))  # an exact retry changes nothing
        # A later result never takes the audit row as its review.
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        self.assertEqual(json.loads(self.hook('stop'))['decision'], 'block')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        owed.write_bytes(pending)  # a replay validates the corrected receipts without a second charge
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(receipt_path.read_bytes(), saved)

    def test_correct_binding_retry_after_a_crash_appends_no_second_audit_row(self):
        scrub, capacity, _ = self.swapped_pair()
        receipt_path = self.base / 'state/ultraship/accounted.json'
        wrong = receipt_path.read_bytes()
        self.assertEqual(self.cli('correct-binding', scrub, self.line_of('scrub'), 'swap').returncode, 0)
        audited = self.resolve().read_bytes()
        receipt_path.write_bytes(wrong)  # the audit row landed and the receipts did not
        self.assertEqual(self.cli('correct-binding', scrub, self.line_of('scrub'), 'swap').returncode, 0)
        self.assertEqual(self.resolve().read_bytes(), audited)
        self.assertEqual(self.bound(), {scrub: 'scrub', capacity: 'capacity'})
        # A later, different move still appends its own audit row.
        self.assertEqual(self.cli('correct-binding', scrub, self.line_of('capacity'), 'undo').returncode, 0)
        self.assertEqual(json.loads(ledger.rows(self.resolve())[-1][5])['reason'], 'undo')

    def test_correct_binding_refuses_each_unfit_target(self):
        scrub, capacity, _ = self.swapped_pair()
        for note, agent, verdict in (('owed-row', 'ship:reviewer--sol', 'owed'),
                                     ('other-type', 'ship:reviewer--opus', 'pass'),
                                     ('other-id', 'ship:reviewer--sol@zzz', 'pass')):
            self.assertEqual(self.cli('append', 'deep-review', agent, 'sha', verdict, note).returncode, 0)
        for step in ledger.MARKS:
            self.assertNotEqual(self.cli('append', step, 'ship:reviewer--sol', 'sha', 'pass').returncode, 0)
        self.finish_run()
        self.assertEqual(self.cli('run-start', 'light', 'run-2').returncode, 0)
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass', 'next-run').returncode, 0)
        home = self.resolve()
        before = (home.read_bytes(), (self.base / 'state/ultraship/accounted.json').read_bytes())
        for note in ('owed-row', 'other-type', 'other-id', 'next-run'):
            with self.subTest(target=note):
                refused = self.cli('correct-binding', scrub, self.line_of(note), 'move')
                self.assertIn('target line must be a completed review row', refused.stderr)
        self.assertIn('target line must be', self.cli('correct-binding', scrub, '999', 'move').stderr)
        self.assertEqual((home.read_bytes(), (self.base / 'state/ultraship/accounted.json').read_bytes()), before)
        with home.open('ab') as fh:
            fh.write(b'\n')  # a blank line before the next row makes file lines and rows differ
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass', 'after-blank').returncode, 0)
        self.assertIn('ledger lines differ', self.cli('correct-binding', scrub, self.line_of('scrub'), 'move').stderr)

    def test_correct_binding_refuses_a_swap_onto_an_explicit_record(self):
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        first, second = (json.loads(line.split('\t')[3])['id'] for line in owed.read_text().splitlines())
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass', 'ordinary').returncode, 0)
        self.assertEqual(self.cli('account', str(owed), first, 'deep-review', 'ship:reviewer--sol',
                                  'sha', 'pass', 'First report.md').returncode, 0)
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(self.bound()[second], 'ordinary')
        refused = self.cli('correct-binding', first, self.line_of('ordinary'), 'move')
        self.assertIn('cannot take the current row', refused.stderr)
        explicit = str(next(i for i, r in enumerate(ledger.rows(self.resolve())) if r[1] == 'account-result') + 1)
        refused = self.cli('correct-binding', second, explicit, 'move')  # same agent column, but a record row
        self.assertIn('target line must be a completed review row', refused.stderr)

    def test_correct_binding_refuses_a_ledger_with_another_line_break(self):
        scrub, _, _ = self.swapped_pair()
        self.assertEqual(self.cli('append', 'deep-review', 'other', 'sha', 'pass', 'a\u2028b').returncode, 0)
        self.assertIn('ledger lines differ', self.cli('correct-binding', scrub, self.line_of('scrub'), 'move').stderr)

    def test_older_pending_record_with_an_agent_id_accepts_a_row_without_one(self):
        self.hook('subagent-stop', agent_type='ship:reviewer--sol', agent_id='in-flight')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        epoch, agent, cwd, raw = owed.read_text().rstrip('\n').split('\t')
        result = json.loads(raw)
        del result['v']  # written before ID binding
        owed.write_text('\t'.join([epoch, agent, cwd, json.dumps(result)]) + '\n')
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol@someone-else', 'sha', 'pass').returncode, 0)
        self.assertEqual(json.loads(self.hook('stop'))['decision'], 'block')
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode, 0)
        self.assertEqual(self.hook('stop'), '')

    def test_explicit_accounting_checks_the_named_agent_id(self):
        self.hook('subagent-stop', agent_type='ship:reviewer--sol', agent_id='mine')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        result = json.loads(owed.read_text().split('\t')[3])
        self.finish_run()
        args = (str(owed), result['id'], 'deep-review')
        self.assertNotEqual(self.cli('account', *args, 'ship:reviewer--sol@other', 'sha', 'pass', 'r.md').returncode, 0)
        recorded = self.cli('account', *args, 'ship:reviewer--sol', 'sha', 'pass', 'r.md')
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        self.assertEqual(ledger.rows(self.resolve())[-1][2], 'ship:reviewer--sol@mine')  # the record names the result's ID
        retry = self.cli('account', *args, 'ship:reviewer--sol@mine', 'sha', 'pass', 'r.md')
        self.assertEqual(retry.returncode, 0, retry.stderr)
        self.assertEqual(self.hook('stop'), '')
