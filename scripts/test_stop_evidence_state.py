"""Deterministic Stop reminders with retained review evidence."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import shlex
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('stop_hook', ROOT / 'plugins/ship/hooks/ultraship.py')
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class StopEvidenceStateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
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
        self.ledger.load_receipts.return_value = {}
        loader = mock.patch.object(hook, 'load_ledger', return_value=self.ledger)
        loader.start()
        self.addCleanup(loader.stop)
        account = mock.patch.object(hook, 'account', return_value=[], side_effect=ValueError('review row missing'))
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
        return result

    def test_recovery_guidance_covers_every_retained_agent_identity(self):
        for row, agent_id in zip(self.rows, ('first-agent', 'second-agent')):
            result = json.loads(row[3])
            result['agent_id'] = agent_id
            row[3] = json.dumps(result)
        self.write_rows(self.rows)
        pending = self.path.read_bytes()
        self.account.side_effect = ValueError('no ledger row for first-agent')
        reason = self.assert_blocked()['reason']
        self.assertIn('no ledger row for first-agent', reason)
        self.assertIn('Record each result with', reason)
        self.assertIn('Use the exact agent identity, including @agent_id when present.', reason)
        self.assertIn('\none ship:reviewer--sol@first-agent ', reason)
        self.assertIn('\ntwo ship:reviewer--opus@second-agent ', reason)
        self.assertEqual(self.path.read_bytes(), pending)
        self.assertIsNone(self.stop())

    def test_stop_names_void_accounting_for_a_stopped_agent_without_review_evidence(self):
        reason = self.assert_blocked()['reason']
        self.assertIn(f'account-void {shlex.quote(str(self.path))} <result-id>', reason)
        self.assertIn('zero tool calls and no review labels', reason)

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

    def test_stop_loads_receipts_through_ledger(self):
        path = hook.STATE / 'accounted.json'
        receipts = {'result': ['ledger', [0, 'run'], [1, 'row']]}
        self.ledger.load_receipts.return_value = receipts
        self.account.side_effect = None
        self.assertIsNone(self.stop())
        self.ledger.load_receipts.assert_called_once_with(path)
        self.account.assert_called_once_with(self.ledger, self.rows, receipts, str(self.path))
        self.ledger.publish.assert_called_once_with(path, receipts)

    def test_pending_list_has_twenty_results_with_utc_times_and_an_overflow_count(self):
        self.write_rows([['100', 'ship:reviewer--sol', '/checkout',
                          json.dumps({'id': f'result-{i:02d}', 'agent_id': 'seat'})] for i in range(22)])
        reason = self.assert_blocked()['reason']
        lines = [line for line in reason.splitlines() if line.startswith('result-')]
        self.assertEqual(lines, [f'result-{i:02d} ship:reviewer--sol@seat 1970-01-01T00:01:40+00:00'
                                 for i in range(20)])
        self.assertIn('2 more results (22 total pending)', reason.splitlines())
        self.assertNotIn(' account-auto ', reason)

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

    def test_compact_retains_pending_path_recovery_and_stop_fingerprint(self):
        self.assert_blocked()
        pending, fingerprint = self.path.read_bytes(), self.reminder.read_bytes()
        self.ledger.open_run.return_value = None
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            hook.compact(self.data)
        self.assertIn(f'Pending review evidence remains at {self.path}', output.getvalue())
        self.assertIn('Account each result with ledger.py', output.getvalue())
        self.assertEqual(self.path.read_bytes(), pending)
        self.assertEqual(self.reminder.read_bytes(), fingerprint)
        self.assertIsNone(self.stop())
        for missing in (False, True):
            with self.subTest(missing=missing):
                self.path.write_text('')
                if missing:
                    self.path.unlink()
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    hook.compact(self.data)
                self.assertNotIn('Pending review evidence', output.getvalue())
                self.assertEqual(self.reminder.read_bytes(), fingerprint)

    def test_reminder_access_failure_keeps_blocking_and_preserves_evidence(self):
        pending = self.path.read_bytes()
        self.reminder.mkdir()
        for _ in range(2):
            reason = self.assert_blocked()['reason']
            self.assertIn('review row missing', reason)
            self.assertIn('Stop reminder unavailable', reason)
            self.assertEqual(self.path.read_bytes(), pending)
        self.reminder.rmdir()
        with mock.patch.object(Path, 'write_text', side_effect=PermissionError('reminder denied')):
            for _ in range(2):
                reason = self.assert_blocked()['reason']
                self.assertIn('review row missing', reason)
                self.assertIn('Stop reminder unavailable: reminder denied', reason)
                self.assertEqual(self.path.read_bytes(), pending)
        self.assertFalse(self.reminder.exists())
        self.assert_blocked()
        self.assertIsNone(self.stop())


class StopAccountingGrantTests(unittest.TestCase):
    def test_accounting_commands_work_through_the_hook_and_cli(self):
        for form in ('account', 'account-auto', '--fail-unparsed', 'driver-batch'):
            with self.subTest(form=form), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary).resolve() / 'with spaces'
                state = base / 'state'
                script = base / 'plugin scripts/ledger.py'
                script.parent.mkdir(parents=True)
                script.write_bytes(hook.ledger_script().read_bytes())
                ledger_spec = importlib.util.spec_from_file_location('quoted_ledger', script)
                ledger = importlib.util.module_from_spec(ledger_spec)
                ledger_spec.loader.exec_module(ledger)
                session = 's1'
                data = {'session_id': session, 'cwd': str(base)}
                with mock.patch.object(hook, 'STATE', state), \
                        mock.patch.object(hook, 'ledger_script', return_value=script), \
                        mock.patch.object(hook, 'load_ledger', return_value=ledger), \
                        mock.patch.object(ledger, 'grant_store', return_value=base / 'grants'):
                    owed = hook.owed_file(data)
                    owed.parent.mkdir(parents=True)
                    home = base / 'ledger.tsv'
                    start = ['1', 'run-start', 'light', 'abcdef1', 'open', 'run']
                    home.write_text('\t'.join(start) + '\n')
                    transcript = base / 's1/subagents/agent-seat.jsonl'
                    transcript.parent.mkdir(parents=True)
                    review = 'Verdict: PASS ' + 'ab' * 20 if form != '--fail-unparsed' else 'Verdict: PASS'
                    transcript.write_text('\n'.join(json.dumps(row) for row in (
                        {'timestamp': '1970-01-01T00:01:38Z', 'type': 'user', 'message': {'content': 'Review.'}},
                        {'timestamp': '1970-01-01T00:01:39Z', 'type': 'assistant',
                         'message': {'content': [{'type': 'text', 'text': review}]}})) + '\n')
                    identifier = '11111111-1111-1111-1111-111111111111'
                    result = {'id': identifier, 'v': 2, 'agent_id': 'seat', 'ledger': str(home),
                              'run': ledger.run_identity(0, start), 'agent_transcript_path': str(transcript)}
                    notices = [result]
                    if form == 'driver-batch':
                        second = transcript.with_name('agent-second.jsonl')
                        second.write_bytes(transcript.read_bytes())
                        notices.append({**result, 'id': '22222222-2222-2222-2222-222222222222',
                                        'agent_id': 'second', 'agent_transcript_path': str(second)})
                    owed.write_text(''.join('\t'.join(['100', 'ship:reviewer--sol', str(base), json.dumps(record)]) + '\n'
                                            for record in notices))
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        hook.stop(data)
                    diagnostic = json.loads(output.getvalue())
                    self.assertEqual(diagnostic['decision'], 'block')
                    if form == 'account':
                        command, = re.findall(r'`([^`]* account [^`]*)`', diagnostic['reason'])
                        for placeholder, value in zip(
                                ('<result-id>', '<step>', '<agent>', '<sha>', '<verdict>', '<evidence>'),
                                (identifier, 'review', 'ship:reviewer--sol@seat', 'abcdef1', 'pass', 'review file')):
                            command = command.replace(placeholder, value)
                    else:
                        self.assertNotIn(' account-auto ', diagnostic['reason'])
                        flags = ['--fail-unparsed'] if form == '--fail-unparsed' else []
                        command = shlex.join(['python3', str(script), 'account-auto', *flags, str(owed)])
                    event = {**data, 'tool_name': 'Bash', 'tool_input': {'command': command}}
                    if form == 'driver-batch':
                        event['agent_type'] = 'ship:driver'
                    words = shlex.split(command)
                    with mock.patch.object(sys, 'argv', words[1:]), \
                            mock.patch.object(ledger.time, 'time_ns', return_value=100_000_000_000), \
                            contextlib.redirect_stdout(io.StringIO()) as accounting:
                        hook.guarded_pre(event)
                        ledger.main(words[2:])
                        if form == 'driver-batch':
                            self.assertIn('2 accounted, 0 pending', accounting.getvalue())
                        after = home.read_bytes()
                        with self.assertRaisesRegex(SystemExit, 'requires a fresh grant'):
                            ledger.main(words[2:])
                        self.assertEqual(home.read_bytes(), after)
                        hook.guarded_pre(event)
                        ledger.main(words[2:])
                        self.assertEqual(home.read_bytes(), after)
                    row = ledger.rows(home)[-1]
                    self.assertEqual(row[1], 'account-result')
                    self.assertEqual(row[4], 'fail' if form == '--fail-unparsed' else 'pass')
                    self.assertEqual(row[3], '0' * 40 if form == '--fail-unparsed' else (
                        'abcdef1' if form == 'account' else 'ab' * 20))
                    if form == 'driver-batch':
                        pending = owed.read_bytes()
                        failure = io.StringIO()
                        with mock.patch.object(ledger, 'publish', side_effect=OSError('receipt write failed')) as publish, \
                                contextlib.redirect_stdout(failure):
                            hook.stop(data)
                        publish.assert_called_once()
                        self.assertFalse((state / 'accounted.json').exists())
                        self.assertEqual(owed.read_bytes(), pending)
                        retry = io.StringIO()
                        with mock.patch.object(sys, 'argv', words[1:]), contextlib.redirect_stdout(retry):
                            hook.guarded_pre(event)
                            ledger.main(words[2:])
                        self.assertEqual(retry.getvalue(),
                                         '2 recorded and awaiting Stop\n0 accounted, 0 pending\n')
                        self.assertEqual(home.read_bytes(), after)
                        self.assertEqual(owed.read_bytes(), pending)
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        hook.stop(data)
                    self.assertEqual(output.getvalue(), '')
                    self.assertEqual(owed.read_bytes(), b'')


if __name__ == '__main__':
    unittest.main()
