"""The driver brief supplies the writer contract and an admissible tool command."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'plugins/ship/skills/ship/scripts/row_reanchor.py'
REFERENCE = ROOT / 'plugins/ship/skills/ship/references/owner-decisions.md'
spec = importlib.util.spec_from_file_location('brief_text_lint', ROOT / 'plugins/ship/hooks/text_lint.py')
text_lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(text_lint)
spec = importlib.util.spec_from_file_location('brief_hook', ROOT / 'plugins/ship/hooks/ultraship.py')
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


SHARED_VALUES = {
    'Input UUID': 'f39a1c87-62de-4b09-a153-7cd02e8916ab', 'version': '1',
    'workspace UUID': 'e17d0c39-84a1-4f6b-b205-9c73a8de621f',
    'event ID': '7c9e01a4-d628-43fb-9a16-0e8b27d5c391',
    'event hash': '3b8f14e29cd065a781b9e40c6f2a8d3174e95bc0a6d723f8c109b5e467a2d8c3',
    'decision file SHA256': 'c8' * 32, 'run ID': '19874203156', 'attempt': '1',
    'job ID': '67284901352', 'count': '0', 'expected': '1', 'tested merge SHA': 'b4' * 20,
    'tested merge tree SHA': 'c5' * 20, 'subject commit SHA': 'd6' * 20,
    'CI base SHA': '9e14c2f80a6d37b5914e08c2d6f7a3b9051ce824',
    'author head SHA': 'a38d91e5c7b204f6d819ec03a7f52b6084de19c2',
    'tool base SHA': '9e14c2f80a6d37b5914e08c2d6f7a3b9051ce824',
    'rule Input UUID': 'a5c2e8f1-3b74-4d09-96e0-1f8d27b4c053',
    'rule event ID': '2d6f9b08-71ce-4a35-8e14-b09c53a7d6f2',
    'rule event hash': '9a1e5c73d08b4f26a7e3910c5d8b6f42e0a7c319d5b86e24f1a03c7d9e58b2f6',
    'commit subject': 'test: re-anchor warning race',
}


def documented_command(reference, plugin_root, row, row_id, subject, base, head):
    documented = re.search(r'Use exactly `([^`]+)`', reference.split('## Row re-anchor tool admission record\n', 1)[1])[1]
    command = documented.replace('<plugin root>', plugin_root).replace('<absolute path>', str(row))
    command = command.replace('<id>', row_id).replace('<repository-relative path>', subject)
    command = command.replace('<ref>', base, 1).replace('<ref>', head, 1)
    return command


class BriefTests(unittest.TestCase):
    def setUp(self):
        self.reference = REFERENCE.read_text()
        section = self.reference.split('## Row re-anchor tool brief\n', 1)[1].split('\n## ', 1)[0]
        self.template = section.split('```text\n', 1)[1].split('\n```', 1)[0]

    def prepare_admission(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        root = Path(os.path.realpath(temporary))
        worktree = root / 'worktree'
        row = worktree / 'tests/mutation/rows.toml'
        row.parent.mkdir(parents=True)
        row.write_text('synthetic')
        base, head = SHARED_VALUES['CI base SHA'], SHARED_VALUES['author head SHA']
        row_id, subject = 'P25-warning-race', 'src/warning.py'
        plugin_root = str(ROOT / 'plugins/ship')
        command = documented_command(self.reference, plugin_root, row, row_id, subject, base, head)
        self.assertEqual(command, 'python3 -I ' + str(TOOL) + ' --row-file ' + str(row)
                         + ' --row-id ' + row_id + ' --subject ' + subject + ' --base ' + base + ' --head ' + head)
        expiry = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() + 3600))
        values = {
            **SHARED_VALUES,
            'row ID': row_id, 'PR URL': 'https://github.com/example/repo/pull/25',
            'verifier name': 'Coordinator', 'verification time': '2026-11-16T10:00:00Z',
            'decision file path': str(root / 'decision.md'),
            'tool route decision path': str(root / 'tool-route.md'),
            'row file path': str(row), 'subject path': subject, 'job name': 'Anchor validation',
            'job log URL': 'https://github.com/example/repo/actions/runs/19874203156/job/67284901352',
            'subject line range': '41-58', 'review time': '2026-11-16T09:30:00Z',
            'added': '4', 'deleted': '2', 'tool base reason': 'the CI base',
            'method-only denials': 'one `python3` heredoc denial',
            'denial times': '08:10Z', 'denial record path': str(root / 'denial.jsonl'),
            'denial record lines': '3', 'assigned topic': 'the warning race rows',
            'plugin root': plugin_root,
            'rule verifier name': 'Coordinator', 'rule verification time': '2026-11-16T10:00:00Z',
            'earlier attempts': 'one heredoc attempt',
            'attempt record path': str(root / 'attempt.jsonl'),
            'expiry time': expiry, 'worktree path': str(worktree), 'tool command': command,
            'return time': '2026-11-16T11:00:00Z', 'decision file name': 'decision.md',
        }
        self.assertEqual(set(re.findall(r'<([^>]+)>', self.template)), set(values))
        brief = re.sub(r'<([^>]+)>', lambda match: values[match[1]], self.template)
        self.assertNotIn('<', brief)
        text_lint.check(brief, 'peer')
        self.assertIsNone(re.search(r'^\s*(old|new)\s*=', brief, re.M))
        self.assertFalse(any(line.startswith('[') for line in brief.splitlines()))
        admitted_command = re.search(r'run once, alone: `([^`]+)`', brief)[1]
        self.assertEqual(admitted_command, command)
        return root, worktree, row, row_id, expiry, values['PR URL'], admitted_command

    def hook_decision(self, root, worktree, command, **record_fields):
        state = root / 'state'
        record = state / 'row-reanchor/agent-1.json'
        record.parent.mkdir(parents=True, exist_ok=True)
        record.unlink(missing_ok=True)
        record.write_text(json.dumps({'agent_id': 'agent-1', **record_fields}))
        record.chmod(0o600)
        payload = {'agent_type': 'ship:writer--sol', 'agent_id': 'agent-1', 'cwd': str(worktree),
                   'tool_name': 'Bash', 'tool_input': {'command': command}}
        output = io.StringIO()
        with patch.object(hook, 'STATE', state), contextlib.redirect_stdout(output):
            try:
                hook.pre(payload)
            except SystemExit as error:
                self.assertEqual(error.code, 0)
        return json.loads(output.getvalue())['hookSpecificOutput'] if output.getvalue() else {}

    def test_filled_brief_long_values_and_twelve_word_headroom(self):
        root = '/home/dev/workspaces/p25-warning-race-lane'
        plugin_root = root + '/ultraship/plugins/ship'
        row = root + '/repository/rows/warning-race.toml'
        subject = 'backend/api/agent/warnings/race_window.py'
        base, head = SHARED_VALUES['CI base SHA'], SHARED_VALUES['author head SHA']
        command = documented_command(self.reference, plugin_root, row, 'P25-warning-race', subject, base, head)
        values = {
            **SHARED_VALUES,
            'row ID': 'P25-warning-race', 'PR URL': 'https://github.com/example/repository/pull/7516',
            'verifier name': 'Flow, the chief that drives the P25 acceptance lane',
            'verification time': '2026-11-16T05:30:00.357469375Z',
            'decision file path': root + '/records/decision.md',
            'tool route decision path': root + '/records/tool-route.md',
            'row file path': row, 'subject path': subject, 'job name': 'mutation-anchors · changed anchor guard',
            'job log URL': 'https://github.com/example/repository/actions/runs/19874203156/job/67284901352',
            'subject line range': '212 to 247',
            'review time': '2026-11-16T05:45:00.357469375Z', 'added': '14', 'deleted': '8',
            'tool base reason': 'the CI base, because the row file and the row both exist there',
            'method-only denials': 'one python3 heredoc denial, one script file denial, and one wrapper command denial',
            'denial times': '04:41Z, 04:55Z and 05:12Z',
            'denial record path': root + '/records/denial.jsonl', 'denial record lines': '3, 7 and 12',
            'assigned topic': 'the P25 warning race row re-anchor for pull request 7516',
            'plugin root': plugin_root,
            'rule verifier name': 'Flow, the chief that drives the P25 acceptance lane',
            'rule verification time': '2026-11-16T05:30:00.357469375Z',
            'earlier attempts': 'attempt 1 drew a heredoc denial, attempt 2 a script denial, and attempt 3 an output contract refusal',
            'attempt record path': root + '/records/attempt.jsonl', 'expiry time': '2026-11-16T09:00:00+00:00',
            'worktree path': root + '/repository', 'tool command': command,
            'return time': '2026-11-16T08:15:00+00:00',
            'decision file name': 'pr7516-p25-reanchor-tool-brief-20261116.md',
        }
        self.assertEqual(set(re.findall(r'<([^>]+)>', self.template)), set(values))
        brief = re.sub(r'<([^>]+)>', lambda match: values[match[1]], self.template)
        text_lint.check(brief, 'peer')
        for placeholder in values:
            with self.subTest(placeholder=placeholder):
                brief = re.sub(r'<([^>]+)>', lambda match: ' '.join(['value'] * 12)
                               if match[1] == placeholder else 'x', self.template)
                text_lint.check(brief, 'peer')

    def test_filled_brief_passes_text_lint_and_command_admission(self):
        root, worktree, row, row_id, expiry, pr, command = self.prepare_admission()
        decision = self.hook_decision(root, worktree, command, pr=pr, row_file=str(row), row_id=row_id, expires_at=expiry)
        self.assertNotEqual(decision.get('permissionDecision'), 'deny', decision)

    def test_scope_mismatch_still_blocks_the_tool_run(self):
        root, worktree, row, row_id, expiry, pr, command = self.prepare_admission()
        other_file = worktree / 'tests/mutation/other.toml'
        other_file.write_text('synthetic')
        for label, fields in (('row ID', {'row_file': str(row), 'row_id': 'P25-other-row'}),
                              ('row file', {'row_file': str(other_file), 'row_id': row_id})):
            with self.subTest(different=label):
                decision = self.hook_decision(root, worktree, command, pr=pr, expires_at=expiry, **fields)
                self.assertEqual(decision.get('permissionDecision'), 'deny', decision)

    def test_template_dispatch_lines(self):
        lines = (
            'Owner helper request: the owner\'s global CLAUDE.md, heading "Helper agents (standing request)", '
            'requests helper agents. Covered role: writer. Topic: <assigned topic>. '
            'Every permission, denial and gate stays in force.\n'
            'Readable files: `<worktree path>`, `<plugin root>/skills/ship/references/owner-decisions.md`, '
            '`<decision file path>`, `<tool route decision path>`, '
            '`<denial record path>`, `<attempt record path>`; every other path is out of scope\n'
            'A hook refusal is final: report it and stop.\n'
            'Never print a key value; never post outside bettergroupinc and miguelrisero.\n'
            'Never chain a glob listing into a write command.'
        )
        first = self.template.split('\n', 1)[0]
        self.assertIn(first + '\n\n' + lines + '\n\nFacts:\n', self.template)

    def test_template_fields_map_to_writer_requirements(self):
        writer = (ROOT / 'plugins/ship/agents/writer--sol.md').read_text()
        requirements = (
            ('Route: lane-derived', 'name this route in the brief'),
            ('Input `<Input UUID>` version <version>, workspace `<workspace UUID>`',
             'Bind full Input/workspace UUIDs, current version, event id/hash, choice, actual owner answer, verifier name, and verification time.'),
            ('<verifier name>', 'verifier name, and verification time'),
            ('<verification time>', 'verifier name, and verification time'),
            ('choice B, answer text null', 'Record selected choice B and `payload.answer.text=null` separately'),
            ('`answer_submitted`, `owner_ui`, `no_answer_yet` false',
             'Require `event_type=answer_submitted`, `actor_kind=owner_ui`, and `payload.no_answer_yet=false`'),
            ('Verify the standing rule event with `get_input` against choice `plugin_rule`',
             'Verify the owner event yourself when you have a `get_input` tool'),
            ('and the access event against choice B.', 'Use `get_input` directly when available'),
            ('Without `get_input`, or on an auth or tool error, use the records above.',
             'Verifier fallback: when you have no `get_input` tool, or the call fails with an auth or tool error'),
            ('Allowlist: row file', 'Require CoC approval of the exact row allowlist before any protected read or edit.'),
            ('CI: run', 'Evidence binds the repository, PR, base SHA, author head SHA, tested merge SHA/tree, CI run ID, attempt, and job ID/name.'),
            ('parents `<CI base SHA>` and `<author head SHA>`', 'The tested merge must contain the recorded base and author head'),
            ('Subject change:', "Require the recorded base/head diff to show that the PR's own subject change breaks each named row."),
            ('Same operation:', 'The CoC reviews the same-operation, same-claim reason'),
            ('Method-only denials:', "After a hook denies only the method of this route's row edit"),
            ('Tool route:', 'When the brief names the sanctioned row re-anchor tool'),
            ('Standing rule:', 'cites this owner rule'),
            ('Standing rule event:', 'records in the brief the full Input UUID, workspace UUID, event id, event hash, `actor_kind`, choice id, and verifier name'),
            ('zero tool runs', 'The tool run is its own single attempt'),
            ("ended only in a tool error under another head's grant",
             'a new CoC grant bound to a different head SHA, one with no used attempt, gets one fresh attempt'),
            ('its SHA256 and `<author head SHA>` in the attempt record',
             "with the grant's CoC decision file, its SHA256 and the head SHA"),
            ('- Attempt record:', "record the tool attempt, with the grant's CoC decision file, its SHA256 and the head SHA, on the brief's attempt record before the run"),
            ('- Worktree:', "with the brief's row file, row ID, subject, base and head"),
            ('- On `REFUSED` or any denial, stop.', 'A tool refusal or hook denial ends the attempt.'),
            ('run once, alone:', 'When the brief names the sanctioned row re-anchor tool, run it once'),
        )
        for field, rule in requirements:
            with self.subTest(field=field):
                self.assertIn(field, self.template)
                self.assertIn(rule, writer)
        standing_event = next(line for line in self.template.splitlines() if line.startswith('- Standing rule event:'))
        self.assertIn('`answer_submitted`', standing_event)
        self.assertIn('`owner_ui`', standing_event)
        self.assertIn('A content, scope or protected-access denial blocks the tool run', self.template)
        self.assertIn('every content, scope or protected-access denial', self.reference)

    def test_carriers_and_admission_flow_link_the_brief(self):
        carriers = [Path('plugins/ship/agents') / name for name in
                    ('writer--sol.md', 'writer--sonnet.md', 'writer--fable52.md', 'driver.md', 'driver--sol.md')]
        carriers.append(Path('plugins/ship/skills/ship/SKILL.md'))
        for carrier in carriers:
            link = ('../skills/ship/' if carrier.parent.name == 'agents' else '')
            link += 'references/owner-decisions.md#row-re-anchor-tool-brief'
            lines = (
                'A brief built from the [row re-anchor tool brief](' + link + ') with every field filled supplies '
                "this route's owner access record, CoC row allowlist, CI and source binding, and method-only denial evidence; "
                'verify each field, use `get_input` when available, and refuse a missing or mismatched field.\n'
                'The tool run is its own single attempt under one CoC grant and its head SHA: '
                'an earlier attempt on the row that made zero native Edit calls and zero tool runs, '
                'and drew only the listed method-only shell denials, leaves it unused, '
                'even when its record marks that attempt consumed; any native Edit call on the row, '
                'any tool run, and any refusal or hook denial of the tool command uses it; '
                'a new CoC grant bound to a different head SHA, one with no used attempt, gets one fresh attempt '
                'only when every earlier used attempt on the row ended only in a tool error, '
                'such as no match or a changed file, with no hook refusal, hook denial or `REFUSED`; '
                'a second grant for a head that already used its attempt frees nothing; '
                "record the tool attempt, with the grant's CoC decision file, its SHA256 and the head SHA, "
                "on the brief's attempt record before the run."
            )
            text = (ROOT / carrier).read_text()
            with self.subTest(carrier=carrier):
                self.assertIn(lines, text)
                route = text.split('#### Lane-derived route\n', 1)[1]
                route = re.split(r'\n#{1,4} ', route, maxsplit=1)[0]
                self.assertIn('A tool refusal or hook denial ends the attempt.', route)
        self.assertIn('9. Send the exact scoped brief, built from the [row re-anchor tool brief]'
                      '(#row-re-anchor-tool-brief), with SendMessage.', self.reference)
        self.assertIn('The [row re-anchor tool brief](#row-re-anchor-tool-brief) lists the fields that supply this evidence; '
                      'the tool run is its own single attempt under one CoC grant and its head SHA, '
                      'unused by an earlier attempt that made zero native Edit calls and zero tool runs, '
                      'and used by any native Edit call on the row, any tool run, '
                      'and any refusal or hook denial of the tool command. '
                      'A new CoC grant bound to a different head SHA, one with no used attempt, gets one fresh attempt '
                      'only when every earlier used attempt on the row ended only in a tool error, '
                      'with no hook refusal, hook denial or `REFUSED`; '
                      'a second grant for a head that already used its attempt frees nothing.', self.reference)


if __name__ == '__main__':
    unittest.main()
