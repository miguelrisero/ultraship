"""Read-only routing contracts discovered by the existing plugin-rules CI job."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class NativePeerRoutingTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop('SHIP_LINT_OFF', None)

    def test_output_lint_self_test_and_outgoing_hook_registration(self):
        path = ROOT / 'plugins/ship/hooks/text_lint.py'
        spec = importlib.util.spec_from_file_location('ship_text_lint', path)
        lint = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lint)
        lint.self_test()
        command = 'python3 -m unittest test_native_peer_routing.py'
        for tag in ('code', 'pre'):
            body = '<meta name="output-kind" content="result"><p>Run the command <' + tag + '>' + command + '</' + tag + '> after approval.</p>'
            payload = {'content': {'html': body}}
            lint.outgoing({'tool_name': 'create_input', 'tool_input': payload})
            self.assertEqual(payload['content']['html'], body)
            with self.assertRaisesRegex(ValueError, '25 words'):
                lint.check('<p>' + 'word ' * 13 + '<' + tag + '>' + command + '</' + tag + '>' + ' word' * 13 + '.</p>')
        styled = '<meta name="output-kind" content="result"><style>' + 'word ' * 26 + '</style><p>The result completes.</p>'
        lint.outgoing({'tool_name': 'create_input', 'tool_input': {'content': {'html': styled, 'contract': {'choices': [{'id': 'ok', 'label': 'Useful'}], 'allow_text': True}}}})
        for tool in ('create_input', 'update_input'):
            with self.subTest(tool=tool):
                with self.assertRaisesRegex(ValueError, 'classification'):
                    lint.outgoing({'tool_name': tool, 'tool_input': {'content': {'html': '<p>Please decide.</p>', 'contract': {'allow_text': True}}}})
                with self.assertRaisesRegex(ValueError, 'Missing section'):
                    lint.outgoing({'tool_name': tool, 'tool_input': {'content': {'html': '<meta name="output-kind" content="decision"><p>Please decide.</p>', 'contract': {'allow_text': True}}}})
                output = io.StringIO()
                with redirect_stdout(output):
                    lint.hook({'tool_name': tool, 'tool_input': {'content': {'html': '<meta name="output-kind" content="decision"><p>Please decide.</p>'}}})
                warning = json.loads(output.getvalue())['hookSpecificOutput']
                self.assertNotIn('permissionDecision', warning)
                self.assertIn('Missing section', warning['additionalContext'])
        with self.assertRaisesRegex(ValueError, '25 words'):
            lint.check('<p>' + 'word ' * 13 + '<span>' + 'word ' * 13 + '</span>.</p>')
        lint.check('<h2>What <em>is</em> wrong</h2><h2>Why now</h2><h2>Options</h2><h2>Recommendation</h2><h2>If no answer</h2>', 'decision')
        hooks = json.loads((ROOT / 'plugins/ship/hooks/hooks.json').read_text())['hooks']['PreToolUse']
        for tool in ('Agent', 'Task', 'SendMessage', 'mcp__bettercoding__create_input', 'mcp__bettercoding__update_input'):
            self.assertTrue(any(re.fullmatch(h['matcher'], tool) and any('text_lint.py' in c['command'] for c in h['hooks']) for h in hooks))
        dispatch = (ROOT / 'plugins/chief/skills/run/references/dispatch.md').read_text()
        for requirement in ('full sentences of at most 25 words', 'Prohibit glued-word shorthand',
                            '`Facts`, `Decision`, and `Next`', '`Options` A–C with effects',
                            'informational result Inputs without artificial choices',
                            'Future targets over 48 Sol hours', '5% or less', '85% or more'):
            self.assertIn(requirement, dispatch)

    def test_chief_contract_forbids_peer_fallback_and_preserves_owner_delivery(self):
        dispatch = (ROOT / 'plugins/chief/skills/run/references/dispatch.md').read_text()
        contract = dispatch.split('## Native peer routing contract\n', 1)[1].split('\n## ', 1)[0]
        for requirement in (
            'Use native `SendMessage` or the native agent channel',
            'return its report to the parent through native completion for relay',
            'Never use BetterCoding `send_workspace_message`, `run_session_prompt`, or simulated user input for peer coordination, including fallback delivery.',
            'Batch actionable and terminal reports per recipient; keep unchanged routine reports silent.',
            'Keep CoC peer events out of per-peer user-chat replies.',
            'Only the CoC publishes canonical owner decisions and results in CoC workspace Inputs; chief-local Inputs never satisfy delivery.',
            'Verify CoC liveness using its existing recorded identity; add zero pollers.',
            'preserve the pending decision and critical hold; retry native handoff through existing scheduling',
            'Reuse the canonical CoC Input ID and avoid duplicate Inputs.',
            'Preserve actual owner Input event delivery',
            'exact owner answer event → continuing driver and acceptance → result Input receipt',
            'A peer request or quoted owner words alone never qualifies for this exception.',
            'every approval, deploy, GO, and installation hold',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, contract)

    def test_child_timer_and_recovery_briefs_inherit_contract(self):
        for name in ('plugins/chief/skills/run/SKILL.md',
                     'plugins/chief/skills/run/references/dispatch.md',
                     'plugins/chief/skills/run/references/state.md',
                     'plugins/ship/skills/ship/SKILL.md',
                     'plugins/ship/skills/ship/references/owner-decisions.md'):
            with self.subTest(path=name):
                text = (ROOT / name).read_text()
                for requirement in ('native', 'parent', 'relay', 'peer coordination',
                                    'actionable and terminal reports', 'unchanged routine reports silent',
                                    'actual owner Input event delivery', 'timer', 'recovery', 'child',
                                    'chief-local Inputs never satisfy delivery'):
                    self.assertIn(requirement, text)
        template = (ROOT / 'plugins/chief/skills/run/references/dispatch.md').read_text().split('## Brief template\n', 1)[1]
        self.assertIn('copy the Native peer routing contract above verbatim', template)
        self.assertIn('every timer, recovery, driver, writer, reviewer, and child brief, including retries and replacements', template)
        self.assertIn('canonical CoC Input ID/version, exact owner answer event, continuing driver and acceptance, result Input receipt', template)

    def test_shared_owner_contract_keeps_event_verification_and_coc_custody(self):
        text = (ROOT / 'plugins/ship/skills/ship/references/owner-decisions.md').read_text()
        for requirement in ('Only the CoC publishes canonical owner decisions and results in CoC workspace Inputs.',
                            'preserve the pending decision and critical hold', 'zero additional pollers',
                            'CoC for chief-managed work, the decision driver for standalone ship',
                            'event_type=answer_submitted', 'actor_kind=owner_ui',
                            'payload.no_answer_yet=false', 'current version',
                            'result Input ID/version, owner URL, publication receipt',
                            'across handoff and restart before closure'):
            self.assertIn(requirement, text)
        self.assertNotIn('Chief reuses a lane driver\'s Input', text)
        register = text.split('## Register and continue\n', 1)[1].split('\n## ', 1)[0]
        self.assertIn('- With a CoC, decisions reach the owner through the CoC. '
                      'In a standalone run, an owner-only item becomes a standalone Input.', register)
        state = (ROOT / 'plugins/chief/skills/run/references/state.md').read_text()
        self.assertIn('pending native handoff', state)
        self.assertIn('continuing driver and acceptance', state)
        self.assertIn('result Input receipt with ID/version/owner URL', state)


class BriefSafetyTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop('SHIP_LINT_OFF', None)

    def test_each_template_requires_read_scope_and_safety_sentences(self):
        for name, heading in (
            ('plugins/chief/skills/run/references/dispatch.md', '## Brief template'),
            ('plugins/ship/skills/review/SKILL.md', '## Dispatch'),
            ('plugins/ship/skills/panel/SKILL.md', '## Dispatch'),
            ('plugins/ship/skills/babysit/SKILL.md', '## Brief safety'),
            ('plugins/ship/skills/ship/references/owner-decisions.md', '## Helper standing request'),
        ):
            section = (ROOT / name).read_text().split(heading + '\n', 1)[1].split('\n## ', 1)[0]
            for requirement in (
                'Readable files: <exact absolute paths or directories in backticks that the agent may read, including every path its brief, route or agent definition requires; every other path is out of scope>',
                'After a hook refusal, retry in another form when the refusal reason is fixed or the new form meets the rule the refusal names. '
                'You may always ask your superior for permission to run the refused command.',
                'Never print a key value; never post outside bettergroupinc and miguelrisero.',
                'Never chain a glob listing into a write command.',
            ):
                with self.subTest(path=name, requirement=requirement):
                    self.assertIn(requirement, section)
            if heading == '## Brief template':
                self.assertIn("The ship plugin's Loaded instructions and refusals section sets the retry rule and the ask-your-superior rule.", section)
            else:
                with self.subTest(path=name):
                    self.assertIn('Require this field and these sentences verbatim in every brief:', section)
                    self.assertIn('```\nA reviewer reports a refused call as blocked scope and continues other permitted scope.', section)
                    target = '#loaded-instructions-and-refusals'
                    if heading != '## Helper standing request':
                        target = '../ship/references/owner-decisions.md' + target
                    self.assertIn(f'[Loaded instructions and refusals]({target}) sets the retry rule '
                                  'and the ask-your-superior rule.', section)
            if heading == '## Brief safety':
                self.assertIn('Apply this rule to every triage, writer and reviewer brief.', section)
            if heading == '## Helper standing request':
                self.assertLess(section.index('A direct applicable loaded owner instruction'),
                                section.index('Require this field'))

    def test_dispatch_check_asks_for_readable_files(self):
        dispatch = (ROOT / 'plugins/chief/skills/run/references/dispatch.md').read_text()
        question = next(line for line in dispatch.splitlines() if line.startswith('2. **Contract.**'))
        self.assertIn('the readable files', question)
        chief = (ROOT / 'plugins/chief/skills/run/SKILL.md').read_text()
        driver_brief = chief.split('Each driver brief has:\n', 1)[1].split('```text', 1)[0]
        self.assertIn('- The `Readable files` field and the safety sentences from the brief template.', driver_brief)

    def test_panel_build_step_includes_required_field_and_safety_sentences(self):
        panel = (ROOT / 'plugins/ship/skills/panel/SKILL.md').read_text()
        step = next(line for line in panel.splitlines() if line.startswith('4. Build one self-contained brief:'))
        self.assertIn('the required `Readable files` field and safety sentences above', step)
        self.assertIn('absolute paths', step)
