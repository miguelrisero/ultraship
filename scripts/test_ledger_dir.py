"""Synthetic linked-worktree ledger and hook regressions."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import errno
import hashlib
import io
import importlib.util
import json
import os
import shlex
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
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
        self.base = Path(tempfile.mkdtemp(prefix='ship-ledger-regression-', dir=scratch)).resolve()
        self.addCleanup(shutil.rmtree, self.base)
        self.env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
                    'XDG_STATE_HOME': str(self.base / 'state'), 'HOME': str(self.base)}
        self.env.pop('CLAUDE_CODE_SESSION_ID', None)
        self.env.pop('SHIP_LEDGER_DIR', None)
        self.enterContext(mock.patch.object(ledger.pwd, 'getpwuid',
                                           return_value=SimpleNamespace(pw_dir=str(self.base))))
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
        start = self.git(self.checkout, 'rev-parse', 'HEAD')
        self.history = (f'1\trun-start\tlight\t{start}\topen\trun-1 /board\n'.encode()
                        + b'2\tslices\twriter\tsha\tpass\tall evidence\n'
                        + b'3\tdeep-review\treviewer\tsha\towed\tkeep this\n')
        self.legacy.write_bytes(self.history)

    def git(self, cwd, *args):
        return subprocess.run(['git', '-C', str(cwd), *args], env=self.env,
                              capture_output=True, text=True, check=True).stdout.strip()

    def issue_grant(self, args, *, state=None, session='s1'):
        state = state if state is not None else Path(self.env['XDG_STATE_HOME']) / 'ultraship'
        ledger._issue_grant(str(LEDGER), list(args), state, session)

    def cli(self, *args, env=None, cwd=None, grant=True):
        if args[0] in ledger.ACCOUNT_COMMANDS:
            pending_arg = ledger.account_pending_arg(args)
            if grant and pending_arg and Path(pending_arg).is_absolute():
                self.issue_grant(args)
            stdout = io.StringIO()
            with mock.patch.dict(os.environ, env or self.env, clear=True), \
                    mock.patch.object(sys, 'argv', [str(LEDGER), *args]), redirect_stdout(stdout):
                try:
                    ledger.main(list(args))
                except SystemExit as exc:
                    if exc.code is None or isinstance(exc.code, int):
                        return subprocess.CompletedProcess(args, exc.code or 0, stdout.getvalue(), '')
                    return subprocess.CompletedProcess(args, 1, stdout.getvalue(), f'{exc.code}\n')
                return subprocess.CompletedProcess(args, 0, stdout.getvalue(), '')
        return subprocess.run([sys.executable, str(LEDGER), *args], cwd=cwd or self.checkout,
                              env=env or self.env, capture_output=True, text=True)

    def correction(self, *args):
        return self.cli('correct-binding', str(self.base / 'state/ultraship/owed/s1.tsv'), *args)

    def resolve(self):
        with mock.patch.dict(os.environ, self.env, clear=True):
            return ledger.ledger_path(self.checkout)

    def hook(self, mode, env=None, **extra):
        payload = {'session_id': 's1', 'cwd': str(self.checkout), **extra}
        return subprocess.run([sys.executable, str(HOOK), mode], input=json.dumps(payload),
                              cwd=self.checkout, env=env or self.env, capture_output=True,
                              text=True, check=True).stdout

    def non_git_fixture(self):
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        owed.parent.mkdir(parents=True)
        return owed, owed.parent.parent / 'accounted.json'

    def non_git_notice(self, cwd=None, epoch=20, identifier='fallback', **fields):
        result = {'id': identifier, 'v': 2, 'agent_id': 'reviewer', **fields}
        return f'{epoch}\tship:reviewer--sol\t{cwd or self.workspace}\t{json.dumps(result)}\n'.encode()

    def non_git_stop_block(self, owed, pending, reason, **kwargs):
        owed.with_suffix('.stop-state').unlink(missing_ok=True)
        owed.write_bytes(pending)
        block = json.loads(self.hook('stop', **kwargs))
        self.assertEqual(block['decision'], 'block')
        self.assertIn(reason, block['reason'])
        self.assertEqual(owed.read_bytes(), pending)
        return block['reason']

    def test_stop_non_git_match(self):
        owed, receipts = self.non_git_fixture()
        pending = self.non_git_notice()
        key = json.dumps([str(owed), str(self.workspace), 'fallback'])
        row = b'20\treview\tship:reviewer--sol@reviewer\tsha\tpass\t\n'
        local = self.resolve()
        full = self.workspace / 'full/.git/ship/ledger/main.tsv'
        full.parent.mkdir(parents=True)
        deeper = self.workspace / 'nested/checkout/.git/ship/ledger/main.tsv'
        deeper.parent.mkdir(parents=True)
        for outside in (deeper, self.legacy):
            outside.write_bytes(self.history + row)
        for home in (local, full):
            with self.subTest(home=home):
                home.write_bytes(self.history + row)
                owed.write_bytes(pending)
                self.assertEqual(self.hook('stop'), '')
                history = ledger.rows(home)
                self.assertEqual(json.loads(receipts.read_bytes()), {key: [str(home),
                    ledger.run_identity(0, history[0]), ledger.run_identity(3, history[3])]})
                self.assertEqual(owed.read_bytes(), b'')
                home.unlink()
                receipts.unlink()
        self.non_git_stop_block(owed, pending, 'Found 0 workspace ledger rows')
        # A stale, owed duplicate still counts, even in a different ledger.
        full.write_bytes(self.history + row)
        local.write_bytes(self.history + row.replace(b'20\t', b'4\t').replace(b'\tpass\t', b'\towed\t'))
        self.non_git_stop_block(owed, pending, 'Found 2 workspace ledger rows')
        self.assertFalse(receipts.exists())

    def test_stop_non_git_window_and_markers(self):
        owed, receipts = self.non_git_fixture()
        home = self.resolve()
        start = b'10\trun-start\tlight\tsha\topen\tfirst\n'
        row = b'18\treview\tship:reviewer--sol@reviewer\tsha\tpass\t\n'
        end = b'20\trun-end\t\tsha\tclosed\tfirst\n'
        following = b'20\trun-start\tlight\tsha\topen\tsecond\n'
        for epoch in (10, 20):
            home.write_bytes(start + row + end)
            owed.write_bytes(self.non_git_notice(epoch=epoch))
            self.assertEqual(self.hook('stop'), '')
            receipts.unlink()
        key = json.dumps([str(owed), str(self.workspace), 'fallback'])
        run = ledger.run_identity(0, start.decode().splitlines()[0].split('\t'))
        note = json.dumps({'result': key, 'run': run, 'step': 'review', 'evidence': 'review report'})
        marker = f'21\taccount-result\tship:reviewer--sol@reviewer\tsha\tpass\t{note}\n'
        for epoch, history, reason in (
                (9, start + row + end, 'outside the bound ship run'),
                (21, start + row + end, 'outside the bound ship run'),
                (20, start + row + following, 'outside the bound ship run'),
                (20, start + row + end + following, 'outside the bound ship run'),
                (20, start + end + row, 'outside the bound ship run'),
                (20, start + row.replace(b'--sol', b'--opus'), 'Found 0 workspace ledger rows'),
                (20, start + row.replace(b'@reviewer', b'@other'), 'Found 0 workspace ledger rows'),
                (20, start + row.replace(b'\tpass\t', b'\towed\t'), 'no unused ledger row'),
                (24, start + row, 'no unused ledger row'),
                (20, start + row + end + marker.encode(), 'explicit marker for this pending result')):
            with self.subTest(epoch=epoch, history=history):
                home.write_bytes(history)
                self.non_git_stop_block(owed, self.non_git_notice(epoch=epoch), reason)
                self.assertFalse(receipts.exists())

    def test_stop_non_git_main_parity(self):
        owed, receipts = self.non_git_fixture()
        home = self.resolve()
        row = b'20\treview\tship:reviewer--sol@reviewer\tsha\tpass\t\n'
        home.write_bytes(self.history + row)
        run = ledger.run_identity(0, ledger.rows(home)[0])
        recorded = self.non_git_notice(identifier='recorded', ledger=str(home), run=run)
        git_notice = self.non_git_notice(cwd=self.checkout)
        legacy_notice = git_notice.rsplit(b'\t', 1)[0] + b'\n'
        legacy_id = 'legacy:' + hashlib.sha256(json.dumps([str(owed), legacy_notice.decode().rstrip('\n'), 0]).encode()).hexdigest()
        for pending, cwd, identifier in ((git_notice, self.checkout, 'fallback'),
                                         (recorded, self.workspace, 'recorded'),
                                         (legacy_notice, self.checkout, legacy_id)):
            history = self.history + (row.replace(b'@reviewer', b'') if pending == legacy_notice else row)
            home.write_bytes(history)
            owed.write_bytes(pending)
            self.assertEqual(self.hook('stop'), '')
            key = json.dumps([str(owed), str(cwd), identifier])
            expected = json.dumps({key: [str(home), run, ledger.run_identity(3, ledger.rows(home)[3])]}).encode()
            self.assertEqual((owed.read_bytes(), receipts.read_bytes(), home.read_bytes()), (b'', expected, history))
            receipts.unlink()

        home.write_bytes(self.history + row)
        fallback = self.non_git_notice()
        broken = self.workspace / '.git'
        env = {**self.env, 'SHIP_LEDGER_DIR': str(home.parent)}
        error = 'returned non-zero exit status 128'
        baseline = self.non_git_stop_block(owed, fallback, error, env=env)
        reminder = owed.with_suffix('.stop-state')
        state = (owed.read_bytes(), reminder.read_bytes(), home.read_bytes(), receipts.exists())
        broken.mkdir()
        self.assertEqual(self.non_git_stop_block(owed, fallback, error), baseline)
        self.assertEqual((owed.read_bytes(), reminder.read_bytes(), home.read_bytes(), receipts.exists()), state)
        self.assertFalse(receipts.exists())
        broken.rmdir()
        for pending in (self.non_git_notice(agent_id=' '), self.non_git_notice(agent_id=5), self.non_git_notice(run=None),
                        self.non_git_notice(v=1), fallback.rsplit(b'\t', 1)[0] + b'\n'):
            self.non_git_stop_block(owed, pending, 'returned non-zero exit status 128')
        self.non_git_stop_block(owed, self.non_git_notice(cwd=f'{self.workspace}/.'), error)

        token = [str(home), run, ledger.run_identity(3, ledger.rows(home)[3])]
        for first, leftover, winner, loser in ((recorded, fallback, 'recorded', 'fallback'),
                                               (fallback, recorded, 'fallback', 'recorded')):
            with self.subTest(winner=winner):
                reason = self.non_git_stop_block(owed, first + leftover, 'no unused ledger row')
                self.assertEqual(json.loads(receipts.read_bytes()), {json.dumps([str(owed), str(self.workspace), winner]): token})
                self.assertIn(f'\n{loser} ship:reviewer--sol@reviewer ', reason)
                self.assertNotIn(f'\n{winner} ship:reviewer--sol@reviewer ', reason)
                receipts.unlink()

    def test_stop_non_git_io(self):
        owed, receipts = self.non_git_fixture()
        pending = self.non_git_notice()
        home = self.resolve()
        history = self.history + b'20\treview\tship:reviewer--sol@reviewer\tsha\tpass\t\n'
        home.write_bytes(history)
        bad = home.with_name('other.tsv')
        unrelated = self.base / 'unrelated.tsv'
        unrelated.write_bytes(self.history)
        spec = importlib.util.spec_from_file_location('stop_hook', HOOK)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        real_scandir, real_open, account = os.scandir, os.open, hook.account
        receipts.write_bytes(b'{}\n')

        def blocked(reason):
            def check_failure(*args):
                failures = account(*args)
                [(failed, result, error)] = failures
                self.assertEqual((failed, result['id']), (pending.decode().rstrip('\n').split('\t'), 'fallback'))
                self.assertIsInstance(error, ValueError)
                return failures

            owed.with_suffix('.stop-state').unlink(missing_ok=True)
            owed.write_bytes(pending)
            output = io.StringIO()
            with mock.patch.dict(os.environ, self.env, clear=True), \
                    mock.patch.object(hook, 'STATE', receipts.parent), \
                    mock.patch.object(hook, 'account', side_effect=check_failure), redirect_stdout(output):
                hook.stop({'session_id': 's1'})
            block = json.loads(output.getvalue())
            self.assertEqual(block['decision'], 'block')
            self.assertIn(reason, block['reason'])
            self.assertEqual((owed.read_bytes(), receipts.read_bytes(), home.read_bytes()), (pending, b'{}\n', history))

        def deny_listing(path):
            if path == home.parent:
                raise PermissionError('denied enumeration')
            return real_scandir(path)

        def fail_open(path, *args, **kwargs):
            if path == bad:
                raise error
            return real_open(path, *args, **kwargs)

        with mock.patch.object(os, 'scandir', side_effect=deny_listing):
            blocked('denied enumeration')
        bad.touch()
        for error in (PermissionError('denied read'), FileNotFoundError('vanished ledger')):
            with mock.patch.object(os, 'open', side_effect=fail_open):
                blocked(str(error))
        bad.unlink()

        def replace_at_open(path, flags, *args, **kwargs):
            if path == bad:
                self.assertTrue(flags & os.O_NOFOLLOW and flags & os.O_NONBLOCK)
                bad.unlink()
                make()
            return real_open(path, flags, *args, **kwargs)

        for make, reason in ((lambda: bad.symlink_to(unrelated), os.strerror(errno.ELOOP)),
                             (lambda: os.mkfifo(bad), 'regular file')):
            bad.touch()
            with mock.patch.object(os, 'open', side_effect=replace_at_open):
                blocked(reason)
            bad.unlink()
        for make, reason in ((lambda: bad.write_text('bad\trow\n'), 'Malformed workspace ledger'),
                             (lambda: bad.write_bytes(b' ' * (1024 * 1024 + 1)), 'exceeds its byte limit')):
            make()
            blocked(reason)
            bad.unlink()
        for suffix, count, reason in (('tsv', 64, 'Too many workspace ledger files'),
                                      ('txt', 128, 'Too many entries')):
            paths = [home.with_name(f'{i}.{suffix}') for i in range(count)]
            for path in paths:
                path.touch()
            blocked(reason)
            for path in paths:
                path.unlink()
        link = self.workspace / 'linked'
        link.symlink_to(self.base, target_is_directory=True)
        blocked('real directory')
        self.assertEqual(unrelated.read_bytes(), self.history)

    def test_stop_non_git_replay(self):
        owed, receipts = self.non_git_fixture()
        workspace = self.base / 'replay'
        home = workspace / 'child/.git/ship/ledger/main.tsv'
        home.parent.mkdir(parents=True)
        pending = self.non_git_notice(cwd=workspace)
        row = b'20\treview\tship:reviewer--sol@reviewer\tsha\tpass\t\n'
        history = self.history + row
        home.write_bytes(history)
        owed.write_bytes(pending)
        self.assertEqual(self.hook('stop'), '')
        saved = receipts.read_bytes()
        owed.write_bytes(pending)
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual((owed.read_bytes(), receipts.read_bytes()), (b'', saved))
        home.write_bytes(history + row)
        self.non_git_stop_block(owed, pending, 'Found 2 workspace ledger rows')
        self.assertEqual(receipts.read_bytes(), saved)
        home.write_bytes(history)
        elsewhere = self.base / 'vanished'
        workspace.rename(elsewhere)
        try:
            self.non_git_stop_block(owed, pending, 'returned non-zero exit status 128')
            self.assertEqual(receipts.read_bytes(), saved)
        finally:
            elsewhere.rename(workspace)
        self.assertEqual(home.read_bytes(), history)
        git = workspace / '.git'
        git.mkdir()
        self.non_git_stop_block(owed, pending, 'returned non-zero exit status 128')
        self.assertEqual(receipts.read_bytes(), saved)
        git.rmdir()
        self.git(workspace, 'init', '-q', '-b', 'main')
        self.git(workspace, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'init')
        other = git / 'ship/ledger/main.tsv'
        other.parent.mkdir(parents=True)
        other.write_bytes(history)
        self.non_git_stop_block(owed, pending, 'Accounting receipt names a different ledger or run')
        self.assertEqual((receipts.read_bytes(), home.read_bytes(), other.read_bytes()), (saved, history, history))

    def test_stop_non_git_refuses_hard_link_to_recorded_row(self):
        owed, receipts = self.non_git_fixture()
        home = self.resolve()
        history = self.history + b'20\treview\tship:reviewer--sol@reviewer\tsha\tpass\t\n'
        self.legacy.write_bytes(history)
        home.unlink()
        os.link(self.legacy, home)
        rows = ledger.rows(self.legacy)
        run = ledger.run_identity(0, rows[0])
        recorded = self.non_git_notice(identifier='recorded', ledger=str(self.legacy), run=run)
        pending = self.non_git_notice() + recorded
        self.non_git_stop_block(owed, pending, 'needs exactly one hard link')
        key = json.dumps([str(owed), str(self.workspace), 'recorded'])
        self.assertEqual(json.loads(receipts.read_bytes()), {key: [str(self.legacy), run, ledger.run_identity(3, rows[3])]})
        self.assertEqual((home.read_bytes(), self.legacy.read_bytes()), (history, history))

    def test_stop_non_git_refuses_malformed_marker_identities(self):
        owed, receipts = self.non_git_fixture()
        home = self.resolve()
        review = b'20\treview\tship:reviewer--sol@reviewer\tsha\tpass\t\n'
        identity = ledger.run_identity(3, review.decode().splitlines()[0].split('\t'))
        pending = self.non_git_notice()
        correction = {'agent': 'other', 'swap': None, 'reason': 'review', 'from': identity, 'to': identity}
        for step, fields in (('account-result', {'run': None, 'step': 'review', 'evidence': 'report'}),
                             ('correct-binding', {**correction, 'from': [True, 'bad']}),
                             ('correct-binding', {**correction, 'to': [3]})):
            with self.subTest(step=step, fields=fields):
                note = json.dumps({'result': 'unrelated', **fields})
                marker = f'21\t{step}\tother\tsha\tpass\t{note}\n'.encode()
                history = self.history + review + marker
                home.write_bytes(history)
                self.non_git_stop_block(owed, pending, 'Malformed workspace ledger marker')
                self.assertFalse(receipts.exists())
                self.assertEqual(home.read_bytes(), history)

    def test_stop_non_git_requires_marker_fields(self):
        owed, receipts = self.non_git_fixture()
        home = self.resolve()
        review = b'20\treview\tship:reviewer--sol@reviewer\tsha\tpass\t\n'
        identity = ledger.run_identity(3, review.decode().splitlines()[0].split('\t'))
        pending = self.non_git_notice()
        account = {'result': 'unrelated', 'run': ledger.run_identity(0, ledger.rows(home)[0]),
                   'step': 'review', 'evidence': 'report'}
        correction = {'result': 'unrelated', 'agent': 'other', 'from': identity, 'to': identity,
                      'swap': None, 'reason': 'review'}
        for step, payload, field in (('account-result', account, 'evidence'),
                                     ('correct-binding', correction, 'swap')):
            with self.subTest(step=step):
                fields = {key: value for key, value in payload.items() if key != field}
                marker = f'21\t{step}\tother\tsha\tpass\t'
                history = self.history + review + (marker + json.dumps(fields) + '\n').encode()
                home.write_bytes(history)
                self.non_git_stop_block(owed, pending, 'Malformed workspace ledger marker')
                self.assertFalse(receipts.exists())
                self.assertEqual(home.read_bytes(), history)
                home.write_bytes(self.history + review + (marker + json.dumps({**payload, 'extra': 1}) + '\n').encode())
                self.assertEqual(self.hook('stop'), '')
                self.assertEqual(owed.read_bytes(), b'')
                receipts.unlink()

    def test_stop_non_git_preserves_broken_parent_git_pointer_error(self):
        owed, receipts = self.non_git_fixture()
        checkout = self.base / 'broken-checkout'
        cwd = checkout / 'subdir'
        home = cwd / 'child/.git/ship/ledger/main.tsv'
        home.parent.mkdir(parents=True)
        missing = checkout / 'missing-git-dir'
        (checkout / '.git').write_text(f'gitdir: {missing}\n')
        history = self.history + b'20\treview\tship:reviewer--sol@reviewer\tsha\tpass\t\n'
        home.write_bytes(history)
        probe = subprocess.run(['git', '-C', str(cwd), 'rev-parse', '--abbrev-ref', 'HEAD'],
                               env=self.env, capture_output=True, text=True)
        self.assertEqual(probe.returncode, 128)
        self.assertTrue(probe.stderr.startswith('fatal: '), probe.stderr)
        self.assertFalse(probe.stderr.startswith('fatal: not a git repository (or any '), probe.stderr)
        pending = self.non_git_notice(cwd=cwd)
        reminder = owed.with_suffix('.stop-state')
        error = 'returned non-zero exit status 128'
        env = {**self.env, 'SHIP_LEDGER_DIR': str(home.parent)}
        baseline = self.non_git_stop_block(owed, pending, error, env=env)
        state = (owed.read_bytes(), reminder.read_bytes(), home.read_bytes(), receipts.exists())
        self.assertEqual(self.non_git_stop_block(owed, pending, error), baseline)
        self.assertEqual((owed.read_bytes(), reminder.read_bytes(), home.read_bytes(), receipts.exists()), state)
        self.assertFalse(receipts.exists())

    def test_stop_non_git_preserves_git_error_for_noncanonical_broken_cwd(self):
        owed, receipts = self.non_git_fixture()
        home = self.resolve()
        history = self.history + b'20\treview\tship:reviewer--sol@reviewer\tsha\tpass\t\n'
        home.write_bytes(history)
        (self.workspace / '.git').mkdir()
        pending = self.non_git_notice(cwd=f'{self.workspace}/.')
        reminder = owed.with_suffix('.stop-state')
        error = 'returned non-zero exit status 128'
        env = {**self.env, 'SHIP_LEDGER_DIR': str(home.parent)}
        baseline = self.non_git_stop_block(owed, pending, error, env=env)
        state = (owed.read_bytes(), reminder.read_bytes(), home.read_bytes(), receipts.exists())
        self.assertEqual(self.non_git_stop_block(owed, pending, error), baseline)
        self.assertEqual((owed.read_bytes(), reminder.read_bytes(), home.read_bytes(), receipts.exists()), state)
        self.assertFalse(receipts.exists())

    def test_stop_non_git_replay_failure_allows_unrelated_receipt(self):
        owed, receipts = self.non_git_fixture()
        fallback = self.non_git_notice()
        home = self.resolve()
        review = b'20\treview\tship:reviewer--sol@reviewer\tsha\tpass\t\n'
        home.write_bytes(self.history + review)
        owed.write_bytes(fallback)
        self.assertEqual(self.hook('stop'), '')
        saved = json.loads(receipts.read_bytes())
        other = home.with_name('other.tsv')
        home.rename(other)
        unrelated = review.replace(b'@reviewer', b'@other')
        home.write_bytes(self.history + unrelated)
        rows = ledger.rows(home)
        run = ledger.run_identity(0, rows[0])
        recorded = self.non_git_notice(identifier='recorded', agent_id='other', ledger=str(home), run=run)
        pending = fallback + recorded
        key = json.dumps([str(owed), str(self.workspace), 'recorded'])
        expected = json.dumps({**saved, key: [str(home), run, ledger.run_identity(3, rows[3])]}).encode()
        env = {**self.env, 'SHIP_LEDGER_DIR': str(home.parent)}
        self.non_git_stop_block(owed, pending, 'returned non-zero exit status 128', env=env)
        self.assertEqual(receipts.read_bytes(), expected)
        receipts.write_text(json.dumps(saved))
        reason = self.non_git_stop_block(owed, pending, 'Accounting receipt names a different ledger or run')
        self.assertIn('\nfallback ship:reviewer--sol@reviewer ', reason)
        self.assertNotIn('\nrecorded ship:reviewer--sol@other ', reason)
        self.assertEqual(receipts.read_bytes(), expected)

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

    def test_nested_managed_checkout_binds_stop_to_workspace_ledger(self):
        workspace = self.base / '.bettercoding-workspaces' / 'managed'
        scratch = workspace / '.scratch'
        scratch.mkdir(parents=True)
        self.checkout = workspace / 'lanes' / 'nested'
        self.checkout.parent.mkdir()
        self.git(self.common, 'worktree', 'add', '-q', '-b', 'nested', str(self.checkout))
        path = self.cli('path')
        self.assertEqual(path.returncode, 0, path.stderr)
        home = Path(path.stdout.strip())
        self.assertEqual(home, scratch / 'ship-ledgers' / hashlib.sha256(
            str(self.checkout).encode()).hexdigest() / 'nested.tsv')
        self.assertEqual(self.cli('run-start', 'light', 'nested-run').returncode, 0)
        (self.checkout.parent / '.scratch').mkdir()
        self.assertEqual(self.cli('path').stdout.strip(), str(home))
        self.hook('subagent-stop', agent_type='ship:reviewer--sol', agent_id='nested-seat')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        result = json.loads(owed.read_text().strip().split('\t')[3])
        self.assertEqual(result['ledger'], str(home))
        self.assertEqual(result['run'], ledger.run_identity(0, ledger.rows(home)[0]))
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol@nested-seat',
                                  'sha', 'pass').returncode, 0)
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(owed.read_bytes(), b'')
        competing = self.checkout.parent / '.scratch' / home.relative_to(scratch)
        competing.parent.mkdir(parents=True)
        competing.write_bytes(b'other ledger\n')
        saved = home.read_bytes()
        refused = self.cli('path')
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('Multiple workspace ledger homes contain evidence', refused.stderr)
        self.assertEqual(home.read_bytes(), saved)
        self.assertEqual(competing.read_bytes(), b'other ledger\n')

    def test_nested_checkout_does_not_search_above_managed_workspace(self):
        container = self.base / '.bettercoding-workspaces'
        checkout = container / 'managed' / 'lanes' / 'nested'
        checkout.parent.mkdir(parents=True)
        (container / '.scratch').mkdir()
        self.git(self.common, 'worktree', 'add', '-q', '-b', 'isolated', str(checkout))
        result = self.cli('path', cwd=checkout)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHIP_LEDGER_DIR', result.stderr)
        self.assertFalse((container / '.scratch/ship-ledgers').exists())

    def test_nested_checkout_preserves_snapshot_when_common_git_is_in_workspace(self):
        workspace = self.base / '.bettercoding-workspaces' / 'managed'
        scratch = workspace / '.scratch'
        scratch.mkdir(parents=True)
        common = workspace / 'primary'
        self.common.rename(common)
        checkout = workspace / 'lanes' / 'nested'
        checkout.parent.mkdir()
        self.git(common, 'worktree', 'add', '-q', '-b', 'nested', str(checkout))
        legacy = common / '.git/ship/ledger/nested.tsv'
        legacy.write_bytes(self.history)
        path = self.cli('path', cwd=checkout)
        self.assertEqual(path.returncode, 0, path.stderr)
        self.assertEqual(path.stdout.strip(), str(legacy))
        self.assertFalse((scratch / 'ship-ledgers').exists())

        old_home = checkout.parent / '.scratch/ship-ledgers' / hashlib.sha256(str(checkout).encode()).hexdigest()
        old_home.mkdir(parents=True)
        snapshot = old_home / legacy.name
        snapshot.write_bytes(self.history)
        snapshot.with_suffix('.import.json').write_text('{}')
        path = self.cli('path', cwd=checkout)
        self.assertEqual(path.returncode, 0, path.stderr)
        self.assertEqual(path.stdout.strip(), str(snapshot))
        self.assertEqual(legacy.read_bytes(), self.history)
        scratch.rmdir()
        path = self.cli('path', cwd=checkout)
        self.assertEqual(path.returncode, 0, path.stderr)
        self.assertEqual(path.stdout.strip(), str(snapshot))

    def test_nested_checkout_uses_common_ledger_with_only_parent_scratch(self):
        workspace = self.base / '.bettercoding-workspaces' / 'managed'
        parent = workspace / 'lanes'
        (parent / '.scratch').mkdir(parents=True)
        common = parent / 'primary'
        self.common.rename(common)
        checkout = parent / 'nested'
        self.git(common, 'worktree', 'add', '-q', '-b', 'nested', str(checkout))
        legacy = common / '.git/ship/ledger/nested.tsv'
        legacy.write_bytes(self.history)
        path = self.cli('path', cwd=checkout)
        self.assertEqual(path.returncode, 0, path.stderr)
        self.assertEqual(path.stdout.strip(), str(legacy))
        self.assertFalse((workspace / '.scratch').exists())
        self.assertFalse((parent / '.scratch/ship-ledgers').exists())

    def test_checkout_named_scratch_cannot_store_ledger_inside_itself(self):
        workspace = self.base / '.bettercoding-workspaces' / 'managed'
        workspace.mkdir(parents=True)
        checkout = workspace / '.scratch'
        self.git(self.common, 'worktree', 'add', '-q', '-b', 'scratch', str(checkout))
        result = self.cli('path', cwd=checkout)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHIP_LEDGER_DIR', result.stderr)
        self.assertFalse((checkout / 'ship-ledgers').exists())

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

    def commit_fixture(self, cwd, *args):
        self.git(cwd, '-c', 'user.name=t', '-c', 'user.email=t@t', *args)
        return self.git(cwd, 'rev-parse', 'HEAD')

    def test_review_gaps_follow_the_run_history(self):
        self.legacy.unlink()
        before_run = self.git(self.checkout, 'rev-parse', 'HEAD')
        start = self.commit_fixture(self.checkout, 'commit', '--allow-empty', '-qm', 'start')
        for mode in ('full', 'light'):
            with self.subTest(mode=mode):
                self.git(self.checkout, 'switch', '-qc', f'review-gaps-{mode}', start)
                self.assertEqual(self.cli('run-start', mode, 'review-gaps').returncode, 0)
                home = self.resolve()
                reviewed = self.commit_fixture(self.checkout, 'commit', '--allow-empty', '-qm', f'review {mode}')
                short_sha = self.git(self.checkout, 'rev-parse', '--short', reviewed).upper()
                ledger.append(home, 'deep-review', 'ship:reviewer--sol@deep', short_sha, 'findings', '')
                ledger.append(home, 'simplify', 'ship:reviewer--opus@simplify', reviewed, 'pass', '')
                if mode == 'full':
                    ledger.append(home, 'panel-high', 'ship:reviewer--astra@high', reviewed, 'pass', '')
                    ledger.append(home, 'select', 'ship:reviewer--sol@select', reviewed, 'pass', '')
                fixed = self.commit_fixture(self.checkout, 'commit', '--allow-empty', '-qm', f'fix {mode}')
                ledger.append(home, 'fix-read', 'ship:reviewer--sonnet@fix', fixed, 'pass', '')
                if mode == 'full':
                    ledger.append(home, 'panel-final', 'ship:reviewer--opus-panel@final', fixed, 'pass', '')
                self.commit_fixture(self.common, 'commit', '--allow-empty', '-qm', f'main {mode}')
                head = self.commit_fixture(self.checkout, 'merge', '--no-ff', '--no-edit', 'main')
                for step in ('plan', 'slices', 'pr', 'babysit', 'gate'):
                    ledger.append(home, step, 'driver', before_run, 'pass', '')

                if mode == 'full':
                    ledger.append(home, 'closing', 'reviewer--sol', fixed, 'pass', '')
                    status = self.cli('status').stdout.splitlines()[-1]
                    self.assertIn('gaps: closing (', status)
                    self.assertIn(f'HEAD {head}', status)
                    closed = self.cli('run-end')
                    self.assertEqual(closed.returncode, 1)
                    self.assertEqual(closed.stderr, f'refusing run-end; {status}\n')
                    ledger.append(home, 'closing', 'reviewer--sol', head, 'pass', '')
                gaps = self.cli('gaps')
                self.assertEqual((gaps.returncode, gaps.stdout), (0, 'gaps: none\n'))
                self.assertEqual(self.cli('run-end').returncode, 0)
                self.assertEqual(ledger.rows(home)[-1][1:5], ['run-end', '', head, 'closed'])

    def test_review_gaps_report_bad_roles_and_commits(self):
        before_run = self.git(self.checkout, 'rev-parse', 'HEAD')
        self.git(self.common, 'switch', '-qc', 'unmerged')
        unmerged = self.commit_fixture(self.common, 'commit', '--allow-empty', '-qm', 'unmerged')
        self.legacy.unlink()
        start = self.commit_fixture(self.checkout, 'commit', '--allow-empty', '-qm', 'start')
        self.assertEqual(self.cli('run-start', 'light', 'review-gaps').returncode, 0)
        home = self.resolve()
        head = self.commit_fixture(self.checkout, 'commit', '--allow-empty', '-qm', 'head')
        ledger.append(home, 'simplify', 'ship:reviewer--x-writer', head, 'pass', '')
        ledger.append(home, 'simplify', 'ship:reviewer--sol@owed', head, 'owed', '')
        ledger.append(home, 'deep-review', 'ship:reviewer--sol', unmerged, 'pass', '')
        ledger.append(home, 'fix-read', 'ship:reviewer--sol', before_run, 'pass', '')
        gaps = self.cli('gaps')
        self.assertEqual(gaps.returncode, 1)
        for reason in ('simplify (needs a reviewer--* row', 'wrong role', 'reviewer--x-writer',
                       f'newest reviewer row {unmerged!r}; is not an ancestor of HEAD {head}',
                       f'newest reviewer row {before_run!r}; does not descend from run start {start}'):
            self.assertIn(reason, gaps.stdout)

        missing = '0' * len(head)
        for sha, suffix in ((head, ')'), (missing, '; unknown commit)')):
            ledger.append(home, 'simplify', 'ship:writer--sol', sha, 'pass', '')
            gaps = self.cli('gaps')
            self.assertEqual(gaps.returncode, 1)
            self.assertIn(f"wrong role 'ship:writer--sol' at {sha!r}{suffix}", gaps.stdout)
        self.assertIn(gaps.stdout.strip().replace('gaps:', 'Gaps:', 1), self.hook('compact'))

    def finish_run(self):
        head = self.git(self.checkout, 'rev-parse', 'HEAD')
        for step in ledger.REQUIRED['light']:
            agent, sha = ('ship:reviewer--sol@finish', head) if step in (
                'simplify', 'deep-review', 'fix-read') else ('driver', 'sha')
            self.assertEqual(self.cli('append', step, agent, sha, 'pass').returncode, 0)
        self.assertEqual(self.cli('run-end').returncode, 0)

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
        fixed = self.correction(complete, explicit, 'keep')
        self.assertEqual(fixed.returncode, 0, fixed.stderr)
        self.assertNotIn(complete, blocked['reason'])
        refused = self.correction(missing, explicit, 'keep')
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
        fixed = self.correction(result['id'], explicit, 'bind exact result')
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

    def test_stop_prints_exact_command_for_commit_bound_findings(self):
        sha = self.git(self.checkout, 'rev-parse', 'HEAD')
        owed, transcript, result, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Reviewed commit: {sha}\nVerdict: findings')])
        home = self.resolve()
        before = (owed.read_bytes(), home.read_bytes())
        message = json.loads(self.hook('stop'))
        self.assertEqual(message['decision'], 'block')
        commands = [line for line in message['reason'].splitlines() if line.startswith('python3 ')]
        self.assertEqual(len(commands), 1)
        argv = shlex.split(commands[0])
        self.assertEqual(argv[:9], ['python3', str(LEDGER), 'account', str(owed), result['id'],
                                    'review', 'ship:reviewer--sol@reviewer', sha, 'findings'])
        # Custody refuses a command whose words name a receipt store; the transcript path stays out.
        self.assertNotIn(str(transcript), commands[0])
        self.assertIn(result['id'], argv[9])
        self.assertEqual((owed.read_bytes(), home.read_bytes()), before)
        accounted = self.cli(*argv[2:])
        self.assertEqual(accounted.returncode, 0, accounted.stderr)
        self.assertEqual(ledger.rows(home)[-1][3:5], [sha, 'findings'])
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(owed.read_bytes(), b'')

    def test_stop_withholds_findings_command_when_accounted_sibling_shares_transcript(self):
        sha = self.git(self.checkout, 'rev-parse', 'HEAD')
        owed, transcript, result, epoch = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Reviewed commit: {sha}\nVerdict: findings')])
        home = self.resolve()
        with home.open('ab') as stream:
            stream.write(f'{epoch}\treview\tship:reviewer--sol@reviewer\t{sha}\tfindings\tSibling review\n'.encode())
        hardlink = transcript.with_name('agent-other.jsonl')
        hardlink.hardlink_to(transcript)
        original = owed.read_bytes()
        receipts = owed.parent.parent / 'accounted.json'
        for path in (str(transcript), f'{transcript.parent}/./{transcript.name}', str(hardlink)):
            with self.subTest(path=path):
                receipts.unlink(missing_ok=True)
                sibling = {**result, 'id': '22222222-2222-2222-2222-222222222222',
                           'agent_transcript_path': path}
                first = f'{epoch}\tship:reviewer--sol\t{self.checkout}\t{json.dumps(sibling)}\n'.encode()
                reason = self.non_git_stop_block(owed, first + original, result['id'])
                self.assertNotIn(sibling['id'], reason)
                self.assertNotIn('Run each verified findings command', reason)
                self.assertEqual([json.loads(key)[2] for key in json.loads(receipts.read_text())], [sibling['id']])

    def test_stop_withholds_findings_command_before_bound_run_start(self):
        sha = self.git(self.checkout, 'rev-parse', 'HEAD')
        owed, _, result, epoch = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Reviewed commit: {sha}\nVerdict: findings')])
        home = self.resolve()
        history = ledger.rows(home)
        for offset, emits_command in ((1, False), (0, True)):
            with self.subTest(offset=offset):
                history[0][0] = str(epoch + offset)
                home.write_text(''.join('\t'.join(row) + '\n' for row in history))
                notice = {**result, 'run': ledger.run_identity(0, history[0])}
                pending = f'{epoch}\tship:reviewer--sol\t{self.checkout}\t{json.dumps(notice)}\n'.encode()
                reason = self.non_git_stop_block(owed, pending, result['id'])
                self.assertEqual('Run each verified findings command' in reason, emits_command)
                self.assertFalse((owed.parent.parent / 'accounted.json').exists())

    def test_stop_retains_v2_null_run_without_review_credit(self):
        owed, receipts = self.non_git_fixture()
        home = self.resolve()
        history = self.history + b'20\treview\tship:reviewer--sol@reviewer\tsha\tpass\t\n'
        home.write_bytes(history)
        for binding in ({'ledger': str(home)}, {}):
            with self.subTest(binding=binding):
                receipts.unlink(missing_ok=True)
                pending = self.non_git_notice(cwd=self.checkout, run=None, **binding)
                owed.write_bytes(pending)
                output = self.hook('stop')
                self.assertTrue(output, 'Stop cleared the v2 null-run notice')
                stopped = json.loads(output)
                self.assertEqual(stopped['decision'], 'block')
                self.assertIn('lacks its original ledger or run binding', stopped['reason'])
                self.assertNotIn('ledger.py append', stopped['reason'])
                self.assertEqual(self.hook('stop'), '')
                self.assertEqual(owed.read_bytes(), pending)
                self.assertFalse(receipts.exists())
                self.assertEqual(home.read_bytes(), history)

    def test_stop_keeps_legacy_null_run_behavior(self):
        owed, receipts = self.non_git_fixture()
        home = self.resolve()
        owed.write_bytes(self.non_git_notice(cwd=self.checkout, v=1, ledger=str(home), run=None))
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(owed.read_bytes(), b'')
        self.assertEqual(json.loads(receipts.read_text()), {})

    def test_stop_keeps_patch_only_findings_pending_without_exact_command(self):
        base = self.git(self.checkout, 'rev-parse', 'HEAD')
        owed, _, _, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Base: {base}\nPatch: {"ab" * 32}\nVerdict: findings')])
        before = owed.read_bytes()
        message = json.loads(self.hook('stop'))
        self.assertEqual(message['decision'], 'block')
        self.assertIn('patch digest', message['reason'])
        self.assertIn('Link a later review on the run board. Keep the original subject and verdict.', message['reason'])
        self.assertIn('The link gives zero accounting or review credit.', message['reason'])
        self.assertFalse(any(line.startswith('python3 ') for line in message['reason'].splitlines()))
        self.assertNotIn(' account-auto ', message['reason'])
        self.assertEqual(owed.read_bytes(), before)
        self.assertFalse((owed.parent.parent / 'accounted.json').exists())

    def test_stop_withholds_guidance_for_mixed_commit_and_patch_subject(self):
        base = self.git(self.checkout, 'rev-parse', 'HEAD')
        owed, _, _, _ = self.auto_owed([
            (-2, 'user', 'Review.'),
            (-1, 'assistant', f'Reviewed commit: {base}\nReviewed patch: {"ab" * 32}\nVerdict: findings')])
        before = owed.read_bytes()
        message = json.loads(self.hook('stop'))
        self.assertEqual(message['decision'], 'block')
        self.assertFalse(any(line.startswith('python3 ') for line in message['reason'].splitlines()))
        self.assertNotIn(' account-auto ', message['reason'])
        self.assertEqual(owed.read_bytes(), before)

    def test_stop_withholds_commands_for_multiple_reviewed_commit_labels(self):
        sha = self.git(self.checkout, 'rev-parse', 'HEAD')
        owed, _, _, _ = self.auto_owed([
            (-2, 'user', 'Review.'),
            (-1, 'assistant', f'Reviewed commit: {sha}\nReviewed commit: 123abcd\nVerdict: findings')])
        before = owed.read_bytes()
        result = json.loads(self.hook('stop'))
        self.assertEqual(result['decision'], 'block')
        self.assertFalse(any(line.startswith('python3 ') for line in result['reason'].splitlines()))
        self.assertEqual(owed.read_bytes(), before)

    def test_stop_withholds_findings_when_line_separator_hides_a_second_label(self):
        sha = self.git(self.checkout, 'rev-parse', 'HEAD')
        for label in ('Verdict: pass', 'Reviewed commit: 123abcd'):
            with self.subTest(label=label):
                owed, _, result, _ = self.auto_owed([
                    (-2, 'user', 'Review.'),
                    (-1, 'assistant', f'Reviewed commit: {sha}\nVerdict: findings\nDetails {label}')])
                pending = owed.read_bytes().splitlines(keepends=True)[-1]
                reason = self.non_git_stop_block(owed, pending, result['id'])
                self.assertNotIn('Run each verified findings command', reason)
                self.assertFalse((owed.parent.parent / 'accounted.json').exists())

    def test_stop_withholds_findings_when_a_hidden_label_starts_with_unicode_space(self):
        sha = self.git(self.checkout, 'rev-parse', 'HEAD')
        for label in (' Overall: pass', ' Reviewed commit: 123abcd'):
            with self.subTest(label=label):
                owed, _, result, _ = self.auto_owed([
                    (-2, 'user', 'Review.'),
                    (-1, 'assistant', f'Reviewed commit: {sha}\nVerdict: findings\nDetails {label}')])
                pending = owed.read_bytes().splitlines(keepends=True)[-1]
                reason = self.non_git_stop_block(owed, pending, result['id'])
                self.assertNotIn('Run each verified findings command', reason)

    def test_stop_withholds_findings_when_a_split_sibling_shares_the_transcript(self):
        sha = self.git(self.checkout, 'rev-parse', 'HEAD')
        owed, _, result, epoch = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Reviewed commit: {sha}\nVerdict: findings')])
        original = owed.read_bytes()
        sibling = json.dumps({**result, 'id': '33333333-3333-3333-3333-333333333333'}).replace(', ', ',\t', 1)
        row = f'{epoch}\tship:reviewer--sol\t{self.checkout}\t{sibling}\n'.encode()
        reason = self.non_git_stop_block(owed, row + original, result['id'])
        self.assertNotIn('Run each verified findings command', reason)

    def test_stop_withholds_findings_when_the_transcript_has_a_later_turn(self):
        sha = self.git(self.checkout, 'rev-parse', 'HEAD')
        owed, _, result, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Reviewed commit: {sha}\nVerdict: findings'),
            (5, 'user', 'Review again.'), (6, 'assistant', f'Reviewed commit: {sha}\nVerdict: findings')])
        reason = self.non_git_stop_block(owed, owed.read_bytes(), result['id'])
        self.assertNotIn('Run each verified findings command', reason)

    def test_stop_withholds_findings_when_a_resumed_prompt_lands_on_the_notice_second(self):
        sha = self.git(self.checkout, 'rev-parse', 'HEAD')
        owed, _, result, _ = self.auto_owed([
            (-3, 'user', 'Review.'), (-2, 'assistant', f'Reviewed commit: {sha}\nVerdict: pass'),
            (0, 'user', 'Review again.'), (0.5, 'assistant', f'Reviewed commit: {sha}\nVerdict: findings')])
        reason = self.non_git_stop_block(owed, owed.read_bytes(), result['id'])
        self.assertNotIn('Run each verified findings command', reason)

    def test_stop_withholds_findings_command_that_custody_would_refuse(self):
        sha = self.git(self.checkout, 'rev-parse', 'HEAD')
        owed, _, result, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Reviewed commit: {sha}\nVerdict: findings')])
        # The state folder name contains a receipt folder name, so custody refuses any command with this path.
        state = self.base / 'ultraship' / 'text-lint-fixtures'
        shutil.copytree(self.base / 'state', state)
        stopped = json.loads(self.hook('stop', env={**self.env, 'XDG_STATE_HOME': str(state)}))
        self.assertEqual(stopped['decision'], 'block')
        self.assertIn(result['id'], stopped['reason'])
        self.assertFalse(any(line.startswith('python3 ') for line in stopped['reason'].splitlines()))

    def test_stop_retains_malformed_notice_beside_commit_findings(self):
        sha = self.git(self.checkout, 'rev-parse', 'HEAD')
        owed, _, _, epoch = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Reviewed commit: {sha}\nVerdict: findings')])
        with owed.open('a') as stream:
            stream.write(f'{epoch}\tship:reviewer--sol\t{self.checkout}\t' + '[' * 2000 + ']' * 2000 + '\n')
        before = owed.read_bytes()
        result = json.loads(self.hook('stop'))
        self.assertEqual(result['decision'], 'block')
        self.assertFalse(any(line.startswith('python3 ') for line in result['reason'].splitlines()))
        self.assertEqual(owed.read_bytes(), before)

    def test_stop_withholds_findings_command_for_symlinked_pending_file(self):
        sha = self.git(self.checkout, 'rev-parse', 'HEAD')
        owed, _, _, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Reviewed commit: {sha}\nVerdict: findings')])
        saved = owed.with_suffix('.saved')
        owed.rename(saved)
        owed.symlink_to(saved)
        before = saved.read_bytes()
        stopped = json.loads(self.hook('stop'))
        self.assertEqual(stopped['decision'], 'block')
        self.assertFalse(any(line.startswith('python3 ') for line in stopped['reason'].splitlines()))
        self.assertEqual(saved.read_bytes(), before)

    def test_stop_withholds_findings_command_for_noncanonical_pending_path(self):
        sha = self.git(self.checkout, 'rev-parse', 'HEAD')
        owed, _, result, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Reviewed commit: {sha}\nVerdict: findings')])
        env = {**self.env, 'XDG_STATE_HOME': str(self.base / 'state/../state')}
        pending = Path(env['XDG_STATE_HOME']) / 'ultraship/owed/s1.tsv'
        before = owed.read_bytes()
        self.assertEqual(pending.read_bytes(), before)
        stopped = json.loads(self.hook('stop', env=env))
        self.assertEqual(stopped['decision'], 'block')
        self.assertIn(result['id'], stopped['reason'])
        self.assertFalse(any(line.startswith('python3 ') for line in stopped['reason'].splitlines()))
        self.assertEqual(owed.read_bytes(), before)

    def test_stop_limits_mixed_batch_guidance_to_original_runs(self):
        sha = self.git(self.checkout, 'rev-parse', 'HEAD')
        owed, _, _, epoch = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Reviewed commit: {sha}\nVerdict: findings')])
        with owed.open('ab') as stream:
            stream.write(self.non_git_notice(cwd=self.checkout, epoch=epoch, identifier='unbound', agent_id='other'))
        before = owed.read_bytes()
        stopped = json.loads(self.hook('stop'))
        self.assertEqual(stopped['decision'], 'block')
        self.assertIn('1 pending result lacks its original ledger or run binding.', stopped['reason'])
        self.assertIn('Record only results with their original ledger and run binding', stopped['reason'])
        self.assertNotIn('Record each result with', stopped['reason'])
        self.assertEqual(len([line for line in stopped['reason'].splitlines() if line.startswith('python3 ')]), 1)
        self.assertEqual(owed.read_bytes(), before)
        self.assertFalse((owed.parent.parent / 'accounted.json').exists())

    def test_stop_reports_missing_original_binding_and_allows_blocker_report(self):
        (self.workspace / '.scratch').rmdir()
        owed, _, result, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', 'Verdict: findings')])
        self.assertNotIn('ledger', result)
        self.assertNotIn('run', result)
        before = (owed.read_bytes(), self.legacy.read_bytes())
        stopped = json.loads(self.hook('stop'))
        self.assertEqual(stopped['decision'], 'block')
        self.assertIn(result['id'], stopped['reason'])
        self.assertIn('1 pending result lacks its original ledger or run binding.', stopped['reason'])
        self.assertIn('End this turn with a blocker report. Keep run completion on hold.', stopped['reason'])
        self.assertNotIn('ledger.py append', stopped['reason'])
        self.assertNotIn(' account ', stopped['reason'])
        self.assertNotIn('account-auto', stopped['reason'])
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual((owed.read_bytes(), self.legacy.read_bytes()), before)
        self.assertFalse((owed.parent.parent / 'accounted.json').exists())

    def assert_account_auto_refuses_grant(self, session, *, foreign=False):
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
            env.pop('CLAUDE_CODE_SESSION_ID', None)
        else:
            env['CLAUDE_CODE_SESSION_ID'] = session
        if foreign:
            sibling = owed.with_name('s2.tsv')
            sibling.write_bytes(owed.read_bytes())
            self.issue_grant(['account-auto', str(sibling)], session='s2')
        refused = self.cli('account-auto', str(owed), env=env, grant=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(refused.stdout, '')
        self.assertEqual(refused.stderr.splitlines(), [ledger.GRANT_REFUSAL])
        self.assertEqual([path.read_bytes() for path in paths], before)
        allowed = self.cli('account-auto', str(owed))
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertIn('1 accounted, 0 pending\n', allowed.stdout)
        self.assertNotEqual(home.read_bytes(), before[0])

    def test_account_auto_refuses_foreign_grant(self):
        self.assert_account_auto_refuses_grant('s2', foreign=True)

    def test_account_auto_refuses_missing_grant(self):
        self.assert_account_auto_refuses_grant(None)

    def test_account_auto_refuses_empty_session_without_a_grant(self):
        self.assert_account_auto_refuses_grant('')

    def test_account_auto_refuses_when_the_account_has_no_passwd_entry(self):
        owed, _, _, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Verdict: PASS {"ab" * 20}')])
        args = ('account-auto', str(owed))
        self.issue_grant(args)
        receipts = owed.parent.parent / 'accounted.json'
        receipts.write_bytes(b'{}\n')
        paths = (self.resolve(), owed, receipts)
        before = tuple(path.read_bytes() for path in paths)
        with mock.patch.object(ledger.pwd, 'getpwuid', side_effect=KeyError('getpwuid(): uid not found')):
            refused = self.cli(*args, grant=False)
        self.assertEqual((refused.returncode, refused.stdout, refused.stderr), (1, '', ledger.GRANT_REFUSAL + '\n'))
        self.assertEqual(tuple(path.read_bytes() for path in paths), before)

    def test_accounting_refuses_caller_session_and_fake_grant_stores(self):
        owed, _, result, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Verdict: PASS {"ab" * 20}')])
        home = self.resolve()
        receipts = owed.parent.parent / 'accounted.json'
        receipts.write_bytes(b'{}\n')
        paths = (home, owed, receipts)
        before = tuple(path.read_bytes() for path in paths)
        caller_home = self.base / 'caller-home'
        caller_home.mkdir()
        fake_home = self.base / 'fake-home'
        caller_state = fake_home / '.local/state'
        fake_state = caller_state / 'ultraship'
        fake_owed = fake_state / 'owed' / owed.name
        fake_owed.parent.mkdir(parents=True)
        fake_owed.write_bytes(owed.read_bytes())
        key = json.dumps([str(fake_owed), str(self.checkout), result['id']])
        history = ledger.rows(home)
        (fake_state / 'accounted.json').write_text(json.dumps({key: [str(home), result['run'],
                                                                     ledger.run_identity(1, history[1])]}))
        env = {**self.env, 'HOME': str(caller_home), 'XDG_STATE_HOME': str(caller_state),
               'CLAUDE_CODE_SESSION_ID': 's1'}
        args = [
            ('account', str(owed), result['id'], 'review', 'ship:reviewer--sol', 'abcdef1', 'pass', 'report'),
            ('account-auto', str(owed)), ('account-auto', '--fail-unparsed', str(owed)),
            ('correct-binding', str(owed), result['id'], '2', 'report'),
            ('correct-binding', str(fake_owed), result['id'], '2', 'report'),
        ]
        reminder = owed.with_suffix('.stop-state')
        control = self.hook('stop')
        reminder.unlink()
        with mock.patch.object(ledger.time, 'time_ns', return_value=10_000_000_000) as clock:
            for argv in args:
                with self.subTest(command=argv[0]):
                    state = fake_state if argv[1] == str(fake_owed) else owed.parent.parent
                    for fake in (caller_home, fake_home):
                        with mock.patch.object(ledger.pwd, 'getpwuid',
                                               return_value=SimpleNamespace(pw_dir=str(fake))):
                            self.issue_grant(argv, state=state)
                    refused = self.cli(*argv, env=env, grant=False)
                    self.assertEqual((refused.returncode, refused.stdout, refused.stderr),
                                     (1, '', ledger.GRANT_REFUSAL + '\n'))
                    self.assertEqual(tuple(path.read_bytes() for path in paths), before)
                    clock.return_value += ledger.GRANT_LIFETIME_NS
        self.assertEqual(self.hook('stop'), control)

    def test_account_auto_refuses_an_owed_inode_replacement(self):
        owed, _, _, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Verdict: PASS {"ab" * 20}')])
        args = ('account-auto', '--fail-unparsed', str(owed))
        self.issue_grant(args)
        detached = owed.rename(owed.with_name('original.tsv'))
        owed.write_bytes(detached.read_bytes())
        receipts = owed.parent.parent / 'accounted.json'
        receipts.write_bytes(b'{}\n')
        paths = (self.resolve(), owed, detached, receipts)
        before = tuple(path.read_bytes() for path in paths)
        refused = self.cli(*args, grant=False)
        self.assertEqual((refused.returncode, refused.stdout, refused.stderr), (1, '', ledger.GRANT_REFUSAL + '\n'))
        self.assertEqual(tuple(path.read_bytes() for path in paths), before)

    def test_account_auto_refuses_a_symlinked_owed_file(self):
        owed, _, _, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Verdict: PASS {"ab" * 20}')])
        args = ('account-auto', str(owed))
        self.issue_grant(args)
        target = owed.rename(owed.with_name('retained.tsv'))
        owed.symlink_to(target)
        home = self.resolve()
        receipts = self.base / 'state/ultraship/accounted.json'
        receipts.write_bytes(b'{}\n')
        paths = (home, receipts, target)
        before = [path.read_bytes() for path in paths]
        with mock.patch.object(Path, 'read_text', side_effect=AssertionError('unexpected read')):
            refused = self.cli(*args, grant=False)
        self.assertEqual(refused.returncode, 1)
        self.assertEqual(refused.stderr, 'Accounting refuses a symlinked owed file.\n')
        self.assertTrue(owed.is_symlink())
        self.assertEqual([path.read_bytes() for path in paths], before)

    def test_account_auto_reads_the_owed_file_once(self):
        owed, _, _, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Verdict: PASS {"ab" * 20}')])
        home = self.resolve()
        args = ('account-auto', str(owed))
        self.issue_grant(args)
        with mock.patch.object(ledger.os, 'open', wraps=os.open) as fd_open, \
                mock.patch.object(Path, 'open', autospec=True, side_effect=Path.open) as path_open:
            result = self.cli(*args, grant=False)
        reads = [call for spy in (fd_open, path_open) for call in spy.call_args_list
                 if call.args[0] in (owed, str(owed), owed.name)]
        self.assertEqual(len(reads), 1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('1 accounted, 0 pending\n', result.stdout)
        self.assertEqual(ledger.rows(home)[-1][1], 'account-result')

    def test_account_auto_reports_unbound_result_without_review_credit(self):
        sha = 'ab' * 20
        owed, transcript, result, epoch = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Verdict: PASS {sha}')])
        orphan = {key: value for key, value in result.items() if key not in ('ledger', 'run')}
        owed.write_text(f'{epoch}\tship:reviewer--sol\t{self.checkout}\t{json.dumps(orphan)}\n')
        receipt = owed.parent.parent / 'accounted.json'
        home = self.resolve()
        before = (owed.read_bytes(), home.read_bytes())

        auto = self.cli('account-auto', str(owed))
        self.assertEqual(auto.returncode, 0, auto.stderr)
        record, total = auto.stdout.splitlines()
        kind, _, evidence = record.partition(' ')
        self.assertEqual(kind, 'orphaned', auto.stdout)
        self.assertEqual(json.loads(evidence), {
            'id': result['id'], 'agent': 'ship:reviewer--sol@reviewer', 'sha': '',
            'transcript': str(transcript), 'reason': 'original ledger and run binding is missing',
        })
        self.assertEqual(total, '0 accounted, 1 pending')
        self.assertEqual(self.cli('account-auto', str(owed)).stdout, auto.stdout)
        self.assertEqual((owed.read_bytes(), home.read_bytes()), before)
        self.assertFalse(receipt.exists())
        self.assertIn('"decision": "block"', self.hook('stop'))
        self.assertEqual(owed.read_bytes(), before[0])
        self.assertFalse(receipt.exists())

    def test_account_auto_distinguishes_missing_bindings_from_invalid_data_and_receipts(self):
        owed, _, result, epoch = self.auto_owed(None)
        home = self.resolve()
        receipt = owed.parent.parent / 'accounted.json'
        key = json.dumps([str(owed), str(self.checkout), result['id']])
        for field, saved, invalid in (('ledger', False, False), ('run', False, False),
                                      ('ledger', True, False), ('ledger', False, True)):
            with self.subTest(field=field, receipt=saved, invalid=invalid):
                notice = result.copy()
                if invalid:
                    notice[field] = 0
                else:
                    del notice[field]
                owed.write_text(f'{epoch}\tship:reviewer--sol\t{self.checkout}\t{json.dumps(notice)}\n')
                history = ledger.rows(home)
                receipt.write_text(json.dumps({key: [str(home), result['run'],
                    ledger.run_identity(1, history[1])]} if saved else {}))
                paths = (owed, home, receipt)
                before = tuple(path.read_bytes() for path in paths)
                auto = self.cli('account-auto', '--fail-unparsed', str(owed))
                self.assertEqual(auto.returncode, 0, auto.stderr)
                status = 'pending' if invalid or saved else 'orphaned'
                self.assertTrue(auto.stdout.startswith(status + ' '), auto.stdout)
                self.assertTrue(auto.stdout.endswith('0 accounted, 1 pending\n'), auto.stdout)
                self.assertEqual(tuple(path.read_bytes() for path in paths), before)

    def test_account_auto_recovers_recorded_run_in_mixed_queue(self):
        sha = 'ab' * 20
        owed, transcript, unbound, epoch = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Verdict: FINDINGS {sha}')])
        del unbound['ledger'], unbound['run']
        owed.write_text(f'{epoch}\tship:reviewer--sol\t{self.checkout}\t{json.dumps(unbound)}\n')
        _, _, bound, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Verdict: FINDINGS {sha}')])
        home = self.resolve()
        pending = owed.read_bytes()

        auto = self.cli('account-auto', str(owed))
        self.assertEqual(auto.returncode, 0, auto.stderr)
        orphan, recorded, count = auto.stdout.splitlines()
        self.assertEqual(json.loads(orphan.removeprefix('orphaned '))['transcript'], str(transcript))
        self.assertEqual(recorded, f"accounted {bound['id']} ship:reviewer--sol@reviewer {sha} findings")
        self.assertEqual(count, '1 accounted, 1 pending')
        snapshot = home.read_bytes()
        self.assertEqual(ledger.rows(home)[-1][3:5], [sha, 'findings'])
        self.assertEqual(owed.read_bytes(), pending)
        self.assertIn('1 recorded and awaiting Stop', self.cli('account-auto', str(owed)).stdout)
        self.assertIn('"decision": "block"', self.hook('stop'))
        self.assertEqual(owed.read_bytes(), pending)
        self.assertEqual(home.read_bytes(), snapshot)
        receipts = json.loads((owed.parent.parent / 'accounted.json').read_bytes())
        self.assertEqual([json.loads(key)[2] for key in receipts], [bound['id']])

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
        self.assertEqual(self.cli('account-auto', str(owed)).stdout,
                         '1 recorded and awaiting Stop\n0 accounted, 0 pending\n')
        self.assertEqual(home.read_bytes(), saved)
        pending = owed.read_bytes()
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(owed.read_bytes(), b'')
        owed.write_bytes(pending)
        # Once a Stop receipt covers the result, a later run counts it instead of listing it as accounted again.
        self.assertEqual(self.cli('account-auto', str(owed)).stdout, '1 accounted at an earlier Stop\n0 accounted, 0 pending\n')
        self.assertEqual(home.read_bytes(), saved)
        # A result without evidence stays listed as pending beside it.
        fields = pending.decode().rstrip('\n').split('\t')
        bare = {**json.loads(fields[3]), 'id': 'no-evidence'}
        del bare['agent_transcript_path']
        owed.write_bytes(pending + '\t'.join(fields[:3] + [json.dumps(bare)]).encode() + b'\n')
        self.assertEqual(self.cli('account-auto', str(owed)).stdout,
                         'pending no-evidence no transcript\n1 accounted at an earlier Stop\n0 accounted, 1 pending\n')
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

    def assert_auto_accounts_unparsed(self, owed, transcript, result, epoch, reason):
        home = self.resolve()
        before = ledger.rows(home)
        auto = self.cli('account-auto', '--fail-unparsed', str(owed))
        self.assertEqual(auto.returncode, 0, auto.stderr)
        sha = '0' * 40
        self.assertEqual(auto.stdout.splitlines(), [
            f"accounted {result['id']} ship:reviewer--sol@reviewer {sha} fail", '1 accounted, 0 pending'])
        *history, row = ledger.rows(home)
        self.assertEqual(history, before)
        self.assertEqual(row[1:5], ['account-result', 'ship:reviewer--sol@reviewer', sha, 'fail'])
        note = json.loads(row[5])
        self.assertEqual(note['step'], 'review')
        self.assertEqual(note['evidence'],
                         f'{transcript} at {datetime.fromtimestamp(epoch, timezone.utc).isoformat()}: {reason}')

    def test_fail_unparsed_accounts_a_missing_commit(self):
        owed, transcript, result, epoch = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', 'Verdict: PASS abcd1234')])
        before = self.cli('gaps')
        self.assertEqual(before.returncode, 1, before.stderr)
        self.assertIn('deep-review', before.stdout)
        self.assert_auto_accounts_unparsed(owed, transcript, result, epoch, 'expected one commit')
        after = self.cli('gaps')
        self.assertEqual((after.returncode, after.stdout), (before.returncode, before.stdout))

    def test_fail_unparsed_accounts_conflicting_verdicts_as_fail(self):
        owed, transcript, result, epoch = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'OVERALL: PASS\nVerdict: FAIL {"ab" * 20}')])
        self.assert_auto_accounts_unparsed(owed, transcript, result, epoch, 'expected one verdict')

    def test_fail_unparsed_accounts_a_transcript_parse_error(self):
        owed, transcript, result, epoch = self.auto_owed([(-2, 'user', 'Review.')])
        transcript.write_text('{bad json\n')
        self.assert_auto_accounts_unparsed(owed, transcript, result, epoch, 'transcript parse error')

    def test_account_auto_requires_opt_in_for_a_missing_commit(self):
        owed, _, result, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', 'Verdict: PASS abcd1234')])
        before = self.resolve().read_bytes()
        auto = self.cli('account-auto', str(owed))
        self.assertEqual(auto.returncode, 0, auto.stderr)
        self.assertEqual(auto.stdout.splitlines(), [
            f"pending {result['id']} expected one commit", '0 accounted, 1 pending'])
        self.assertEqual(self.resolve().read_bytes(), before)

    def test_fail_unparsed_leaves_a_missing_final_turn_pending(self):
        owed, _, result, _ = self.auto_owed([(-2, 'user', 'Review.')])
        before = self.resolve().read_bytes()
        auto = self.cli('account-auto', '--fail-unparsed', str(owed))
        self.assertEqual(auto.returncode, 0, auto.stderr)
        self.assertEqual(auto.stdout.splitlines(), [
            f"pending {result['id']} no final turn text", '0 accounted, 1 pending'])
        self.assertEqual(self.resolve().read_bytes(), before)

    def test_fail_unparsed_keeps_an_account_refusal_pending(self):
        owed, transcript, result, _ = self.auto_owed([(-2, 'user', 'Review.')])
        transcript.write_text('{bad json\n')
        _, rest = owed.read_text().split('\t', 1)
        owed.write_text('0\t' + rest)
        before = self.resolve().read_bytes()
        auto = self.cli('account-auto', '--fail-unparsed', str(owed))
        self.assertEqual(auto.returncode, 0, auto.stderr)
        self.assertEqual(auto.stdout.splitlines(), [
            f"pending {result['id']} recorded run is missing or differs", '0 accounted, 1 pending'])
        self.assertEqual(self.resolve().read_bytes(), before)

    def test_fail_unparsed_preserves_a_clear_pass(self):
        sha = 'ab' * 20
        owed, _, result, _ = self.auto_owed([
            (-2, 'user', 'Review.'), (-1, 'assistant', f'Verdict: PASS {sha}')])
        auto = self.cli('account-auto', '--fail-unparsed', str(owed))
        self.assertEqual(auto.returncode, 0, auto.stderr)
        self.assertEqual(auto.stdout.splitlines(), [
            f"accounted {result['id']} ship:reviewer--sol@reviewer {sha} pass", '1 accounted, 0 pending'])
        self.assertEqual(ledger.rows(self.resolve())[-1][3:5], [sha, 'pass'])

    def test_account_auto_parses_a_hyphen_prefixed_owed_path(self):
        self.assertEqual(ledger.account_pending_arg(['account-auto', '-archive/s1.tsv']), '-archive/s1.tsv')
        refused = self.cli('account-auto', '-archive/s1.tsv', grant=False)
        self.assertNotIn('usage:', refused.stderr)

    def test_account_auto_refuses_a_foreign_hyphen_prefixed_path(self):
        owed, _, _, _ = self.auto_owed(None)
        relative = Path('-archive/s1.tsv')
        target = self.checkout / relative
        target.parent.mkdir()
        owed.rename(target)
        home = self.resolve()
        before = (target.read_bytes(), home.read_bytes())
        refused = self.cli('account-auto', str(relative), grant=False)
        self.assertEqual(refused.returncode, 1)
        self.assertEqual(refused.stderr, ledger.GRANT_REFUSAL + '\n')
        self.assertEqual(refused.stdout, '')
        self.assertEqual((target.read_bytes(), home.read_bytes()), before)

    def test_account_auto_rejects_invalid_flag_shapes(self):
        grant_refusal = ledger.GRANT_REFUSAL
        usage = 'usage: ledger.py '
        for args, error in (
            ((), usage),
            (('--fail-unparsed',), grant_refusal),
            (('--other', 'pending.tsv'), usage),
            (('pending.tsv', '--fail-unparsed'), usage),
            (('--fail-unparsed', '--fail-unparsed'), grant_refusal),
            (('--fail-unparsed', 'pending.tsv', 'extra'), usage),
        ):
            with self.subTest(args=args):
                auto = self.cli('account-auto', *args)
                self.assertNotEqual(auto.returncode, 0)
                self.assertEqual(auto.stdout, '')
                self.assertTrue(auto.stderr.startswith(error), auto.stderr)

    def test_fail_unparsed_preserves_transcript_and_binding_refusals(self):
        home = self.resolve()
        for reason in ('transcript unavailable', 'transcript scan limit reached',
                       'transcript path does not match the recorded agent and session'):
            with self.subTest(reason=reason):
                owed, transcript, result, _ = self.auto_owed([(-2, 'user', 'Review.')])
                if reason == 'transcript unavailable':
                    transcript.unlink()
                    transcript.mkdir()
                elif reason == 'transcript scan limit reached':
                    with transcript.open('wb') as source:
                        source.truncate(ledger.TRANSCRIPT_SCAN_LIMIT + 1)
                else:
                    fields = owed.read_text().rstrip('\n').split('\t')
                    fields[-1] = json.dumps({**result, 'agent_transcript_path': str(transcript.with_name('agent-other.jsonl'))})
                    owed.write_text('\t'.join(fields) + '\n')
                before = home.read_bytes()
                auto = self.cli('account-auto', '--fail-unparsed', str(owed))
                if transcript.is_dir():
                    transcript.rmdir()
                owed.write_text('')
                self.assertEqual(auto.returncode, 0, auto.stderr)
                self.assertEqual(auto.stdout.splitlines(), [
                    f"pending {result['id']} {reason}", '0 accounted, 1 pending'])
                self.assertEqual(home.read_bytes(), before)

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
        guidance = skill.split('Use `account-auto` only after verifying', 1)[1].split('`correct-binding`', 1)[0]
        for phrase in ('`<session>/subagents/agent-<agent-id>.jsonl`', 'The first word must be a verdict word.',
                       'exactly one `run-start` row', 'The receipt must name the same ledger and run.'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, guidance)

    def test_account_auto_skill_describes_path_row_and_commit_boundaries(self):
        skill = (LEDGER.parent.parent / 'SKILL.md').read_text()
        guidance = skill.split('Use `account-auto` only after verifying', 1)[1].split('`correct-binding`', 1)[0]
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
        self.assertNotEqual(self.correction(scrub, self.line_of('scrub'), ' ').returncode, 0)
        self.assertIn('result ID must match exactly one', self.correction('absent', self.line_of('scrub'), 'swap').stderr)
        self.assertEqual(home.read_bytes(), before)
        fixed = self.correction(scrub, self.line_of('scrub'), 'scrub findings bound to the capacity PASS')
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
        self.assertEqual(self.correction(scrub, self.line_of('scrub'), 'retry').returncode, 0)
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
        self.assertEqual(self.correction(scrub, self.line_of('scrub'), 'swap').returncode, 0)
        audited = self.resolve().read_bytes()
        receipt_path.write_bytes(wrong)  # the audit row landed and the receipts did not
        self.assertEqual(self.correction(scrub, self.line_of('scrub'), 'swap').returncode, 0)
        self.assertEqual(self.resolve().read_bytes(), audited)
        self.assertEqual(self.bound(), {scrub: 'scrub', capacity: 'capacity'})
        # A later, different move still appends its own audit row.
        self.assertEqual(self.correction(scrub, self.line_of('capacity'), 'undo').returncode, 0)
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
                refused = self.correction(scrub, self.line_of(note), 'move')
                self.assertIn('target line must be a completed review row', refused.stderr)
        self.assertIn('target line must be', self.correction(scrub, '999', 'move').stderr)
        self.assertEqual((home.read_bytes(), (self.base / 'state/ultraship/accounted.json').read_bytes()), before)
        with home.open('ab') as fh:
            fh.write(b'\n')  # a blank line before the next row makes file lines and rows differ
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass', 'after-blank').returncode, 0)
        self.assertIn('ledger lines differ', self.correction(scrub, self.line_of('scrub'), 'move').stderr)

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
        refused = self.correction(first, self.line_of('ordinary'), 'move')
        self.assertIn('cannot take the current row', refused.stderr)
        explicit = str(next(i for i, r in enumerate(ledger.rows(self.resolve())) if r[1] == 'account-result') + 1)
        refused = self.correction(second, explicit, 'move')  # same agent column, but a record row
        self.assertIn('target line must be a completed review row', refused.stderr)

    def test_correct_binding_refuses_receipt_and_swap_from_another_owed_path(self):
        scrub, capacity, _ = self.swapped_pair()
        home = self.resolve()
        root = self.base / 'state/ultraship'
        owed, receipt_path = root / 'owed/s1.tsv', root / 'accounted.json'
        receipts = json.loads(receipt_path.read_text())
        for identifier in (scrub, capacity):
            with self.subTest(receipt='selected' if identifier == scrub else 'swap'):
                key = next(key for key in receipts if json.loads(key)[2] == identifier)
                foreign_key = json.dumps([str(owed.with_name('s2.tsv')), *json.loads(key)[1:]])
                receipt_path.write_text(json.dumps({foreign_key if k == key else k: v for k, v in receipts.items()}))
                paths = (home, owed, receipt_path)
                before = tuple(path.read_bytes() for path in paths)
                refused = self.correction(scrub, self.line_of('scrub'), 'swap')
                self.assertEqual(refused.returncode, 1)
                expected = ('Accounting receipt belongs to a different owed file.' if identifier == scrub else
                            'target row is credited to another result that cannot take the current row')
                self.assertEqual(refused.stderr, expected + '\n')
                self.assertEqual(tuple(path.read_bytes() for path in paths), before)

    def test_correct_binding_refuses_a_ledger_with_another_line_break(self):
        scrub, _, _ = self.swapped_pair()
        self.assertEqual(self.cli('append', 'deep-review', 'other', 'sha', 'pass', 'a\u2028b').returncode, 0)
        self.assertIn('ledger lines differ', self.correction(scrub, self.line_of('scrub'), 'move').stderr)

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
