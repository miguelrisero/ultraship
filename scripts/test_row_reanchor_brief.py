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


class BriefTests(unittest.TestCase):
    def setUp(self):
        self.reference = REFERENCE.read_text()
        section = self.reference.split('## Row re-anchor tool brief\n', 1)[1].split('\n## ', 1)[0]
        self.template = section.split('```text\n', 1)[1].split('\n```', 1)[0]

    def test_filled_brief_passes_text_lint_and_command_admission(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        root = Path(os.path.realpath(temporary))
        worktree = root / 'worktree'
        row = worktree / 'tests/mutation/rows.toml'
        row.parent.mkdir(parents=True)
        row.write_text('synthetic')
        base, head = '9e14c2f80a6d37b5914e08c2d6f7a3b9051ce824', 'a38d91e5c7b204f6d819ec03a7f52b6084de19c2'
        row_id, subject = 'P25-warning-race', 'src/warning.py'
        command = ('python3 -I ' + str(TOOL) + ' --row-file ' + str(row)
                   + ' --row-id ' + row_id + ' --subject ' + subject + ' --base ' + base + ' --head ' + head)
        expiry = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() + 3600))
        values = {
            'row ID': row_id, 'PR URL': 'https://github.com/example/repo/pull/25',
            'Input UUID': 'f39a1c87-62de-4b09-a153-7cd02e8916ab', 'version': '1',
            'workspace UUID': 'e17d0c39-84a1-4f6b-b205-9c73a8de621f',
            'event ID': '7c9e01a4-d628-43fb-9a16-0e8b27d5c391',
            'event hash': '3b8f14e29cd065a781b9e40c6f2a8d3174e95bc0a6d723f8c109b5e467a2d8c3',
            'verifier name': 'Coordinator', 'verification time': '2026-11-16T10:00:00Z',
            'decision file path': str(root / 'decision.md'), 'decision file SHA256': 'c8' * 32,
            'row file path': str(row), 'subject path': subject, 'run ID': '19874203156',
            'attempt': '1', 'job ID': '67284901352', 'job name': 'Anchor validation',
            'job log URL': 'https://github.com/example/repo/actions/runs/19874203156/job/67284901352',
            'count': '0', 'expected': '1', 'tested merge SHA': 'b4' * 20,
            'tested merge tree SHA': 'c5' * 20, 'CI base SHA': base, 'author head SHA': head,
            'added': '4', 'deleted': '2', 'tool base SHA': base, 'tool base reason': 'the CI base',
            'hook': 'the shell hook', 'method': 'a heredoc', 'denial time': '2026-11-16T10:01:00Z',
            'denial record path': str(root / 'denial.jsonl'), 'denial record line': '8',
            'earlier attempts': 'one native Edit attempt', 'attempt record path': str(root / 'attempt.jsonl'),
            'expiry time': expiry, 'worktree path': str(worktree), 'tool command': command,
            'commit subject': 'test: re-anchor warning race', 'return time': '2026-11-16T11:00:00Z',
            'decision file name': 'decision.md',
        }
        brief = re.sub(r'<([^>]+)>', lambda match: values[match[1]], self.template)
        self.assertNotIn('<', brief)
        text_lint.check(brief, 'peer')
        self.assertIsNone(re.search(r'^\s*(old|new)\s*=', brief, re.M))
        self.assertFalse(any(line.startswith('[') for line in brief.splitlines()))
        admitted_command = re.search(r'run once, alone: `([^`]+)`', brief)[1]
        self.assertEqual(admitted_command, command)
        state = root / 'state'
        record = state / 'row-reanchor/agent-1.json'
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({'pr': values['PR URL'], 'agent_id': 'agent-1',
                                     'row_file': str(row), 'row_id': row_id, 'expires_at': expiry}))
        record.chmod(0o600)
        payload = {'agent_type': 'ship:writer--sol', 'agent_id': 'agent-1', 'cwd': str(worktree),
                   'tool_name': 'Bash', 'tool_input': {'command': admitted_command}}
        output = io.StringIO()
        with patch.object(hook, 'STATE', state), contextlib.redirect_stdout(output):
            try:
                hook.pre(payload)
            except SystemExit as error:
                self.assertEqual(error.code, 0)
        decision = json.loads(output.getvalue())['hookSpecificOutput'] if output.getvalue() else {}
        self.assertNotEqual(decision.get('permissionDecision'), 'deny', decision)

    def test_template_fields_map_to_writer_requirements(self):
        writer = (ROOT / 'plugins/ship/agents/writer--sol.md').read_text()
        requirements = (
            ('Route: lane-derived', 'name this route in the brief'),
            ('Input `<Input UUID>` version <version>, workspace `<workspace UUID>`',
             'Bind full Input/workspace UUIDs, current version, event id/hash, choice, actual owner answer, verifier name, and verification time.'),
            ('choice B, answer text null', 'Record selected choice B and `payload.answer.text=null` separately'),
            ('`answer_submitted`, `owner_ui`, `no_answer_yet` false',
             'Require `event_type=answer_submitted`, `actor_kind=owner_ui`, and `payload.no_answer_yet=false`'),
            ('Verify the owner event with `get_input` when you have it', 'Use `get_input` directly when available'),
            ('Allowlist: row file', 'Require CoC approval of the exact row allowlist before any protected read or edit.'),
            ('CI: run', 'Evidence binds the repository, PR, base SHA, author head SHA, tested merge SHA/tree, CI run ID, attempt, and job ID/name.'),
            ('parents `<CI base SHA>` and `<author head SHA>`', 'The tested merge must contain the recorded base and author head'),
            ('Subject diff', "Require the recorded base/head diff to show that the PR's own subject change breaks each named row."),
            ('Method-only denial:', "After a hook denies only the method of this route's row edit"),
            ('the tool attempt is unused', 'The tool run is its own single attempt'),
            ('run once, alone:', 'When the brief names the sanctioned row re-anchor tool, run it once'),
        )
        for field, rule in requirements:
            with self.subTest(field=field):
                self.assertIn(field, self.template)
                self.assertIn(rule, writer)

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
                'The tool run is its own single attempt: an earlier native Edit attempt on the row that applied no edit '
                "leaves it unused; record the tool attempt on the brief's attempt record before the run."
            )
            with self.subTest(carrier=carrier):
                self.assertIn(lines, (ROOT / carrier).read_text())
        self.assertIn('9. Send the exact scoped brief, built from the [row re-anchor tool brief]'
                      '(#row-re-anchor-tool-brief), with SendMessage.', self.reference)
        self.assertIn('The [row re-anchor tool brief](#row-re-anchor-tool-brief) lists the fields that supply this evidence; '
                      'the tool run is its own single attempt, unused by an earlier native Edit attempt that applied no edit.',
                      self.reference)


if __name__ == '__main__':
    unittest.main()
