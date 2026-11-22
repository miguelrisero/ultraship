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

    def test_07_loop_with_unresolved_interpreter_operand_denies(self):
        # The variable could hold the hook path, so an unresolved interpreter operand stays fail-closed.
        self.assert_denied('for r in a b; do python3 -I $J sample "$r" 7; done',
                           start='Only the text_lint hook reads or writes refusal receipts')
        self.assert_allowed('for r in a b; do python3 -I tools/sample.py "$r" 7; done')

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

    def test_fail_closed_1_unreadable_text_that_can_build_gh(self):
        self.assert_denied("bash -c 'gh pr view 7'", start='Ship replies to and resolves review threads')
        for command in ("printf '%s' $'\\x67h' | sh", 'X=1; eval "$CMD" pr comment 1 --body x'):
            with self.subTest(command=command):
                # Custody or the obfuscation rule may refuse first; either way the call is denied.
                self.assert_denied(command)

    def test_fail_closed_2_graphql_extra_query_or_mutation_field(self):
        for command in ("gh api graphql -f query='query{viewer{login}}' -f query='mutation{x}'",
                        "gh api graphql -f query='query($m:String){viewer{login}}' -f m='mutation{x}'"):
            with self.subTest(command=command):
                self.assert_denied(command, 'ship:driver', 'Ship replies to and resolves review threads')

    def test_fail_closed_3_state_root_expansions(self):
        for command in ('cat ~/.local/state/ultraship/te*/key', 'cd "$XDG_STATE_HOME" && cat ultraship/x',
                        'ls ~/.local/sta{te,x}/ultraship'):
            with self.subTest(command=command):
                self.assert_denied(command, start='Only the text_lint hook reads or writes refusal receipts')

    def test_fail_closed_4_hook_name_without_interpreter(self):
        for command in (f'cp {PLUGIN}/hooks/ultraship.py ./copy.py', '$RUN hooks/ultraship.py pre',
                        f'printf %s {PLUGIN}/hooks/ultraship.py'):
            with self.subTest(command=command):
                self.assert_denied(command, start='Only the text_lint hook reads or writes refusal receipts')

    def test_fail_closed_5_program_running_reader_options(self):
        for command in ("sed 's/x/resolveReviewThread/e' notes.txt", 'rg --pre=sh resolveReviewThread notes.txt',
                        'sort --compress-program=sh resolveReviewThread', 'sort --compress-prog=sh resolveReviewThread',
                        'git grep --open-f resolveReviewThread', 'git grep -nO resolveReviewThread',
                        'rg -e -- --pre=sh resolveReviewThread notes.txt', 'git grep -e -- --open-f resolveReviewThread',
                        'rg --hostname-bin=sh resolveReviewThread notes.txt'):
            with self.subTest(command=command):
                self.assert_denied(command, start='Ship replies to and resolves review threads')

    def test_fail_closed_review_round_two(self):
        custody = 'Only the text_lint hook reads or writes refusal receipts'
        for command in ('H=$HOME/.claude/plugins/cache/x/ship/1/hooks/ultra; python3 "${H}ship.py" pre',
                        "python3 \"$(find ~/.claude/plugins/cache -name 'ultra*.py' | head -n1)\" pre",
                        'ls ~/.local/state/ultraship; cat "$_/text-lint/key"',
                        'P=$HOME/.local/state/ultra; cat "${P}ship/text-lint/key"',
                        f'cp {PLUGIN}/hooks/ultraship.py {PLUGIN}/hooks/u.py && python3 {PLUGIN}/hooks/u.py pre',
                        'cd ~ && cat .lo*/st*/ul*/te*/key',
                        f'cd / && cat {str(self.home.parent)[1:]}/*/.lo*/st*/ul*/te*/key',
                        "grep -r '' ~/.loc*"):
            with self.subTest(command=command):
                self.assert_denied(command, start=custody)
        self.assert_denied("gh api graphql -f query='query($id:ID!){node(id:$id){id}}' -F id=@notes.txt",
                           'ship:driver', 'Ship replies to and resolves review threads')

    def test_hook_folder_glob_denies_unless_listed(self):
        installed = self.home / '.claude/plugins/cache/x/ship/1/hooks/ultraship.py'
        with patch.object(ultraship, '__file__', str(installed)):
            for command in ("sed -i 's/^/#/' ~/.claude/plugins/cache/*/ship/*/hooks/u*.py",
                            'cp ~/.claude/plugins/cache/*/ship/*/hooks/u*.py z.py && python3 z.py pre'):
                with self.subTest(command=command):
                    self.assert_denied(command, start='Only the text_lint hook reads or writes refusal receipts')
            self.assert_allowed('ls ~/.claude/plugins/cache/*/ship/*/hooks/u*.py', advisory=True)

    def test_fail_closed_review_round_three(self):
        installed = self.home / '.claude/plugins/cache/x/ship/1/hooks/ultraship.py'
        with patch.object(ultraship, '__file__', str(installed)):
            for command in ('cd && cd .local && cd state && cd ultraship && cd account-grants && cat *',
                            'cd .local; cd state; cd ultraship; cd text\\-lint; cat key',
                            'cd ~/.claude/plugins/cache/x/ship/1/hooks && ./u*.py pre',
                            'cd ~/.claude/plugins/cache/x/ship/1 && hoo?s/ultra*.py pre',
                            'touch api graphql; /usr/bin/g? a[p]i gr[a]phql -F query=@q.txt',
                            'cd ~/.claude/plugins/cache/x/ship/1 && cd hooks && sed -i s/a/b/ u*.py',
                            'cd ~/.claude/plugins/cache/x/ship/1 && cd hooks && cp u*.py /tmp/z.py',
                            'grep -r . ~/.local', 'grep -r . ~', 'cd ~; grep -r . .local', 'cd "$D" && cat key'):
                with self.subTest(command=command):
                    self.assert_denied(command, 'ship:driver')
        self.assert_allowed('cd repo && git status')

    def test_any_program_but_a_listing_denies_a_parent_of_a_store(self):
        for command in ('grep -d recurse . ~/.local', 'grep --directories=recurse . ~', 'grep --recur . ~/.local',
                        'find ~/.local -type f', 'du -a ~/.local/state', 'tree ~/.local/state', 'ag . ~/.local',
                        'ugrep . ~/.local', 'git grep --no-index . ~/.local', 'ls --recur ~/.local', 'ls -lR ~'):
            with self.subTest(command=command):
                self.assert_denied(command, start='Only the text_lint hook reads or writes refusal receipts')
        self.assert_allowed('ls -la ~/.local/state')

    def test_cd_variable_resolves_only_through_one_earlier_literal(self):
        for command in ('D=/tmp; D=~/.local/state/ultraship/text-lint; cd "$D" && cat key',
                        'cd "$D" && cat key; D=/tmp',
                        'D=/tmp; for D in ~/.local/state/ultraship/text-lint; do cd "$D"; cat key; done',
                        'D=/tmp; read D; cd "$D" && cat key', 'D=/tmp; declare D; cd "$D" && cat key'):
            with self.subTest(command=command):
                self.assert_denied(command, start='Only the text_lint hook reads or writes refusal receipts')
        self.assert_allowed('D=/tmp/x; cd "$D" && git status')

    def test_cdpath_makes_a_relative_cd_unreadable(self):
        self.assert_denied('CDPATH=~/.local/state/ultraship cd text-lint && cat key',
                           start='Only the text_lint hook reads or writes refusal receipts')
        with patch.dict(os.environ, {'CDPATH': str(self.home / '.local/state/ultraship')}):
            self.assert_denied('cd text-lint && cat key', start='Only the text_lint hook reads or writes refusal receipts')
        self.assert_allowed('cd repo && git status')

    def test_relative_cd_after_the_repository_top_folder_denies(self):
        self.assert_denied('cd "$(git rev-parse --show-toplevel)" && cd .local/state/ultraship/text-lint && cat key',
                           start='Only the text_lint hook reads or writes refusal receipts')
        self.assert_allowed('cd "$(git rev-parse --show-toplevel)" && git status')

    def test_cd_double_dash_reads_the_next_word(self):
        for command in ('cd -- ~/.local/state/ultraship/text-lint && cat key', 'cd -- && cat key',
                        'cd -- -x && cat key'):
            with self.subTest(command=command):
                self.assert_denied(command, start='Only the text_lint hook reads or writes refusal receipts')
        self.assert_allowed('cd -- repo && git status')
        for command in ('cd -- .. && cd -- .local && cd -- state && cd -- ultraship && cd -- account-grants && cat key',
                        'cd -P .. && cd -L .local/state/ultraship/text-lint && cat key',
                        'CDPATH=.. cd .local && cd state && cd ultraship && cd account-grants && cat key'):
            with self.subTest(command=command):
                self.assert_denied(command, start='Only the text_lint hook reads or writes refusal receipts')

    def test_unparsable_text_with_a_path_or_directory_change_denies(self):
        for command in ("cd ..; cd .local; cd state; cd ultraship; cd account-grants; cat key; cat <<'EOF'\nordinary\n",
                        "cd ..; cat .lo*/st*/ul*/ac*/key; cat <<'EOF'\nordinary\n",
                        "cat ../.local/state/ultraship/account-grants/key\necho 'x"):
            with self.subTest(command=command):
                self.assert_denied(command, start='Only the text_lint hook reads or writes refusal receipts')

    def test_run_time_file_operand_denies(self):
        for command in ("p=$(printf '%s/.%s/%s/%s/%s' .. local state ultraship account-grants key); cat \"$p\"",
                        "cat \"$(printf '%s/.%s/%s/%s/%s' .. local state ultraship account-grants key)\"",
                        'f=`cat name.txt`; head "$f"', 'cat `cat name.txt`'):
            with self.subTest(command=command):
                self.assert_denied(command, start='Only the text_lint hook reads or writes refusal receipts')
        self.assert_allowed('f=notes.md; cat "$f"')
        self.assert_allowed("grep -e '$X' notes.md")

    def test_reviewer_globs_split_on_any_whitespace(self):
        rows = self.cwd / 'repo/backend/tests/mutation'
        rows.mkdir(parents=True)
        (rows / 'rows.py').write_text('x')
        self.assertEqual(ultraship.glob_pieces(['a\tb,c\nd']), ['a', 'b', 'c', 'd'])
        for glob in ('*.toml\t*.py', '!**/tests/mutation/**\n*.py', '*.toml\x0b../x'):
            with self.subTest(glob=glob):
                self.assertEqual(self.reviewer_grep(glob=glob).get('permissionDecision'), 'deny')

    def test_plugin_update_commands_name_ultraship_without_a_store(self):
        for command in ('claude plugin marketplace update ultraship', 'claude plugin update ship@ultraship'):
            with self.subTest(command=command):
                self.assert_allowed(command)

    def test_reviewer_brace_and_unusual_character_globs_deny(self):
        rows = self.cwd / 'repo/backend/tests/mutation'
        rows.mkdir(parents=True)
        (rows / 'rows.py').write_text('x')
        for glob in ('{!**/tests/mutation/**,x}', '!**/tests/mutation/** !}x,*.py', 'x{', '*.{ts,tsx}',
                     'foo﻿*.py', '!**/tests/mutation/**\x1f!x', '!**/tests/mutation/**\x85!x'):
            with self.subTest(glob=glob):
                self.assertEqual(self.reviewer_grep(glob=glob).get('permissionDecision'), 'deny')

    def test_reviewer_row_globs_that_can_reach_rows_deny(self):
        rows = self.cwd / 'repo/backend/tests/mutation'
        rows.mkdir(parents=True)
        (rows / 'rows.py').write_text('x')
        for glob in ('!tests/mutation', 'rows\\.py', '[^x]*', '/backend/**', '/rows.py',
                     'a/**,backend/tests/mutation/**', '*.toml,*.py', '!**/tests/mutation/**,*.py',
                     '{!**/tests/mutation/**,x}', '{x,!**/tests/mutation/**}'):
            with self.subTest(glob=glob):
                self.assertEqual(self.reviewer_grep(glob=glob).get('permissionDecision'), 'deny')

    def test_grant_refusal_after_checks_prints_one_document(self):
        output = io.StringIO()
        event = {'cwd': str(self.cwd), 'session_id': 'precise', 'agent_type': '', 'tool_name': 'Bash',
                 'tool_input': {'command': 'ls ~/.local/state/ultraship/'}}
        with (patch.object(ultraship, 'pre_output', return_value={'hookEventName': 'PreToolUse',
                                                                  'additionalContext': 'S2: x'}),
              patch.object(ultraship, 'issue_' + 'account_grant', side_effect=lambda _: ultraship.deny('refused')),
              redirect_stdout(output), redirect_stderr(io.StringIO())):
            with self.assertRaises(SystemExit):
                ultraship.guarded_pre(event)
        self.assertEqual(json.loads(output.getvalue())['hookSpecificOutput']['permissionDecision'], 'deny')

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
