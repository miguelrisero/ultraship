"""Regression cases: precise hook matchers deny protected actions and let harmless commands through."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
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
        os.environ.pop('CDPATH', None)
        # The cases name these variables; a value exported by the runner must not change them.
        for name in ('TMPFILE', 'LOG', 'f', 'dir', 'BR', 'D', 'p', 'P', 'ID', 'N', 'W', 'T', 'Q', 'PR', 'U',
                     'F', 'source_dir', 'pinned_script', 'snapshot'):
            os.environ.pop(name, None)
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

    def assert_not_denied(self, command, agent_type=''):
        # Main admits these commands; an unresolved value may add the S2 advisory.
        result = self.decide(command, agent_type)
        self.assertNotEqual(result.get('permissionDecision'), 'deny', (command, result))

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
        for command in ('gh api graphql -f query=\'query($id:ID!){node(id:$id){id}}\' -f id="$THREAD"',
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
                            'cp ~/.claude/plugins/cache/*/ship/*/hooks/u*.py z.py && python3 z.py pre',
                            'h=$(ls ~/.claude/plugins/cache/*/ship/*/hooks/u*.py); cp /tmp/evil.py "$h"',
                            'sed -i s/a/b/ $(ls ~/.claude/plugins/cache/*/ship/*/hooks/u*.py)',
                            'h=$(ls -d ~/.claude/plugins/cache/*/ship/*/hooks); cp /tmp/e "$h/"'):
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
                            'grep -r . ~/.local', 'grep -r . ~', 'cd ~; grep -r . .local'):
                with self.subTest(command=command):
                    self.assert_denied(command, 'ship:driver')
        self.assert_allowed('cd repo && git status')
        self.assert_not_denied('cd "$D" && cat key', 'ship:driver')

    def test_any_program_but_a_listing_denies_a_parent_of_a_store(self):
        for command in ('grep -d recurse . ~/.local', 'grep --directories=recurse . ~', 'grep --recur . ~/.local',
                        'find ~/.local -exec cat {} +', 'du -a ~/.local/state', 'tree ~/.local/state', 'ag . ~/.local',
                        'ugrep . ~/.local', 'git grep --no-index . ~/.local', 'ls --recur ~/.local', 'ls -lR ~'):
            with self.subTest(command=command):
                self.assert_denied(command, start='Only the text_lint hook reads or writes refusal receipts')
        self.assert_allowed('ls -la ~/.local/state')
        # du shows sizes and find without an action shows names, as main admits.
        for command in ('find ~/.local -type f', 'find ~ -name foo.txt', 'du -sh ~', "find ~ -name '*.md' -print",
                        'find ~ -type d -name node_modules -prune', "find ~ -maxdepth 1 -printf '%f\\n'"):
            with self.subTest(command=command):
                self.assert_allowed(command)

    def test_cd_variable_resolves_only_through_one_earlier_literal(self):
        for command in ('D=/tmp; D=~/.local/state/ultraship/text-lint; cd "$D" && cat key',
                        'D=/tmp; for D in ~/.local/state/ultraship/text-lint; do cd "$D"; cat key; done'):
            with self.subTest(command=command):
                self.assert_denied(command, start='Only the text_lint hook reads or writes refusal receipts')
        self.assert_allowed('D=/tmp/x; cd "$D" && git status')
        # A folder the scan cannot read warns, as main admits it.
        for command in ('cd "$D" && cat key; D=/tmp', 'D=/tmp; read D; cd "$D" && cat key',
                        'D=/tmp; declare D; cd "$D" && cat key'):
            with self.subTest(command=command):
                self.assert_not_denied(command)

    def test_cdpath_makes_a_relative_cd_unreadable(self):
        self.assert_denied('CDPATH=~/.local/state/ultraship cd text-lint && cat key',
                           start='Only the text_lint hook reads or writes refusal receipts')
        with patch.dict(os.environ, {'CDPATH': str(self.home / '.local/state/ultraship')}):
            self.assert_allowed('cd text-lint && cat key', advisory=True)
        self.assert_allowed('cd repo && git status')

    def test_relative_cd_after_the_repository_top_folder_denies(self):
        self.assert_denied('cd "$(git rev-parse --show-toplevel)" && cd .local/state/ultraship/text-lint && cat key',
                           start='Only the text_lint hook reads or writes refusal receipts')

    def test_cd_double_dash_reads_the_next_word(self):
        self.assert_denied('cd -- ~/.local/state/ultraship/text-lint && cat key',
                           start='Only the text_lint hook reads or writes refusal receipts')
        self.assert_allowed('cd -- repo && git status')
        for command in ('cd -- && cat key', 'cd -- -x && cat key', 'cd -'):
            with self.subTest(command=command):
                self.assert_not_denied(command)
        for command in ('cd -- .. && cd -- .local && cd -- state && cd -- ultraship && cd -- account-grants && cat key',
                        'cd -P .. && cd -L .local/state/ultraship/text-lint && cat key',
                        'CDPATH=.. cd .local && cd state && cd ultraship && cd account-grants && cat key'):
            with self.subTest(command=command):
                self.assert_denied(command, start='Only the text_lint hook reads or writes refusal receipts')

    def test_unparsable_text_with_a_path_or_directory_change_denies(self):
        for command in ("cd ..; cd .local; cd state; cd ultraship; cd account-grants; cat key; cat <<'EOF'\nordinary\n",
                        "cd ..; cat .lo*/st*/ul*/ac*/key; cat <<'EOF'\nordinary\n",
                        "cat ../.local/state/ultraship/account-grants/key\necho 'x",
                        "grep -r SECRET ..\ncat <<'EOF'\nx\n", "grep -r SECRET ~\ncat <<'EOF'\nx\n"):
            with self.subTest(command=command):
                self.assert_denied(command, start='Only the text_lint hook reads or writes refusal receipts')

    def test_quoted_two_word_and_cdpath_directory_changes_deny(self):
        for command in ('"cd" ~/.local && "cd" state && "cd" ultraship && cat text-lint/key',
                        '\\cd ~/.local && cat state/ultraship/text-lint/key',
                        'cd ws .local && cd state && cd ultraship && cat text-lint/key',
                        'cdpath=~/.local; cd state; cd ultraship; cat text-lint/key'):
            with self.subTest(command=command):
                self.assert_denied(command, start='Only the text_lint hook reads or writes refusal receipts')
        self.assert_not_denied("c''d ~/.local && cat x")

    def test_quoted_literal_and_repository_top_cd_targets_are_read(self):
        subprocess.run(['git', 'init', '-q', str(self.cwd)], check=True)
        (self.cwd / 'backend').mkdir()
        for command in ('cd "/tmp" && git status', "cd '/tmp/my dir' && ls",
                        'cd "$(git rev-parse --show-toplevel)/backend" && uv run pytest -q',
                        'cd "$(git rev-parse --show-toplevel)" && cd backend && uv run pytest -q'):
            with self.subTest(command=command):
                self.assert_allowed(command)
        self.assert_denied('cd "$(git rev-parse --show-toplevel)" && cd ../.local/state/ultraship/text-lint && cat key',
                           start='Only the text_lint hook reads or writes refusal receipts')

    def test_run_time_file_operand_denies(self):
        # The bare module name keeps main's denial when a value is unresolved.
        for command in ("p=$(printf '%s/.%s/%s/%s/%s' .. local state ultraship account-grants key); cat \"$p\"",
                        "cat \"$(printf '%s/.%s/%s/%s/%s' .. local state ultraship account-grants key)\"",
                        "p=$(printf '%s/.%s/%s/%s/%s/x' ~ local state ultraship text-lint); echo \"$(<\"$p\")\""):
            with self.subTest(command=command):
                self.assert_denied(command, start='Only the text_lint hook reads or writes refusal receipts')
        for command in ('f=`cat name.txt`; head "$f"', 'cat `cat name.txt`'):
            with self.subTest(command=command):
                self.assert_allowed(command, advisory=True)
        self.assert_allowed('f=notes.md; cat "$f"')
        self.assert_allowed("grep -e '$X' notes.md")

    def test_run_time_values_need_one_provable_literal(self):
        # A gh upload field and an interpreter operand stay denied.
        for command in ('gh api graphql -f query=\'query($id:ID!){node(id:$id){id}}\' -F id="$ID"',
                        'bash "$(cat name.txt)"'):
            with self.subTest(command=command):
                self.assert_denied(command)
        # Values read at run time warn, as main admits them.
        for command in ('printf -v p %s x; cat "$p"', 'p=a; p+=b; cat "$p"',
                        'p="x$(cat name.txt)"; cat "$p"', 'q=$(cat name.txt); p=$q; cat "$p"',
                        'read p < name.txt; cat "$p"', 'mapfile p < name.txt; cat "$p"', 'cat "$1"', 'cat "${p:-x}"',
                        'cat name.txt | xargs cat', 'while read -r f; do cat "$f"; done < name.txt',
                        'shuf "$(cat name.txt)"', 'p=$(cat name.txt); pr -t "$p"', 'sort --files0-from=list',
                        'tar -T list -cf - ', 'curl -d @"$p" x', 'date -f "$(cat name.txt)"',
                        'run --at "$(date -rname.txt)"', 'run --at "$(date -uf name.txt)"',
                        'run --at "$(date -r name.txt +%s)"', 'run --at "$(date --file=name.txt)"'):
            with self.subTest(command=command):
                self.assert_not_denied(command)
        for command in ('p=notes.md; cat "$p"', 'for f in a.md b.md; do cat "$f"; done',
                        'git commit -m "$(date)"', 'gh pr view 7 --json title --jq "$Q"',
                        'curl -H "Authorization: $T" https://example.invalid', 'run --deadline "$(date -u +%s)"',
                        "run --deadline \"$(date -u -d '+600 sec' +%s)\"", 'run --at "$(date -Iseconds)"',
                        'echo "$(cat name.txt)"', 'git show "$(git merge-base HEAD main)"'):
            with self.subTest(command=command):
                self.assert_allowed(command)

    def test_git_with_a_store_parent_or_unknown_folder_denies(self):
        for command in ('git -C ~/.local/state grep --no-index x', 'git --work-tree=~/.local/state diff',
                        'git --git-dir ~/.local/state show', 'git -C ~/.local stash -u',
                        'git -C / ls-remote --upload-pack=x origin',
                        'git -C ~ log --output=x', 'git -C ~ fetch --upload-pack=x origin',
                        'git -C ~ -c core.fsmonitor=x status', 'git -C ~ -calias.st=x status'):
            with self.subTest(command=command):
                self.assert_denied(command, start='Only the text_lint hook reads or writes refusal receipts')
        self.assert_allowed('git -C / ls-remote --symref https://example.invalid/o/r.git HEAD')
        for command in ('git -C ~ --config-env=core.pager=X log', 'GIT_CONFIG_COUNT=1 git -C ~ status',
                        'GIT_CONFIG_GLOBAL=cfg git -C ~ status'):
            with self.subTest(command=command):
                self.assert_denied(command)
        for command in ('git -C repo status', 'git -C ~ status -uall', 'git -C ~ log -1', 'git -C "$W" status',
                        'git -C ~ -c credential.helper= status'):
            with self.subTest(command=command):
                self.assert_allowed(command)
        self.assert_not_denied('git -C "$(cat name.txt)" grep --no-index x')

    def test_known_variable_values_are_checked_as_paths(self):
        for command in ('a=.local; b=state; c=ultra; d=ship; e=text; p=$HOME/$a/$b/$c$d/$e-lint; cat $p/r.json',
                        'a=.local; b=state; c=ultra; d=ship; e=account; cat ~/$a/$b/$c$d/$e-grants/g.json',
                        'for a in .local; do for b in state; do cat ~/$a/$b/ultraship/te*/r.json; done; done'):
            with self.subTest(command=command):
                self.assert_denied(command, start='Only the text_lint hook reads or writes refusal receipts')
        self.assert_allowed('a=notes; cat $a.md')

    def test_values_the_scan_cannot_prove_deny(self):
        for command in ("d=.loc'al'; u=ultra'ship'; t=text'-lint'; cat ~/$d/state/$u/$t/x",
                        'd=.loc"al"; cat ~/$d/state/ultraship/text-lint/x',
                        'HOME=~/.local; u=ultraship; t=text-lint; cat $HOME/state/$u/$t/x',
                        'HOME=~/.local cat ~/state/ultraship/text-lint/x',
                        'd=x; printf -v "d" %s .local; u=ultraship; t=text-lint; cat ~/$d/state/$u/$t/x',
                        "d=x; printf -v 'd' %s .local; echo forged > ~/$d/state/ultraship/text-lint/x",
                        'd=.local; u=ultraship; t=text-lint; true ~/$d; cat $_/state/$u/$t/x',
                        'cd ~/.local && cat $PWD/state/ultraship/text-lint/x'):
            with self.subTest(command=command):
                self.assert_denied(command, start='Only the text_lint hook reads or writes refusal receipts')

    def test_store_paths_built_from_pieces_deny(self):
        pieces = 'u=ultra; v=ship; t=text-lint; s=state'
        for command in (f'{pieces}; d=.local; read -r l < ~/$d/$s/$u$v/$t/x; echo $l',
                        f'{pieces}; d=x true; echo "${{d:=.local}}" >/dev/null; cat ~/$d/$s/$u$v/$t/x',
                        f"{pieces}; d=.loc'al'; touch ~/$d/$s/$u$v/$t/forged",
                        f"{pieces}; d=.loc'al'; mkdir -p ~/$d/$s/$u$v/$t/forged",
                        f'{pieces}; printf "-v" HOME %s ~/.local; cat ~/$s/$u$v/$t/x',
                        f'{pieces}; printf "-v" d %s .local; cat ~/$d/$s/$u$v/$t/x',
                        f'{pieces}; "printf" -v d %s .local; cat ~/$d/$s/$u$v/$t/x',
                        f'{pieces}; n=d; printf -v "$n" %s .local; cat ~/$d/$s/$u$v/$t/x',
                        f'{pieces}; cd ~/.local && cat ~+/$s/$u$v/$t/x',
                        f'{pieces}; cd ~/.local && cat "$PWD/$s/$u$v/$t/x"',
                        f'{pieces}; cd ~/.local && cd /tmp && cat "$OLDPWD/$s/$u$v/$t/x"',
                        f'{pieces}; d=.local; echo x > ~/$d/$s/$u$v/$t/x # printf -v',
                        f'{pieces}; d=.local; printf -v z %s q; echo x >> ~/$d/$s/$u$v/$t/x',
                        f'{pieces}; printf -v d %s .local; echo x >> ~/$d/$s/$u$v/$t/x',
                        f"{pieces}; d=.loc'al'; echo x > ~/$d/$s/$u$v/$t/x"):
            with self.subTest(command=command):
                self.assert_denied(command, start='Only the text_lint hook reads or writes refusal receipts')

    def test_harmless_commands_main_allows_still_pass(self):
        for command in ('gh pr view "$(git branch --show-current)" --json state',
                        'git diff "$(git merge-base HEAD origin/main)"',
                        'git -C "$(git rev-parse --show-toplevel)" status --short',
                        'GIT_SEQUENCE_EDITOR=: git rebase -i HEAD~3', 'GIT_TRACE=1 git fetch origin',
                        'export EDITOR=vim', "grep -rn 'GIT_DIR=' src", 'grep -n "cd" Makefile',
                        'env -i HOME=/tmp/h PATH="/usr/bin:/bin" make lint'):
            with self.subTest(command=command):
                self.assert_allowed(command)
        # Values main admits: run-time operands, editors, pagers, names-only finds and xargs.
        for command in ('git diff --no-index "$(cat name.txt)" /dev/null', 'export EDITOR=code', 'export EDITOR=nvim',
                        'PAGER=less git log', 'GIT_DIR=.git git status', 'cat "$(ls -t *.log | head -1)"',
                        'for f in $(git diff --name-only); do wc -l "$f"; done', 'git checkout -b "$BR"',
                        'git restore "$f"', 'git add "$f"', 'rm -f "$TMPFILE"', 'head -n 20 "$LOG"', 'jq . "$f"',
                        'ls "$dir"', 'cat "$PWD/README.md"', "find . -name '*.pyc' | xargs rm",
                        'while read -r f; do cat "$f"; done < list.txt', 'mkdir -p "${TMPDIR:-/tmp}/x"',
                        'touch "/tmp/x$RANDOM"', 'echo ultraship',
                        'printf -v ts "%(%F)T" -1; echo x > "log-$ts.txt"', 'cd sub && echo x > "$PWD/o"',
                        'out=a.log; out=b.log; make > "$out"', 'out=a; out+=.log; make > "$out"',
                        'log=build.log make > "$log"', 'cd build && make > "$OLDPWD/build.log"',
                        'cd sub && cat "$PWD/o"', 'printf -v out %s.log; make > "$out"'):
            with self.subTest(command=command):
                self.assert_not_denied(command)

    def test_browser_image_check_requires_a_complete_managed_invocation(self):
        short_tmp = self.home / ('bc-' + '1' * 32)
        short_tmp.mkdir()
        browser = '/usr/local/bin/agent-browser'
        timeout = '/usr/bin/timeout'
        expression = '"JSON.stringify([...document.images].map(i=>i.naturalWidth))"'
        command = (f'T={short_tmp}; cd $T && {timeout} 60 {browser} open '
                   f'"file://$T/pptx_check.html" >/dev/null 2>&1; {timeout} 30 {browser} eval '
                   f'{expression} 2>&1 | tail -1; {timeout} 20 {browser} close >/dev/null 2>&1')
        for agent_type in ('', 'ship:driver'):
            with self.subTest(agent_type=agent_type):
                with patch.object(ultraship, 'trusted_executable', side_effect={browser, timeout}.__contains__):
                    self.assert_not_denied(command, agent_type)
                    self.assert_denied(command.replace(browser, 'agent-browser'), agent_type)
                    self.assert_denied(command.replace(timeout, 'timeout'), agent_type)
                    self.assert_denied(command.replace(expression, f'{expression} extra'), agent_type)
                    self.assert_denied(command.replace(expression, f'{expression} '), agent_type)
                for untrusted in (browser, timeout):
                    with self.subTest(untrusted=untrusted), patch.object(
                            ultraship, 'trusted_executable', side_effect=lambda path: path != untrusted):
                        self.assert_denied(command, agent_type)

    def test_managed_executable_checks_file_and_each_parent(self):
        executable = Path('/managed/bin/probe')
        stats = {entry: SimpleNamespace(st_uid=0, st_mode=0o40755) for entry in executable.parents}
        stats[executable] = SimpleNamespace(st_uid=0, st_mode=0o100755)
        with patch.object(Path, 'lstat', autospec=True, side_effect=stats.__getitem__):
            self.assertTrue(ultraship.trusted_executable(str(executable)))
            for entry in stats:
                original = stats[entry]
                for owner, mode in ((1, original.st_mode), (0, original.st_mode | 0o020),
                                    (0, original.st_mode | 0o002), (0, 0o120755)):
                    with self.subTest(entry=entry, owner=owner, mode=mode):
                        stats[entry] = SimpleNamespace(st_uid=owner, st_mode=mode)
                        self.assertFalse(ultraship.trusted_executable(str(executable)))
                stats[entry] = original

    def test_html_report_uses_bundled_reader_and_keeps_inline_refusal(self):
        report = self.cwd / '.scratch/refactor/voice-b-teammate-review.html'
        helper = PLUGIN / 'skills/ship/scripts/read-scratch-report.py'
        python = Path(ultraship.sys.executable).resolve()
        command = f'{python} -I -S {helper} refactor/{report.name}'
        for agent_type in ('', 'ship:driver', 'ship:writer--sol'):
            with self.subTest(agent_type=agent_type):
                self.assert_not_denied(command, agent_type)
                for interpreter in ('python3', f'{python} -I -S'):
                    inline = (f'F={report}; {interpreter} -c '
                              '''"import re,sys,html; t=open('$F').read(); t=re.sub(r'data:image/[^\\\"]+','IMG',t); s=html.unescape(t); print(s[:5000])"''')
                    self.assert_denied(inline, agent_type)

    def test_gate_snapshot_commands_are_not_denied(self):
        command = (
            'set -eu\n'
            'source_dir="$PWD/../better-plugin-mutation-gate/plugins/chief-of-chiefs"\n'
            'pinned_script="$PWD/../better-plugin-mutation-gate/scripts/pin-helper-sha.py"\n'
            'python3 -B "$pinned_script" --check\n'
            'snapshot=$(mktemp -d "$PWD/../.scratch/b28-retest.XXXXXXXX")\n'
            'mkdir -p "$snapshot/plugin/skills/run/scripts" "$snapshot/plugin/skills/run/references" '
            '"$snapshot/plugin/tests" "$snapshot/tmp" "$snapshot/home"\n'
            'cp -- "$source_dir/skills/run/scripts/gate-b28.sh" "$source_dir/skills/run/scripts/gate_child.py" '
            '"$source_dir/skills/run/scripts/slot_gate.sh" "$snapshot/plugin/skills/run/scripts/"\n'
            'cp -- "$source_dir/skills/run/references/launcher-step1.md" "$snapshot/plugin/skills/run/references/"\n'
            'cp -- "$source_dir/tests/test_gate_child_identity.py" "$source_dir/tests/test_launcher_step1.py" '
            '"$source_dir/tests/test_mutation_gate.py" "$source_dir/tests/test_slot_gate.py" "$snapshot/plugin/tests/"\n'
            'git -C ../better-plugin-mutation-gate rev-parse HEAD > "$snapshot/base"\n'
            'sha256sum "$snapshot/plugin/skills/run/scripts/gate-b28.sh" "$snapshot/plugin/skills/run/scripts/gate_child.py" '
            '"$snapshot/plugin/skills/run/scripts/slot_gate.sh" "$snapshot/plugin/tests/test_mutation_gate.py" '
            '"$snapshot/plugin/tests/test_slot_gate.py" | tee "$snapshot/checksums"\n'
            'printf \'%s\\n\' "$snapshot"'
        )
        for agent_type in ('', 'ship:driver'):
            with self.subTest(agent_type=agent_type):
                self.assert_not_denied(command, agent_type)

    def test_bound_ledger_path_keeps_exact_call_requirement(self):
        ledger = self.cwd / 'accounting-helper.py'
        with patch.object(ultraship, 'ledger_script', return_value=ledger):
            for binding, target in ((f'P={ledger}', '"$P"'), (f'P={ledger.parent}', '"$P/accounting-helper.py"')):
                command = f'set -eu\n{binding}\npython3 {target} {{subcommand}}\nprintf "%s" "done"'
                for agent_type in ('', 'ship:driver'):
                    with self.subTest(target=target, agent_type=agent_type):
                        self.assert_denied(command.format(subcommand='account-auto'), agent_type,
                                           'Use the exact Stop command for your session')
                        for subcommand in ('path', 'status', 'gaps'):
                            self.assert_not_denied(command.format(subcommand=subcommand), agent_type)
                self.assert_denied(command.format(subcommand='account-auto'), 'ship:writer--sol')

    def test_harness_ledger_reads_require_the_active_plugin_root(self):
        base = 'python3 "${CLAUDE_PLUGIN_ROOT}/skills/ship/scripts/ledger.py"'
        with patch.dict(os.environ, {'CLAUDE_PLUGIN_ROOT': str(PLUGIN)}):
            for agent_type in ('', 'ship:driver'):
                for subcommand in ('path', 'status', 'gaps'):
                    with self.subTest(agent_type=agent_type, subcommand=subcommand):
                        self.assert_not_denied(f'{base} {subcommand}', agent_type)
                self.assert_denied(f'{base} account-auto', agent_type)
                self.assert_denied(f'CLAUDE_PLUGIN_ROOT={self.cwd}; {base} status', agent_type)
        with patch.dict(os.environ, {'CLAUDE_PLUGIN_ROOT': str(self.cwd)}):
            self.assert_denied(f'{base} status')

    def test_synthetic_receipt_write_is_denied(self):
        command = 'printf test > ~/.local/state/ultraship/text-lint/receipts/' + '0' * 32 + '.json'
        for agent_type in ('', 'ship:driver'):
            with self.subTest(agent_type=agent_type):
                self.assert_denied(command, agent_type, 'Only the text_lint hook reads or writes refusal receipts')

    def test_git_takes_a_run_time_value_only_as_a_message_ref_or_names_only_folder(self):
        for command in ('git tag -a -F "$(cat name.txt)" probe', 'git checkout --pathspec-from-file="$(cat name.txt)"',
                        'git log -n "$N" --output=x'):
            with self.subTest(command=command):
                self.assert_not_denied(command)
        for command in ('git commit -m "$(date)"', 'git show "$(git merge-base HEAD main)"', 'git -C "$W" status',
                        'git ls-remote --symref "$U" HEAD'):
            with self.subTest(command=command):
                self.assert_allowed(command)

    def test_curl_and_gh_take_a_run_time_value_only_where_no_file_is_named(self):
        for command in ('curl -s "file://$(cat name.txt)"', 'curl -s -w "@$(cat name.txt)" https://example.invalid',
                        'curl --data-ascii "@$P" https://example.invalid', 'gh gist create "$(cat name.txt)"',
                        'gh release upload v1 "$(cat name.txt)"'):
            with self.subTest(command=command):
                self.assert_not_denied(command)
        for command in ('curl -s "https://example.invalid/$(date +%s)"', 'curl -H "Authorization: $T" https://example.invalid',
                        'gh api "repos/o/r/pulls/$PR/comments" --jq \'.[].id\'', 'gh pr list --search "$Q"'):
            with self.subTest(command=command):
                self.assert_allowed(command)

    def test_git_pager_and_editor_variables_pass_only_from_an_allowlist(self):
        for command in ('GIT_SSH_COMMAND=x git fetch', 'export GIT_PAGER=less; git log', 'declare -x PAGER=x; git log',
                        'env EDITOR=ed git commit', 'typeset GIT_EXTERNAL_DIFF=x; git diff', 'readonly SSH_ASKPASS=x',
                        'GIT_DIR="$D" git status'):
            with self.subTest(command=command):
                self.assert_not_denied(command)
        for command in ('GIT_TERMINAL_PROMPT=0 git status', 'GIT_PAGER=cat git log -1',
                        'GIT_AUTHOR_NAME="A B" git commit -m x'):
            with self.subTest(command=command):
                self.assert_allowed(command)

    def test_date_substitution_exemption_refuses_braces_and_globs(self):
        for command in ('run --at "$(date +{x,y})"', 'run --at "$(date -d {a,b})"', 'run --at "$(date +*)"'):
            with self.subTest(command=command):
                self.assert_allowed(command, advisory=True)
        self.assert_allowed("run --at \"$(date -u -d '+1 day' '+%F')\"")

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
