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
import subprocess
import sys
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

    def entrypoint_output(self, payload):
        clock = self.clock

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock

        output = io.StringIO()
        with patch('datetime.datetime', Clock), patch('sys.argv', ['text_lint.py', 'hook']), \
                patch('sys.stdin', io.StringIO(payload)), redirect_stdout(output):
            runpy.run_path(str(ROOT / 'plugins/ship/hooks/text_lint.py'), run_name='__main__')
        return json.loads(output.getvalue())['hookSpecificOutput']

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
        """Catch a child resend shape that drops the required sections."""
        for recipient in ('main', 'a' + '0' * 16):
            for prose, error in (
                    (' '.join(['word'] * 26) + '.', 'Write at most 25 words per sentence.'),
                    ('Send deadline2026 by8November00.',
                     'Separate glued words with spaces; remove compressed shorthand.')):
                with self.subTest(recipient=recipient, error=error):
                    message = prose + '\nFacts: Checks pass.\nDecision: Continue.\nNext: Resume.'
                    event = {'session_id': recipient + error, 'tool_name': 'SendMessage',
                             'tool_input': {'to': recipient, 'message': message}}
                    self.assertEqual(self.hook_refusal(event),
                                     'Output contract: ' + error + self.RESEND
                                     + text_lint.PEER_TEMPLATE)

    def test_one_refusal_names_format_and_section_findings(self):
        for recipient in ('main', 'a' + '0' * 16, 'peer'):
            with self.subTest(recipient=recipient):
                event = {'session_id': recipient, 'tool_name': 'SendMessage',
                         'tool_input': {'to': recipient, 'message': 'Send deadline2026 by8November00.'}}
                reason = self.hook_refusal(event)
                self.assertEqual(reason,
                                 'Output contract: Separate glued words with spaces; remove compressed shorthand. '
                                 'Missing section: Facts Missing section: Decision Missing section: Next'
                                 + self.RESEND + text_lint.PEER_TEMPLATE)
                self.assertIn('at most 25 words each, with a space between words', reason)
                for heading in ('\nFacts\n', '\nDecision\n', '\nNext\n'):
                    self.assertIn(heading, reason)

    def test_subagent_missing_section_refusal_has_peer_template(self):
        """Catch a child remedy that omits required peer headings."""
        for prose in ('The review passes.', ' '.join(['word'] * 26) + '.'):
            with self.subTest(prose=prose):
                message = prose + '\nDecision: Continue.\nNext: Resume.'
                event = {'session_id': prose, 'tool_name': 'SendMessage',
                         'tool_input': {'to': 'main', 'message': message}}
                prefix = ('Write at most 25 words per sentence. '
                          if prose.startswith('word') else '')
                self.assertEqual(self.hook_refusal(event),
                                 'Output contract: ' + prefix + 'Missing section: Facts'
                                 + self.RESEND + text_lint.PEER_TEMPLATE)

    def test_peer_owner_helper_label_keeps_sentence_limit(self):
        for prefix in ('', '- '):
            with self.subTest(prefix=prefix):
                message = (prefix + 'Owner helper request: ' + ' '.join(['word'] * 40)
                           + '\nFacts: Checks pass.\nDecision: Continue.\nNext: Resume.')
                with self.assertRaises(text_lint.FormatError) as refusal:
                    text_lint.check(message, 'peer')
                self.assertEqual(refusal.exception.findings, ['Write at most 25 words per sentence.'])

    def test_peer_owner_helper_request_on_its_own_line_passes(self):
        message = ('Owner helper request:\n'
                   'I explicitly request that chiefs, drivers and lanes start helper agents '
                   '(writers, reviewers, verifiers, researchers, planners, council seats) '
                   'whenever their assigned topic needs one.\n'
                   'The source is the global CLAUDE.md under Helper agents (standing request).\n'
                   'The covered roles are the driver, writer and reviewers.\n'
                   'The assigned topic is text lint.\n'
                   'Retain host limits and every permission, denial and gate.\n'
                   'Facts: Checks pass.\nDecision: Continue.\nNext: Resume.')
        text_lint.check(message, 'peer')

    def test_peer_sections_survive_tag_like_text(self):
        for line in ("cat <<'PY'; x<y", 'cat <<EOF'):
            with self.subTest(line=line):
                message = ('Facts: Checks pass.\n' + line
                           + '\nDecision: Continue.\nNext: Resume.')
                text_lint.check(message, 'peer')

    def test_peer_tag_like_text_keeps_missing_decision(self):
        for line in ("cat <<'PY'; x<y", 'cat <<EOF'):
            with self.subTest(line=line):
                message = 'Facts: Checks pass.\n' + line + '\nNext: Resume.'
                with self.assertRaises(text_lint.FormatError) as refusal:
                    text_lint.check(message, 'peer')
                self.assertEqual(refusal.exception.findings, ['Missing section: Decision'])

    def test_peer_heredoc_keeps_later_sentence_limit(self):
        message = ('Facts: Checks pass.\ncat <<EOF\n'
                   'Owner helper request: one two three four five six seven eight nine ten '
                   'eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen '
                   'nineteen twenty twentyone twentytwo twentythree twentyfour twentyfive twentysix.\n'
                   'Decision: Continue.\nNext: Resume.')
        with self.assertRaises(text_lint.FormatError) as refusal:
            text_lint.check(message, 'peer')
        self.assertEqual(refusal.exception.findings, ['Write at most 25 words per sentence.'])

    def test_peer_bold_glued_words_keep_token_check(self):
        message = ('Facts: <b>deadline2026</b> <b>by8November00</b>\n'
                   'Decision: Continue.\nNext: Resume.')
        with self.assertRaises(text_lint.FormatError) as refusal:
            text_lint.check(message, 'peer')
        self.assertEqual(refusal.exception.findings,
                         ['Separate glued words with spaces; remove compressed shorthand.'])

    def test_peer_entity_glued_words_keep_token_check(self):
        message = ('Facts: deadline2026 by8November0&#48;\n'
                   'Decision: Continue.\nNext: Resume.')
        with self.assertRaises(text_lint.FormatError) as refusal:
            text_lint.check(message, 'peer')
        self.assertEqual(refusal.exception.findings,
                         ['Separate glued words with spaces; remove compressed shorthand.'])
        text_lint.check(message.replace('&#48;', '&amp;#48;'), 'peer')

    def test_peer_hold_wall_reads_text_after_tag_like_text(self):
        message = ('Facts: Checks wait.\ncat <<EOF\n'
                   'Preserve every hold. Custody stays. Admission waits. Preserve the refusal.\n'
                   'Decision: Wait.\nNext: Resume.')
        with self.assertRaises(ValueError) as refusal:
            text_lint.hold_wall(message)
        self.assertEqual(str(refusal.exception),
                         'Keep any new hold in one line, drop restated standing holds, '
                         'and send what changed and the next action.')

    def test_peer_paths_stay_whole_tokens(self):
        message = ('Facts: Read /home/user/.scratch/deadline2026/by8November00.md\n'
                   'Decision: Continue.\nNext: Resume.')
        text_lint.check(message, 'peer')

    def test_decision_sections_use_visible_text_only(self):
        message = ('<h2>What is wrong</h2><h2>Why now</h2><h2>Options</h2>'
                   '<h2>If no answer</h2><script>\nRecommendation\n</script>')
        with self.assertRaises(text_lint.FormatError) as refusal:
            text_lint.check(message, 'decision')
        self.assertEqual(refusal.exception.findings, ['Missing section: Recommendation'])

    def test_peer_refusal_has_resend_template(self):
        """Catch a peer formatting refusal that fails to permit one resend."""
        event = self.event()
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
                    event = {'session_id': tool + error, 'tool_name': 'mcp__bettercoding__' + tool,
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
                receipt = text_lint.write_receipt(self.event(), ['Missing section: Facts'], True, None)
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

    def test_receipt_binds_the_sending_agent(self):
        self.hook_refusal(self.event())
        receipt_id = self.last_receipt['id']
        self.assertTrue(self.last_receipt['formatting_only'])
        self.assertTrue(self.last_receipt['resend_allowed'])
        sibling = self.resend(receipt_id)
        sibling['agent_id'] = 'agent-two'
        self.assertIn('Receipt sender differs.', self.hook_refusal(sibling))
        self.assertFalse(self.last_receipt['resend_allowed'])
        self.assertFalse((self.state / 'receipts' / (receipt_id + '.consumed')).exists())
        valid = 'Facts: Checks pass.\nDecision: Continue.\nNext: Resume.'
        sibling = self.event(valid)
        sibling['agent_id'] = 'agent-two'
        self.assertIsNone(self.hook_output(sibling))
        self.assertIsNone(self.hook_output(self.resend(receipt_id)))
        self.assertEqual(list((self.state / 'pending').glob('*')), [])
        self.assertTrue((self.state / 'receipts' / (receipt_id + '.consumed')).exists())
        self.assertIn('Receipt is consumed.', self.hook_refusal(self.resend(receipt_id)))

    def test_session_recipient_tool_and_fields_are_bound(self):
        for field in ('session_id', 'recipient', 'tool_name', 'fields', 'null_session'):
            with self.subTest(field=field):
                receipt = text_lint.write_receipt(self.event(), ['Missing section: Facts'], True, None)
                event = self.resend(receipt['id'])
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
        pending = next((self.state / 'pending').iterdir())
        spent = {'id': self.last_receipt['id'], 'state': 'spent'}
        self.assertEqual(json.loads(pending.read_text()), spent)
        self.hook_refusal(self.event())
        self.assertTrue(self.last_receipt['formatting_only'])
        self.assertFalse(self.last_receipt['resend_allowed'])
        self.assertEqual(json.loads(pending.read_text()), spent)
        valid = 'Facts: Checks pass.\nDecision: Continue.\nNext: Resume.'
        self.assertIsNone(self.hook_output(self.event(valid)))
        self.assertEqual(json.loads(pending.read_text()), spent)

    def test_failed_resend_keeps_spent_state_when_receipt_write_fails(self):
        self.hook_refusal(self.event())
        receipt_id = self.last_receipt['id']
        pending = next((self.state / 'pending').iterdir())
        with patch.object(text_lint, 'write_receipt', side_effect=OSError('disk full')):
            result = self.hook_output(self.resend(receipt_id, 'The review passes.'))
        self.assertEqual(result['permissionDecision'], 'deny')
        self.assertIn('No receipt was written, so no resend', result['permissionDecisionReason'])
        self.assertTrue((self.state / 'receipts' / (receipt_id + '.consumed')).exists())
        self.hook_refusal(self.event())
        self.assertTrue(self.last_receipt['formatting_only'])
        self.assertFalse(self.last_receipt['resend_allowed'])
        self.assertTrue(pending.exists())
        valid = 'Facts: Checks pass.\nDecision: Continue.\nNext: Resume.'
        self.assertIsNone(self.hook_output(self.event(valid)))
        self.assertTrue(pending.exists())
        with patch.object(text_lint, 'now', return_value=self.clock + timedelta(hours=24)):
            self.hook_refusal(self.event())
        self.assertTrue(self.last_receipt['resend_allowed'])

    def test_spent_entry_expires_after_24_hours(self):
        self.hook_refusal(self.event())
        receipt_id = self.last_receipt['id']
        self.hook_refusal(self.resend(receipt_id, 'The review passes.'))
        with patch.object(text_lint, 'now', return_value=self.clock + timedelta(hours=24)):
            self.hook_refusal(self.event())
        self.assertTrue(self.last_receipt['resend_allowed'])

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
                receipt = text_lint.write_receipt(self.event(), ['Missing section: Facts'], True, None)
                receipt_id = receipt['id']
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

    def test_pruning_removes_old_pairs_and_keeps_young_pairs(self):
        directory = self.state / 'receipts'
        directory.mkdir(parents=True)
        pending = self.state / 'pending'
        pending.mkdir()
        stale = pending / 'stale'
        stale.write_text('missing')
        old = self.clock.timestamp() - 8 * 24 * 3600
        os.utime(stale, (old, old))
        for index in range(2002):
            path = directory / (f'{index:032x}' + '.json')
            path.write_text('{}')
            marker = path.with_suffix('.consumed')
            marker.touch()
            modified = old if index == 0 else self.clock.timestamp() - (25 * 3600 if index == 1 else index)
            os.utime(path, (modified, modified))
            os.utime(marker, (modified, modified))
        text_lint.prune_receipts(directory)
        self.assertEqual(len(list(directory.glob('*.json'))), 2000)
        for index in (0, 1):
            self.assertFalse((directory / (f'{index:032x}' + '.json')).exists())
            self.assertFalse((directory / (f'{index:032x}' + '.consumed')).exists())
        for index in range(2, 2002):
            self.assertTrue((directory / (f'{index:032x}' + '.json')).exists())
            self.assertTrue((directory / (f'{index:032x}' + '.consumed')).exists())
        self.assertFalse(stale.exists())
        result = self.hook_output(self.event())
        self.assertIn('No receipt was written, so no resend', result['permissionDecisionReason'])
        self.assertEqual(len(list(directory.glob('*.json'))), 2000)
        self.assertEqual(len(list(directory.glob('*.consumed'))), 2000)

    def test_receipt_size_and_finding_bounds(self):
        receipt = text_lint.write_receipt(self.event(), ['x' * 501], False, None)
        self.assertEqual(receipt['findings'], ['x' * 500])
        with self.assertRaisesRegex(OSError, 'Receipt exceeds 16 KiB'):
            text_lint.write_receipt(self.event(), ['x' * 500] * 40, False, None)

    def test_hook_entrypoint_records_parse_errors_and_absent_ids(self):
        for payload in ('{', json.dumps(self.event())):
            with self.subTest(payload=payload):
                result = self.entrypoint_output(payload)
                self.assertEqual(result['permissionDecision'], 'deny')
                receipt_id = re.search(r'Receipt: `([0-9a-f]{32})`', result['permissionDecisionReason'])[1]
                receipt = json.loads((self.state / 'receipts' / (receipt_id + '.json')).read_text())
                self.assertEqual(receipt['formatting_only'], payload != '{')
                self.assertEqual(receipt['resend_allowed'], payload != '{')
                if payload == '{':
                    for field in ('session_id', 'agent_id', 'tool_use_id'):
                        self.assertIsNone(receipt[field])

    def test_lone_surrogate_entrypoint_denies_without_exception(self):
        event = self.event('\ud800')
        result = self.entrypoint_output(json.dumps(event))
        self.assertEqual(result['permissionDecision'], 'deny')
        self.assertRegex(result['permissionDecisionReason'], r'Receipt: `[0-9a-f]{32}`|No receipt was written')

    def test_missing_session_cannot_resend_or_create_pending(self):
        for session in (None, '', 123):
            event = self.event()
            event['session_id'] = session
            self.hook_refusal(event)
            self.assertFalse(self.last_receipt['resend_allowed'])
            self.assertEqual(list((self.state / 'pending').glob('*')), [])

    def test_future_receipt_refused_at_one_microsecond(self):
        with patch.object(text_lint, 'now', return_value=self.clock + timedelta(microseconds=1)):
            receipt = text_lint.write_receipt(self.event(), ['Missing section: Facts'], True, None)
        self.assertIn('Receipt creation is in the future.', self.hook_refusal(self.resend(receipt['id'])))
        self.assertFalse(self.last_receipt['resend_allowed'])
        self.assertFalse((self.state / 'receipts' / (receipt['id'] + '.consumed')).exists())

    def test_future_pending_entry_is_inactive_at_one_microsecond(self):
        with patch.object(text_lint, 'now', return_value=self.clock + timedelta(microseconds=1)):
            self.hook_refusal(self.event())
        pending = next((self.state / 'pending').iterdir())
        valid = 'Facts: Checks pass.\nDecision: Continue.\nNext: Resume.'
        self.assertIsNone(self.hook_output(self.event(valid)))
        self.assertFalse(pending.exists())

    def test_pending_refusal_requires_citation_for_same_recipient(self):
        self.hook_refusal(self.event())
        receipt_id = self.last_receipt['id']
        pending = next((self.state / 'pending').iterdir())
        expected_key = hashlib.sha256(json.dumps(['session-one', 'agent-one', 'SendMessage', 'chief'],
                                               separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
        self.assertEqual(pending.name, expected_key)
        self.assertEqual(json.loads(pending.read_text()), {'id': receipt_id, 'state': 'open'})
        valid = self.resend(receipt_id)['tool_input']['message'].split('\n<!--')[0]
        for message in (valid, 'The review passes.'):
            reason = self.hook_refusal(self.event(message))
            self.assertIn('A formatting-only refusal to this recipient is pending.', reason)
            self.assertIn('Cite its receipt `' + receipt_id + '`', reason)
            self.assertFalse(self.last_receipt['resend_allowed'])
            self.assertFalse(self.last_receipt['formatting_only'])
            self.assertEqual(json.loads(pending.read_text()), {'id': receipt_id, 'state': 'open'})
        self.assertIsNone(self.hook_output(self.event(valid, to='another-chief')))
        self.assertIsNone(self.hook_output(self.resend(receipt_id)))
        self.assertFalse(pending.exists())

    def test_pending_input_and_stale_entries(self):
        event = {'session_id': 'session-one', 'tool_name': 'create_input',
                 'tool_input': {'workspace_id': 'one', 'content': {'html': '<p>Wait.</p>'}}}
        self.hook_refusal(event)
        receipt_id = self.last_receipt['id']
        pending = next((self.state / 'pending').iterdir())
        event['tool_input']['content']['html'] = '<meta name="output-kind" content="result"><p>Wait.</p>'
        self.assertIn('is pending', self.hook_refusal(event))
        event['tool_input']['content']['html'] += '<!-- ultraship-receipt:' + receipt_id + ' -->'
        self.assertIsNone(self.hook_output(event))
        self.assertFalse(pending.exists())
        for stale in ('missing', 'expired', 'consumed'):
            with self.subTest(stale=stale):
                self.hook_refusal(self.event())
                receipt_id = self.last_receipt['id']
                path = self.state / 'receipts' / (receipt_id + '.json')
                pending = next((self.state / 'pending').iterdir())
                if stale == 'missing':
                    path.unlink()
                elif stale == 'consumed':
                    path.with_suffix('.consumed').touch()
                clock = self.clock + timedelta(hours=25) if stale == 'expired' else self.clock
                with patch.object(text_lint, 'now', return_value=clock):
                    valid = self.resend(receipt_id)['tool_input']['message'].split('\n<!--')[0]
                    self.assertIsNone(self.hook_output(self.event(valid)))
                self.assertEqual(pending.exists(), stale == 'consumed')

    def test_agent_citation_never_consumes_a_send_receipt(self):
        self.hook_refusal(self.event())
        receipt_id = self.last_receipt['id']
        self.assertTrue(self.last_receipt['formatting_only'])
        self.assertTrue(self.last_receipt['resend_allowed'])
        pending = next((self.state / 'pending').iterdir())
        for tool in ('Agent', 'Task'):
            with self.subTest(tool=tool):
                event = {'session_id': 'session-one', 'agent_id': 'agent-one', 'tool_name': tool,
                         'tool_input': {'subagent_type': 'ship:writer--sol', 'prompt': 'word ' * 26}}
                before = list((self.state / 'receipts').glob('*.json'))
                self.assertIsNone(self.hook_output(event))
                self.assertEqual(list((self.state / 'receipts').glob('*.json')), before)
                event['tool_input']['prompt'] += '<!-- ultraship-receipt:' + receipt_id + ' -->'
                event['session_id'] = 'another-session'
                self.assertIn('Receipt session differs', self.hook_refusal(event))
                self.assertFalse(self.last_receipt['resend_allowed'])
                event['session_id'] = 'session-one'
                self.assertIn('Receipt tool, recipient or non-prose fields differ.', self.hook_refusal(event))
                self.assertFalse(self.last_receipt['resend_allowed'])
                self.assertFalse((self.state / 'receipts' / (receipt_id + '.consumed')).exists())
                self.assertEqual(json.loads(pending.read_text()), {'id': receipt_id, 'state': 'open'})
        valid = self.resend(receipt_id)['tool_input']['message'].split('\n<!--')[0]
        self.assertIn('A formatting-only refusal to this recipient is pending.',
                      self.hook_refusal(self.event(valid)))
        self.assertIsNone(self.hook_output(self.resend(receipt_id)))
        self.assertEqual(list((self.state / 'pending').glob('*')), [])
        self.assertTrue((self.state / 'receipts' / (receipt_id + '.consumed')).exists())
        self.assertIn('Receipt is consumed', self.hook_refusal(self.resend(receipt_id)))
        self.assertFalse(self.last_receipt['resend_allowed'])

    def test_unexpected_hook_and_receipt_exceptions_deny_once(self):
        for stage in ('outgoing', 'write_receipt'):
            with self.subTest(stage=stage), patch.object(text_lint, stage, side_effect=RuntimeError('unexpected')):
                result = self.hook_output(self.event())
                self.assertEqual(result['permissionDecision'], 'deny')
                expected = self.NO_RESEND if stage == 'outgoing' else 'No receipt was written, so no resend'
                self.assertIn(expected, result['permissionDecisionReason'])

    def test_receipt_unlocks_only_format_refusals(self):
        result = self.entrypoint_output(json.dumps(self.event()))
        receipt_id = re.search(r'Receipt: `([0-9a-f]{32})`', result['permissionDecisionReason'])[1]
        receipt = json.loads((self.state / 'receipts' / (receipt_id + '.json')).read_bytes())
        self.assertTrue(receipt['resend_allowed'])
        marker = '<!-- ultraship-receipt:' + receipt_id + ' -->'
        credential_dir = self.state.parent / 'gh'
        env = {**os.environ, 'GH_CONFIG_DIR': str(credential_dir)}
        cases = (
            ('Agent', {'subagent_type': 'ship:writer--sol', 'model': 'opus', 'prompt': marker}, 'pin their own model'),
            ('Bash', {'command': 'git push origin HEAD # ' + marker}, 'Writers never push'),
            ('Write', {'file_path': str(credential_dir / 'hosts.yml'), 'content': marker},
             'Writers do not edit GitHub CLI configuration.'),
            ('Write', {'file_path': str(self.state.parent / '.claude/settings.json'), 'content': marker},
             'Writers do not edit harness configuration.'),
            ('Bash', {'command': 'gh repo delete owner/repo --yes # ' + marker}, 'Writers never push'),
            ('Bash', {'command': 'cat ' + str(self.state / 'key') + ' # ' + marker}, 'custody rule'),
        )
        for tool, inputs, reason in cases:
            with self.subTest(tool=tool, reason=reason):
                event = {'session_id': 'session-one', 'agent_type': 'ship:writer--sol',
                         'cwd': str(ROOT), 'tool_name': tool, 'tool_input': inputs}
                process = subprocess.run([sys.executable, str(ROOT / 'plugins/ship/hooks/ultraship.py'), 'pre'],
                                         input=json.dumps(event), text=True, capture_output=True, env=env, cwd=ROOT, check=True)
                denial = json.loads(process.stdout)['hookSpecificOutput']
                self.assertEqual(denial['permissionDecision'], 'deny')
                self.assertIn(reason, denial['permissionDecisionReason'])
        wall = ('Facts: Preserve every hold. Custody stays. Admission waits. Preserve the refusal.\n'
                'Decision: Wait.\nNext: Wait.')
        self.assertIn(self.NO_RESEND, self.hook_refusal(self.resend(receipt_id, wall)))
        self.assertFalse(self.last_receipt['formatting_only'])
        non_format_id = self.last_receipt['id']
        self.assertIn('Receipt does not permit a resend', self.hook_refusal(self.resend(non_format_id)))
        self.assertFalse(self.last_receipt['resend_allowed'])

    def test_failed_first_key_write_allows_next_refusal_receipt(self):
        with patch.object(text_lint.os, 'urandom', side_effect=OSError('random source unavailable')):
            result = self.hook_output(self.event())
        self.assertEqual(result['permissionDecision'], 'deny')
        self.assertIn('No receipt was written, so no resend', result['permissionDecisionReason'])
        self.assertFalse((self.state / 'key').exists())
        self.hook_refusal(self.event())
        self.assertTrue(self.last_receipt['formatting_only'])
        self.assertTrue(self.last_receipt['resend_allowed'])
        self.assertEqual(len((self.state / 'key').read_bytes()), 32)
        self.assertIsNone(self.hook_output(self.resend(self.last_receipt['id'])))

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
