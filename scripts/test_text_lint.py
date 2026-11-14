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

    def hook_refusal(self, recipient, message):
        event = {'tool_name': 'SendMessage',
                 'tool_input': {'to': recipient, 'message': message}}
        output = io.StringIO()
        with patch('sys.argv', ['text_lint.py', 'hook']), \
                patch('sys.stdin', io.StringIO(json.dumps(event))), redirect_stdout(output):
            runpy.run_path(str(ROOT / 'plugins/ship/hooks/text_lint.py'), run_name='__main__')
        result = json.loads(output.getvalue())['hookSpecificOutput']
        self.assertEqual(result['hookEventName'], 'PreToolUse')
        self.assertEqual(result['permissionDecision'], 'deny')
        return result['permissionDecisionReason']

    def test_subagent_format_refusal_has_resend_template(self):
        for recipient in ('main', 'a' + '0' * 16):
            for prose, error in (
                    (' '.join(['word'] * 26) + '.', 'Write at most 25 words per sentence.'),
                    ('Send deadline2026 by8November00.',
                     'Separate glued words with spaces; remove compressed shorthand.')):
                with self.subTest(recipient=recipient, error=error):
                    message = prose + '\nFacts: Checks pass.\nDecision: Continue.\nNext: Resume.'
                    self.assertEqual(self.hook_refusal(recipient, message),
                                     'Output contract: ' + error + ' Resend with this shape:\n'
                                     + text_lint.SUBAGENT_TEMPLATE)

    def test_subagent_missing_section_refusal_has_peer_template(self):
        for prose in ('The review passes.', ' '.join(['word'] * 26) + '.'):
            with self.subTest(prose=prose):
                message = prose + '\nDecision: Continue.\nNext: Resume.'
                prefix = ('Write at most 25 words per sentence. '
                          if prose.startswith('word') else '')
                self.assertEqual(self.hook_refusal('main', message),
                                 'Output contract: ' + prefix + 'Missing section: Facts'
                                 + ' Resend with this shape:\n' + text_lint.PEER_TEMPLATE)

    def test_peer_refusal_has_resend_template(self):
        self.assertEqual(self.hook_refusal('chief', 'The review passes.'),
                         'Output contract: Missing section: Facts Missing section: Decision '
                         'Missing section: Next Resend with this shape:\n' + text_lint.PEER_TEMPLATE)


if __name__ == '__main__':
    unittest.main()
