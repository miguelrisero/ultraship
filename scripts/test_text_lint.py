"""Outgoing prose lint: glued word-number shorthand and restated-hold walls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import runpy
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ship_text_lint', ROOT / 'plugins/ship/hooks/text_lint.py')
text_lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(text_lint)


class TextLintTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {'XDG_STATE_HOME': temporary}))
        self.state = Path(temporary) / 'ultraship' / 'text-lint'
        self.clock = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
        self.enterContext(patch.object(text_lint, 'now', return_value=self.clock))

    def test_self_test(self):
        text_lint.self_test()

    def test_sendmessage_reports_the_exact_missing_facts_remedy(self):
        message = ('The review passes.\n'
                   'Facts: The checks pass.\n'
                   'Decision: Continue.\n'
                   'Next: The driver resumes at 2026-11-13T18:00:00Z.')
        event = {'tool_name': 'SendMessage',
                 'tool_input': {'to': 'chief', 'message': message}}
        text_lint.outgoing(event)
        event['tool_input']['message'] = message.replace('Facts:', 'Evidence:')

        with self.assertRaises(ValueError) as refusal:
            text_lint.outgoing(event)

        self.assertEqual(str(refusal.exception), 'Missing section: Facts')

    RESEND = (' You may resend once with the same action, recipient, scope and content, '
              'changed only in format. Resend with this shape:\n')
    NO_RESEND = (' This refusal is not formatting-only, so no resend of this message '
                 'is allowed in any form.')

    def hook_output(self, event):
        output = io.StringIO()
        with redirect_stdout(output):
            text_lint.hook(event)
        return json.loads(output.getvalue())['hookSpecificOutput'] if output.getvalue() else None

    def hook_refusal(self, event):
        result = self.hook_output(event)
        self.assertEqual(result['hookEventName'], 'PreToolUse')
        self.assertEqual(result['permissionDecision'], 'deny')
        reason = result['permissionDecisionReason']
        match = re.search(r' Receipt: `([0-9a-f]{32})`\.', reason)
        self.assertIsNotNone(match)
        receipt_id = match[1]
        receipt = json.loads((self.state / 'receipts' / (receipt_id + '.json')).read_text())
        suffix = ' Receipt: `' + receipt_id + '`.'
        if receipt['resend_allowed']:
            suffix += ' To resend, put `<!-- ultraship-receipt:' + receipt_id + ' -->` in the resent prose.'
        self.assertTrue(reason.endswith(suffix), reason)
        self.last_receipt = receipt
        return reason[:-len(suffix)]

    def event(self, message='The review passes.', **fields):
        return {'session_id': 'session-one', 'tool_use_id': 'tool-one', 'agent_id': 'agent-one',
                'tool_name': 'SendMessage', 'tool_input': {'to': 'chief', 'message': message, **fields}}

    def resend(self, receipt_id, message=None):
        message = message or 'The review passes.\nFacts: Checks pass.\nDecision: Continue.\nNext: Resume.'
        return self.event(message + '\n<!-- ultraship-receipt:' + receipt_id + ' -->')

    def test_subagent_format_refusal_has_resend_template(self):
        """Catch a missing one-resend grant or a peer template sent to a child."""
        for recipient in ('main', 'a' + '0' * 16):
            for prose, error in (
                    (' '.join(['word'] * 26) + '.', 'Write at most 25 words per sentence.'),
                    ('Send deadline2026 by8November00.',
                     'Separate glued words with spaces; remove compressed shorthand.')):
                with self.subTest(recipient=recipient, error=error):
                    message = prose + '\nFacts: Checks pass.\nDecision: Continue.\nNext: Resume.'
                    event = {'tool_name': 'SendMessage',
                             'tool_input': {'to': recipient, 'message': message}}
                    self.assertEqual(self.hook_refusal(event),
                                     'Output contract: ' + error + self.RESEND
                                     + text_lint.SUBAGENT_TEMPLATE)

    def test_subagent_missing_section_refusal_has_peer_template(self):
        """Catch a child remedy that omits required peer headings."""
        for prose in ('The review passes.', ' '.join(['word'] * 26) + '.'):
            with self.subTest(prose=prose):
                message = prose + '\nDecision: Continue.\nNext: Resume.'
                event = {'tool_name': 'SendMessage',
                         'tool_input': {'to': 'main', 'message': message}}
                prefix = ('Write at most 25 words per sentence. '
                          if prose.startswith('word') else '')
                self.assertEqual(self.hook_refusal(event),
                                 'Output contract: ' + prefix + 'Missing section: Facts'
                                 + self.RESEND + text_lint.PEER_TEMPLATE)

    def test_peer_refusal_has_resend_template(self):
        """Catch a peer formatting refusal that fails to permit one resend."""
        event = {'tool_name': 'SendMessage',
                 'tool_input': {'to': 'chief', 'message': 'The review passes.'}}
        self.assertEqual(self.hook_refusal(event),
                         'Output contract: Missing section: Facts Missing section: Decision '
                         'Missing section: Next' + self.RESEND + text_lint.PEER_TEMPLATE)

    def test_input_format_refusal_has_resend_template(self):
        """Catch Input refusals that omit resend permission or the Input shape."""
        decision = ('<meta name="output-kind" content="decision">'
                    '<h2>What is wrong</h2><p>The release waits.</p>'
                    '<h2>Why now</h2><p>The deadline approaches.</p>'
                    '<h2>Options A to C</h2><p>A: Hold. B: Release. C: Defer.</p>'
                    '<h2>If no answer</h2><p>Keep the hold.</p>')
        for tool in ('create_input', 'update_input'):
            for body, error in (
                    ('<p>The release waits.</p>',
                     'Input HTML requires one explicit output-kind classification: decision or result.'),
                    (decision, 'Missing section: Recommendation')):
                with self.subTest(tool=tool, error=error):
                    event = {'tool_name': 'mcp__bettercoding__' + tool,
                             'tool_input': {'content': {'html': body}}}
                    self.assertEqual(self.hook_refusal(event),
                                     'Output contract: ' + error + self.RESEND
                                     + text_lint.INPUT_TEMPLATE)
        self.assertIn('<meta name="output-kind" content="decision">', text_lint.INPUT_TEMPLATE)
        self.assertIn('<meta name="output-kind" content="result">', text_lint.INPUT_TEMPLATE)
        headings = ('What is wrong', 'Why now', 'Options A to C with effects',
                    'Recommendation', 'If no answer')
        positions = [text_lint.INPUT_TEMPLATE.index('<h2>' + heading + '</h2>') for heading in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('Write at most 25 words per sentence.', text_lint.INPUT_TEMPLATE)

    def test_non_format_refusal_forbids_resend_without_template(self):
        """Catch hold-wall or malformed-payload denials that offer a resend."""
        wall = ('The review waits.\n'
                'Facts: Preserve every hold. Custody stays. Admission waits. Preserve the refusal.\n'
                'Decision: Wait.\nNext: The driver checks.')
        for event, error in (
                ({'tool_name': 'SendMessage', 'tool_input': {'to': 'chief', 'message': wall}},
                 'Keep any new hold in one line, drop restated standing holds, and send what changed and the next action.'),
                ({'tool_name': 'SendMessage', 'tool_input': ['malformed']},
                 "'list' object has no attribute 'get'")):
            with self.subTest(error=error):
                reason = self.hook_refusal(event)
                self.assertEqual(reason, 'Output contract: ' + error + self.NO_RESEND)
                self.assertNotIn('Resend with this shape:', reason)
                self.assertFalse(self.last_receipt['formatting_only'])
                self.assertFalse(self.last_receipt['resend_allowed'])

    def test_receipt_has_all_fields_and_valid_mac(self):
        event = self.event()
        self.hook_refusal(event)
        receipt = self.last_receipt
        self.assertEqual(set(receipt), {'id', 'session_id', 'tool_use_id', 'agent_id', 'tool_name',
                         'recipient', 'input_sha256', 'fields_sha256', 'findings', 'formatting_only',
                         'resend_allowed', 'parent', 'created_at', 'mac'})
        self.assertEqual(len(list((self.state / 'receipts').glob('*.json'))), 1)
        for field in ('session_id', 'tool_use_id', 'agent_id', 'tool_name'):
            self.assertEqual(receipt[field], event[field])
        self.assertEqual(receipt['recipient'], 'chief')
        self.assertEqual(receipt['findings'], ['Missing section: Facts', 'Missing section: Decision', 'Missing section: Next'])
        self.assertTrue(receipt['formatting_only'])
        self.assertTrue(receipt['resend_allowed'])
        self.assertIsNone(receipt['parent'])
        self.assertEqual(receipt['created_at'], '2026-11-15T12:00:00Z')
        key = (self.state / 'key').read_bytes()
        self.assertEqual(len(key), 32)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.state / 'key').stat().st_mode), 0o600)
        body = {k: v for k, v in receipt.items() if k != 'mac'}
        encode = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        self.assertEqual(receipt['mac'], hmac.new(key, encode(body), hashlib.sha256).hexdigest())
        self.assertEqual(receipt['input_sha256'], hashlib.sha256(encode(event['tool_input'])).hexdigest())
        self.assertEqual(receipt['fields_sha256'], hashlib.sha256(encode({'to': 'chief'})).hexdigest())

    def test_mixed_findings_deny_resend(self):
        wall = 'Preserve every hold. Custody stays. Admission waits. Preserve the refusal.'
        reason = self.hook_refusal(self.event(wall))
        self.assertIn('Missing section: Facts', reason)
        self.assertIn('Keep any new hold in one line', reason)
        self.assertFalse(self.last_receipt['formatting_only'])
        self.assertFalse(self.last_receipt['resend_allowed'])
        self.assertEqual(len(self.last_receipt['findings']), 4)

    def test_input_title_and_body_findings_are_collected(self):
        event = {'tool_name': 'mcp__bettercoding__create_input', 'tool_input': {'content': {
            'title': ' '.join(['word'] * 26),
            'html': '<meta name="output-kind" content="decision"><p>The release waits.</p>'}}}
        self.hook_refusal(event)
        self.assertIn('Write at most 25 words per sentence.', self.last_receipt['findings'])
        self.assertIn('Missing section: Recommendation', self.last_receipt['findings'])
        self.assertEqual(len(self.last_receipt['findings']), 6)

    def test_forged_and_edited_receipts_fail_mac(self):
        for edit in ('mac', 'recipient'):
            with self.subTest(edit=edit):
                self.hook_refusal(self.event())
                receipt = self.last_receipt
                receipt[edit] = '0' * 64 if edit == 'mac' else 'another-chief'
                (self.state / 'receipts' / (receipt['id'] + '.json')).write_text(json.dumps(receipt))
                reason = self.hook_refusal(self.resend(receipt['id']))
                self.assertIn('Invalid receipt mac.', reason)
                self.assertFalse(self.last_receipt['resend_allowed'])

    def test_valid_resend_passes_once_and_comments_are_invisible(self):
        self.hook_refusal(self.event())
        receipt_id = self.last_receipt['id']
        event = self.resend(receipt_id)
        self.assertNotIn('ultraship-receipt', ''.join(text_lint.VisibleText(event['tool_input']['message']).parts))
        self.assertIsNone(self.hook_output(event))
        self.assertTrue((self.state / 'receipts' / (receipt_id + '.consumed')).exists())
        self.assertIn('Receipt is consumed.', self.hook_refusal(event))
        self.assertFalse(self.last_receipt['resend_allowed'])

    def test_session_recipient_tool_and_fields_are_bound(self):
        for field in ('session_id', 'recipient', 'tool_name', 'fields', 'null_session'):
            with self.subTest(field=field):
                self.hook_refusal(self.event())
                event = self.resend(self.last_receipt['id'])
                if field == 'session_id':
                    event[field] = 'session-two'
                elif field == 'null_session':
                    event['session_id'] = None
                elif field == 'recipient':
                    event['tool_input']['to'] = 'another-chief'
                elif field == 'fields':
                    event['tool_input']['scope'] = 'new-scope'
                else:
                    marker = event['tool_input']['message']
                    event['tool_name'] = 'mcp__bettercoding__create_input'
                    event['tool_input'] = {'content': {'html': marker}}
                self.assertIn('Invalid receipt citation:', self.hook_refusal(event))
                self.assertFalse(self.last_receipt['resend_allowed'])

    def test_input_resend_preserves_parsed_non_prose_fields(self):
        event = {'session_id': 'session-one', 'tool_name': 'mcp__bettercoding__create_input',
                 'tool_input': {'workspace_id': 'workspace-one', 'content': json.dumps({
                     'title': 'A result', 'html': '<p>The review passes.</p>',
                     'contract': {'allow_text': True}})}}
        self.hook_refusal(event)
        receipt_id = self.last_receipt['id']
        self.assertEqual(self.last_receipt['recipient'], 'workspace-one')
        content = json.loads(event['tool_input']['content'])
        content['html'] = ('<meta name="output-kind" content="result"><p>The review passes.</p>'
                           '<!-- ultraship-receipt:' + receipt_id + ' -->')
        event['tool_input']['content'] = content
        self.assertIsNone(self.hook_output(event))

    def test_expiry_uses_injected_clock(self):
        self.hook_refusal(self.event())
        receipt_id = self.last_receipt['id']
        with patch.object(text_lint, 'now', return_value=self.clock + timedelta(hours=24, microseconds=1)):
            self.assertIn('Receipt expires after 24 hours.', self.hook_refusal(self.resend(receipt_id)))
        self.assertFalse(self.last_receipt['resend_allowed'])

    def test_failed_resend_is_consumed_and_has_parent(self):
        self.hook_refusal(self.event())
        receipt_id = self.last_receipt['id']
        reason = self.hook_refusal(self.resend(receipt_id, 'The review passes.'))
        self.assertIn('Its receipt is used and no further resend of this message is allowed.', reason)
        self.assertEqual(self.last_receipt['parent'], receipt_id)
        self.assertFalse(self.last_receipt['resend_allowed'])
        self.assertTrue((self.state / 'receipts' / (receipt_id + '.consumed')).exists())

    def test_write_failure_denies_without_resend(self):
        with patch.object(text_lint, 'write_receipt', side_effect=OSError('disk full')):
            result = self.hook_output(self.event())
        self.assertEqual(result['permissionDecision'], 'deny')
        self.assertEqual(result['permissionDecisionReason'],
                         'Output contract: Missing section: Facts Missing section: Decision Missing section: Next'
                         ' No receipt was written, so no resend of this message is allowed in any form.')
        self.assertFalse(self.state.exists())

    def test_bad_citations_and_unsafe_files_fail_closed(self):
        for case in ('missing', 'symlink', 'directory', 'oversized', 'json', 'malformed', 'multiple'):
            with self.subTest(case=case):
                self.hook_refusal(self.event())
                receipt_id = self.last_receipt['id']
                path = self.state / 'receipts' / (receipt_id + '.json')
                event = self.resend(receipt_id)
                if case in ('missing', 'symlink', 'directory'):
                    path.unlink()
                    if case == 'symlink':
                        path.symlink_to(self.state / 'key')
                    elif case == 'directory':
                        path.mkdir()
                elif case == 'oversized':
                    path.write_bytes(b'x' * (16 * 1024 + 1))
                elif case == 'json':
                    path.write_text('{')
                elif case == 'malformed':
                    event['tool_input']['message'] = event['tool_input']['message'].replace(receipt_id, 'BAD')
                else:
                    event['tool_input']['message'] += '\n<!-- ultraship-receipt:' + receipt_id + ' -->'
                self.assertIn('Invalid receipt citation:', self.hook_refusal(event))
                self.assertFalse(self.last_receipt['resend_allowed'])
                if case == 'directory':
                    path.rmdir()

    def test_pruning_removes_old_pairs_and_caps_receipts(self):
        self.hook_refusal(self.event())
        directory = self.state / 'receipts'
        for index in range(2002):
            path = directory / (f'{index:032x}' + '.json')
            path.write_text('{}')
            path.with_suffix('.consumed').touch()
            modified = self.clock.timestamp() - (8 * 24 * 3600 if index == 0 else index)
            os.utime(path, (modified, modified))
        self.hook_refusal(self.event())
        self.assertEqual(len(list(directory.glob('*.json'))), 2000)
        self.assertFalse((directory / ('0' * 32 + '.json')).exists())
        self.assertFalse((directory / ('0' * 32 + '.consumed')).exists())
        self.assertFalse((directory / (f'{2001:032x}' + '.json')).exists())
        self.assertFalse((directory / (f'{2001:032x}' + '.consumed')).exists())

    def test_receipt_size_and_finding_bounds(self):
        receipt = text_lint.write_receipt(self.event(), ['x' * 501], False, None)
        self.assertEqual(receipt['findings'], ['x' * 500])
        with self.assertRaisesRegex(OSError, 'Receipt exceeds 16 KiB'):
            text_lint.write_receipt(self.event(), ['x' * 500] * 40, False, None)

    def test_hook_entrypoint_records_parse_errors_and_absent_ids(self):
        for payload in ('{', json.dumps(self.event())):
            with self.subTest(payload=payload):
                output = io.StringIO()
                with patch('sys.argv', ['text_lint.py', 'hook']), \
                        patch('sys.stdin', io.StringIO(payload)), redirect_stdout(output):
                    runpy.run_path(str(ROOT / 'plugins/ship/hooks/text_lint.py'), run_name='__main__')
                result = json.loads(output.getvalue())['hookSpecificOutput']
                self.assertEqual(result['permissionDecision'], 'deny')
                receipt_id = re.search(r'Receipt: `([0-9a-f]{32})`', result['permissionDecisionReason'])[1]
                receipt = json.loads((self.state / 'receipts' / (receipt_id + '.json')).read_text())
                self.assertEqual(receipt['formatting_only'], payload != '{')
                self.assertEqual(receipt['resend_allowed'], payload != '{')
                if payload == '{':
                    for field in ('session_id', 'agent_id', 'tool_use_id'):
                        self.assertIsNone(receipt[field])

    def test_key_symlink_is_refused(self):
        self.state.mkdir(parents=True)
        target = self.state.parent / 'untrusted-key'
        target.write_bytes(b'k' * 32)
        (self.state / 'key').symlink_to(target)
        with self.assertRaises(OSError):
            text_lint.receipt_key()

    def test_expiry_allows_exactly_24_hours(self):
        self.hook_refusal(self.event())
        event = self.resend(self.last_receipt['id'])
        with patch.object(text_lint, 'now', return_value=self.clock + timedelta(hours=24)):
            self.assertIsNone(self.hook_output(event))

    def test_racing_first_writers_share_one_key(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            keys = list(pool.map(lambda _: text_lint.receipt_key(), range(2)))
        self.assertEqual(keys[0], keys[1])
        self.assertEqual(keys[0], (self.state / 'key').read_bytes())

    def test_self_test_and_lint_modes_write_nothing(self):
        for mode, prose in (('--self-test', ''), ('peer', 'Facts: Checks pass.\nDecision: Continue.\nNext: Resume.'),
                            ('decision', 'What is wrong\nWhy now\nOptions\nRecommendation\nIf no answer'),
                            ('result', 'The review passes.')):
            with self.subTest(mode=mode), patch('sys.argv', ['text_lint.py', mode]), \
                    patch('sys.stdin', io.StringIO(prose)):
                runpy.run_path(str(ROOT / 'plugins/ship/hooks/text_lint.py'), run_name='__main__')
            self.assertFalse(self.state.exists())


if __name__ == '__main__':
    unittest.main()
