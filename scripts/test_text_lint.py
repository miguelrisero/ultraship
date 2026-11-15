"""Outgoing prose lint: glued word-number shorthand and restated-hold walls."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ship_text_lint', ROOT / 'plugins/ship/hooks/text_lint.py')
text_lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(text_lint)


class TextLintTests(unittest.TestCase):
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

    def hook_refusal(self, event):
        output = io.StringIO()
        with patch('sys.argv', ['text_lint.py', 'hook']), \
                patch('sys.stdin', io.StringIO(json.dumps(event))), redirect_stdout(output):
            runpy.run_path(str(ROOT / 'plugins/ship/hooks/text_lint.py'), run_name='__main__')
        result = json.loads(output.getvalue())['hookSpecificOutput']
        self.assertEqual(result['hookEventName'], 'PreToolUse')
        self.assertEqual(result['permissionDecision'], 'deny')
        return result['permissionDecisionReason']

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


if __name__ == '__main__':
    unittest.main()
