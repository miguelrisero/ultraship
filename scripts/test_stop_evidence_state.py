"""Deterministic Stop reminders with retained review evidence."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('stop_hook', ROOT / 'plugins/ship/hooks/ultraship.py')
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class StopEvidenceStateTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT.parent / '.scratch'
        scratch.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(temporary.cleanup)
        state = mock.patch.object(hook, 'STATE', Path(temporary.name))
        state.start()
        self.addCleanup(state.stop)
        self.data = {'session_id': 's1', 'cwd': '/checkout'}
        self.path = hook.owed_file(self.data)
        self.path.parent.mkdir()
        self.reminder = self.path.with_suffix('.stop-state')
        self.rows = [['100', 'ship:reviewer--sol', '/checkout', json.dumps({'id': 'one', 'v': 2})],
                     ['101', 'ship:reviewer--opus', '/checkout', json.dumps({'id': 'two', 'v': 2})]]
        self.write_rows(self.rows)
        self.ledger = mock.Mock()
        loader = mock.patch.object(hook, 'load_ledger', return_value=self.ledger)
        loader.start()
        self.addCleanup(loader.stop)
        account = mock.patch.object(hook, 'account', side_effect=ValueError('review row missing'))
        self.account = account.start()
        self.addCleanup(account.stop)

    def write_rows(self, rows):
        self.path.write_text(''.join('\t'.join(row) + '\n' for row in rows))

    def stop(self, **extra):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            hook.stop({**self.data, **extra})
        return json.loads(output.getvalue()) if output.getvalue() else None

    def assert_blocked(self):
        result = self.stop()
        self.assertEqual(result['decision'], 'block')
        self.assertIn(str(self.path), result['reason'])

    def test_same_state_passes_and_still_attempts_accounting(self):
        pending = self.path.read_bytes()
        self.assert_blocked()
        expected = hashlib.sha256(json.dumps(sorted(json.dumps(
            row[:3] + [json.loads(row[3])], sort_keys=True) for row in self.rows)).encode()).hexdigest()
        self.assertEqual(self.reminder.read_text(), expected)
        for _ in range(2):
            self.assertIsNone(self.stop())
            self.assertEqual(self.path.read_bytes(), pending)
        self.assertEqual(self.account.call_count, 3)
        self.ledger.publish.assert_not_called()
        self.assertFalse((hook.STATE / 'accounted.json').exists())

    def test_canonical_order_and_json_format_share_one_state(self):
        self.assert_blocked()
        rows = [row[:3] + [json.dumps(json.loads(row[3]), sort_keys=True, separators=(',', ':'))]
                for row in reversed(self.rows)]
        self.write_rows(rows)
        pending = self.path.read_bytes()
        self.assertIsNone(self.stop())
        self.assertEqual(self.path.read_bytes(), pending)

    def test_each_row_field_and_duplicate_count_rearm_the_block(self):
        self.assert_blocked()
        for index, value in enumerate(['102', 'ship:verifier--opus', '/other', '{"id":"three","v":2}']):
            with self.subTest(field=index):
                rows = [row.copy() for row in self.rows]
                rows[0][index] = value
                self.write_rows(rows)
                self.assert_blocked()
                self.assertIsNone(self.stop())
                self.write_rows(self.rows)
                self.assert_blocked()
        self.write_rows(self.rows + [self.rows[0]])
        self.assert_blocked()
        self.assertIsNone(self.stop())

    def test_accounting_success_clears_evidence_and_reminder(self):
        self.assert_blocked()
        self.account.side_effect = None
        self.assertIsNone(self.stop())
        self.ledger.publish.assert_called_once_with(hook.STATE / 'accounted.json', {})
        self.assertEqual(self.path.read_bytes(), b'')
        self.assertFalse(self.reminder.exists())
        self.account.side_effect = ValueError('review row missing')
        self.write_rows(self.rows)
        self.assert_blocked()

    def test_empty_pending_clears_reminder(self):
        self.assert_blocked()
        self.path.write_text('')
        self.assertIsNone(self.stop())
        self.assertFalse(self.reminder.exists())
        self.write_rows(self.rows)
        self.assert_blocked()

    def test_active_hook_and_missing_file_skip_the_reminder(self):
        self.assertIsNone(self.stop(stop_hook_active=True))
        self.assertFalse(self.reminder.exists())
        self.account.assert_not_called()
        self.path.unlink()
        self.assertIsNone(self.stop())
        self.account.assert_not_called()
        self.write_rows(self.rows)
        self.assert_blocked()
        self.path.unlink()
        self.assertIsNone(self.stop())
        self.assertFalse(self.reminder.exists())
        self.write_rows(self.rows)
        self.assert_blocked()

    def test_legacy_and_malformed_rows_block_once_without_losing_bytes(self):
        for rows in ([row[:3] for row in self.rows], [self.rows[0][:3] + ['{broken']], [['broken']]):
            with self.subTest(rows=rows):
                self.write_rows(rows)
                pending = self.path.read_bytes()
                self.assert_blocked()
                self.assertIsNone(self.stop())
                self.assertEqual(self.path.read_bytes(), pending)

    def test_ledger_load_failure_blocks_once_and_recovers_accounting(self):
        with mock.patch.object(hook, 'load_ledger', side_effect=PermissionError('ledger denied')):
            self.assert_blocked()
            self.assertIsNone(self.stop())
        self.account.side_effect = None
        self.assertIsNone(self.stop())
        self.assertEqual(self.path.read_bytes(), b'')

    def test_reminder_access_failure_keeps_blocking_and_preserves_evidence(self):
        pending = self.path.read_bytes()
        self.reminder.mkdir()
        for _ in range(2):
            self.assert_blocked()
            self.assertEqual(self.path.read_bytes(), pending)
        self.reminder.rmdir()
        with mock.patch.object(Path, 'write_text', side_effect=PermissionError('reminder denied')):
            for _ in range(2):
                self.assert_blocked()
                self.assertEqual(self.path.read_bytes(), pending)
        self.assertFalse(self.reminder.exists())
        self.assert_blocked()
        self.assertIsNone(self.stop())


if __name__ == '__main__':
    unittest.main()
