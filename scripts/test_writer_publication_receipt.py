"""Writer admission distinguishes a local publication receipt from executable push spellings."""
import re
import json
from pathlib import Path
import subprocess
import sys
import unittest

HOOK = Path(__file__).resolve().parents[1] / 'plugins/ship/hooks/ultraship.py'


class WriterPublicationReceiptTests(unittest.TestCase):
    def admission(self, command, original=False):
        # Pass the command as inert hook input. Never execute the proposed shell command.
        args = [sys.executable, str(HOOK), 'pre']
        if original:
            script = ('import json, runpy, sys; hook = runpy.run_path(sys.argv[1]); '
                      'pre = hook["pre"]; pre.__globals__["literal_ps_awk_filter"] = lambda text: text; '
                      'pre(json.load(sys.stdin))')
            args = [sys.executable, '-c', script, str(HOOK)]
        result = subprocess.run(args, input=json.dumps({
            'agent_type': 'ship:writer--sol', 'tool_name': 'Bash', 'tool_input': {'command': command}}),
            capture_output=True, text=True, check=True)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def test_local_python_receipt_with_false_publication_field_is_admitted(self):
        command = """python3 -I - <<'PY'
from pathlib import Path
import subprocess, json
committed = subprocess.check_output(['git', 'diff', 'HEAD^', 'HEAD'])
assert subprocess.check_output(['git', 'status', '--porcelain']) == b''
receipt = {'byte_count': len(committed), 'pushed': False}
Path('receipt.json').write_text(json.dumps(receipt) + '\\n')
PY"""
        self.assertEqual(self.admission(command), {})

    def test_literal_awk_field_filters_are_admitted(self):
        for command in (
            '''ps -eo pid,args | awk '$3 == "git" && $0 ~ /merge/ {print}' ''',
            '''ps -eo pid,args | awk '$2 == "git" && $1 > 0 {print}' ''',
            '''\tps\t-eo pid,args |\tawk '($4 == "git") {print}'\t''',
        ):
            with self.subTest(command=command):
                self.assertEqual(self.admission(command), {})

    def test_unsupported_pipeline_shapes_keep_original_classification(self):
        command = '''ps -eo pid,args | awk '$3 == "git" && $0 ~ /merge/ {print}' '''
        for candidate in (
            command + '\n', command.replace('ps -eo pid,args', 'ps -ef'),
            command.replace('ps ', 'env ps ', 1), command.replace('ps ', 'ps\n', 1),
            command + ' processes.txt', command + ' | cat', command + '; true',
            '''awk '$3 == "git" {print}' ''', 'ps -ef | awk \'{print}\'',
            'printf plain | sort', 'echo plain',
        ):
            with self.subTest(command=candidate):
                self.assertEqual(self.admission(candidate), self.admission(candidate, original=True))

    def test_awk_text_exception_preserves_executable_push_denials(self):
        filter_command = '''ps -eo pid,args | awk '$3 == "git" && $0 ~ /merge/ {print}' '''
        for command in (
            "git $'push'", 'git -C "$PWD" push',
            '''bash -c 'git push origin HEAD' ''', '''eval 'git push origin HEAD' ''',
            '''awk 'BEGIN {system("git push")}' ''',
            '''awk '$3 == "git" {system($3 " push")}' ''',
            '''awk '$3 == "git" {system($3 " pu" "sh")}' ''',
            '''awk '$3 == "git" {"git pu" "sh" | getline}' ''',
            '''awk '$3 == "git" {print | "git pu" "sh"}' ''',
            '''awk '$3 == "git" {print}''BEGIN {system("git pu" "sh")}' /dev/null''',
            '''awk '$3 == "git" {print}'BEGIN' {system("git pu" "sh")}' /dev/null''',
            '''awk '$3 == "git" {print}' -e 'BEGIN {system("git pu" "sh")}' ''',
            '''awk '$3 == "git" {print}' --source='BEGIN {system("git pu" "sh")}' ''',
            '''awk '$3 == "git" {print}' "$(git push)"''',
            '''awk '$3 == "git" {print}' `git push`''',
            '''git awk '$3 == "git" {print}' $'push' ''',
            filter_command + '; git push origin HEAD',
            filter_command + ' && git push origin HEAD',
            filter_command + ' | bash -c "git push"',
            '''printf 'git pu%s\\n' sh | awk '$1 == "git" {print}' | bash''',
            '''echo "$(ps -ef | awk '$1 == "git" {print}')"; git $'push' ''',
        ):
            with self.subTest(command=command):
                result = self.admission(command)
                self.assertEqual(result.get('hookSpecificOutput', {}).get('permissionDecision'), 'deny')

    def test_git_directory_values_preserve_executable_push_denials(self):
        for command in ('git -C $worktree origin HEAD',
                        '''bash -c 'git -C $worktree origin HEAD' ''',
                        'git -C "$worktree" push origin HEAD',
                        "git -C \"$worktree\" $'push'",
                        'git -C "$(git push)" status', 'git -C "`git push`" status',
                        'git -C "${worktree:-$(git push)}" status',
                        'git -C "$worktree" status; git push',
                        'git -C "$worktree" p{u,}sh'):
            with self.subTest(command=command):
                result = self.admission(command)
                self.assertEqual(result.get('hookSpecificOutput', {}).get('permissionDecision'), 'deny')

    def test_quoted_directory_variable_reads_classify_like_a_literal_directory(self):
        # The owner approved reading past a double-quoted folder variable; the subcommand check
        # then runs exactly as it does for a literal folder.
        for command in (
            '''worktree=/home/miguel/.vk-worktrees/.bettercoding-workspaces/ada6-pati-teams-parit/lanes/w-report; head=$(git -C "$worktree" rev-parse HEAD) || exit; status=$(GIT_OPTIONAL_LOCKS=0 git -C "$worktree" status --porcelain) || exit; printf 'HEAD %s\\nSTATUS\\n%s\\n' "$head" "$status"; if [ "$head" != 0971b394465d2b5130643f9e4ab1ee711a6a7657 ] || [ -n "$status" ]; then printf 'BLOCKER: worktree preconditions fail\\n'; exit 1; fi''',
            'git -C "$worktree" rev-parse HEAD',
            'git -C "${worktree}" status --porcelain',
            'head=$(git -C "$worktree" rev-parse HEAD)',
            'status=$(git -C "${worktree}" status --porcelain)',
            'status=$(GIT_OPTIONAL_LOCKS=0 git -C "$worktree" status --porcelain)',
            '{ :; head=$(git -C "$worktree" rev-parse HEAD); }',
            'status=$(git -C "$worktree" status --porcelain); eval "$status"',
            'status=$(git -C "$worktree" status --porcelain); bash -c "$status"',
            'status=$(git -C "$worktree" status --porcelain); "$status"',
            'status=$(git -C "$worktree" status --porcelain); $status',
            '''PATH='/attacker'; head=$(git -C "$worktree" rev-parse HEAD)''',
            '''printf '%n' 'PATH'; head=$(git -C "$worktree" rev-parse HEAD)''',
            'head=$(git -C "$worktree" rev-parse HEAD)"suffix"',
            'head=$(git -C "$worktree" rev-parse HEAD)trailing',
            'head=$(git -C "$worktree" rev-parse HEAD) extra',
            'head=$(git -C "$worktree" rev-parse HEAD)>output',
        ):
            literal = re.sub(r'"\$\{?worktree\}?"', '/w', command)
            with self.subTest(command=command):
                self.assertNotEqual(self.admission(literal).get('hookSpecificOutput', {}).get('permissionDecision'), 'deny')
                self.assertNotEqual(self.admission(command).get('hookSpecificOutput', {}).get('permissionDecision'), 'deny')

    def test_unsupported_assignment_context_preserves_original_refusal(self):
        for command in (
            '''echo "$(head=$(git -C "$worktree" rev-parse HEAD))"''',
            'head=$(git -C "$worktree" rev-parse HEAD) # ; other=$(git -C "$worktree" status --porcelain)',
            r'prefix=value\; head=$(git -C "$worktree" rev-parse HEAD)',
            '''bash -c 'head=$(git -C "$worktree" rev-parse HEAD)' ''',
            '''eval 'head=$(git -C "$worktree" rev-parse HEAD)' ''',
            '''cat <<'EOF'\nhead=$(git -C "$worktree" rev-parse HEAD)\nEOF''',
            '''cat <<<'head=$(git -C "$worktree" rev-parse HEAD)' ''',
            'head=$(git -C "$(git push)" rev-parse HEAD)',
            'head=$(git -C "$worktree" push origin HEAD)',
            'head=$(git -C "$worktree" rev-parse HEAD); git push origin HEAD',
            'head=$(git -C $worktree rev-parse HEAD)',
            'head=$(git -C "$worktree""suffix" rev-parse HEAD)',
            'head=$(git -C "${worktree:-$(git push)}" rev-parse HEAD)',
            'head=$(git -C "`git push`" rev-parse HEAD)',
            'head=$(git -C "$worktree" rev-parse HEAD); echo "$(git push)"',
            'head=$(git -C "$worktree" rev-parse HEAD); echo "unterminated git push',
        ):
            with self.subTest(command=command):
                result = self.admission(command)
                self.assertEqual(result.get('hookSpecificOutput', {}).get('permissionDecision'), 'deny')

    def test_real_remote_operations_remain_denied_beside_a_local_receipt(self):
        for command in ('{git,push} origin HEAD', "$'git' {status,push} origin HEAD",
                        'git p{ush,ull} origin HEAD', 'git push{ed,} origin HEAD',
                        'git push origin HEAD', 'git -C "$PWD" push origin HEAD',
                        "$'git' p{u,}sh origin HEAD", 'gh pr merge 3 --squash',
                        'python3 -c "receipt = {\'pushed\': False}"; git push origin HEAD'):
            with self.subTest(command=command):
                result = self.admission(command)
                self.assertEqual(result.get('hookSpecificOutput', {}).get('permissionDecision'), 'deny')
