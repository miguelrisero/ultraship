"""Regression cases: precise hook matchers deny protected actions and let harmless commands through."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ultraship_precise', ROOT / 'plugins/ship/hooks/ultraship.py')
ultraship = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ultraship)
PLUGIN = ROOT / 'plugins/ship'


class PreciseMatcherTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.home = Path(temporary).resolve()
        self.cwd = self.home / 'ws'
        self.cwd.mkdir()
        self.enterContext(patch.dict(os.environ, {'HOME': str(self.home)}))
        os.environ.pop('XDG_STATE_HOME', None)
        self.enterContext(patch.object(ultraship.pwd, 'getpwuid', return_value=SimpleNamespace(pw_dir=str(self.home))))
        self.enterContext(patch.object(ultraship, 'STATE', self.home / '.local/state/ultraship'))

    def decide(self, command=None, agent_type='', tool='Bash', tool_input=None):
        output = io.StringIO()
        event = {'cwd': str(self.cwd), 'session_id': 'precise', 'agent_type': agent_type, 'tool_name': tool,
                 'tool_input': tool_input if tool_input is not None else {'command': command}}
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            try:
                ultraship.guarded_pre(event)
            except SystemExit as error:
                self.assertEqual(error.code, 0)
        text = output.getvalue()
        return json.loads(text)['hookSpecificOutput'] if text else {}

    def assert_allowed(self, command, agent_type='', advisory=False):
        result = self.decide(command, agent_type)
        self.assertNotIn('permissionDecision', result, (command, result))
        self.assertEqual('additionalContext' in result, advisory, (command, result))

    def assert_denied(self, command, agent_type='', start=''):
        result = self.decide(command, agent_type)
        self.assertEqual(result.get('permissionDecision'), 'deny', (command, result))
        self.assertTrue(result['permissionDecisionReason'].startswith(start), result)

    def test_01_grep_names_helper(self):
        self.assert_allowed(f'grep -rn "thread_reply" {PLUGIN}/skills/')

    def test_02_build_then_node_test(self):
        self.assert_allowed('npm run build && node --test scripts/test-service-examples.mjs')

    def test_03_heredoc_note_names_hook_words(self):
        self.assert_allowed(f"cat > {self.cwd}/.scratch/x.md <<'EOF'\n"
                            'The text_lint custody rule refused ultraship.py once.\nEOF\n')

    def test_04_grep_then_gh_read(self):
        self.assert_allowed('grep -n "shell runner names gh" notes.md; '
                            'gh pr view 214 --repo miguelrisero/ultraship --json state')

    def test_05_list_state_parent_and_cache_versions(self):
        self.assert_allowed('ls ~/.local/state/ultraship/')
        self.assert_allowed('ls -d ~/.claude/plugins/cache/ultraship/ship/*')

    def test_06_diff_piped_to_awk(self):
        self.assert_allowed(r"gh pr diff 214 --repo miguelrisero/ultraship | awk '/ultraship\.py$/' | head")

    def test_07_loop_with_unresolved_operand_warns(self):
        self.assert_allowed('for r in a b; do python3 -I $J sample "$r" 7; done', advisory=True)

    def test_08_integration_make_warns(self):
        command = ('env -i HOME=/home/user PATH="$UVBIN:/usr/bin:/bin" make api-test-integration '
                   'PYTEST_INTEGRATION_ARGS="tests/integration/x.py::test_y"')
        self.assert_allowed(command, advisory=True)

    def test_09_graphql_thread_read(self):
        self.assert_allowed("gh api graphql -f query='query{repository(owner:\"o\",name:\"r\"){pullRequest(number:1)"
                            "{reviewThreads(first:50){nodes{id}}}}}'", agent_type='ship:driver')

    def test_09_graphql_reads_with_variables(self):
        for command in ('gh api graphql -f query=\'query($id:ID!){node(id:$id){id}}\' -F id="$THREAD"',
                        "gh api graphql --paginate -f query='query($endCursor:String){viewer{repositories"
                        "(first:10,after:$endCursor){nodes{name}}}}'"):
            with self.subTest(command=command):
                self.assertNotEqual(self.decide(command, 'ship:driver').get('permissionDecision'), 'deny')

    def test_10_store_read_and_hook_run_deny(self):
        for agent_type in ('', 'ship:driver'):
            with self.subTest(agent_type=agent_type):
                self.assert_denied('cat ~/.local/state/ultraship/text-lint/key', agent_type,
                                   'Only the text_lint hook reads or writes refusal receipts')
                self.assert_denied(f'python3 {PLUGIN}/hooks/ultraship.py pre', agent_type,
                                   'Only the text_lint hook reads or writes refusal receipts')
                self.assert_denied('cd ~/.local/state/ultraship && cat text-lint/key', agent_type,
                                   'Only the text_lint hook reads or writes refusal receipts')

    def test_11_graphql_thread_mutation_denies(self):
        for agent_type in ('', 'ship:driver'):
            with self.subTest(agent_type=agent_type):
                self.assert_denied("gh api graphql -f query='mutation{resolveReviewThread(input:{threadId:\"x\"})"
                                   "{thread{isResolved}}}'", agent_type, 'Ship replies to and resolves review threads')

    def test_mutation_name_as_search_data(self):
        self.assert_allowed(r"rg -n 'resolveReviewThread\|gh.*api' thread_reply.py")

    def test_unparsed_shape_with_api_write_denies(self):
        self.assert_denied('gh pr view 1 | sed -n 1p; gh api -X POST repos/o/r/issues/1/comments -f body=$B',
                           start='Ship replies to and resolves review threads')

    def reviewer_grep(self, **fields):
        return self.decide(agent_type='ship:reviewer--sol', tool='Grep',
                           tool_input={'pattern': 'needle', 'path': str(self.cwd / 'repo'), **fields})

    def test_reviewer_search_above_rows_excludes_them(self):
        rows = self.cwd / 'repo/backend/tests/mutation'
        rows.mkdir(parents=True)
        (rows / 'rows.py').write_text('x')
        result = self.reviewer_grep()
        self.assertEqual(result.get('permissionDecision'), 'allow', result)
        self.assertEqual(result['updatedInput']['glob'], ultraship.ROW_EXCLUSION)
        self.assertEqual(result['updatedInput']['path'], str(self.cwd / 'repo'))
        self.assertNotIn('permissionDecision', self.reviewer_grep(glob=ultraship.ROW_EXCLUSION))
        self.assertNotIn('permissionDecision', self.reviewer_grep(glob='*.toml'))
        self.assertEqual(self.reviewer_grep(glob='*.py').get('permissionDecision'), 'deny')
        self.assertEqual(self.decide(agent_type='ship:reviewer--sol', tool='Read', tool_input={
            'file_path': str(rows / 'rows.py')}).get('permissionDecision'), 'deny')


if __name__ == '__main__':
    unittest.main()
