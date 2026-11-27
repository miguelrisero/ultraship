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


BASE = '9e14c2f80a6d37b5914e08c2d6f7a3b9051ce824'
HEAD = 'a38d91e5c7b204f6d819ec03a7f52b6084de19c2'


def documented_command(reference, plugin_root, row, row_id, subject, base, head):
    documented = re.search(r'Use exactly `([^`]+)`', reference.split('## Row re-anchor tool admission record\n', 1)[1])[1]
    command = documented.replace('<plugin root>', plugin_root).replace('<absolute path>', str(row))
    command = command.replace('<id>', row_id).replace('<repository-relative path>', subject)
    command = command.replace('<ref>', base, 1).replace('<ref>', head, 1)
    return command


class BriefTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop('SHIP_LINT_OFF', None)

        self.reference = REFERENCE.read_text()
        section = self.reference.split('## Row re-anchor tool brief\n', 1)[1].split('\n## ', 1)[0]
        self.template = section.split('```text\n', 1)[1].split('\n```', 1)[0]

    def fill(self, worktree, row, row_id, expiry, pr, command):
        values = {
            'row ID': row_id, 'PR URL': pr, 'row file path': str(row),
            'subject path': 'src/warning.py', 'subject commit SHA': HEAD,
            'run ID': '19874203156', 'count': '0', 'expected': '1', 'base SHA': BASE,
            'worktree path': str(worktree), 'head SHA': HEAD,
            'admission record path': str(worktree / 'state/row-reanchor/agent-1.json'),
            'expiry time': expiry, 'tool command': command,
            'driver': 'Coordinator', 'return time UTC': '2026-11-16T11:00:00Z',
        }
        self.assertEqual(set(re.findall(r'<([^>]+)>', self.template)), set(values))
        return re.sub(r'<([^>]+)>', lambda match: values[match[1]], self.template)

    def prepare_admission(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        root = Path(os.path.realpath(temporary))
        worktree = root / 'worktree'
        row = worktree / 'tests/mutation/rows.toml'
        row.parent.mkdir(parents=True)
        row.write_text('synthetic')
        row_id, subject = 'P25-warning-race', 'src/warning.py'
        plugin_root = str(ROOT / 'plugins/ship')
        command = documented_command(self.reference, plugin_root, row, row_id, subject, BASE, HEAD)
        self.assertEqual(command, 'python3 -I ' + str(TOOL) + ' --row-file ' + str(row)
                         + ' --row-id ' + row_id + ' --subject ' + subject + ' --base ' + BASE + ' --head ' + HEAD)
        expiry = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() + 3600))
        pr = 'https://github.com/example/repo/pull/25'
        brief = self.fill(worktree, row, row_id, expiry, pr, command)
        self.assertNotIn('<', brief)
        text_lint.check(brief, 'peer')
        self.assertIsNone(re.search(r'^\s*(old|new)\s*=', brief, re.M))
        self.assertFalse(any(line.startswith('[') for line in brief.splitlines()))
        (admitted_command,) = re.findall(r'Run once, alone: `([^`]+)`', brief)
        self.assertEqual(admitted_command, command)
        return root, worktree, row, row_id, expiry, pr, admitted_command

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
        worktree = Path('/home/dev/workspaces/p25-warning-race-lane/repository')
        row = worktree / 'tests/mutation/rows/warning-race.toml'
        command = documented_command(self.reference, '/home/dev/workspaces/ultraship/plugins/ship',
                                     row, 'P25-warning-race', 'src/warning.py', BASE, HEAD)
        brief = self.fill(worktree, row, 'P25-warning-race', '2026-11-16T09:00:00Z',
                          'https://github.com/example/repository/pull/7516', command)
        text_lint.check(brief, 'peer')
        for placeholder in set(re.findall(r'<([^>]+)>', self.template)):
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

    def test_template_keeps_exact_scope_and_reports_the_outcome(self):
        for requirement in (
            'Re-anchor row `<row ID>` of `<PR URL>` under the lane-owned row route.',
            'Authority: the owner\'s global CLAUDE.md, heading "CoC decisions (standing grant)".',
            'Row file: `<row file path>`.',
            'Subject: `<subject path>` at commit `<subject commit SHA>`.',
            'CI: run `<run ID>` found `<count>` anchors and expected `<expected>`.',
            'Base: `<base SHA>`.',
            'Worktree: `<worktree path>` at head `<head SHA>`.',
            'Admission record: `<admission record path>`, expires at `<expiry time>`.',
            'Read the standing grant directly.',
            'Verify each binding before running the tool.',
            'Count a pre-start hook refusal as zero runs only with verified per-row evidence.',
            'After that denial, the writer may retry once in a compliant form; the driver re-dispatches it.',
            'The decision-defect rule requires a CoC decision defect as the sole stated cause, with zero bytes written and zero commits.',
            'After the writer verifies the frozen corrected decision under that rule, the refused attempt counts as zero runs.',
            'The writer gets one new attempt under the corrected decision.',
            'The driver re-dispatches it with a fresh admission record.',
            'Commit only the row file on success.',
            'Keep the row pending on a refusal.',
            'Report the refusal to the driver.',
            'Return the tool output, the generated authorization record path and the commit SHA',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.template)
        self.assertIn('Keep all row TOML text and pair bytes out of the brief.', self.reference)
        self.assertIn("Apply the [helper standing request](#helper-standing-request) and the brief's routing and output contracts.", self.reference)
        self.assertIn('Include the global grant and this reference in `Readable files`.', self.reference)

    def test_carriers_and_admission_flow_link_the_brief(self):
        carriers = [Path('plugins/ship/agents') / name for name in
                    ('driver.md', 'driver--sol.md')]
        link = '../skills/ship/references/owner-decisions.md#row-re-anchor-tool-admission-record'
        for carrier in carriers:
            text = (ROOT / carrier).read_text()
            with self.subTest(carrier=carrier):
                self.assertIn(f'Admit the writer with the [row re-anchor tool admission record]({link}).', text)
        admission = self.reference.split('## Row re-anchor tool admission record\n', 1)[1].split('\n## ', 1)[0]
        self.assertIn('Send the [row re-anchor tool brief](#row-re-anchor-tool-brief) with SendMessage.', admission)
        self.assertIn('The record grants zero protected access or edit authority by itself.', admission)


if __name__ == '__main__':
    unittest.main()
