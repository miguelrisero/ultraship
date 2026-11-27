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
                            '`Facts`, `Decision`, and `Next`', '`Options` A–D with effects (three only with the line "Only three real paths exist. A fourth would be padding.")',
                            'informational result Inputs without artificial choices',
                            'Future targets over 48 Sol hours', '5% or less', '85% or more'):
            self.assertIn(requirement, dispatch)

    def test_chief_selects_planners_by_class_and_uses_the_shared_confirmation_gate(self):
        chief = (ROOT / 'plugins/chief/skills/run/SKILL.md').read_text()
        prepare = chief.split('## Prepare the run\n', 1)[1].split('## Dispatch\n', 1)[0]
        self.assertIn('| Planning | `ship:planner--opus` |', chief)
        self.assertIn('| Important planning, including P0 | `ship:planner--fable52` |', chief)
        self.assertIn('Dispatch `ship:planner--fable52` first for important and P0 plans.', prepare)
        self.assertIn('Important planning includes architecture, contracts, migrations, security, and billing.', prepare)
        self.assertIn('Dispatch `ship:planner--opus` first for normal plans.', prepare)
        self.assertIn('Follow the Ship roster at `skills/ship/references/roster.md` for fallback order.', prepare)
        self.assertIn('Apply the installed Ship plugin\'s '
                      '`skills/ship/references/pipeline.md#important-planning` gate only to important plans.', prepare)
        self.assertIn('Record the refutation and confirmation results on the run board.', prepare)
        self.assertIn('Keep dependent lanes pending until the gate passes.', prepare)
        self.assertIn('6. Freeze the goal, lane boundaries, dependencies, safety constraints, and checks.\n'
                      '   For an important plan, take these only from the confirmed final plan. '
                      'Return to the gate on any material change.\n'
                      '   Run `ship:panel design` or `ship:panel high` once on substantive plans.', prepare)
        self.assertIn('Leave the Agent `model` field unset.', chief)
        state = (ROOT / 'plugins/chief/skills/run/references/state.md').read_text()
        self.assertIn('| Planning gate | `plan-refute` and `plan-confirm` records, each with `agent-type@agent-id`, '
                      'repository SHA, verdict, plan digest, and evidence manifest SHA-256; rework count and gate status |', state)

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

    def test_owner_thresholds_live_in_the_canonical_skill(self):
        paths = (
            'plugins/ship/skills/ship/references/owner-decisions.md',
            'plugins/ship/skills/ship/SKILL.md',
            'plugins/chief/skills/run/SKILL.md',
            'plugins/chief/skills/run/references/dispatch.md',
            *(f'plugins/ship/agents/{name}.md' for name in (
                'driver', 'driver--sol', 'writer--sol', 'writer--fable52',
            )),
        )
        for name in paths:
            with self.subTest(path=name):
                section = (ROOT / name).read_text().split('## Only the owner\n', 1)[1]
                section = section.split('\n##', 1)[0]
                self.assertIn('owner-decisions:owner-decisions', section)
                self.assertNotIn('| Deletion of customer data |', section)
                self.assertNotIn('six thresholds', section)

    def test_owner_policy_lookup_requires_current_heading_and_preserves_holds(self):
        target = 'skills/ship/references/owner-decisions.md'
        chief = (ROOT / 'plugins/chief/skills/run/SKILL.md').read_text()
        section = chief.split('## Only the owner\n', 1)[1].split('\n## ', 1)[0]
        self.assertIn(f'`{target}#only-the-owner`', section)
        self.assertIn('`owner-decisions:owner-decisions`', section)
        self.assertIn("Only the owner's own words approve a critical item.", section)
        fallback = ROOT / 'plugins/ship' / target
        self.assertTrue(fallback.is_file())
        for path in (fallback, ROOT / 'plugins/chief/skills/run/references/dispatch.md'):
            with self.subTest(path=path):
                section = path.read_text().split('## Only the owner\n', 1)[1].split('\n## ', 1)[0]
                for requirement in (
                    '`Only the owner`',
                    'Treat the older `Escalate only a critical item` heading as a reason to look up the current policy.',
                    'If the installed skill or `Only the owner` is missing or incomplete, read the',
                    'https://github.com/bettergroupinc/better-plugin/blob/main/plugins/owner-decisions/skills/owner-decisions/SKILL.md#only-the-owner',
                    '`plugins/owner-decisions/skills/owner-decisions/SKILL.md`',
                    'authorized local copy',
                    'If the canonical policy remains unavailable',
                    'refuse a sensitive action whose approval requirement is unclear',
                    'Keep existing permission denials and holds.',
                    'Continue independent work.',
                    "Only the owner's own words approve a critical item.",
                ):
                    self.assertIn(requirement, section)
        ship = (ROOT / 'plugins/ship/skills/ship/references/owner-decisions.md').read_text()
        self.assertIn('Keep separate product, billing, security policy, and architecture scope holds in force.', ship)
        self.assertIn('Keep all separate action, scope, publication, and live-operation gates.', ship)

    def test_copied_chief_brief_uses_canonical_policy_with_older_ship(self):
        dispatch = (ROOT / 'plugins/chief/skills/run/references/dispatch.md').read_text()
        brief = dispatch.split('## Brief template\n', 1)[1].split('```text\n', 1)[1].split('\n```', 1)[0]
        self.assertIn('Include the exact local policy path in `Readable files`', brief)
        self.assertNotIn('ship/references/owner-decisions.md', brief.split('## Only the owner\n', 1)[1].split('\nTask:', 1)[0])
        contract = (ROOT / 'plugins/ship/skills/ship/references/owner-decisions.md').read_text()
        helper = contract.split('## Helper standing request\n', 1)[1].split('\n## ', 1)[0]
        self.assertIn('Include the absolute path of this reference in `Readable files`', helper)

    def test_merge_deadline_starts_after_all_pre_command_gates(self):
        for name in ('plugins/ship/skills/ship/SKILL.md', 'plugins/chief/skills/run/SKILL.md'):
            with self.subTest(path=name):
                text = (ROOT / name).read_text()
                self.assertIn('Send `/merge` within 30 minutes after all applicable pre-command gates pass.', text)
                self.assertIn("Keep the repository's merge rules and queue holds.", text)

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


