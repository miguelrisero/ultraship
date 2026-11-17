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
        event = {'tool_name': 'SendMessage', 'tool_input': {'to': 'peer', 'message': message}}
        with self.assertRaises(text_lint.FormatError) as refusal:
            text_lint.outgoing(event)
        self.assertEqual(refusal.exception.findings,
                         ['Separate glued words with spaces; remove compressed shorthand.'])
        event['tool_input']['message'] = message.replace('&#48;', '&amp;#48;')
        text_lint.outgoing(event)

    def test_peer_hold_wall_decodes_entities_once(self):
        message = ('Facts: Preser&#118;e every ho&#108;d. Cus&#116;ody stays. '
                   'Admi&#115;sion waits. Preser&#118;e the refu&#115;al.\n'
                   'Decision: Wait.\nNext: Resume.')
        event = {'tool_name': 'SendMessage', 'tool_input': {'to': 'chief', 'message': message}}
        with self.assertRaises(text_lint.FindingsError) as refusal:
            text_lint.outgoing(event)
        self.assertEqual(refusal.exception.findings,
                         ['Keep any new hold in one line, drop restated standing holds, '
                          'and send what changed and the next action.'])
        event['tool_input']['message'] = message.replace('&#', '&amp;#')
        text_lint.outgoing(event)

    def test_peer_hold_wall_reads_the_helper_label_raw(self):
        message = ('Facts: Owner helper requ&#101;st: retained. Preserve every hold. '
                   'Custody stays. Admission waits. Preserve the refusal.\n'
                   'Decision: Wait.\nNext: Resume.')
        event = {'tool_name': 'SendMessage', 'tool_input': {'to': 'chief', 'message': message}}
        with self.assertRaises(text_lint.FindingsError) as refusal:
            text_lint.outgoing(event)
        self.assertEqual(refusal.exception.findings,
                         ['Keep any new hold in one line, drop restated standing holds, '
                          'and send what changed and the next action.'])
        event['tool_input']['message'] = message.replace('requ&#101;st', 'request')
        text_lint.outgoing(event)

    def test_peer_hold_wall_counts_words_inside_tags(self):
        message = ('Facts: <b>Preserve</b> every <b>hold</b>. <b>Custody</b> stays. '
                   '<b>Admission</b> waits. <b>Preserve</b> the <b>refusal</b>.\n'
                   'Decision: Wait.\nNext: Resume.')
        event = {'tool_name': 'SendMessage', 'tool_input': {'to': 'chief', 'message': message}}
        with self.assertRaises(text_lint.FindingsError) as refusal:
            text_lint.outgoing(event)
        self.assertEqual(refusal.exception.findings,
                         ['Keep any new hold in one line, drop restated standing holds, '
                          'and send what changed and the next action.'])

    def test_peer_hold_wall_refuses_every_form_main_refuses(self):
        """Main's hold wall refuses every form; the driver's census checks each form against main."""
        labels = ('', 'Owner helper requ&#101;st: retained.\n',
                  'Owner helper request&#58; retained.\n', 'Owner <b>helper</b> request: retained.\n')
        wraps = (
            ('bold', lambda w: f'<b>{w}</b>'),
            ('span', lambda w: f'<span class="x">{w}</span>'),
            ('link', lambda w: f'<a href="/x">{w}</a>'),
            ('closed-break', lambda w: f'{w}<br/>'),
            ('break', lambda w: f'{w}<br>'),
            ('comment', lambda w: f'{w}<!-- c -->'),
            ('in-word-empty-tag', lambda w: w[:2] + '<b></b>' + w[2:]),
            ('in-word-tag', lambda w: w[:2] + '<b>' + w[2:] + '</b>'),
            ('in-word-comment', lambda w: w[:2] + '<!-- c -->' + w[2:]),
            ('decimal', lambda w: w[:2] + f'&#{ord(w[2])};' + w[3:]),
            ('hex', lambda w: w[:2] + f'&#x{ord(w[2]):x};' + w[3:]),
            ('bold-decimal', lambda w: '<b>' + w[:2] + f'&#{ord(w[2])};' + w[3:] + '</b>'),
            ('path', lambda w: f'{w} /tmp/x'),
            ('bold-path', lambda w: f'<b>{w}</b> /tmp/{w}'),
        )
        for label in labels:
            for name, wrap in wraps:
                with self.subTest(label=label, wrap=name):
                    body = ' '.join(wrap(word) + '.' for word in
                                    ('Preserve', 'hold', 'Custody', 'Admission', 'Preserve', 'refusal'))
                    message = 'Facts: ' + label + body + '\nDecision: Wait.\nNext: Resume.'
                    event = {'tool_name': 'SendMessage',
                             'tool_input': {'to': 'chief', 'message': message}}
                    with self.assertRaises(text_lint.FindingsError) as refusal:
                        text_lint.outgoing(event)
                    self.assertEqual(refusal.exception.findings,
                                     ['Keep any new hold in one line, drop restated standing holds, '
                                      'and send what changed and the next action.'])

    def test_peer_token_checks_keep_main_html_view(self):
        for message in (
                'Facts: deadline<b></b>2026 release<b></b>2027\nDecision: Continue.\nNext: Resume.',
                'Facts: abcdefghijklmnopqrstuv <b>one</b> <b>two</b> <b>three</b> <b>four</b>\n'
                'Decision: Continue.\nNext: Resume.'):
            with self.subTest(message=message):
                event = {'tool_name': 'SendMessage', 'tool_input': {'to': 'peer', 'message': message}}
                with self.assertRaises(text_lint.FormatError) as refusal:
                    text_lint.outgoing(event)
                self.assertEqual(refusal.exception.findings,
                                 ['Separate glued words with spaces; remove compressed shorthand.'])

    def test_peer_sentence_check_keeps_main_html_view(self):
        message = ('Facts: one two three four five six seven eight nine ten eleven twelve <!--\n--> '
                   'thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty twentyone '
                   'twentytwo twentythree twentyfour twentyfive twentysix.\n'
                   'Decision: Continue.\nNext: Resume.')
        event = {'tool_name': 'SendMessage', 'tool_input': {'to': 'peer', 'message': message}}
        with self.assertRaises(text_lint.FormatError) as refusal:
            text_lint.outgoing(event)
        self.assertEqual(refusal.exception.findings, ['Write at most 25 words per sentence.'])

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

    def test_invalid_citation_spends_every_matching_receipt(self):
        """Catch an invalid citation that leaves a matching receipt available for a corrected resend."""
        self.hook_refusal(self.event())
        first_id = self.last_receipt['id']
        second = text_lint.write_receipt(self.event(), ['Missing section: Facts'], True, None)
        invalid = self.resend(first_id)
        invalid['tool_input']['message'] += '\n<!-- ultraship-receipt:' + second['id'] + ' -->'

        reason = self.hook_refusal(invalid)

        self.assertIn('Invalid receipt citation: require exactly one well-formed marker.', reason)
        self.assertIn('Well-formed markers: 2. Marker names: 2.', reason)
        self.assertFalse(self.last_receipt['resend_allowed'])
        for receipt_id in (first_id, second['id']):
            with self.subTest(receipt_id=receipt_id):
                self.assertIn('A final citation refusal spent this receipt.',
                              self.hook_refusal(self.resend(receipt_id)))
                self.assertFalse(self.last_receipt['resend_allowed'])

    def test_invalid_citation_preserves_another_recipients_receipt(self):
        """Catch an invalid citation that spends another recipient's resend permission."""
        self.hook_refusal(self.event())
        receipt_id = self.last_receipt['id']
        self.hook_refusal(self.event(to='another-chief'))
        other_id = self.last_receipt['id']
        invalid = self.resend(receipt_id)
        invalid['tool_input']['message'] += '\n<!-- ultraship-receipt:' + receipt_id + ' -->'

        self.assertIn('Invalid receipt citation:', self.hook_refusal(invalid))
        other = self.resend(other_id)
        other['tool_input']['to'] = 'another-chief'
        self.assertIsNone(self.hook_output(other))
        self.assertTrue((self.state / 'receipts' / (other_id + '.consumed')).exists())

    def test_receipt_after_final_citation_refusal_remains_citable(self):
        """Catch a final citation refusal that blocks a later receipt for the same identity."""
        self.hook_refusal(self.event())
        receipt_id = self.last_receipt['id']
        invalid = self.resend(receipt_id)
        invalid['tool_input']['message'] += '\n<!-- ultraship-receipt:' + receipt_id + ' -->'
        self.assertIn('Invalid receipt citation:', self.hook_refusal(invalid))
        with patch.object(text_lint, 'now', return_value=self.clock + timedelta(seconds=1)):
            later = text_lint.write_receipt(self.event(), ['Missing section: Facts'], True, None)
            self.assertIsNone(self.hook_output(self.resend(later['id'])))
        self.assertTrue((self.state / 'receipts' / (later['id'] + '.consumed')).exists())

    def test_unsafe_citation_refusal_markers_fail_closed(self):
        """Catch unsafe final-refusal marker paths that allow a cited resend."""
        for kind in ('symlink', 'directory'):
            with self.subTest(kind=kind):
                event = self.event(to=kind + '-chief')
                self.hook_refusal(event)
                receipt_id = self.last_receipt['id']
                invalid = self.resend(receipt_id)
                invalid['tool_input']['to'] = kind + '-chief'
                invalid['tool_input']['message'] += '\n<!-- ultraship-receipt:' + receipt_id + ' -->'
                self.assertIn('Invalid receipt citation:', self.hook_refusal(invalid))
                path = text_lint.citation_refusal_path(self.last_receipt)
                path.unlink()
                if kind == 'symlink':
                    target = self.state / 'old-refusal-time'
                    target.write_text('2000-01-01T00:00:00Z')
                    path.symlink_to(target)
                else:
                    path.mkdir()
                resend = self.resend(receipt_id)
                resend['tool_input']['to'] = kind + '-chief'
                self.assertIn('Invalid receipt citation:', self.hook_refusal(resend))
                self.assertFalse(self.last_receipt['resend_allowed'])
                self.assertFalse((self.state / 'receipts' / (receipt_id + '.consumed')).exists())

    def test_unknown_citation_spends_the_real_receipts_resend(self):
        """Catch a final unknown-ID citation denial that leaves the real receipt usable."""
        self.hook_refusal(self.event())
        receipt_id = self.last_receipt['id']
        self.assertIn('Invalid receipt citation:', self.hook_refusal(self.resend('0' * 32)))
        self.assertIn('A final citation refusal spent this receipt.',
                      self.hook_refusal(self.resend(receipt_id)))
        self.assertFalse(self.last_receipt['resend_allowed'])

    def test_naive_citation_refusal_time_fails_closed(self):
        """Catch a naive marker time that lacks the required explicit UTC-time refusal."""
        self.hook_refusal(self.event())
        receipt_id = self.last_receipt['id']
        path = text_lint.citation_refusal_path(self.last_receipt)
        path.parent.mkdir(mode=0o700)
        path.write_text('2026-11-15T12:00:00')
        self.assertIn('Citation refusal marker requires a UTC time.',
                      self.hook_refusal(self.resend(receipt_id)))
        self.assertFalse(self.last_receipt['resend_allowed'])
        self.assertFalse((self.state / 'receipts' / (receipt_id + '.consumed')).exists())

    def test_citation_refusal_preserves_other_identity_receipts(self):
        """Catch refusal markers that also spend another session, agent, tool, or non-prose identity."""
        for field in ('session_id', 'agent_id', 'tool_name', 'scope'):
            with self.subTest(field=field):
                first = self.input_event(field) if field == 'tool_name' else self.event(to=field + '-chief')
                receipt = text_lint.write_receipt(first, ['Missing section: Facts'], True, None)
                other = self.input_event(field) if field == 'tool_name' else self.event(to=field + '-chief')
                if field == 'scope':
                    other['tool_input']['scope'] = 'another-scope'
                elif field == 'tool_name':
                    other['tool_name'] = 'mcp__bettercoding__update_input'
                else:
                    other[field] = 'another-identity'
                other_receipt = text_lint.write_receipt(other, ['Missing section: Facts'], True, None)
                marker = '<!-- ultraship-receipt:' + receipt['id'] + ' -->'
                if field == 'tool_name':
                    first['tool_input']['content']['html'] += marker + marker
                else:
                    first['tool_input']['message'] += marker + marker
                self.assertIn('Invalid receipt citation:', self.hook_refusal(first))
                if field == 'tool_name':
                    other['tool_input']['content']['html'] = (
                        '<meta name="output-kind" content="result"><p>The review passes.</p>'
                        '<!-- ultraship-receipt:' + other_receipt['id'] + ' -->')
                else:
                    other['tool_input']['message'] = self.resend(other_receipt['id'])['tool_input']['message']
                self.assertIsNone(self.hook_output(other))
                self.assertTrue((self.state / 'receipts' / (other_receipt['id'] + '.consumed')).exists())

    def test_resend_templates_end_with_single_marker_guidance(self):
        """Catch resend instructions that omit the final warning about duplicate receipt markers."""
        instruction = ('Put the receipt marker exactly once; '
                       'a second marker or marker name makes the refusal final.')
        self.assertTrue(self.hook_refusal(self.event()).endswith('<' + instruction + '>'))
        event = {'session_id': 'session-one', 'tool_name': 'mcp__bettercoding__create_input',
                 'tool_input': {'content': {'html': '<p>The review passes.</p>'}}}
        self.assertTrue(self.hook_refusal(event).endswith('\n' + instruction))

    def test_sendmessage_backfilled_preview_cites_canonical_body_once(self):
        """Catch a generated preview that duplicates a valid receipt marker in the canonical body."""
        fields = {'type': 'message', 'recipient': 'chief', 'recipient_kind': 'agent'}
        self.hook_refusal(self.event(content='The review passes.', **fields))
        receipt_id = self.last_receipt['id']
        message = ('<!-- ultraship-receipt:' + receipt_id + ' -->\n'
                   'The review passes.\nFacts: Checks pass.\nDecision: Continue.\nNext: Resume.')
        resend = self.event(message, content=message[:49] + '…', **fields)

        self.assertIsNone(self.hook_output(resend))
        self.assertTrue((self.state / 'receipts' / (receipt_id + '.consumed')).exists())
        self.assertIn('Receipt is consumed.', self.hook_refusal(resend))

    def test_sendmessage_content_fallback_still_cites_receipt(self):
        """Catch receipt parsing that drops content when SendMessage has no message field."""
        first = self.event(content='The review passes.')
        first['tool_input'].pop('message')
        self.hook_refusal(first)
        receipt_id = self.last_receipt['id']
        resend = self.resend(receipt_id)
        resend['tool_input']['content'] = resend['tool_input'].pop('message')

        self.assertIsNone(self.hook_output(resend))
        self.assertTrue((self.state / 'receipts' / (receipt_id + '.consumed')).exists())

    def test_sendmessage_duplicate_body_and_summary_markers_stay_invalid(self):
        """Catch canonical body parsing that admits duplicate markers in message or summary."""
        for field in ('message', 'summary'):
            with self.subTest(field=field):
                first = self.event(to=field + '-chief')
                self.hook_refusal(first)
                receipt_id = self.last_receipt['id']
                resend = self.resend(receipt_id)
                resend['tool_input']['to'] = field + '-chief'
                marker = '<!-- ultraship-receipt:' + receipt_id + ' -->'
                resend['tool_input'][field] = resend['tool_input'].get(field, '') + '\n' + marker

                reason = self.hook_refusal(resend)

                self.assertIn('Invalid receipt citation: require exactly one well-formed marker.', reason)
                self.assertIn('Well-formed markers: 2. Marker names: 2.', reason)
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

    def assert_entrypoint_allows(self, event):
        with self.assertRaises(json.JSONDecodeError) as empty_output:
            self.entrypoint_output(json.dumps(event))
        self.assertEqual(empty_output.exception.doc, '')

    def test_relay_preserves_the_owners_single_resend(self):
        result = self.entrypoint_output(json.dumps(self.event()))
        receipt_id = re.search(r'Receipt: `([0-9a-f]{32})`', result['permissionDecisionReason'])[1]
        path = self.state / 'receipts' / (receipt_id + '.json')
        pending = {p.name: p.read_bytes() for p in (self.state / 'pending').iterdir()}
        receipt_bytes = path.read_bytes()
        relay = self.resend(receipt_id)
        relay['agent_id'] = None
        relay['tool_input']['to'] = 'agent-one'

        self.assert_entrypoint_allows(relay)

        self.assertEqual(path.read_bytes(), receipt_bytes)
        self.assertFalse(path.with_suffix('.consumed').exists())
        self.assertEqual({p.name: p.read_bytes() for p in (self.state / 'pending').iterdir()}, pending)
        self.assert_entrypoint_allows(self.resend(receipt_id))
        self.assertTrue(path.with_suffix('.consumed').exists())
        result = self.entrypoint_output(json.dumps(self.resend(receipt_id)))
        self.assertIn('Receipt is consumed.', result['permissionDecisionReason'])

    def test_relay_refuses_a_different_recipient(self):
        result = self.entrypoint_output(json.dumps(self.event()))
        receipt_id = re.search(r'Receipt: `([0-9a-f]{32})`', result['permissionDecisionReason'])[1]
        relay = self.resend(receipt_id)
        relay['agent_id'] = None
        relay['tool_input']['to'] = 'agent-one'
        self.assert_entrypoint_allows(relay)
        relay['tool_input']['to'] = 'agent-two'

        result = self.entrypoint_output(json.dumps(relay))

        self.assertEqual(result['permissionDecision'], 'deny')
        self.assertIn('Receipt sender differs.', result['permissionDecisionReason'])
        self.assertFalse((self.state / 'receipts' / (receipt_id + '.consumed')).exists())

    def test_relay_spends_only_the_senders_pending_receipt(self):
        result = self.entrypoint_output(json.dumps(self.event()))
        receipt_id = self.receipt_id(result)
        owner_pending = {p.name: p.read_bytes() for p in (self.state / 'pending').iterdir()}
        owner_receipt = self.state / 'receipts' / (receipt_id + '.json')
        owner_bytes = owner_receipt.read_bytes()
        sender = self.event(to='agent-one')
        sender['agent_id'] = None
        result = self.entrypoint_output(json.dumps(sender))
        sender_id = self.receipt_id(result)
        pending = {p.name: p.read_bytes() for p in (self.state / 'pending').iterdir()}
        relay = self.resend(receipt_id)
        relay['agent_id'] = None
        relay['tool_input']['to'] = 'agent-one'

        result = self.entrypoint_output(json.dumps(relay))

        self.assertEqual(result['permissionDecision'], 'deny')
        reason = result['permissionDecisionReason']
        self.assertIn('Receipt `' + sender_id + '` is now spent.', reason)
        refusal_id = self.receipt_id(result)
        refusal = json.loads((self.state / 'receipts' / (refusal_id + '.json')).read_bytes())
        self.assertIsNone(refusal['parent'])
        self.assertFalse(refusal['resend_allowed'])
        self.assertEqual({p.name: p.read_bytes() for p in (self.state / 'pending').iterdir()}, pending)
        for name, body in owner_pending.items():
            self.assertEqual((self.state / 'pending' / name).read_bytes(), body)
        self.assertEqual(owner_receipt.read_bytes(), owner_bytes)
        self.assertFalse(owner_receipt.with_suffix('.consumed').exists())
        self.assertTrue((self.state / 'receipts' / (sender_id + '.consumed')).exists())

    def receipt_id(self, result):
        return re.search(r'Receipt: `([0-9a-f]{32})`', result['permissionDecisionReason'])[1]

    def test_null_receipt_owner_cannot_relay_to_an_absent_recipient(self):
        owner = self.event()
        owner['agent_id'] = None
        receipt_id = self.receipt_id(self.entrypoint_output(json.dumps(owner)))
        cited = self.resend(receipt_id)
        cited['tool_input'].pop('to')
        prompt = cited['tool_input']['message']
        agent = {**cited, 'tool_name': 'Agent', 'tool_input': {'prompt': prompt}}
        for event in (agent, cited):
            with self.subTest(tool=event['tool_name']):
                result = self.entrypoint_output(json.dumps(event))
                self.assertEqual(result['permissionDecision'], 'deny')
                self.assertIn('Receipt sender differs.', result['permissionDecisionReason'])
                self.assertFalse((self.state / 'receipts' / (receipt_id + '.consumed')).exists())

    def test_self_addressed_citation_consumes_the_owners_resend(self):
        receipt_id = self.receipt_id(self.entrypoint_output(json.dumps(self.event(to='agent-one'))))
        resend = self.resend(receipt_id)
        resend['tool_input']['to'] = 'agent-one'

        self.assert_entrypoint_allows(resend)

        self.assertTrue((self.state / 'receipts' / (receipt_id + '.consumed')).exists())
        result = self.entrypoint_output(json.dumps(resend))
        self.assertIn('Receipt is consumed.', result['permissionDecisionReason'])

    def test_format_refused_relay_resends_with_only_its_own_receipt(self):
        receipt_id = self.receipt_id(self.entrypoint_output(json.dumps(self.event())))
        relay = self.resend(receipt_id, 'Decision: Continue.\nNext: Resume.')
        relay['agent_id'] = None
        relay['tool_input']['to'] = 'agent-one'

        result = self.entrypoint_output(json.dumps(relay))

        self.assertEqual(result['permissionDecision'], 'deny')
        self.assertIn('Missing section: Facts', result['permissionDecisionReason'])
        relay_id = self.receipt_id(result)
        refusal = json.loads((self.state / 'receipts' / (relay_id + '.json')).read_bytes())
        self.assertTrue(refusal['resend_allowed'])
        self.assertIsNone(refusal['parent'])
        message = 'Facts: Receipt `' + receipt_id + '`.\nDecision: Continue.\nNext: Resume.'
        resend = self.resend(relay_id, message)
        resend['agent_id'] = None
        resend['tool_input']['to'] = 'agent-one'
        self.assert_entrypoint_allows(resend)
        self.assertTrue((self.state / 'receipts' / (relay_id + '.consumed')).exists())
        self.assertFalse((self.state / 'receipts' / (receipt_id + '.consumed')).exists())

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

    def input_event(self, key, html='<p>The review passes.</p>', **fields):
        return {'session_id': 'session-one', 'tool_use_id': 'tool-one', 'agent_id': 'agent-one',
                'tool_name': 'mcp__bettercoding__create_input',
                'tool_input': {'workspace_id': 'workspace-one', 'external_key': key,
                               'content': {'html': html}, **fields}}

    def test_unrelated_input_passes_and_keeps_the_first_receipt_open(self):
        self.hook_refusal(self.input_event('input-one'))
        receipt_id = self.last_receipt['id']
        self.assertTrue(self.last_receipt['formatting_only'])
        self.assertTrue(self.last_receipt['resend_allowed'])
        pending = next((self.state / 'pending').iterdir())
        pending_bytes = pending.read_bytes()

        unrelated = self.input_event(
            'input-two', '<meta name="output-kind" content="result"><p>The checks pass.</p>')
        unrelated['tool_use_id'] = 'tool-two'
        self.assertIsNone(self.hook_output(unrelated))

        self.assertEqual(pending.read_bytes(), pending_bytes)
        self.assertEqual(json.loads(pending_bytes), {'id': receipt_id, 'state': 'open'})
        self.assertFalse((self.state / 'receipts' / (receipt_id + '.consumed')).exists())
        resend = self.input_event('input-one', '<meta name="output-kind" content="result">'
                                  '<p>The review passes.</p><!-- ultraship-receipt:' + receipt_id + ' -->')
        self.assertIsNone(self.hook_output(resend))
        self.assertFalse(pending.exists())
        self.assertTrue((self.state / 'receipts' / (receipt_id + '.consumed')).exists())

    def test_uncited_same_input_still_spends_its_receipt(self):
        self.hook_refusal(self.input_event('input-one'))
        receipt_id = self.last_receipt['id']
        replay = self.input_event('input-one', '<meta name="output-kind" content="result">'
                                 '<p>The review passes.</p>')
        replay['tool_use_id'] = 'tool-two'

        self.assertIn('Receipt `' + receipt_id + '` is now spent.', self.hook_refusal(replay))

        self.assertFalse(self.last_receipt['resend_allowed'])
        self.assertTrue((self.state / 'receipts' / (receipt_id + '.consumed')).exists())

    def test_input_cannot_cite_another_external_keys_receipt(self):
        self.hook_refusal(self.input_event('input-one'))
        receipt_id = self.last_receipt['id']
        copied = self.input_event('input-two', '<meta name="output-kind" content="result">'
                                 '<p>The review passes.</p><!-- ultraship-receipt:' + receipt_id + ' -->')

        self.assertIn('Invalid receipt citation: Receipt tool, recipient or non-prose fields differ.',
                      self.hook_refusal(copied))

        self.assertFalse(self.last_receipt['resend_allowed'])
        self.assertFalse((self.state / 'receipts' / (receipt_id + '.consumed')).exists())
        self.assertEqual(json.loads(next((self.state / 'pending').iterdir()).read_text()),
                         {'id': receipt_id, 'state': 'open'})

    def test_identical_input_calls_share_pending_across_tool_use_ids(self):
        first = self.input_event('input-one')
        self.hook_refusal(first)
        receipt_id = self.last_receipt['id']
        pending = next((self.state / 'pending').iterdir())
        repeated = {**first, 'tool_use_id': 'tool-two'}

        self.assertIn('Receipt `' + receipt_id + '` is now spent.', self.hook_refusal(repeated))

        self.assertEqual(list((self.state / 'pending').iterdir()), [pending])
        self.assertEqual(json.loads(pending.read_text()), {'id': receipt_id, 'state': 'open'})
        self.assertTrue((self.state / 'receipts' / (receipt_id + '.consumed')).exists())
        self.assertIsNone(self.hook_output(self.input_event(
            'input-two', '<meta name="output-kind" content="result"><p>The checks pass.</p>')))

    def test_later_input_gets_one_resend_after_another_input_is_spent(self):
        self.hook_refusal(self.input_event('input-one'))
        first_id = self.last_receipt['id']
        self.assertIn('Receipt `' + first_id + '` is now spent.', self.hook_refusal(self.input_event(
            'input-one', '<meta name="output-kind" content="result"><p>The review passes.</p>')))
        self.hook_refusal(self.input_event('input-two'))
        second_id = self.last_receipt['id']
        self.assertTrue(self.last_receipt['formatting_only'])
        self.assertTrue(self.last_receipt['resend_allowed'])
        resend = self.input_event('input-two', '<meta name="output-kind" content="result">'
                                  '<p>The review passes.</p><!-- ultraship-receipt:' + second_id + ' -->')
        resend['tool_use_id'] = 'tool-three'

        self.assertIsNone(self.hook_output(resend))

        self.assertTrue((self.state / 'receipts' / (first_id + '.consumed')).exists())
        self.assertTrue((self.state / 'receipts' / (second_id + '.consumed')).exists())
        self.assertIn('Receipt is consumed.', self.hook_refusal(resend))
        self.assertFalse(self.last_receipt['resend_allowed'])

    def test_input_without_workspace_keeps_pending_per_external_key(self):
        first = self.input_event('input-one')
        first['tool_input'].pop('workspace_id')
        self.hook_refusal(first)
        receipt_id = self.last_receipt['id']
        self.assertIsNone(self.last_receipt['recipient'])
        second = self.input_event('input-two', '<meta name="output-kind" content="result">'
                                  '<p>The checks pass.</p>')
        second['tool_input'].pop('workspace_id')

        self.assertIsNone(self.hook_output(second))

        self.assertFalse((self.state / 'receipts' / (receipt_id + '.consumed')).exists())
        first['tool_input']['content']['html'] = ('<meta name="output-kind" content="result">'
                                                 '<p>The review passes.</p>')
        self.assertIn('Receipt `' + receipt_id + '` is now spent.', self.hook_refusal(first))
        self.assertTrue((self.state / 'receipts' / (receipt_id + '.consumed')).exists())

    def legacy_input_receipt(self, event, state='open'):
        receipt = text_lint.write_receipt(event, ['Missing section: Recommendation'], True, None)
        text_lint.pending_path(receipt).unlink()
        receipt.pop('input_key')
        receipt['mac'] = text_lint.signature(receipt, text_lint.receipt_key())
        (self.state / 'receipts' / (receipt['id'] + '.json')).write_bytes(text_lint.canonical(receipt))
        fields = [receipt.get(field) for field in ('session_id', 'agent_id', 'tool_name', 'recipient')]
        path = self.state / 'pending' / hashlib.sha256(text_lint.canonical(fields)).hexdigest()
        path.write_text(json.dumps({'id': receipt['id'], 'state': state}))
        return receipt, path

    def test_input_pending_key_matches_the_shared_hook_fixture(self):
        self.hook_refusal(self.input_event('input-one'))
        self.assertEqual(self.last_receipt['input_key'],
                         '4acd0ff543a7910ac07be012ae7398e564230fb519bce47a535abe0d24f56413')
        pending = next((self.state / 'pending').iterdir())
        self.assertEqual(pending.name,
                         'c57c4851d317765062fb5cbb32b7de185423bf77516b936618cbca195ea7b186')

    def test_input_keys_with_a_shared_long_prefix_remain_independent(self):
        prefix = 'x' * 200
        self.hook_refusal(self.input_event(prefix + 'one'))
        receipt_id = self.last_receipt['id']
        pending = next((self.state / 'pending').iterdir())
        pending_bytes = pending.read_bytes()

        self.assertIsNone(self.hook_output(self.input_event(
            prefix + 'two', '<meta name="output-kind" content="result"><p>The checks pass.</p>')))

        self.assertEqual(pending.read_bytes(), pending_bytes)
        self.assertFalse((self.state / 'receipts' / (receipt_id + '.consumed')).exists())

    def test_open_legacy_input_receipt_still_blocks_uncited_same_input(self):
        event = self.input_event('input-one')
        receipt, pending = self.legacy_input_receipt(event)
        event['tool_input']['content']['html'] = ('<meta name="output-kind" content="result">'
                                                 '<p>The review passes.</p>')

        self.assertIn('Receipt `' + receipt['id'] + '` is now spent.', self.hook_refusal(event))

        self.assertFalse(self.last_receipt['resend_allowed'])
        self.assertTrue((self.state / 'receipts' / (receipt['id'] + '.consumed')).exists())
        self.assertTrue(pending.exists())

    def test_spent_legacy_input_receipt_prevents_another_resend(self):
        event = self.input_event('input-one')
        receipt, pending = self.legacy_input_receipt(event, 'spent')
        pending_bytes = pending.read_bytes()

        self.hook_refusal(event)

        self.assertTrue(self.last_receipt['formatting_only'])
        self.assertFalse(self.last_receipt['resend_allowed'])
        self.assertEqual(pending.read_bytes(), pending_bytes)
        self.assertEqual(json.loads(pending_bytes), {'id': receipt['id'], 'state': 'spent'})

    def test_other_input_leaves_a_legacy_pending_entry_untouched(self):
        receipt, pending = self.legacy_input_receipt(self.input_event('input-one'))
        pending_bytes = pending.read_bytes()

        self.assertIsNone(self.hook_output(self.input_event(
            'input-two', '<meta name="output-kind" content="result"><p>The checks pass.</p>')))

        self.assertEqual(pending.read_bytes(), pending_bytes)
        self.assertFalse((self.state / 'receipts' / (receipt['id'] + '.consumed')).exists())

    def test_legacy_input_resend_clears_only_the_same_invocations_ship_sibling(self):
        for sibling_tool_id in ('tool-one', 'tool-two'):
            with self.subTest(sibling_tool_id=sibling_tool_id):
                event = self.input_event('input-one')
                event['session_id'] = sibling_tool_id
                legacy, legacy_pending = self.legacy_input_receipt(event)
                sibling_event = {**event, 'tool_use_id': sibling_tool_id}
                sibling = text_lint.write_receipt(
                    sibling_event, ['Missing section: Recommendation'], True, None)
                pending = text_lint.pending_path(sibling)
                pending_bytes = pending.read_bytes()
                event['tool_input']['content']['html'] = (
                    '<meta name="output-kind" content="result"><p>The review passes.</p>'
                    '<!-- ultraship-receipt:' + legacy['id'] + ' -->')

                self.assertIsNone(self.hook_output(event))

                self.assertFalse(legacy_pending.exists())
                self.assertTrue((self.state / 'receipts' / (legacy['id'] + '.consumed')).exists())
                self.assertEqual(pending.exists(), sibling_tool_id != 'tool-one')
                if sibling_tool_id != 'tool-one':
                    self.assertEqual(pending.read_bytes(), pending_bytes)
                self.assertFalse((self.state / 'receipts' / (sibling['id'] + '.consumed')).exists())

    def test_cited_input_resend_survives_pending_cleanup_errors_once(self):
        for case in ('malformed', 'missing-id', 'wrong-type', 'missing-sibling', 'bad-mac'):
            with self.subTest(case=case):
                event = self.input_event('input-one')
                event['session_id'] = case
                legacy, legacy_pending = self.legacy_input_receipt(event)
                sibling = text_lint.write_receipt(
                    event, ['Missing section: Recommendation'], True, None)
                pending = text_lint.pending_path(sibling)
                sibling_path = self.state / 'receipts' / (sibling['id'] + '.json')
                if case == 'malformed':
                    pending.write_text('{')
                elif case == 'missing-id':
                    pending.write_text('{}')
                elif case == 'wrong-type':
                    pending.write_text('[]')
                elif case == 'missing-sibling':
                    sibling_path.unlink()
                else:
                    sibling['mac'] = '0' * 64
                    sibling_path.write_text(json.dumps(sibling))
                pending_bytes = pending.read_bytes()
                event['tool_input']['content']['html'] = (
                    '<meta name="output-kind" content="result"><p>The review passes.</p>'
                    '<!-- ultraship-receipt:' + legacy['id'] + ' -->')

                self.assertIsNone(self.hook_output(event))

                self.assertEqual(pending.read_bytes(), pending_bytes)
                self.assertFalse(legacy_pending.exists())
                consumed = self.state / 'receipts' / (legacy['id'] + '.consumed')
                self.assertTrue(consumed.exists())
                self.assertFalse((self.state / 'receipts' / (sibling['id'] + '.consumed')).exists())
                self.assertIn('Receipt is consumed.', self.hook_refusal(event))
                self.assertFalse(self.last_receipt['resend_allowed'])
                self.assertTrue(consumed.exists())

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

    def test_uncited_refusal_spends_pending_receipt_and_admits_later_messages(self):
        self.hook_refusal(self.event())
        receipt_id = self.last_receipt['id']
        marker = self.state / 'receipts' / (receipt_id + '.consumed')
        valid = 'Facts: Checks pass.\nDecision: Continue.\nNext: Resume.'
        self.assertIsNone(self.hook_output(self.event(valid, to='another-chief')))
        other_session = self.event()
        other_session['session_id'] = 'another-session'
        self.hook_refusal(other_session)
        other_receipt_id = self.last_receipt['id']
        self.assertTrue(self.last_receipt['resend_allowed'])
        self.assertFalse(marker.exists())

        reason = self.hook_refusal(self.event(valid))
        self.assertIn('Receipt `' + receipt_id + '` is now spent.', reason)
        self.assertIn('The message refused under receipt `' + receipt_id + '` stays refused. '
                      'Later messages need no citation.', reason)
        self.assertTrue(marker.exists())
        self.assertEqual(stat.S_IMODE(marker.stat().st_mode), 0o600)
        self.assertFalse(self.last_receipt['resend_allowed'])
        self.assertIsNone(self.hook_output(self.event('The next review passes.\n' + valid)))
        self.assertIn('Receipt is consumed', self.hook_refusal(self.resend(receipt_id)))
        self.assertFalse(self.last_receipt['resend_allowed'])

        other_session = self.resend(other_receipt_id)
        other_session['session_id'] = 'another-session'
        self.assertIsNone(self.hook_output(other_session))

    def test_parallel_consumption_gets_normal_content_checks(self):
        self.hook_refusal(self.event())
        receipt_id = self.last_receipt['id']
        (self.state / 'receipts' / (receipt_id + '.consumed')).touch()
        valid = 'Facts: Checks pass.\nDecision: Continue.\nNext: Resume.'
        with patch.object(text_lint, 'pending_entry', return_value={'id': receipt_id, 'state': 'open'}):
            self.assertIsNone(self.hook_output(self.event(valid)))
            reason = self.hook_refusal(self.event())
        self.assertIn('Missing section: Facts Missing section: Decision Missing section: Next', reason)
        self.assertTrue(self.last_receipt['formatting_only'])

    def test_pending_marker_write_error_keeps_the_pending_refusal(self):
        self.hook_refusal(self.event())
        receipt_id = self.last_receipt['id']
        valid = 'Facts: Checks pass.\nDecision: Continue.\nNext: Resume.'
        marker = self.state / 'receipts' / (receipt_id + '.consumed')
        open_file = text_lint.os.open

        def fail_marker(path, flags, mode=0o777):
            if path == marker:
                raise PermissionError('marker unavailable')
            return open_file(path, flags, mode)

        with patch.object(text_lint.os, 'open', side_effect=fail_marker):
            reason = self.hook_refusal(self.event(valid))
        self.assertIn('A formatting-only refusal to this recipient is pending.', reason)
        self.assertIn('Cite its receipt `' + receipt_id + '`', reason)
        self.assertFalse(marker.exists())
        identity = {'session_id': 'session-one', 'agent_id': 'agent-one',
                    'tool_name': 'SendMessage', 'recipient': 'chief'}
        self.assertEqual(text_lint.pending_entry(identity), {'id': receipt_id, 'state': 'open'})
        self.assertIsNone(self.hook_output(self.resend(receipt_id)))

    def test_uncited_spend_survives_receipt_write_failure(self):
        self.hook_refusal(self.event())
        receipt_id = self.last_receipt['id']
        valid = 'Facts: Checks pass.\nDecision: Continue.\nNext: Resume.'
        with patch.object(text_lint, 'write_receipt', side_effect=OSError('disk full')):
            result = self.hook_output(self.event(valid))
        self.assertEqual(result['permissionDecision'], 'deny')
        self.assertIn('Receipt `' + receipt_id + '` is now spent.', result['permissionDecisionReason'])
        self.assertIn('No receipt was written, so no resend', result['permissionDecisionReason'])
        self.assertTrue((self.state / 'receipts' / (receipt_id + '.consumed')).exists())
        self.assertIsNone(self.hook_output(self.event('The next review passes.\n' + valid)))
        self.assertIn('Receipt is consumed', self.hook_refusal(self.resend(receipt_id)))
        self.assertFalse(self.last_receipt['resend_allowed'])

    def test_uncited_message_spends_receipt_and_keeps_content_checks(self):
        self.hook_refusal(self.event())
        receipt_id = self.last_receipt['id']
        pending = next((self.state / 'pending').iterdir())
        expected_key = hashlib.sha256(json.dumps(['session-one', 'agent-one', 'SendMessage', 'chief'],
                                               separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
        self.assertEqual(pending.name, expected_key)
        self.assertEqual(json.loads(pending.read_text()), {'id': receipt_id, 'state': 'open'})
        valid = self.resend(receipt_id)['tool_input']['message'].split('\n<!--')[0]
        reason = self.hook_refusal(self.event(valid))
        self.assertIn('Receipt `' + receipt_id + '` is now spent.', reason)
        self.assertIn('The message refused under receipt `' + receipt_id + '` stays refused. '
                      'Later messages need no citation.', reason)
        self.assertFalse(self.last_receipt['resend_allowed'])
        self.assertFalse(self.last_receipt['formatting_only'])
        self.assertTrue((self.state / 'receipts' / (receipt_id + '.consumed')).exists())
        identity = {'session_id': 'session-one', 'agent_id': 'agent-one',
                    'tool_name': 'SendMessage', 'recipient': 'chief'}
        self.assertEqual(text_lint.pending_entry(identity), {'id': receipt_id, 'state': 'spent'})
        reason = self.hook_refusal(self.event('The review passes.'))
        self.assertIn('Missing section: Facts Missing section: Decision Missing section: Next', reason)
        self.assertIn('This refusal permits no resend, because a receipt to this recipient '
                      'was spent within 24 hours.', reason)
        self.assertFalse(self.last_receipt['resend_allowed'])
        self.assertTrue(self.last_receipt['formatting_only'])
        self.assertEqual(text_lint.pending_entry(identity), {'id': receipt_id, 'state': 'spent'})
        self.assertIsNone(self.hook_output(self.event(valid, to='another-chief')))
        self.assertIn('Receipt is consumed', self.hook_refusal(self.resend(receipt_id)))
        self.assertTrue((self.state / 'receipts' / (receipt_id + '.consumed')).exists())
        self.assertEqual(text_lint.pending_entry(identity), {'id': receipt_id, 'state': 'spent'})

    def test_uncited_input_spends_receipt_and_refuses_cited_resend(self):
        event = {'session_id': 'session-one', 'tool_name': 'create_input',
                 'tool_input': {'workspace_id': 'one', 'content': {'html': '<p>Wait.</p>'}}}
        self.hook_refusal(event)
        receipt_id = self.last_receipt['id']
        event['tool_input']['content']['html'] = '<meta name="output-kind" content="result"><p>Wait.</p>'
        self.assertIn('Receipt `' + receipt_id + '` is now spent.', self.hook_refusal(event))
        event['tool_input']['content']['html'] += '<!-- ultraship-receipt:' + receipt_id + ' -->'
        self.assertIn('Receipt is consumed', self.hook_refusal(event))
        self.assertTrue((self.state / 'receipts' / (receipt_id + '.consumed')).exists())
        identity = {'session_id': 'session-one', 'agent_id': None,
                    'tool_name': 'create_input', 'recipient': 'one'}
        self.assertEqual(text_lint.pending_entry(identity), {'id': receipt_id, 'state': 'spent'})

    def test_pending_stale_entries(self):
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
        self.assertIn('Receipt `' + receipt_id + '` is now spent.',
                      self.hook_refusal(self.event(valid)))
        identity = {'session_id': 'session-one', 'agent_id': 'agent-one',
                    'tool_name': 'SendMessage', 'recipient': 'chief'}
        self.assertEqual(text_lint.pending_entry(identity), {'id': receipt_id, 'state': 'spent'})
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
