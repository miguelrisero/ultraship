"""Synthetic linked-worktree ledger and hook regressions; retain all allocations."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
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
        print(f'Retained synthetic ledger allocation: {self.base}', flush=True)
        self.env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
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

    def test_stop_accounts_closed_run_and_refuses_next_run_evidence(self):
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode, 0)
        self.finish_run()
        self.assertEqual(self.hook('stop'), '')
        self.hook('subagent-stop', agent_type='ship:reviewer--opus')
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
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode, 0)
        self.assertEqual(self.hook('stop'), '')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        receipts = self.base / 'state/ultraship/accounted.json'
        committed = receipts.read_bytes()
        self.hook('subagent-stop', agent_type='ship:reviewer--sol', agent_id='same-agent')
        fields = owed.read_text().rstrip('\n').split('\t')
        # Keep the historical five-second tolerance in play across separate Stops.
        row_epoch = next(r[0] for r in ledger.rows(self.resolve()) if r[2] == 'ship:reviewer--sol')
        fields[0] = str(int(row_epoch) + 4)
        owed.write_text('\t'.join(fields) + '\n')
        evidence = owed.read_bytes()
        self.assertEqual(json.loads(self.hook('stop'))['decision'], 'block')
        self.assertEqual(owed.read_bytes(), evidence)
        self.assertEqual(receipts.read_bytes(), committed)
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode, 0)
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
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode, 0)
        self.finish_run()
        self.assertEqual(self.hook('stop'), '')

    def test_actual_hooks_retain_exact_evidence_until_accounted(self):
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        self.hook('subagent-stop', agent_type='ship:reviewer--sol')
        owed = self.base / 'state/ultraship/owed/s1.tsv'
        evidence = owed.read_bytes()
        bad_env = {**self.env, 'SHIP_LEDGER_DIR': 'relative'}
        blocked = json.loads(self.hook('stop', env=bad_env))
        self.assertEqual(blocked['decision'], 'block')
        self.assertIn('SHIP_LEDGER_DIR', blocked['reason'])
        self.assertEqual(owed.read_bytes(), evidence)
        self.assertIn('Ledger resolution failed', self.hook('compact', env=bad_env))
        self.assertEqual(owed.read_bytes(), evidence)
        self.assertEqual(self.hook('stop', env=bad_env, stop_hook_active=True), '')
        self.assertEqual(owed.read_bytes(), evidence)
        empty_env = {**self.env, 'SHIP_LEDGER_DIR': str(self.base / 'empty')}
        self.assertIn('Ledger home differs', json.loads(self.hook('stop', env=empty_env))['reason'])
        self.assertEqual(owed.read_bytes(), evidence)
        # A failed CLI append leaves the pending evidence intact.
        obstruction = self.base / 'file-not-directory'
        obstruction.write_text('keep')
        failed_env = {**self.env, 'SHIP_LEDGER_DIR': str(obstruction)}
        self.assertNotEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha',
                                     'pass', env=failed_env).returncode, 0)
        self.assertEqual(json.loads(self.hook('stop', env=failed_env))['decision'], 'block')
        self.assertEqual(owed.read_bytes(), evidence)
        local = self.resolve()
        local.chmod(0o400)
        try:
            if os.geteuid() != 0:
                failed = self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass')
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn('PermissionError', failed.stderr)
                self.assertEqual(json.loads(self.hook('stop'))['decision'], 'block')
                self.assertEqual(owed.read_bytes(), evidence)
        finally:
            local.chmod(0o600)
        self.assertEqual(self.cli('append', 'deep-review', 'unrelated', 'sha', 'pass').returncode, 0)
        self.assertEqual(json.loads(self.hook('stop'))['decision'], 'block')
        self.assertEqual(owed.read_bytes(), evidence)
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'owed').returncode, 0)
        self.assertEqual(json.loads(self.hook('stop'))['decision'], 'block')
        self.assertEqual(owed.read_bytes(), evidence)
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode, 0)
        self.assertEqual(json.loads(self.hook('stop'))['decision'], 'block')
        self.assertEqual(owed.read_bytes(), evidence)
        self.assertEqual(self.cli('append', 'deep-review', 'ship:reviewer--sol', 'sha', 'pass').returncode, 0)
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(owed.read_bytes(), b'')
        self.assertEqual(self.hook('stop'), '')
        self.assertEqual(self.legacy.read_bytes(), self.history)