DRAFT_PUSH = ('A draft PR in a private repository is not publication, so a publication or activation hold never blocks its draft push. '
              'An owner hold that names the push still applies.')


class BriefSafetyTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop('SHIP_LINT_OFF', None)

    def test_draft_push_is_never_blocked_by_a_publication_hold(self):
        # A Sol lane held its draft push on a brief's "publication holds" wording (CoC replay, 26 Nov).
        for name in ('plugins/ship/skills/ship/SKILL.md', 'plugins/chief/skills/run/SKILL.md',
                     'plugins/chief/skills/run/references/dispatch.md', 'plugins/ship/agents/driver.md'):
            item = next(line for line in (ROOT / name).read_text().splitlines() if line.startswith('2. ') and 'draft CI' in line)
            with self.subTest(path=name):
                self.assertTrue(item.endswith(DRAFT_PUSH))
                self.assertEqual(item.count('is not publication'), 1)
        self.assertIn('before marking ready. ' + DRAFT_PUSH, (ROOT / 'plugins/ship/agents/driver--sol.md').read_text())
        for doc in sorted((ROOT / 'plugins').rglob('*.md')):
            with self.subTest(broad_rule=str(doc.relative_to(ROOT))):
                text = doc.read_text()
                self.assertNotIn('A draft PR is not publication', text)
                self.assertNotIn('blocks a draft push', text)
        self.assertIn('A publication or activation hold blocks a push to a public repository or one of unknown visibility.',
                      (ROOT / 'plugins/ship/skills/ship/references/pipeline.md').read_text())

    def test_hold_report_names_pr_sha_and_next_step(self):
        for name in ('plugins/ship/skills/ship/SKILL.md', 'plugins/chief/skills/run/SKILL.md'):
            text = (ROOT / name).read_text()
            with self.subTest(path=name):
                self.assertIn('In a peer hold or wait report, give `Facts` (direct PR URL, or `no PR:` with the reason, and the 40-hex '
                              'head SHA), `Decision` (blocked step, release condition), and `Next` (accountable owner, exact permitted '
                              'action, UTC deadline).', text)
                self.assertIn('The chief refuses an incomplete hold or wait report and asks the sender for all required fields.', text)

    def test_lane_cap_follows_the_quota_tier(self):
        skill = (ROOT / 'plugins/chief/skills/run/SKILL.md').read_text()
        self.assertIn('There is no lane cap in the Green and Amber quota tiers', skill)
        self.assertIn('In the Red and Critical tiers, apply the CoC emergency lane limits', skill)
        self.assertIn('- Lanes: no cap in the Green and Amber quota tiers; the CoC emergency limits apply in Red and Critical;',
                      (ROOT / 'plugins/chief/README.md').read_text())

    def test_decision_options_run_a_to_d_with_the_three_option_line(self):
        line = '`Options` A–D with effects (three only with the line "Only three real paths exist. A fourth would be padding.")'
        self.assertIn(line, (ROOT / 'plugins/ship/skills/ship/references/owner-decisions.md').read_text())
        self.assertIn('<p>With three real options, add: Only three real paths exist. A fourth would be padding.</p>',
                      (ROOT / 'plugins/ship/hooks/text_lint.py').read_text())

    def test_each_template_requires_read_scope_and_safety_sentences(self):
        for name, heading in (
            ('plugins/chief/skills/run/references/dispatch.md', '## Brief template'),
            ('plugins/ship/skills/review/SKILL.md', '## Dispatch'),
            ('plugins/ship/skills/panel/SKILL.md', '## Dispatch'),
            ('plugins/ship/skills/babysit/SKILL.md', '## Brief safety'),
            ('plugins/ship/skills/ship/references/owner-decisions.md', '## Helper standing request'),
        ):
            body = (ROOT / name).read_text().split(heading + '\n', 1)[1]
            if heading == '## Brief template':
                section = body.split('```text\n', 1)[1].split('\n```', 1)[0]
                self.assertLess(section.index('## You may always'), section.index('## Only the owner'))
                self.assertLess(section.index('## Only the owner'), section.index('Task:'))
            else:
                section = body.split('\n## ', 1)[0]
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
