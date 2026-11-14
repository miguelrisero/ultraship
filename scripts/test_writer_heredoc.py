"""Writer publication decisions for heredoc data and executable shell text."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import signal
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ultraship_heredoc', ROOT / 'plugins/ship/hooks/ultraship.py')
ultraship = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ultraship)


class WriterHeredocTests(unittest.TestCase):
    BYTECODE_FLAGS = ('-I -B', '-B -I', '-B', '-IB', '-BI')

    def denied(self, command, cwd=None):
        output = io.StringIO()
        payload = {'agent_type': 'ship:writer--sol', 'tool_name': 'Bash', 'tool_input': {'command': command}}
        if cwd is not None:
            payload['cwd'] = cwd
        with contextlib.redirect_stdout(output):
            try:
                ultraship.pre(payload)
            except SystemExit as error:
                self.assertEqual(error.code, 0)
        text = output.getvalue()
        self.reason = json.loads(text)['hookSpecificOutput']['permissionDecisionReason'] if text else ''
        return bool(text and json.loads(text)['hookSpecificOutput']['permissionDecision'] == 'deny')

    def test_process_capable_python_inline_strings_are_denied(self):
        code = "import subprocess; subprocess.run([\"git\", \"pu\" + \"sh\"])"
        for command in (
            'python3 -c "import subprocess; subprocess.run([\'git\', \'pu\' + \'sh\'])"',
            f"python3 -Ic '{code}'", f"python3 -c'{code}'", f"X=$(python3 -c '{code}')",
            'bash -c "python3 -c \'import sys; print(sys.argv)\'"',
            *(f"{python} -c '{code}'" for python in (
                'uv run python', 'env python3', '/usr/bin/python3', 'python3.12',
                'timeout 5 python3', 'xargs python3', 'nohup python3', 'sudo python3')),
            'python3 -c "print($(echo 1))"', 'python3 -c a*b',
            "python3 -c 'import sys; print(sys.argv)'", "python3 -c 'print(1)",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('process-capable python -c rule', self.reason)

    def test_inert_python_inline_strings_are_admitted(self):
        for command in (
            "python3 -c 'print(1)'", 'python3 -c "print(1)"',
            'python3 -I -c \'import json; print(json.dumps({"a": 1}))\'',
            "python3 -Ic'print(1)'", 'python3 -m pytest -q',
        ):
            with self.subTest(command=command):
                self.assertFalse(self.denied(command))

    def test_inline_python_write_requires_check_only_remainder(self):
        write = 'python3 -c \'open("r.sh", "w").write("echo x")\''
        self.assertTrue(self.denied(write + ' && bash r.sh'))
        self.assertIn('python -c then run rule', self.reason)
        self.assertFalse(self.denied(write + ' && bash -n r.sh'))
        self.assertFalse(self.denied(write + ' && cat r.sh'))

    def test_inline_literal_git_read_requires_isolation_and_names_reason(self):
        code = 'import subprocess; subprocess.run(["git", "branch", "--show-current"])'
        self.assertFalse(self.denied(f"python3 -I -c '{code}'"))
        self.assertTrue(self.denied(f"python3 -c '{code}'"))
        bad = code.replace('"branch", "--show-current"', '"status"')
        self.assertTrue(self.denied(f"python3 -I -c '{bad}'"))
        self.assertIn('process-capable python -c rule: git read requires', self.reason)

    def test_other_interpreter_inline_code_is_denied(self):
        for interpreter, option in (
            ('node', '-e'), ('node', '-p'), ('node', '--eval=x'), ('nodejs', '-e'),
            ('perl', '-e'), ('perl', '-ne'), ('perl', '-MPOSIX -e'), ('perl', '-E'),
            ('perl5.36', '-lne'), ('pypy3', '-c'), ('pypy3.10', '-m'), ('ruby', '-e'),
            ('php', '-r'), ('deno', 'eval'), ('bun', '-e'), ('osascript', '-e'),
            ('Rscript', '-e'), ('lua', '-e'), ('luajit', '-e'),
        ):
            with self.subTest(interpreter=interpreter, option=option):
                self.assertTrue(self.denied(f'{interpreter} {option} x'))
                self.assertIn('inline interpreter code rule (', self.reason)

    def test_unresolved_inline_command_words_are_denied(self):
        for command in ('"python3" -c x', "pyth''on3 -c x", r'p\ython3 -c x',
                        '$P -c x', '$(which node) -e x'):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
        self.assertTrue(self.denied('$P -c x'))
        self.assertIn('inline interpreter code rule (unresolved command word)', self.reason)

    def test_heredoc_reader_allowlist_denies_interpreters_and_wrappers(self):
        for reader in ('node -', 'node', 'perl', 'pypy3 -', 'ruby', '"python3" -',
                       "pyth''on3 -", 'env node', 'X=1 node'):
            with self.subTest(reader=reader):
                self.assertTrue(self.denied(reader + " <<'EOF'\nx\nEOF\n"))
                self.assertIn('process-capable heredoc rule (heredoc reader not on the allowlist)', self.reason)
        for command in ("cat <<'EOF' | node\nx\nEOF\n", "cat <<'EOF' |\nx\nEOF\nnode\n",
                        "env cat <<'EOF'\nx\nEOF\n", "cat <<'EOF'; node\nx\nEOF\n"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('heredoc reader not on the allowlist', self.reason)

    def test_here_strings_require_data_reader(self):
        for reader in ('python3', 'node', 'perl'):
            with self.subTest(reader=reader):
                self.assertTrue(self.denied(reader + " <<< 'abc'"))
                self.assertIn('heredoc reader not on the allowlist', self.reason)

    def test_quoted_conflict_marker_search_is_data(self):
        loop = 'git diff --name-only | while IFS= read -r f; do grep -n {} "$f" && exit 1; done'
        for marker in ("'^<<<<<<<'", "'<<<<<<< HEAD'"):
            with self.subTest(marker=marker):
                self.assertFalse(self.denied(loop.format(marker)), self.reason)
        alternation = ("git status --short && rg -n '^(<<<<<<<|=======|>>>>>>>)' a.py"
                       " && git diff --name-only --diff-filter=U && date -u")
        self.assertFalse(self.denied(alternation), self.reason)
        for command in (
            "grep -n '^<<<<<<<' a.py; python3 <<< 'import os'",
            "grep \\' x && python3 <<< 'import os'",
            "grep -n '^<<<<<<< a.py",
            "echo 'a\n'<<<'\n'",
            "grep -n $'\\'' a.py; python3 <<< x # '",
            'grep -n "$(python3 <<< \'import os\')" a.py',
        ):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('heredoc reader not on the allowlist', self.reason)
        for line in ("a $'x' '<<'", "a '<<' # x", "a `b` '<<'", 'a "$(b)" \'<<\'', 'a "${b}" \'<<\'',
                     'a "$[1]" \'<<\'', "a '<<"):
            with self.subTest(line=line):
                self.assertEqual(ultraship.literal_quotes_removed(line), line)
        self.assertEqual(ultraship.literal_quotes_removed("a \\' <<< \\' '<<'"), "a \\' <<< \\' ")
        self.assertEqual(ultraship.literal_quotes_removed('a "x\\"y" \'<<\''), 'a "x\\"y" ')

    def test_program_from_pipe_is_denied(self):
        for command in ("printf '%s' x | python3", 'echo x | node', 'cat f | perl'):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_data_readers_and_script_operands_are_admitted(self):
        for command in ('node --version', 'node script.js', 'perl script.pl',
                        "cat > notes.md <<'EOF'\ntext\nEOF\n", "tee x.txt <<'EOF'\ntext\nEOF\n",
                        "grep x <<< 'abc'"):
            with self.subTest(command=command):
                self.assertFalse(self.denied(command))

    def test_commit_prefix_keeps_later_inline_code_checked(self):
        command = ('git commit -m x\n: <<\'Z\'\nZ\n'
                   'python3 -c \'import subprocess; subprocess.run(["git", "pu" + "sh"])\'')
        self.assertTrue(self.denied(command))
        self.assertIn('process-capable heredoc rule', self.reason)
        self.assertIn('process-capable python -c rule', ultraship.python_inline_denial(command))

    def test_expansions_cannot_assemble_inline_interpreter(self):
        for command in ('$P -c x', 'py${X}thon3 -c x', 'python3${IFS}-c x'):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (unresolved command word)', self.reason)

    def test_python_value_options_keep_inline_code_checked(self):
        code = 'import subprocess; subprocess.run(["git", "pu" + "sh"])'
        for flags in ('-W ignore', '-X dev', '-Wignore', '-Xdev', '-m module', '-- script.py'):
            with self.subTest(flags=flags):
                self.assertTrue(self.denied(f"python3 {flags} -c '{code}'"))
                self.assertIn('process-capable python -c rule', self.reason)
        self.assertFalse(self.denied("python3 -W ignore -c 'print(1)'"))

    def test_inline_newline_operators_terminate_recursion(self):
        self.assertFalse(self.denied("python3 -c 'print(1)'\ncat x\n"))
        self.assertTrue(self.denied("cat x\npython3 -c 'import sys; print(sys.argv)'\n"))
        self.assertIn('process-capable python -c rule', self.reason)

    def test_named_interpreters_refuse_unlisted_code_options(self):
        for command in ('php -B x', 'node --import x', 'deno run x', 'bun --preload x'):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (', self.reason)

    def test_stdin_paths_cannot_supply_interpreter_programs(self):
        for reader in ('python3', 'node', 'perl'):
            for path in ('-', '/dev/stdin', '/dev/fd/0', '/proc/self/fd/0'):
                with self.subTest(reader=reader, path=path):
                    self.assertTrue(self.denied(f'cat f | {reader} {path}'))
                    self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_redirects_and_process_substitution_cannot_supply_programs(self):
        for command in ('node <(echo x)', 'perl < x', 'python3 < x', 'python3 /dev/stdin'):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_unquoted_data_heredoc_expansions_are_denied(self):
        for body in ('$(python3 -c x)', '`node -e x`', '${PROGRAM}'):
            with self.subTest(body=body):
                self.assertTrue(self.denied('cat <<EOF\n' + body + '\nEOF\n'))
                self.assertIn('process-capable heredoc rule', self.reason)

    def test_warning_operand_cannot_hide_real_python_code(self):
        code = 'import subprocess; subprocess.run(["git", "pu" + "sh"])'
        for flags in ('-W ignore', "-Wc'print(1)'", '-X I'):
            with self.subTest(flags=flags):
                self.assertTrue(self.denied(f"python3 {flags} -c '{code}'"))
                self.assertIn('process-capable python -c rule', self.reason)

    def test_nested_python_write_checks_outer_consumer(self):
        command = 'bash -c "python3 -c \'open(\\"r.sh\\", \\"w\\").write(\\"echo x\\")\'" && bash r.sh'
        self.assertTrue(self.denied(command))
        self.assertIn('python -c then run rule', self.reason)

    def test_path_open_write_keeps_consumers_denied(self):
        code = 'from pathlib import Path; Path("r.sh").open("w").write("echo x")'
        self.assertTrue(self.denied(f"python3 -I -c '{code}' && bash r.sh"))
        self.assertIn('python -c then run rule', self.reason)
        self.assertTrue(self.denied("python3 -I - <<'EOF'\n" + code + '\nEOF\nbash r.sh'))
        self.assertIn('heredoc-then-run rule', self.reason)

    def test_heredoc_denial_before_a_git_commit_prints_the_plain_git_shape(self):
        check = "import subprocess\ndef git(*args):\n    return subprocess.check_output(['git', *args])\nPY\n"
        commit = "git add -- a.py b.py && git commit -m 'test(scope): pin a; b'"
        for lead in ("cd -- /tmp/lane && /usr/bin/python3 -I - <<'PY'\n", "python3 - <<'PY'\n"):
            with self.subTest(lead=lead):
                self.assertTrue(self.denied(lead + check + commit))
                self.assertIn('process-capable heredoc rule', self.reason)
                self.assertIn('Resend with this shape:', self.reason)
                self.assertIn('`git status --porcelain`', self.reason)
        for tail in ('git commit-tree HEAD^{tree} -m x', 'git status', 'echo git commit', 'git\ncommit',
                     '# note; git commit', "echo 'a; git commit'", 'git # x\ncommit', "echo ';' git commit",
                     'X="x; git commit -m x"', 'echo \\; git commit', "printf '%s\\n' \\\ngit commit",
                     "cat <<'TEXT'\ngit commit\nTEXT", 'items=(git commit)', commit + ' && echo done', "git commit -m 'x"):
            with self.subTest(tail=tail):
                self.assertTrue(self.denied("python3 - <<'PY'\n# git commit\n" + check + tail))
                self.assertNotIn('Resend with this shape:', self.reason)
        self.assertTrue(self.denied("python3 - <<'PY'\nimport subprocess\ntext = '''\n PY\ngit commit\n'''\nPY\n"))
        self.assertNotIn('Resend with this shape:', self.reason)
        self.assertTrue(self.denied('python3 - <<PY\nimport subprocess\n# \\\nPY\ngit commit -m x'))
        self.assertNotIn('Resend with this shape:', self.reason)
        self.assertTrue(self.denied("python3 - <<'FIRST' <<'PY'\nPY\ngit commit -m x"))
        self.assertNotIn('Resend with this shape:', self.reason)
        self.assertFalse(self.denied(commit))
        self.assertFalse(self.denied('git status --porcelain'))
        self.assertTrue(self.denied("python3 - <<'PY'\nopen('r.sh', 'w').write('x')\nPY\nbash r.sh\n"))
        self.assertNotIn('Resend with this shape:', self.reason)

    def test_plain_quoted_arguments_do_not_reparse_as_programs(self):
        self.assertFalse(self.denied('echo "it\'s fine"'))

    def test_shell_options_and_string_wrappers_keep_nested_code_checked(self):
        script = "python3 -c 'import sys; print(sys.argv)'"
        for wrapper in ('bash -o pipefail -c', 'sh -ec', 'bash --norc -c', 'env -S', 'eval'):
            with self.subTest(wrapper=wrapper):
                self.assertTrue(self.denied(f'{wrapper} "{script}"'))
                self.assertIn('process-capable python -c rule', self.reason)

    def test_wrapper_option_values_cannot_hide_unresolved_interpreters(self):
        for wrapper in ('timeout --signal=TERM 5', 'env -u A'):
            with self.subTest(wrapper=wrapper):
                self.assertTrue(self.denied(f"{wrapper} $P -c 'x'"))
                self.assertIn('inline interpreter code rule (unresolved command word)', self.reason)

    def test_shell_program_skip_uses_token_offset(self):
        command = "bash -c '$P'; timeout --signal=TERM 5 '$P' -c 'x'"
        self.assertTrue(self.denied(command))
        self.assertIn('inline interpreter code rule (unresolved command word)', self.reason)

    def test_ansi_quoted_node_option_is_denied(self):
        self.assertTrue(self.denied("node $'-e' 'require(\"child_process\").execSync(\"git \" + \"pu\" + \"sh\")'"))
        self.assertIn('process-capable python -c rule', self.reason)

    def test_python_pipe_stdin_operand_keeps_trailing_arguments_denied(self):
        command = ('printf \'%s\' \'import subprocess; subprocess.run(["git", "pu" + "sh"])\' '
                   '| python3 - ignored')
        self.assertTrue(self.denied(command))
        self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_env_split_string_keeps_later_code_arguments_checked(self):
        code = 'require("child_process").execSync("git " + "pu" + "sh")'
        self.assertTrue(self.denied(f"env -S 'node' -e '{code}'"))
        self.assertIn('inline interpreter code rule', self.reason)

    def test_wrapper_program_attribution_keeps_direct_tokens_checked(self):
        command = "bash -o -c $P -c 'x'"
        self.assertTrue(self.denied(command))
        self.assertIn('inline interpreter code rule (unresolved command word)', self.reason)

    def test_unresolved_attached_and_multiline_code_options_are_denied(self):
        for command in ("P=python3; $P -Ic'import os'", "P=perl; $P -we'system(1)'",
                        "P=perl; $P '-e\nsystem(1)'"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule', self.reason)

    def test_additional_string_wrappers_scan_programs(self):
        for command in ('watch -n 9 \'python3 -c "import sys; print(sys.argv)"\'',
                        'script -qc \'python3 -c "import sys"\' /dev/null', "flock f -c 'node -e x'"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule' if command.startswith('flock')
                              else 'process-capable python -c rule', self.reason)

    def test_github_run_watch_is_a_read_only_command(self):
        self.assertFalse(self.denied('gh run watch 123 --exit-status'))

    def test_unquoted_heredoc_backslash_cannot_move_end_line(self):
        self.assertTrue(self.denied('cat > a <<EOF\nx\\\nEOF\necho ok\nEOF'))
        self.assertIn('process-capable heredoc rule (expandable data body)', self.reason)

    def test_bare_interpreter_groups_cannot_read_stdin(self):
        for command in ("printf '%s' 'x' | (node)", "printf '%s' 'x' | { node; }", '(node) < x.js'):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (unresolved command word)' if '{' in command
                              else 'inline interpreter code rule (program from a pipe)', self.reason)

    def test_ansi_quote_at_any_word_position_is_denied(self):
        for command in (r'''echo x$'\''; bun --eval 'require("child_process")' #' ''', "echo $'text'"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('process-capable python -c rule', self.reason)

    def test_relative_stdin_paths_cannot_supply_program(self):
        for command in ("printf '%s' 'x' | node ../../../../../../dev/stdin",
                        "cd / && printf '%s' 'x' | node dev/stdin"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_shell_continuations_cannot_hide_interpreter_or_code_option(self):
        code = "'import os; os.system(chr(103))'"
        for command in ('pyth\\\non3 -c ' + code, '"pyth\\\non3" -c ' + code, 'python3 -\\\nc ' + code):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('process-capable python -c rule', self.reason)
        self.assertFalse(self.denied("python3 -c 'print(\\\n1)'"))

    def test_all_non_shell_whitespace_is_denied(self):
        for separator in (chr(0x3000), chr(0x1f)):
            command = "python3 -c '#'" + separator + "'\nimport subprocess; subprocess.run((\"git\", \"pu\" + \"sh\"))'"
            self.assertTrue(self.denied(command))
            self.assertIn('line separator rule', self.reason)

    def test_unresolved_pipeline_command_cannot_supply_program(self):
        for command in ("N=node; printf '%s' 'x' | $N", "printf '%s' 'x' | =node"):
            self.assertTrue(self.denied(command))
            self.assertIn('inline interpreter code rule (unresolved command word)', self.reason)
        self.assertFalse(self.denied("git diff | grep -n 'foo'"))

    def test_leading_input_redirect_keeps_later_python_stdin_denied(self):
        self.assertTrue(self.denied("< <(printf '%s' 'x') python3 -I"))
        self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_legacy_data_body_scan_preserves_base_denial_reasons(self):
        command = ('cat > f.sh <<\'EOF\'\npython3 - <<\'PY\'\nimport subprocess\n'
                   'subprocess.run(("git", "pu" + "sh"))\nPY\nEOF\nbash f.sh')
        self.assertTrue(self.denied(command))
        self.assertIn('process-capable heredoc rule (interpreter heredoc must start the command)', self.reason)
        self.assertTrue(self.denied('cat <<EOF\n$(git push)\nEOF'))
        self.assertIn('git writer expansion or glob rule', self.reason)

    def test_python_option_values_cannot_supply_pipe_program(self):
        for flags in ('-W ignore', '-Wignore', '-X dev', '--check-hash-based-pycs always'):
            command = "printf '%s\\n' 'import subprocess' | python3 " + flags
            self.assertTrue(self.denied(command))
            self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_command_pipeline_input_reaches_grouped_python(self):
        for command in ("printf '%s' 'x' | (python3 -I)", "printf '%s' 'x' |& python3 -I",
                        "printf '%s' 'x' | { python3 -I; }"):
            self.assertTrue(self.denied(command))
            self.assertIn('inline interpreter code rule', self.reason)

    def test_python_clusters_consume_warning_and_runtime_option_values(self):
        for flags in ('-bW ignore', '-IX dev', '-IWignore'):
            self.assertTrue(self.denied("printf '%s' 'x' | python3 " + flags))
            self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_relative_program_after_directory_change_is_denied(self):
        for command in ("cd /dev && printf '%s' 'x' | node stdin",
                        "cd /dev/fd && printf '%s' 'x' | python3 0", 'cd /dev && node stdin'):
            self.assertTrue(self.denied(command))
            self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)
        self.assertFalse(self.denied('node scripts/build.js'))

    def test_nested_text_contributes_pipeline_and_directory_state(self):
        for command in ('sh -c "printf \'%s\' \'x\' | python3 -I"',
                        'eval "printf \'%s\' \'x\' | python3 -I"',
                        'sh -c "cd /dev && printf \'%s\' \'x\' | node stdin"'):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_word_internal_glob_groups_cannot_hide_interpreters(self):
        # These process calls remain classifier input only.
        for command in ("/usr/bin/pyth(o)n3 -c 'import os; os.system(chr(103))'",
                        "cd /usr/bin && env (p)ython3 -c 'import os; os.system(chr(103))'",
                        "/usr/bin/pyth@(o)n3 -c 'import os; os.system(chr(103))'", "/usr/bin/no(d)e -e 'x'"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('process-capable python -c rule', self.reason)
        self.assertFalse(self.denied('a=(1 2); echo ok'))
        self.assertFalse(self.denied('head=$(git -C /w rev-parse HEAD)trailing'))

    def test_shell_comments_preserve_following_program_checks(self):
        self.assertTrue(self.denied("# it's\nprintf %s x | node\n# '"))
        self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)
        self.assertFalse(self.denied("ls # it's fine"))
        self.assertFalse(self.denied('echo word#literal'))

    def test_coprocess_interpreters_read_stdin(self):
        for command in ('coproc node; print -p x; coproc true; wait',
                        'coproc python3 -B; print -p x; coproc true; wait'):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_wrapper_words_without_command_options_remain_data(self):
        self.assertFalse(self.denied('grep -n script -r src'))

    def test_comment_after_substitution_cannot_hide_pipeline(self):
        for command in ("echo $(true)#; printf '%s' 'x' | node",
                        "echo `true #`; printf '%s' 'x' | node"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('process-capable python -c rule' if '`' in command
                              else 'inline interpreter code rule (program from a pipe)', self.reason)

    def test_wrapper_code_bundles_and_command_prefixes_are_checked(self):
        for command in ('script -qec \'python3 -c "import os"\' /dev/null', "flock f --comm 'node -e x'"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule' if command.startswith('flock')
                              else 'process-capable python -c rule', self.reason)

    def test_wrapper_attached_code_values_are_checked(self):
        for command in ("script -qc'node -e x' /dev/null", "flock f -c'node -e x'", "su -c'node -e x'",
                        "script -Ologc.txt -c 'node -e x' /dev/null"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (node)', self.reason)

    def test_comment_inside_process_substitution_is_denied(self):
        for command in ("cat <(true #); printf '%s' 'x' | node",
                        "echo x >(true #); printf '%s' 'x' | node"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('process-capable python -c rule', self.reason)

    def test_comment_quote_cannot_hide_continued_interpreter(self):
        for command in ("# '\npyth\\\non3 -c 'import os; os.system(chr(105)+chr(100))'",
                        "echo x # '\nno\\\nde -e 'require(1)'"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (node)' if command.startswith('echo')
                              else 'process-capable python -c rule', self.reason)

    def test_nested_shell_keeps_intermediate_pipe_state(self):
        body = 'import subprocess; subprocess.run(["git", "pu" + "sh"])'
        command = "sh -c 'printf \"%s\\n\" \"" + body.replace('"', '\\"') + "\" | sh -c \"python3 -I\"'"
        for command in (command, 'bash -c \'cat f | bash -c "bash -c node"\''):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (unresolved command word)' if command.startswith('sh')
                              else 'inline interpreter code rule (program from a pipe)', self.reason)

    def test_relative_program_after_literal_cd_is_admitted(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for directory in ('frontend', 'backend', 'x'):
            (root / directory).mkdir()
        for command in ('cd frontend && bun test', 'cd frontend && bun install', 'cd frontend && bun run lint',
                        'pushd frontend && bun test', 'cd x && deno test', 'cd backend && python3 scripts/x.py'):
            with self.subTest(command=command):
                self.assertFalse(self.denied(command, cwd=str(root)))

    def test_relative_program_after_unsafe_cd_is_denied(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for directory in ('frontend', 'backend', 'x'):
            (root / directory).mkdir()
        (root / 'proc-fd').symlink_to('/proc/self/fd', target_is_directory=True)
        for command in ('cd /dev && node stdin', 'cd ../x && node 0', 'cd $X && node 0', 'cd - && node 0',
                        'cd && node 0', 'cd ~/x && node 0', 'CDPATH=x; cd x && node 0',
                        'setopt cdable_vars; cd x && node 0', 'cd missing && node 0',
                        'cd x && cd frontend && node 0', 'cd proc-fd && node 0'):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command, cwd=str(root)))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_interpreter_name_after_grep_is_data(self):
        for command in ('ps aux | grep python', 'ps aux | grep node', 'ps aux | grep -i python3'):
            with self.subTest(command=command):
                self.assertFalse(self.denied(command))
        for command in ('ps aux | grep python | node', 'ps aux | xargs python'):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_output_process_substitution_is_piped_input(self):
        for command in ('printf \'%s\' \'import subprocess; subprocess.run(("git", "pu" + "sh"))\' > >(python3 -I)',
                        'echo x > >(python3 -B)'):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)
        self.assertFalse(self.denied('echo x > >(python3 -m json.tool)'))

    def test_chdir_wrapper_makes_relative_programs_unsafe(self):
        for command in ('env -C /dev/fd python3 0', 'env --chdir=/dev/fd node 0',
                        "env -C /dev/fd sh -c 'cd . && python3 0'", "env -S '-C /dev/fd node 0'"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_wrapper_words_in_grep_segments_are_data(self):
        self.assertFalse(self.denied('grep -n script -rc src'))
        self.assertFalse(self.denied('git grep -n script -c'))
        self.assertTrue(self.denied("grep x src; script -qc 'node -e x' /dev/null"))
        self.assertIn('inline interpreter code rule (node)', self.reason)

    def test_output_substitution_state_reaches_nested_texts(self):
        for command in ("echo x > >(sh -c 'python3 -I')", "echo x > >(sh -c 'true; python3 -I')"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_relative_program_before_pipe_is_admitted(self):
        for command in ('bun test 2>&1 | tail -20', 'bun run lint | head -50', 'python3 scripts/check.py | head'):
            with self.subTest(command=command):
                self.assertFalse(self.denied(command))
        self.assertTrue(self.denied('cat x | bun run build'))
        self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_absolute_literal_cd_target_is_admitted(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / 'frontend').mkdir()
        self.assertFalse(self.denied(f'cd {root}/frontend && bun test', cwd=str(root)))
        self.assertTrue(self.denied('cd /proc/self/fd && node 0', cwd=str(root)))
        self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_rg_patterns_are_data(self):
        self.assertFalse(self.denied('rg -n node -t ts'))
        self.assertTrue(self.denied('rg --pre node -e x src'))
        self.assertIn('inline interpreter code rule (node)', self.reason)

    def test_relative_script_pipe_exemption_keeps_input_and_symlinks_denied(self):
        for command in ('bun test 2>&1 | tail -20', 'bun run lint | head -50',
                        'python3 scripts/check.py | head', 'node ./x.js | cat'):
            self.assertFalse(self.denied(command))
        for command in ("sh -c 'node ./rel.js' | cat", "printf x | sh -c 'node ./0'", 'cat code.py | python3 ./0'):
            self.assertTrue(self.denied(command))
            self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / 'script').symlink_to('/proc/self/fd', target_is_directory=True)
        self.assertTrue(self.denied('node ./script', cwd=str(root)))
        self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_namespace_and_unknown_wrappers_make_relative_programs_unsafe(self):
        for command in ('chroot /dev/fd node 0', 'nsenter --wd=/dev/fd node 0', 'sudo --unknownopt node ./x.js'):
            self.assertTrue(self.denied(command))
            self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)
        self.assertFalse(self.denied('sudo -n node ./x.js'))
        self.assertFalse(self.denied('env FOO=1 node scripts/x.js'))

    def test_python_inline_check_keeps_grep_words_as_data(self):
        self.assertFalse(self.denied('grep -n python3 -c src'))
        self.assertFalse(self.denied('grep -c python -r src'))
        self.assertTrue(self.denied("cat x | python3 -c 'import os'"))
        self.assertIn('process-capable python -c rule', self.reason)

    def test_git_global_options_preserve_grep_data_words(self):
        self.assertFalse(self.denied('git -C . grep -n node -- src'))
        self.assertFalse(self.denied('git --no-pager grep -n python src'))
        self.assertFalse(self.denied('git grep -n script -c'))

    def test_chdir_scan_stops_at_program_word(self):
        for command in ('env NODE_ENV=production node scripts/build.js --check',
                        'sudo -n node ./x.js --chunk', 'env FOO=1 node scripts/x.js -C 3'):
            self.assertFalse(self.denied(command))
        for command in ("env -S '-C /dev/fd node 0'", 'env -C /dev/fd node 0'):
            self.assertTrue(self.denied(command))
            self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_git_attached_global_options_preserve_grep_data(self):
        self.assertFalse(self.denied('git -C. grep -n node -- src'))
        self.assertFalse(self.denied('git -ccolor.ui=never grep -n node src'))

    def test_env_split_string_forms_are_chdir_checked(self):
        for command in ("env -S'-C /dev/fd node 0'", "env --split-string='-C /dev/fd node 0'",
                        "env --split-string '-C /dev/fd node 0'", "env -S'--chdir=/dev/fd node 0'"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_env_split_string_escapes_fail_closed(self):
        for command in (r"env -S'-C\_/dev/fd node 0'", r"env -S '-C\_/dev/fd node 0'",
                        r"env --split-string='-C\_/dev/fd node 0'", r"env --split-string '-C\_/dev/fd node 0'",
                        "env -S '${X} node ./x.js'"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule', self.reason)
        self.assertFalse(self.denied("env -S'FOO=1 node ./x.js'"))

    def test_unresolved_grep_segment_keeps_nested_shell_scan(self):
        self.assertTrue(self.denied('grep -rn "$PAT" src eval \'node -e 1\''))
        self.assertIn('inline interpreter code rule (node)', self.reason)
        self.assertFalse(self.denied("grep -rn x eval 'node -e 1'"))
        self.assertFalse(self.denied('grep -rn eval "$DIR"'))
        self.assertFalse(self.denied('grep -rn eval src/*.py | head'))
        self.assertFalse(self.denied('grep -rn eval *.py | wc -l'))
        self.assertTrue(self.denied("gre? -rn x eval 'node -e 1'"))
        self.assertIn('inline interpreter code rule (unresolved command word)', self.reason)
        self.assertFalse(self.denied('grep -n script -rc "$DIR"'))

    def test_joined_named_interpreter_code_is_denied(self):
        for command in ("bun${IFS}--eval${IFS}'console.log(1)'", "deno${IFS}eval${IFS}'console.log(1)'"):
            self.assertTrue(self.denied(command))
            self.assertIn('inline interpreter code rule', self.reason)

    def test_nested_work_limit_denies_large_eval_chain(self):
        command = 'eval ' * 3000 + "node -e 'x'"
        self.assertTrue(self.denied(command))
        self.assertIn('(nesting limit)', self.reason)
        self.assertIn('(nesting limit)', ultraship.inline_interpreter_denial(command))

    def test_unresolved_interpreter_subcommands_are_denied(self):
        for command in ("DENO=deno; $DENO eval 'console.log(1)'", 'DENO=deno; $DENO run https://example.invalid/mod.ts',
                        'DENO=deno; $DENO repl', 'D=deno; "$D" eval x'):
            self.assertTrue(self.denied(command))
            self.assertIn('process-capable python -c rule' if 'console.log' in command
                          else 'inline interpreter code rule (unresolved command word)', self.reason)

    def test_here_string_cannot_hide_later_python_program(self):
        command = 'grep x <<< \'<<"Z"\'\npython3 -c \'import subprocess; subprocess.run(("git", "pu" + "sh"))\''
        self.assertTrue(self.denied(command))
        self.assertIn('process-capable heredoc rule', self.reason)

    def test_python_brace_expansion_before_code_is_denied(self):
        self.assertTrue(self.denied('python3 {-Ic,\'import subprocess; subprocess.run(("git", "pu" + "sh"))\'}'))
        self.assertIn('process-capable python -c rule', self.reason)

    def test_ansi_escape_cannot_hide_following_interpreter(self):
        command = r'''echo $'\''; bun --eval 'require("child_process").execSync("git "+"pu"+"sh")' #' '''.rstrip()
        self.assertTrue(self.denied(command))
        self.assertIn('process-capable python -c rule', self.reason)

    def test_python_pipe_flags_and_normalized_stdin_paths_are_denied(self):
        for command in ("printf '%s' 'import subprocess' | python3 -I", "printf '%s\\n' 'x' | python3 -i -c 'print(1)'",
                        "printf '%s' 'x' | node /dev/./stdin", "python3 =(printf '%s' 'x')"):
            self.assertTrue(self.denied(command))
            self.assertIn('process-capable python -c rule' if command.startswith('python3 =')
                          else 'inline interpreter code rule (program from a pipe)', self.reason)

    def test_shell_cluster_scans_every_following_program_word(self):
        # Shell and process calls below are classifier fixtures only; the test never executes them.
        for command in ('bash -c -- "python3 -c \'import os; os.system(chr(103))\'"',
                        'rbash -c "python3 -c \'import os; os.system(chr(103))\'"'):
            self.assertTrue(self.denied(command))
            self.assertIn('process-capable python -c rule', self.reason)

    def test_nonbreaking_space_keeps_inline_python_denied(self):
        command = "python3 -c '#'" + chr(0xa0) + "'\nimport subprocess; subprocess.run((\"git\", \"pu\" + \"sh\"))'"
        def expired(signum, frame):
            raise AssertionError('classifier exceeds the 10 second hang guard')
        previous = signal.signal(signal.SIGALRM, expired)
        signal.alarm(10)
        try:
            self.assertTrue(self.denied(command))
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
        self.assertIn('line separator rule', self.reason)

    def test_literal_quoted_arguments_keep_base_admissions(self):
        for command in ("grep 'foo' -r src", "git log --format='%h %s' -c -n 3", "find src -name '*.py' -type f"):
            self.assertFalse(self.denied(command))
        for command in ('P=python3; "$P" -c \'import os\'', "node $'-e' x", 'pyth?n3 -c x'):
            self.assertTrue(self.denied(command))

    def test_data_reader_body_extent_keeps_data_and_checks_remainder(self):
        for body in ('x = 1 << 3', "Run python3 - <<'PY' first."):
            self.assertFalse(self.denied("cat > notes.md <<'EOF'\n" + body + '\nEOF\n'))
        self.assertTrue(self.denied("cat > f.py <<'EOF'\nx = 1 << 3\n"))
        self.assertTrue(self.denied("cat > f <<'EOF'\nx\nEOF\nnode <<'JS'\nconsole.log(1)\nJS\n"))

    def test_tab_stripped_delimiters_agree_on_body_extent(self):
        self.assertFalse(self.denied('cat <<-EOF\n\tx\n\tEOF\necho $HOME'))
        self.assertTrue(self.denied('cat <<-EOF\n\tx\n  EOF\n'))

    def test_unquoted_data_body_keeps_literal_apostrophe(self):
        self.assertFalse(self.denied("cat > notes.md <<EOF\nit's fine\nEOF\n"))
        self.assertTrue(self.denied('cat <<EOF\n$(node -e x)\nEOF\n'))

    def test_nonisolated_string_replace_is_read_only(self):
        self.assertFalse(self.denied("python3 - <<'PY'\nprint(open('a.txt').read().replace('x', 'y'))\nPY\nmake test"))
        self.assertFalse(self.denied('python3 -c \'print("a".replace("a", "b"))\' && make test'))
        self.assertTrue(self.denied("python3 - <<'PY'\nfrom pathlib import Path\nPath('a.txt').replace('b.sh')\nPY\nbash b.sh"))

    def test_reader_pass_keeps_python_and_commit_bodies_as_data(self):
        self.assertFalse(self.denied("python3 - <<'PY'\nprint('<<<<<<< HEAD')\nPY\n"))
        self.assertFalse(self.denied("git commit -F - <<'EOF'\nfix: refuse <<< readers\nEOF\n"))
        self.assertTrue(self.denied("python3 - <<'PY'\nprint(1)\nPY\nnode <<< 'x'"))

    def test_quoted_less_than_arguments_keep_base_admissions(self):
        self.assertFalse(self.denied("python3 -c 'print(1 < 2)'"))
        self.assertFalse(self.denied("node build.js --banner '<b>'"))
        self.assertTrue(self.denied('node < x.js'))
        self.assertTrue(self.denied("node -e 'print(1 < 2)'"))

    def test_bare_interpreter_words_require_no_stdin_input(self):
        for command in ('which python3', 'cd sdk/python && uv run pytest', 'brew install node'):
            self.assertFalse(self.denied(command))
        for command in ('printf x | node', 'node < x.js', "node <<< 'x'"):
            self.assertTrue(self.denied(command))

    def test_python_helper_without_import_is_denied(self):
        body = "def git(*args):\n    return subprocess.check_output(['git', *args])\n"
        for operator, delimiter, indent in (('<<', 'EOF', ''), ('<<', "'EOF'", ''),
                                            ('<<', '"EOF"', ''), ('<<', '\\EOF', ''),
                                            ('<<-', "'EOF'", '\t')):
            with self.subTest(operator=operator, delimiter=delimiter):
                script = indent + body.replace('\n', '\n' + indent).rstrip('\t')
                self.assertTrue(self.denied(f'python3 - {operator}{delimiter}\n{script}{indent}EOF\n'))

    W14 = r'''cd /w/wt-inbox && git add -- backend/api/tests/test_loop_result_provenance_census.py && python3 -I - <<'PY'
import hashlib
import subprocess
from pathlib import Path
root = '/w/wt-inbox'
p = 'backend/api/tests/test_loop_result_provenance_census.py'
def git(*args):
    return subprocess.check_output(['git', '-C', root, *args])
assert git('branch', '--show-current').strip() == b'drv/inbox-6943-int'
assert git('rev-parse', 'HEAD').strip() == b'e57ccb0b1494ee72e4b840afa2ece96788ec19e9'
assert git('diff', '--cached', '--name-only', '-z') == p.encode() + b'\0'
before = git('show', 'HEAD:' + p)
staged = git('show', ':' + p)
lines = before.splitlines(keepends=True)
assert lines[269] == b'        "fbde5af8b0bd0d664b737d760a339cc94902c7d50dc48fdc27483c8b1c7ba4b4",\n'
lines[269] = b'        "3e2c44fa1bbe4f811bceb26e102fccca7d81cf3cf2c6a1f98a1ee56fa8fd536a",\n'
assert staged == b''.join(lines)
assert Path(root, p).read_bytes() == staged
assert hashlib.sha256(staged).hexdigest() == 'a5e96776c9941ec83cfb3b40f5baebeb45c3ddfe1b152854fa15e2af60c76fb5'
print('PASS: staged content equals the exact approved one-line edit')
PY
if [ "$?" -eq 0 ]; then git commit -m "test(census): re-pin the task offer forecast closure"; else exit 1; fi
'''

    def test_w14_requires_fsmonitor_pair(self):
        self.assertTrue(self.denied(self.W14))
        self.assertIn('fsmonitor rule', self.reason)
        amended = self.W14.replace("root, *args", "root, '-c', 'core.fsmonitor=false', *args")
        self.assertFalse(self.denied(amended))
        self.assertFalse(ultraship.runs_heredoc_output(amended))
        self.assertNotEqual(ultraship.python_heredoc_shell(amended, inert_only=True), amended)

    def test_literal_git_read_commands(self):
        for argv in (
            "'-c', 'core.fsmonitor=false', 'rev-parse', '--verify', 'HEAD'", "'branch', '--show-current'",
            "'-c', 'core.fsmonitor=false', 'diff', '--cached', '--name-only'",
            "'-c', 'core.fsmonitor=false', 'diff', '--numstat', '--no-textconv'",
            "'-c', 'core.fsmonitor=false', 'show', 'HEAD:x'",
            "'-c', 'core.fsmonitor=false', 'status', '--porcelain'",
            "'-c', 'core.fsmonitor=false', 'ls-files', '--stage'",
        ):
            with self.subTest(argv=argv):
                self.assertFalse(self.denied("python3 -I - <<'PY'\nimport subprocess\n"
                                             f"subprocess.run(['git', {argv}], text=True)\nPY\n"))

    def test_literal_git_read_requires_isolation_and_literal_lead(self):
        body = "import subprocess\nsubprocess.run(['git', '-c', 'core.fsmonitor=false', 'rev-parse', 'HEAD'])\n"
        literal_reason = ('process-capable heredoc rule (literal git read needs -I, '
                          'a cd/date/git add lead and a quoted delimiter)')
        start_reason = 'process-capable heredoc rule (interpreter heredoc must start the command)'
        for header, delimiter, reason in (('python3 -', "'PY'", literal_reason),
                                          ('echo x && python3 -I -', "'PY'", start_reason),
                                          ('PYTHONHASHSEED=0 python3 -I -', "'PY'", start_reason),
                                          ('GIT_CONFIG_COUNT=0 python3 -I -', "'PY'", start_reason),
                                          ('python3 -I -', 'PY', literal_reason)):
            with self.subTest(header=header, delimiter=delimiter):
                self.assertTrue(self.denied(header + ' <<' + delimiter + '\n' + body + 'PY\n'))
                self.assertIn(reason, self.reason)

    def test_python_heredoc_header_suffixes_are_denied(self):
        for suffix in ('; true', ' | sh', ' > /w/out.json'):
            with self.subTest(suffix=suffix):
                command = "python3 - <<'PY'" + suffix + "\nprint('git push origin HEAD')\nPY\n"
                self.assertTrue(self.denied(command))
                self.assertIn('unsupported interpreter header', self.reason)

    def test_writer_line_separators_are_denied(self):
        for separator in ('\r', '\v', '\f', '\x1c', '\x1d', '\x1e', '\x85', chr(0x2028), chr(0x2029)):
            with self.subTest(separator=repr(separator)):
                command = ("python3 -I - <<'PY'\nimport subprocess\n"
                           "subprocess.run(['git', 'rev-parse', 'HEAD'])\n# " + separator + 'PY\n'
                           "__import__('subprocess').run(['git', 'pu' + 'sh', 'origin', 'HEAD'])\nPY\n")
                self.assertTrue(self.denied(command))
                self.assertIn('Rule: line separator rule.', self.reason)

    def test_unsupported_heredoc_headers_are_denied(self):
        unsupported_reason = 'process-capable heredoc rule (unsupported interpreter header)'
        start_reason = 'process-capable heredoc rule (interpreter heredoc must start the command)'
        for header, reason in (("python3 - 2>&1 <<'PY'", unsupported_reason),
                               ("python3 -<<'PY'", unsupported_reason),
                               ("python3 - 0<<'PY'", unsupported_reason),
                               ("<<'PY' python3 -", start_reason),
                               ("python3 - <<'PY-END'", unsupported_reason),
                               ("/usr/bin/python3 - <<'PY'", unsupported_reason),
                               ("$PYTHON - <<'PY'", start_reason),
                               ("`which python3` - <<'PY'", start_reason),
                               ("python3 -I - <<'PY' <<'OTHER'", unsupported_reason),
                               ("cat <<'PY' | python3 -", start_reason)):
            with self.subTest(header=header):
                delimiter = 'PY-END' if 'PY-END' in header else 'PY'
                command = (header + "\nimport subprocess\nsubprocess.run(['git', 'pu' + 'sh'])\n"
                           + delimiter + '\n')
                self.assertTrue(self.denied(command))
                self.assertIn(reason, self.reason)

    def test_quoted_cat_commit_message_is_data(self):
        command = ('git commit -m "$(cat <<\'EOF\'\nfix: x\n\n'
                   "- Admit `python3 -I - <<'PY'` bodies.\nEOF\n)\"\n")
        self.assertFalse(self.denied(command))

    def test_commit_stdin_message_is_data(self):
        for lead in ('', 'cd /w/lane && '):
            with self.subTest(lead=lead):
                self.assertFalse(self.denied(lead + "git commit --verbose -F - <<'EOF'\nfix: x\n\n"
                                             "- Admit `python3 -I - <<'PY'` bodies.\nEOF\n"))

    def test_commit_stdin_escaped_delimiter_is_denied(self):
        command = r'''git commit -F - <<"\$X"
fix: x
$X
python3 -I - <<'PY'
import subprocess
subprocess.run(['git', 'pu' + 'sh'])
PY
: <<'TAIL'
\$X
TAIL
'''
        self.assertTrue(self.denied(command))
        self.assertIn('process-capable heredoc rule (commit message heredoc must be the whole command)', self.reason)

    def test_commit_cat_escaped_delimiter_is_denied(self):
        command = r'''git commit -m "$(cat <<"\$X"
fix: x
$X
)"
python3 -I - <<'PY'
import subprocess
subprocess.run(['git', 'pu' + 'sh'])
PY
: <<'TAIL'
\$X
TAIL
'''
        self.assertTrue(self.denied(command))
        self.assertIn('process-capable heredoc rule (commit message heredoc must be the whole command)', self.reason)

    def test_commit_message_after_unclosed_heredoc_is_denied(self):
        command = ("bash <<'SH'\ngit commit -m \"$(cat <<'X'\nSH\npython3 -I - <<'PY'\n"
                   "import subprocess\nsubprocess.run(['git', 'pu' + 'sh'])\nPY\nX\n")
        self.assertTrue(self.denied(command))
        self.assertIn('process-capable heredoc rule (interpreter heredoc must start the command)', self.reason)

    def test_commit_message_after_open_quote_is_denied(self):
        command = ('echo "\ngit commit -m "$(cat <<\'X\'\n"\npython3 -I - <<\'PY\'\n'
                   "import subprocess\nsubprocess.run(['git', 'pu' + 'sh'])\nPY\nX\n")
        self.assertTrue(self.denied(command))
        self.assertIn('process-capable heredoc rule (interpreter heredoc must start the command)', self.reason)

    def test_commit_message_inside_multiline_quote_is_denied(self):
        for header in ("git commit -F - <<'X'", "git commit -m \"$(cat <<'X'"):
            with self.subTest(header=header):
                command = (": '\n" + header + "\n'\npython3 -I - <<'PY'\nimport subprocess\n"
                           "subprocess.run(['git', 'pu' + 'sh'])\nPY\n: '\nX\n'\n")
                self.assertTrue(self.denied(command))
                self.assertIn('process-capable heredoc rule', self.reason)

    def test_interpreter_cat_substitution_is_denied(self):
        unsupported_reason = 'process-capable heredoc rule (unsupported interpreter header)'
        start_reason = 'process-capable heredoc rule (interpreter heredoc must start the command)'
        for consumer, reason in (('python3 -c', unsupported_reason),
                                 ('P=python3; $P -c', start_reason), ('sh -c', start_reason)):
            with self.subTest(consumer=consumer):
                command = (consumer + ' "$(cat <<\'EOF\'\nimport subprocess\n'
                           "subprocess.run(['git', 'pu' + 'sh'])\nEOF\n)\"\n")
                self.assertTrue(self.denied(command))
                self.assertIn(reason, self.reason)

    def test_other_heredoc_headers_keep_scanning(self):
        command = ("sh <<'SH'\npython3 -I - <<'PY'\nimport subprocess\n"
                   "subprocess.run(['git', 'pu' + 'sh'])\nPY\nSH\n")
        self.assertTrue(self.denied(command))
        self.assertIn('Rule: process-capable heredoc rule (interpreter heredoc must start the command).', self.reason)

    def test_git_helper_must_forward_args_at_argv_end(self):
        for argv in ("['git', '-c', 'core.fsmonitor=false', 'diff']",
                     "['git', '-c', 'core.fsmonitor=false', *args, 'diff']"):
            with self.subTest(argv=argv):
                body = ("import subprocess\ndef git(*args):\n"
                        f"    return subprocess.run({argv})\ngit('--name-only')\n")
                self.assertTrue(self.denied("python3 -I - <<'PY'\n" + body + 'PY\n'))
                self.assertIn('Rule: process-capable heredoc rule.', self.reason)

    def test_git_rev_parse_requires_fsmonitor_pair(self):
        for revision in ('HEAD', ':x'):
            with self.subTest(revision=revision):
                body = f"import subprocess\nsubprocess.run(['git', 'rev-parse', {revision!r}])\n"
                self.assertTrue(self.denied("python3 -I - <<'PY'\n" + body + 'PY\n'))
                self.assertIn('fsmonitor rule', self.reason)

    def test_git_show_refuses_separator_and_message_search(self):
        for arguments in ("'--', 'HEAD:x'", "':/message'", "'HEAD:x', ':/'"):
            with self.subTest(arguments=arguments):
                body = ("import subprocess\nsubprocess.run(['git', '-c', 'core.fsmonitor=false', 'show', "
                        + arguments + '])\n')
                self.assertTrue(self.denied("python3 -I - <<'PY'\n" + body + 'PY\n'))
                self.assertIn('literal git read show object', self.reason)

    def test_git_diff_double_separator_has_named_reason(self):
        body = ("import subprocess\nsubprocess.run(['git', '-c', 'core.fsmonitor=false', "
                "'diff', '--name-only', '--', '--'])\n")
        self.assertTrue(self.denied("python3 -I - <<'PY'\n" + body + 'PY\n'))
        self.assertIn('process-capable heredoc rule: literal git read options: --.', self.reason)

    def test_literal_git_read_refuses_unsafe_argv(self):
        for argv in (
            "'pu' + 'sh'", "'push', 'origin', 'HEAD'",
            "'-c', 'core.fsmonitor=true', 'status'",
            "'-c', 'core.fsmonitor=false', 'diff', '--cached', '--name-only', '--output=x'",
            "'-c', 'core.fsmonitor=false', 'diff', '--cached', '--name-only', '--ext-diff'",
            "'-c', 'core.fsmonitor=false', 'show', 'HEAD'",
            "'-c', 'core.fsmonitor=false', 'diff', '--cached'",
            "'-c', 'core.fsmonitor=false', 'diff', '--', '--name-only'",
            "'-c', 'core.fsmonitor=false', 'branch', '-D', 'x'",
            "'-C', '-bad', 'rev-parse', 'HEAD'",
            "'-c', 'alias.x=push', 'rev-parse', 'HEAD'",
            "'diff', '--cached', '--name-only'",
        ):
            with self.subTest(argv=argv):
                for helper in (False, True):
                    body = ("import subprocess\ndef git(*args):\n"
                            "    return subprocess.check_output(['git', *args])\n"
                            f"git({argv})\n" if helper else
                            f"import subprocess\nsubprocess.run(['git', {argv}])\n")
                    self.assertTrue(self.denied("python3 -I - <<'PY'\n" + body + 'PY\n'))
                    self.assertIn('Rule: process-capable heredoc rule.' if argv == "'pu' + 'sh'"
                                  else 'process-capable heredoc rule: ', self.reason)
                    self.assertNotIn('unsupported interpreter header', self.reason)

    def test_literal_git_read_rejects_writes_and_rebinding(self):
        body = "import subprocess\nsubprocess.run(['git', '-c', 'core.fsmonitor=false', 'status'])\n"
        for write in ("open('x', 'w').write('x')", "Path('x').write_text('x')", "Path('x').unlink()",
                      "Path('x').replace('y')", "Path('x').chmod(0o755)", "Path('x').mkdir()"):
            with self.subTest(write=write):
                self.assertTrue(self.denied("python3 -I - <<'PY'\nfrom pathlib import Path\n" + body + write + '\nPY\n'))
                self.assertIn('Rule: process-capable heredoc rule.', self.reason)
        for extra in ("root = '/other'\n", "def f(root):\n    return root\n"):
            command = self.W14.replace("root, *args", "root, '-c', 'core.fsmonitor=false', *args")
            self.assertTrue(self.denied(command.replace("p = 'backend", extra + "p = 'backend")))

    def test_literal_git_read_requires_exact_process_and_helper_forms(self):
        bodies = (
            "import subprocess as sp\nsp.run(['git', 'rev-parse', 'HEAD'])",
            "from subprocess import run\nrun(['git', 'rev-parse', 'HEAD'])",
            "import subprocess\nf = subprocess.run\nf(['git', 'rev-parse', 'HEAD'])",
            "import subprocess\nsubprocess.run(['git', 'rev-parse', 'HEAD'], shell=True)",
            "import subprocess\nsubprocess.run(['git', 'rev-parse', 'HEAD'], text=1)",
            "import subprocess\nsubprocess.run(['git', '--no-pager', 'rev-parse', 'HEAD'])",
            "import subprocess\ns = 'rev-parse'\nsubprocess.run(['git', s, 'HEAD'])",
            "import subprocess\ndef git(*args):\n    return subprocess.run(['git', *args])\ngit(args='status')",
            "import subprocess\ndef git(*args):\n    return subprocess.run(['git', *args])\nf = git\nf('rev-parse')",
            "import subprocess\ndef git(x, *args):\n    return subprocess.run(['git', *args])\ngit('rev-parse')",
            "import subprocess\ndef git(*args):\n    return subprocess.run(['git', *args])\ngit = print\ngit('rev-parse')",
        )
        for body in bodies:
            with self.subTest(body=body):
                self.assertTrue(self.denied("python3 -I - <<'PY'\n" + body + '\nPY\n'))
                self.assertIn('process-capable heredoc rule', self.reason)
                self.assertNotIn('unsupported interpreter header', self.reason)
        for header in ('''python -c 'import os; os.system("git "+"pu"+"sh")' ''',
                       "python3 -c 'print(1)'", 'python3 -m module', 'python3 -O -'):
            with self.subTest(header=header):
                self.assertTrue(self.denied(header + " <<'PY'\nimport subprocess\n"
                                           "subprocess.run(['git', 'rev-parse', 'HEAD'])\nPY\n"))

    def test_process_capable_heredocs_on_every_line(self):
        body = "import subprocess\nsubprocess.run(['git', 'pu' + 'sh'])\n"
        for lead in ('', 'echo ready\n'):
            for python in ('python', 'python3', 'python3.14'):
                with self.subTest(lead=lead, python=python):
                    self.assertTrue(self.denied(lead + python + " - <<'PY'\n" + body + 'PY\n'))
                    self.assertIn('process-capable heredoc rule', self.reason)
        self.assertTrue(self.denied("python3 - <<'PY'\nimport subprocess\n"
                                    "subprocess.run(['sh', 'x.sh'])\nPY\ngit status\n"))

    def test_nonpublication_classifier_refusals_grant_zero_replay_or_driver_handoff(self):
        from unittest.mock import patch

        cases = (
            ("python3 - <<'PY'\nimport subprocess\nsubprocess.run(['sh', 'synthetic.sh'])\nPY\n",
             'process-capable heredoc rule', False),
            ("python3 -I - <<'PY' | sh\nprint('synthetic')\nPY\n",
             'process-capable heredoc rule', False),
            ("python3 - <<'PY'\nopen('synthetic.sh', 'w').write('synthetic')\nPY\nsh synthetic.sh\n",
             'heredoc-then-run rule', False),
            ("node <<'SYNTHETIC'\nsynthetic\nSYNTHETIC\n",
             'process-capable heredoc rule (heredoc reader not on the allowlist)', False),
            ("python3 -c 'import sys; print(sys.argv)'", 'process-capable python -c rule', False),
            ('node -e synthetic', 'inline interpreter code rule', False),
            ('echo synthetic\r', 'line separator rule', False),
            ('echo synthetic', 'classifier exception', True),
        )
        for command, rule, broken_classifier in cases:
            with self.subTest(rule=rule, command=command):
                context = (patch.object(ultraship, 'python_heredoc_shell', side_effect=ValueError('synthetic'))
                           if broken_classifier else contextlib.nullcontext())
                with context:
                    self.assertTrue(self.denied(command))
                self.assertIn('Rule: ' + rule, self.reason)
                self.assertRegex(self.reason, r'(?i)(?:operation|scope).*denied')
                self.assertRegex(self.reason, r'(?i)zero.*(?:alternate|alternative).*(?:form|actor)')
                self.assertRegex(self.reason, r'(?i)cause.*resolution.*fresh.*disposition')
                self.assertNotIn('Return this step to your driver', self.reason)
                self.assertNotIn('the driver may run it', self.reason)

    def test_publication_refusal_retains_publication_specific_driver_handoff(self):
        for command in ('git push origin HEAD', 'npm publish'):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('Writers never push, run `/merge` or `gh pr merge`, deploy, publish, or release;',
                              self.reason)
                self.assertIn('Return this step to your driver; the driver may run it.', self.reason)

    def test_named_writer_denial_rules(self):
        cases = (
            ("python3 - <<'PY'\nimport subprocess\nsubprocess.run(['sh', 'x.sh'])\nPY\n",
             'process-capable heredoc rule'),
            ('git push origin HEAD', 'git remote writer rule (push)'),
            ("python3 - <<'PY'\nopen('x.sh', 'w').write('x')\nPY\nsh x.sh\n", 'heredoc-then-run rule'),
            ('npm publish', "WRITER_BASH 'npm publish'"),
        )
        for command, reason in cases:
            with self.subTest(reason=reason):
                self.assertTrue(self.denied(command))
                self.assertIn(reason, self.reason)
        self.assertTrue(self.denied("python3 - <<'PY'\nimport subprocess\n"
                                    "subprocess.run(['git', '-c', 'core.fsmonitor=false', 'diff', '--name-only', '--output=x'])\nPY\n"))
        self.assertIn('literal git read options: --output=x', self.reason)

    def test_inert_python_file_edit_is_file_text(self):
        body = ("p = '.github/scripts/merge-queue-gate-status.test.mjs'\n"
                "s = open(p).read()\n"
                "s = s.replace('hits.push(a)', 'signals.push({ b: `${c}` })')  # an auto-merge request can merge\n"
                "open(p, 'w').write(s)\n")
        for header in ("python3 - <<'EOF'", 'python3 - <<"EOF"', 'python3 - <<\\EOF', "python3 -I - <<'EOF'",
                       "cd /w/lane-1 && python3 - <<'EOF'"):
            with self.subTest(header=header):
                self.assertFalse(self.denied(f'{header}\nimport re, json\n{body}EOF\n'))

    CLEANUP_SCRIPT = r"""cd /w/ws && python3 -I - <<'PY'
from pathlib import Path
s=Path('/w/ws/.scratch/ship-video/ui-gate')
r=s.parents[2]
t=(r/'.scratch/ship-video/battery-template-s1.sh').read_text().splitlines()
h='\n'.join(t[:24]).replace('ROOT='+str(r/'wt-video'),'ROOT='+str(r))
b=h+'''
for project in video-ui-before video-ui-after; do
 test -z "$(docker ps -aq --filter label=com.docker.compose.project=$project)"
done
git -C "$ROOT/wt-ui-before" status --porcelain
git -C /w/repo worktree remove "$ROOT/wt-ui-before"
echo 'capture worktrees=0'
'''
p=s/'battery-ui-cleanup.sh';p.write_text(b);p.chmod(0o755)
PY
"""
    TOML_APPEND = r"""cd /w/wt && python3 -I - <<'PY'
from pathlib import Path
import subprocess
import tomllib
root = Path('/w/wt')
subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True)
subprocess.check_output(['git', '-C', str(root), 'branch', '--show-current'], text=True)
subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain'], text=True)
text = '\n[[retired]]\nid = "XX01"\nreason = "synthetic"\n'
tomllib.loads(text)
with open(root / 'backend/api/tests/mutation/benchmark-ads.toml', 'ab') as f:
    f.write(text.encode())
PY

"""
    TOML_DIFF = 'git -C /w/wt diff --numstat -- backend/api/tests/mutation/benchmark-ads.toml'

    def test_isolated_cleanup_script_is_file_text(self):
        self.assertFalse(self.denied(self.CLEANUP_SCRIPT))
        start = self.CLEANUP_SCRIPT.index("b=h+'''")
        end = self.CLEANUP_SCRIPT.index("'''\np=s/")
        publication_text = ('gh release create v1\nnpm publish\nvercel deploy --prod\n'
                            'git push origin HEAD\n')
        command = self.CLEANUP_SCRIPT[:start] + "b='''\n" + publication_text + self.CLEANUP_SCRIPT[end:]
        self.assertFalse(self.denied(command))

    def test_cleanup_script_requires_isolation_and_empty_remainder(self):
        start = self.CLEANUP_SCRIPT.index("b=h+'''")
        end = self.CLEANUP_SCRIPT.index("'''\np=s/")
        command = self.CLEANUP_SCRIPT[:start] + "b='''git push origin HEAD\n" + self.CLEANUP_SCRIPT[end:]
        self.assertTrue(self.denied(command.replace('python3 -I -', 'python3 -')))
        for remainder in ('sh x.sh', 'git status', 'git diff --stat', 'wc -l x', 'cat x'):
            with self.subTest(remainder=remainder):
                self.assertTrue(self.denied(command + remainder))

    def test_isolated_computed_paths_keep_reflection_denied(self):
        for expression in ("getattr(p, 'write_text')('git push origin HEAD')",
                           "p.__class__  # git push origin HEAD"):
            with self.subTest(expression=expression):
                command = ("python3 -I - <<'PY'\nfrom pathlib import Path\n"
                           "p = Path('/w') / 'x.sh'\np.chmod(0o755)\n" + expression + '\nPY\n')
                self.assertTrue(self.denied(command))

    def test_isolated_toml_append_and_separate_git_check_are_admitted(self):
        command = r"""cd /w/wt && python3 -I - <<'PY'
import tomllib
text = '\n[[retired]]\nid = "XX01"\nreason = "The PR removed the push retry, so no publish or release path remains."\n'
tomllib.loads(text)
with open('/w/wt/backend/api/tests/mutation/benchmark-ads.toml', 'a') as f:
    f.write(text)
PY
"""
        self.assertFalse(self.denied(command))
        self.assertFalse(self.denied(self.TOML_DIFF))
        self.assertTrue(self.denied(command + self.TOML_DIFF))

    def test_subprocess_toml_append_with_git_check_stays_denied(self):
        self.assertTrue(self.denied(self.TOML_APPEND + self.TOML_DIFF))

    def test_isolated_computed_git_config_with_status_stays_denied(self):
        command = ("python3 -I - <<'PY'\nfrom pathlib import Path\n"
                   "p = Path('/w/wt/.gi' + 't/config')\n"
                   "p.write_text('[core]\\n    fsmonitor = sh x.sh\\n')\nPY\n"
                   'git status --porcelain\n')
        self.assertTrue(self.denied(command))

    def test_writer_publication_commands_stay_denied(self):
        for command in ('git push origin HEAD:refs/heads/x', 'gh pr merge 1 --squash',
                        "gh pr comment 1 --body '/merge fix: x'", 'npm publish',
                        'vercel deploy --prod', 'gh release create v1.0.0'):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))

    def test_isolated_writes_to_loadable_git_or_unresolved_paths_stay_denied(self):
        # Process calls are synthetic classifier input; this test never executes the bodies.
        bodies = (
            "open('lib/python3.13/encodings/rot_13.py', 'w').write('import os; os.system(\"git push origin HEAD\")')\n"
            "b'x'.decode('rot_13')\n",
            "from pathlib import Path\np = Path('.gi' + 't/hooks/pre-commit')\n"
            "p.write_text('git push origin HEAD')\np.chmod(0o755)\n",
            "from pathlib import Path\nd = Path('/w/site-packages')\n"
            "(d / 'zz.pth').write_text('import os; os.system(\"git push origin HEAD\")')\n",
            "from pathlib import Path\np = Path('/w/x.txt')\n"
            "p.write_text('git push origin HEAD')\np.replace('/w/traceback.py')\n",
            "from pathlib import Path\nw = Path('/w/x.sh').write_text\nw('git push origin HEAD')\n",
            "from pathlib import Path\nc = Path\nPath('/w/x.txt').write_text('x')\nc.replace(Path('/w/x.txt'), '/w/traceback.py')\n",
            "import pathlib\npathlib.Path.replace(pathlib.Path('/w/x.txt'), '/w/traceback.py')\n",
            "from pathlib import Path\nPath('/w/x.txt').write_text('x')\n"
            "type(Path('/w/x.txt')).replace(Path('/w/x.txt'), '/w/traceback.py')\n",
        )
        for body in bodies:
            with self.subTest(body=body):
                self.assertTrue(self.denied("cd /usr/local && python3 -I - <<'PY'\n" + body + 'PY\n'))

    def test_isolated_attribute_stores_stay_denied(self):
        # Process calls are synthetic classifier input; this test never executes the bodies.
        bodies = (
            "Path.parent = Path('lib/python3.13/encodings/rot_13.py')\n"
            "Path('/w/x.txt').parent.write_text('import os; os.system(\"git push origin HEAD\")')\n"
            "b'x'.decode('rot_13')\n",
            "Path.parents = [Path('lib/python3.13/encodings/rot_13.py')]\n"
            "Path('/w/x.txt').parents[0].write_text('import os; os.system(\"git push origin HEAD\")')\n"
            "b'x'.decode('rot_13')\n",
            "p = Path('/w/x.txt')\np.parent = 1\np.write_text('git push origin HEAD')\n",
        )
        for body in bodies:
            with self.subTest(body=body):
                command = "cd /usr/local && python3 -I - <<'PY'\nfrom pathlib import Path\n" + body + 'PY\n'
                self.assertTrue(self.denied(command))

    def test_isolated_normalized_path_string_joins_stay_denied(self):
        for body in (
            "open(str(Path('/w/repo/.gi/')) + 't/config', 'a').write('git push origin HEAD')",
            "open(str(Path('/w/traceback.p/')) + 'y', 'w').write('git push origin HEAD')",
        ):
            with self.subTest(body=body):
                command = "cd /usr/local && python3 -I - <<'PY'\nfrom pathlib import Path\n" + body + '\nPY\n'
                self.assertTrue(self.denied(command))

    def test_isolated_path_command_write_with_read_only_consumer_stays_denied(self):
        command = ("python3 -I - <<'PY'\nfrom pathlib import Path\np = Path('/w/bin') / 'wc'\n"
                   "p.write_text('git push origin HEAD')\np.chmod(0o755)\nPY\nwc -l x\n")
        self.assertTrue(self.denied(command))

    def test_bytecode_flags_keep_inert_publication_words_as_file_text(self):
        for flags in self.BYTECODE_FLAGS:
            with self.subTest(flags=flags):
                command = (f"python3 {flags} - <<'EOF'\nfrom pathlib import Path\n"
                           "Path('notes.txt').write_text('git push; npm publish; gh pr merge')\nEOF\n")
                self.assertFalse(self.denied(command))

    def test_bytecode_flags_keep_process_capable_bodies_denied(self):
        for flags in self.BYTECODE_FLAGS:
            with self.subTest(flags=flags):
                command = (f"python3 {flags} - <<'EOF'\nimport subprocess\n"
                           "subprocess.run(['git', 'push'])\nEOF\n")
                self.assertTrue(self.denied(command))

    def test_bytecode_flag_write_then_execute_stays_denied(self):
        command = ("python3 -I -B - <<'EOF'\n"
                   "open('x.sh', 'w').write('git ' + 'pu' + 'sh')\nEOF\nsh x.sh\n")
        self.assertTrue(self.denied(command))

    def test_unlisted_python_options_keep_the_full_scan(self):
        for flags in ('-X dev', '-c', '-m', '-IBX dev', '-O', '-IS', '-i'):
            with self.subTest(flags=flags):
                command = (f"python3 {flags} - <<'EOF'\n"
                           "open('notes.txt', 'w').write('git push')\nEOF\n")
                self.assertTrue(self.denied(command))

    def test_bytecode_flags_keep_non_inert_publication_text_denied(self):
        command = ("python3 -I -B - <<'EOF'\nimport os\n"
                   "print('gh pr merge; npm publish')\nEOF\n")
        self.assertTrue(self.denied(command))

    def test_python_that_can_reach_a_process_keeps_the_scan(self):
        for body in ("__import__('os').system('git push')", "import sys\nsys.modules['os'].system('git push')",
                     "().__class__.__base__.__subclasses__()  # git push", "exec('git push')",
                     "eval('git push')", "getattr(open, 'git push')", "from os import system\nsystem('git push')",
                     "import importlib\nimportlib.import_module('os').system('git push')",
                     "from . import x  # git push", "help('git push')", "print(__builtins__)  # git push"):
            with self.subTest(body=body):
                self.assertTrue(self.denied(f"python3 - <<'EOF'\n{body}\nEOF\n"))
        self.assertTrue(self.denied("python3 - <<EOF\nprint('$(git push)')\nEOF\n"))
        self.assertTrue(self.denied("python3 - <<'EOF'\nprint('git push')\nEOF\ngit push origin HEAD\n"))
        self.assertTrue(self.denied("cd /w && git push && python3 - <<'EOF'\nprint(1)\nEOF\n"))

    def test_reflection_and_write_then_execute_keep_push_denied(self):
        header, end = "python3 - <<'EOF'\n", 'EOF\n'
        # These process-launch strings are classifier input only; the test never executes them.
        commands = (
            header + "from pathlib import os\nos.system('git push origin HEAD')\n" + end,
            header + "import pathlib\npathlib.os.system('git push origin HEAD')\n" + end,
            'cd /w && python3 -I - <<"EOF"\nfrom json import codecs\n'
            "codecs.sys.modules['os'].system('git push')\nEOF\n",
            header + "import string\nf = string.Formatter().get_field('0.__globals__', (string.capwords,), {})[0]\n"
            "f['_re'].enum.sys.modules['os'].system('git push origin HEAD')\n" + end,
            header + "match object:\n    case type(__subclasses__=s):\n        for c in s():\n"
            "            match c:\n                case object(__name__='_wrap_close', __init__=object(__globals__=g)):\n"
            "                    g['system']('git push origin HEAD')\n" + end,
            header + "open('.git/config', 'a').write('[core]\\n\\tfsmonitor = git push origin HEAD\\n')\n"
            + end + 'git status\n',
            header + "open('/tmp/x.sh','w').write('git push origin HEAD')\n" + end + 'sh /tmp/x.sh\n',
            "echo 'a;ps -eo pid,args | awk '$1 ~ /x;git pu${x}sh origin HEAD;/ {print}';echo '",
            "python3() { git push origin HEAD; }; python3 - <<'EOF'\nprint(1)\nEOF\n",
            "alias python3='git push origin HEAD #'\n" + header + 'print(1)\n' + end,
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(ultraship.git_push(command))
                self.assertTrue(self.denied(command))

    def test_attribute_chains_and_shell_consumers_keep_push_denied(self):
        header, end = "python3 - <<'EOF'\n", 'EOF\n'
        # These strings are classifier input; process calls and shell consumers never execute.
        commands = (
            header + "from pathlib import Path\np = Path('.gi' + 't/hooks/pre-commit')\n"
            "p.write_text('#!/bin/sh' + chr(10) + 'git push origin HEAD' + chr(10))\np.chmod(0o755)\n"
            + end + 'git commit -m wip\n',
            header + "from pathlib import Path\nPath('Makefile').write_text('all:' + chr(10) + chr(9) + 'git push origin HEAD' + chr(10))\n"
            + end + 'make\n',
            "true # don't\necho 'a;ps -eo pid,args | awk '$1 ~ /x| git p[u]sh origin HEAD|/ {print}';echo '",
            "echo $'a\\';ps -eo pid,args | awk '$1 ~ /x| git p[u]sh origin HEAD|/ {print}';echo '",
            "cat <<X\n'\nX\necho 'a;ps -eo pid,args | awk '$1 ~ /x| git p[u]sh origin HEAD|/ {print}';echo '",
            ": >push # don't\necho 'a;ps -eo pid,args | awk '$1 ~ /x| git p[u]sh origin HEAD|/ {print}';echo '",
            'git p[u]sh origin HEAD',
            header + "from pathlib import Path\nPath.parser.os.system('git push origin HEAD')\n" + end,
            header + "from pathlib import Path\nPath('.').parser.os.system('git push origin HEAD')\n" + end,
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(ultraship.git_push(command))
                self.assertTrue(self.denied(command))

    def test_heredoc_remainder_allows_only_read_commands(self):
        header = "python3 - <<'EOF'\nopen('x','w').write('git push origin HEAD')\nEOF\n"
        for remainder in ('pytest', '"$SHELL" x', 'make', 'git commit -m wip', 'git status',
                          'true;make', 'true\npytest', 'cat x | ./x', 'sed -i 1p x',
                          "sed -n '1e' x", "sed -n '1w x' x", "sed -n '1p' -e '1e' x",
                          "sed -n '1p;1e' x", 'echo x >x', "sed -n '1'p x", "ec'h'o x", 'cat x"y"', 'cat \'x\'"y"', "sed -n '1p''x' f"):
            with self.subTest(remainder=remainder):
                self.assertFalse(ultraship.read_only_shell(remainder))
                self.assertTrue(self.denied(header + remainder))
        for remainder in ("sed -n '1,3p' x | head -3; grep -n x x", 'cat x\nwc x',
                          "echo x; ls", 'cat x && echo x', 'wc -l x || true'):
            with self.subTest(remainder=remainder):
                self.assertTrue(ultraship.read_only_shell(remainder))
                self.assertFalse(self.denied(header + remainder))

    def test_imported_members_and_formatting_keep_the_scan(self):
        for body in (
            "import pathlib as p\np.os.system('git push')",
            "import pathlib\np = pathlib\np.os.system('git push')",
            "from json import *\nprint('git push')",
            "print('0.__globals__', 'git push')",
            "f = '0.' + '_' * 2 + 'globals' + '_' * 2\nx.get_field(f, (), {})  # git push",
            "f = '0.' + '_' * 2 + 'globals' + '_' * 2\nf.format(x)  # git push",
            "f = '0.' + '_' * 2 + 'globals' + '_' * 2\nf.format_map(x)  # git push",
            "match x:\n    case {'x': y}:\n        print('git push')",
            "open('/w/.git', 'w').write('git push')",
        ):
            with self.subTest(body=body):
                self.assertTrue(self.denied(f"python3 - <<'EOF'\n{body}\nEOF\n"))

    def test_written_files_keep_the_scan_before_execution(self):
        for execution in ('sh /tmp/x.sh', 'bash /tmp/x.sh', 'zsh /tmp/x.sh',
                          'source /tmp/x.sh', '. /tmp/x.sh', 'exec /tmp/x.sh', './x.sh',
                          'python /tmp/x.py', 'python3 /tmp/x.py', '/bin/sh /tmp/x.sh',
                          "sh '/tmp/x.sh'", 'python3 -I /tmp/x.py',
                          'true;sh /tmp/x.sh', 'true&&bash /tmp/x.sh', '$(sh /tmp/x.sh)'):
            command = "python3 - <<'EOF'\nopen('x.sh','w').write('git push origin HEAD')\nEOF\n" + execution
            with self.subTest(execution=execution):
                self.assertTrue(self.denied(command))

    def test_imports_after_a_file_write_keep_the_scan(self):
        for command in (
            "python3 - <<'EOF'\nopen('difflib.py', 'w').write('import os' + chr(10) + 'os.system(\"git push origin HEAD\")' + chr(10))\nimport difflib\nEOF\n",
            "cd /w && python3 - <<'EOF'\nopen('textwrap.py', 'w').write('import os; os.system(\"git push origin HEAD\")')\nfrom textwrap import dedent\nEOF\necho done\n",
            "python3 - <<'EOF'\nif True:\n    import difflib\nopen('x', 'w').write('git push origin HEAD')\nEOF\n",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))

    def test_writes_to_loadable_or_computed_paths_keep_the_scan(self):
        for body in (
            "open('traceback.py', 'w').write('import os' + chr(10) + 'os.system(\"git push origin HEAD\")')\nopen('missing.txt').read()\n",
            "open('traceb' + 'ack.py', 'w').write('git push origin HEAD')\n1 / 0\n",
            "p = 'x.txt'\np = 'traceback.py'\nopen(p, 'w').write('git push origin HEAD')\n",
            "open('lib/site.pth', 'a').write('git push origin HEAD')\n",
            "from pathlib import Path\nPath('x.txt').write_text('git push origin HEAD')\nPath('x.txt').replace('traceback.py')\n",
            "open('x.txt', 'w', opener=None).write('git push origin HEAD')\n",
            "f = open\nf('traceback.py', 'w').write('git push origin HEAD')\n1 / 0\n",
            "open(*['traceback.py', 'w']).write('git push origin HEAD')\n1 / 0\n",
            "o = [open]\no[0]('traceback.py', 'w').write('git push origin HEAD')\n1 / 0\n",
            "from pathlib import Path\nn = 'traceback'\nn += '.py'\nPath(n).write_text('git push origin HEAD')\n1 / 0\n",
            "from pathlib import Path\nn = 'x.txt'\n(lambda n: Path(n).write_text('git push origin HEAD'))('traceback.py')\n1 / 0\n",
            "from pathlib import Path\nn = 'x.txt'\n(n := 'traceback.py')\nPath(n).write_text('git push origin HEAD')\n1 / 0\n",
            "n = 'x.txt'\nfor n in ['traceback.py']:\n    open(n, 'w').write('git push origin HEAD')\n1 / 0\n",
            "n = 'x.txt'\ndef f():\n    global n\n    n = 'traceback.py'\nf()\nopen(n, 'w').write('git push origin HEAD')\n1 / 0\n",
            "n = 'x.txt'\ntry:\n    1 / 0\nexcept ZeroDivisionError as n:\n    pass\nopen(n, 'w').write('git push')\n",
            "from pathlib import Path\nn = 'x.txt'\nif True:\n    n = 'traceback.py'\nPath(n).write_text('git push origin HEAD')\n1 / 0\n",
            "n = 'x.txt'\nif True:\n    n = 'traceback.py'\nopen(n, 'w').write('git push origin HEAD')\n1 / 0\n",
            "from pathlib import Path\nPath('vendor/__init__.py').write_text('git push origin HEAD')\n",
            "open('backend/api/json.py', 'w').write('git push origin HEAD')\n",
        ):
            with self.subTest(body=body):
                self.assertTrue(self.denied("python3 - <<'EOF'\n" + body + "EOF\n"))
        # Another interpreter has other standard-library names than the one this hook runs on.
        for header, path in (('cd /usr/local && python3', 'lib/python3.13/encodings/rot_13.py'),
                             ('python3', 'lib/python3.13/encodings/rot_13.py'),
                             ('cd /usr/lib/python3.13/xml && python3', 'dom/minidom.py')):
            with self.subTest(header=header):
                self.assertTrue(self.denied(
                    f"{header} - <<'EOF'\nopen('{path}', 'w').write('git push origin HEAD')\nb'x'.decode('rot_13')\nEOF\n"))
        for python in ('python', 'python3.14'):
            with self.subTest(python=python):
                self.assertTrue(self.denied(
                    python + " - <<'EOF'\nopen('vendor/mod.py', 'w').write('git push origin HEAD')\nEOF\n"))

    def test_quotes_that_open_no_literal_keep_the_remainder_scan(self):
        write = "python3 - <<'EOF'\nopen('x.txt', 'w').write('gh pr merge 3')\nEOF\n"
        for remainder in ('echo "\'" $(bash x.txt) "\'"\n', "echo \\' $(bash x.txt) \\'\n",
                          "sed -n 1p ';' echo -e e x.txt\n", 'sed -n 1p ";" echo -e e x.txt\n',
                          "sed -n 1p \\; echo -e e x.txt\n", "sed -n 1p [-]e e x.txt\n"):
            with self.subTest(remainder=remainder):
                self.assertTrue(self.denied(write + remainder))

    def test_literal_non_python_write_is_file_text(self):
        command = ("python3 - <<'EOF'\np = 'notes.md'\ns = open(p).read()\n"
                   "open(p, 'w').write(s.replace('git push', 'git status'))\nEOF\n")
        self.assertFalse(self.denied(command))

    def test_pathlib_file_edit_with_push_and_publish_words_is_file_text(self):
        rust = ("    keys.push(code);  // The release job runs cargo publish, gh release create and gh pr merge."
                + chr(92) + "n")
        for body in (
            "from pathlib import Path\np = Path('apps/desktop/src-tauri/src/macos_keys.rs')\n"
            "s = p.read_text()\ns = s.replace('    keys.clear();\\n', '" + rust + "')\np.write_text(s)\n",
            "from pathlib import Path\nPath('notes.md').write_text(Path('notes.md').read_text()"
            ".replace('draft', 'released with docker push and npm publish'))\n",
            "import pathlib\nf = 'src/queue.rs'\npathlib.Path(f).write_text('jobs.push(job);' + chr(10), encoding='utf-8')\n",
        ):
            with self.subTest(body=body):
                self.assertFalse(self.denied("python3 - <<'EOF'\n" + body + "EOF\n"))

    def test_multi_file_pathlib_edits_are_file_text(self):
        readme = ("python3 -I - <<'PY'\nfrom pathlib import Path\n"
                  "p=Path('.github/workflows/ci.yml');s=p.read_text();s=s.replace('a', 'b');p.write_text(s)\n"
                  "p=Path('services/merge-queue/README.md');s=p.read_text();p.write_text(s + 'The publisher `merge` step pushes with a lease.')\n"
                  "PY\nsed -n '1,125p' Makefile && grep -n '^api-lint\\|^api-test:' Makefile\n")
        tests = ("cd /w/lane-1 && python3 - <<'PY'\nfrom pathlib import Path\n"
                 "Path('backend/api/tests/test_decision_native.py').unlink()\n"
                 "p = Path('backend/api/tests/decision_custody.md')\n"
                 "s = p.read_text().replace('x', '    from evals.decisions import __main__ as command')\n"
                 "s += '''\n\ndef test_missing_git(monkeypatch):\n    def missing_git(*args, **kwargs):\n"
                 "        raise FileNotFoundError(\"git\")\n    [call] = run()\n    assert [call] == [{\"code\": \"git_state_unavailable\"}]\n'''\n"
                 "p.write_text(s)\n"
                 "PY\nsed -n '30,95p' backend/api/evals/decisions/offline.py\n")
        single = ("cd /w/lane-1 && python3 - <<'PY'\np = 'backend/api/tests/queue.md'\n"
                  "open(p, 'w').write('''def f():\n    raise FileNotFoundError(\"git\")\n    [x] = [1]\n''')\nPY\n")
        for command in (readme, tests, single):
            with self.subTest(command=command):
                self.assertFalse(self.denied(command))
        # Python can import a module written moments earlier, so a module file is never file text.
        for command in (tests.replace('decision_custody.md', 'test_decision_custody.py'),
                        single.replace('queue.md', 'test_queue.py'),
                        "python3 - <<'EOF'\nopen('scripts/review_probe.py', 'w').write('git push origin HEAD')\n"
                        "raise ImportError('missing', name='scripts.review_probe', name_from='missing')\nEOF\n"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))

    LOOP_EDIT = ("cd /w/lane-1 && python3 - <<'PY'\nfrom pathlib import Path\n"
                 "edits = {'a.md': [('old push', 'new push')], 'b.md': [('a', 'push')]}\n"
                 "for name in ('writer.md', 'driver.md'):\n"
                 "    edits['plugins/ship/agents/' + name] = [('old', 'push')]\n"
                 "for name, pairs in edits.items():\n"
                 "    path = Path(name)\n"
                 "    text = path.read_text()\n"
                 "    for old, new in pairs:\n"
                 "        assert text.count(old) == 1, (name, old)\n"
                 "        text = text.replace(old, new)\n"
                 "    path.write_text(text)\nPY\n")

    def test_loop_built_file_edits_are_file_text(self):
        self.assertFalse(self.denied(self.LOOP_EDIT))

    def test_saved_combined_command_stays_denied(self):
        command = r"""cd /w/lane-1 && python3 - <<'PY'
from pathlib import Path
edits = {
'plugins/ship/skills/ship/references/pipeline.md': [
("3. At the lane's first commit, push it with the [resolved destination preflight](#9-push-and-pr) and open a draft PR at once, so CI and review run while the lane builds.", "3. At the lane's first commit, push it with the [resolved destination preflight](#9-push-and-pr) and open a draft PR, so CI starts while the lane builds."),
('4. Update the draft PR from step 3, or open it now if none exists. Put scope, behavior, verification steps, and risks in the body. Mark it ready after the last code commit and any row update.', '4. Update the draft PR from [step 3](#3-slices), or open it now if none exists. Put scope, behavior, verification steps, and risks in the body. Mark it ready right after this push, before step 10, unless the brief holds the lane draft-only.')],
'plugins/ship/skills/ship/SKILL.md': [
('Batch actionable and terminal reports; keep unchanged routine reports silent, except one: from the first push until merge, report to the parent every 15 minutes, day and night, even when nothing changed.\nKeep one background `watchers.py wait` on the PR armed with `--max-seconds 900` or less, so the driver wakes to report.', 'Batch actionable and terminal reports; keep unchanged routine reports silent.'),
('Repeat only when a later fix or a main merge moves an anchored line.', 'Repeat only when a later commit moves an anchored line.')],
'plugins/ship/skills/ship/references/ci-and-locks.md': [
('--max-seconds <remaining-stage-seconds>', '--max-seconds <the smaller of 600 and the remaining stage seconds>'),
('Messages contain only a state transition, a blocker, or a decision need.', "Messages contain only a state transition, a blocker, a decision need, or a driver's timed report.")],
'plugins/ship/skills/babysit/SKILL.md': [
('Messages contain only transitions, blockers, or decision needs.', "Messages contain only transitions, blockers, decision needs, or the driver's timed report."),
('Send all `real` items to `ship:writer--sol` as one batch within 1 hour of the review; checks still pending then join the next round.', 'Send all `real` items to `ship:writer--sol` as one batch, and push the fix within 1 hour of the review that raised them. Stop the step 2 wait in time for that deadline; checks still pending then join the next round.')],
'plugins/chief/skills/run/SKILL.md': [
('Replace a PR driver that sends no report for 15 minutes: stop it by its recorded identity, then dispatch `ship:driver` on the same lane in that turn. Keep a harness-supported wake within 15 minutes while a PR driver runs.', 'Replace a PR driver that sends no report for 15 minutes before merge: stop it, its writers, and its wait by recorded identity, apply [WIP recovery](references/state.md#wip-recovery), then dispatch `ship:driver` on the same lane in the same turn. An unchanged report needs no other chief action. Arm one single-shot background wake for the earliest time a PR driver turns silent, and rearm it after each report; this liveness timer reads no GitHub state.')],
'plugins/chief/skills/run/references/dispatch.md': [
('Batch actionable and terminal reports per recipient; keep unchanged routine reports silent.', "Batch actionable and terminal reports per recipient; keep unchanged routine reports silent. A PR driver's timed report under the ship driver definition is the one exception.")],
'plugins/ship/README.md': [
('3. Write each slice, test it, and review it.', '3. Write each slice, test it, and review it. The first commit opens a draft PR.'),
('9. Merge main, run full checks, push, open the PR.', '9. Merge main, run full checks, push, mark the PR ready.')],
'README.md': [
('├─ ship:writer--sol writes each slice', '├─ ship:writer--sol writes each slice; the first commit opens a draft PR'),
('├─ push, PR, /ship:babysit (CI + Better Review)', '├─ push, mark the PR ready, /ship:babysit (CI + Better Review)')],
}
for name in ('writer--sol.md', 'writer--sonnet.md', 'writer--fable52.md'):
    edits['plugins/ship/agents/' + name] = [("- Commit only when the brief grants commits. Before every commit, auto-format the changed files with the repository's formatters, such as `ruff format` for Python and Prettier for frontend files. Follow the repository's commit style and attribution rules.", "- Commit only when the brief grants commits. Before every commit except a base merge, auto-format the hand-written files you changed with the formatters that the repository's CI or hooks check, such as `ruff format` and the frontend formatter. Never format generated files. Follow the repository's commit style and attribution rules.")]
paragraph = "From the first push until merge, report to your parent at least every 15 minutes, day and night, even when nothing changed; this report overrides every silent-report and message-content rule. Run helpers and long commands in the background, and keep one [`watchers.py wait`](../skills/ship/references/ci-and-locks.md#github-quota) on the PR armed, so you wake in time."
for name in ('driver.md', 'driver--sol.md'):
    edits['plugins/ship/agents/' + name] = [('\nReturn a checkpoint:', '\n' + paragraph + '\n\nReturn a checkpoint:')]
for name, pairs in edits.items():
    path = Path(name)
    text = path.read_text()
    for old, new in pairs:
        assert text.count(old) == 1, (name, old)
        text = text.replace(old, new)
    path.write_text(text)
PY
 git diff --check && git diff --stat
"""
        self.assertTrue(self.denied(command))
        self.assertFalse(self.denied(command.removesuffix(' git diff --check && git diff --stat\n')))

    def test_loop_paths_accept_only_known_writable_values(self):
        for iterator in ("('a.md', 'b.md')", "['a.md', 'b.md']", "{'a.md', 'b.md'}",
                         'edits', 'edits.keys()'):
            with self.subTest(iterator=iterator):
                command = self.LOOP_EDIT.replace('for name, pairs in edits.items():', f'for name in {iterator}:')
                self.assertFalse(self.denied(command))
        for command in (
            self.LOOP_EDIT.replace("'plugins/ship/agents/' + name", "'x' + '.py'"),
            self.LOOP_EDIT.replace("'a.md'", "'sitecustomize.py'"),
            self.LOOP_EDIT.replace('for name, pairs', "other = edits\nother['a.py'] = []\nfor name, pairs"),
            self.LOOP_EDIT.replace('for name, pairs', "edits |= {'a.py': []}\nfor name, pairs"),
            self.LOOP_EDIT.replace('for name, pairs in edits.items():',
                                   "for name in open('list.txt').read().split():"),
        ):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))

    def test_loop_edits_keep_executable_publication_denied(self):
        self.assertTrue(self.denied(self.LOOP_EDIT + ' && git push origin HEAD'))
        self.assertTrue(self.denied(self.LOOP_EDIT.replace('from pathlib import Path',
                                                          'from pathlib import Path\nimport subprocess')))

    def test_loop_dict_uses_keep_unknown_keys_denied(self):
        for statement in ("edits = {'c.md': []}", 'print(edits)', "del edits['a.md']",
                          "edits.pop('a.md')", 'alias = edits.items', "edits['a.md'] += []",
                          "edits[unknown] = []", "edits[('a.md',)] = []"):
            with self.subTest(statement=statement):
                self.assertTrue(self.denied(self.LOOP_EDIT.replace('for name, pairs', statement + '\nfor name, pairs')))

    def test_loop_targets_and_holders_keep_rebinding_denied(self):
        for command in (
            self.LOOP_EDIT.replace('    path = Path(name)', "    name = 'a.py'\n    path = Path(name)"),
            self.LOOP_EDIT.replace('    path = Path(name)', "    path = Path(name)\n    path = Path('a.md')"),
            self.LOOP_EDIT.replace('    text = path.read_text()', '    alias = path\n    text = path.read_text()'),
            self.LOOP_EDIT.replace('for name, pairs in edits.items():', 'for (name,), pairs in edits.items():'),
            self.LOOP_EDIT.replace('path.write_text(text)', 'path.write_text(text, **options)'),
            self.LOOP_EDIT.replace('for name, pairs in edits.items():',
                                   "def f():\n    global name\n    name = 'traceback.py'\n"
                                   'for name, pairs in edits.items():')
            .replace('    path = Path(name)', '    f()\n    path = Path(name)')
            .replace('PY\n', 'for d[name] in ():\n    pass\nfor d[name] in ():\n    pass\nPY\n'),
        ):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))

    def test_loop_paths_refuse_unknown_or_empty_values(self):
        for iterator in ('()', "('a.md', 1)", "('a.py',)", 'edits.items()', 'unknown',
                         "[name for name in ('a.md',)]"):
            with self.subTest(iterator=iterator):
                command = self.LOOP_EDIT.replace('for name, pairs in edits.items():', f'for name in {iterator}:')
                self.assertTrue(self.denied(command))
        command = self.LOOP_EDIT.replace("'a.md': [('old push', 'new push')], 'b.md': [('a', 'push')]", '')
        command = command.replace("    edits['plugins/ship/agents/' + name] = [('old', 'push')]", '    pass  # git push')
        self.assertTrue(self.denied(command))

    def test_loop_key_concatenation_checks_every_combination(self):
        command = self.LOOP_EDIT.replace("'plugins/ship/agents/' + name", "'plugins/' + name + '.md'")
        self.assertFalse(self.denied(command))
        command = self.LOOP_EDIT.replace("('writer.md', 'driver.md')", "('writer.md', 'driver.py')")
        self.assertTrue(self.denied(command))

    def test_loop_key_concatenation_keeps_git_paths_denied(self):
        command = self.LOOP_EDIT.replace("'plugins/ship/agents/' + name", "'.gi' + 't/config'")
        self.assertTrue(self.denied(command))

    def test_loop_edits_keep_git_diff_remainders_denied(self):
        body = self.LOOP_EDIT
        for remainder in ('git diff --check', 'git diff --stat', 'git diff --check -- a.md',
                          'git diff --stat -- plugins/ship/agents/a.md'):
            with self.subTest(remainder=remainder):
                self.assertTrue(self.denied(body + remainder))
        for remainder in ('git diff', 'git diff --ext-diff', 'git status', 'git log',
                          'git diff --stat > out.txt', 'git -c core.pager=cat diff --stat',
                          'git diff --stat --ext-diff', 'git diff --stat HEAD..main',
                          'git diff --check HEAD'):
            with self.subTest(remainder=remainder):
                self.assertTrue(self.denied(body + remainder))

    def test_git_configuration_edits_keep_diff_remainders_denied(self):
        commands = (
            "python3 - <<'EOF'\nopen('/home/u/.gitconfig', 'a').write("
            "'[core]\\n    fsmonitor = git push origin HEAD\\n')\nEOF\ngit diff --stat\n",
            "python3 - <<'EOF'\nopen('.gitattributes', 'w').write('* filter=x\\n')\n"
            "open('/home/u/.gitconfig', 'a').write('[filter \\\"x\\\"]\\n    clean = git push origin HEAD\\n')\n"
            'EOF\ngit diff --check\n',
            "cat <<'EOF' >> /home/u/.gitconfig\n[core]\n    fsmonitor = git push origin HEAD\n"
            'EOF\ngit diff --stat\n',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))

    def test_loop_key_work_limits_keep_publication_denied(self):
        for count, names in ((40, "('a', 'b')"), (1200, "('a',)")):
            with self.subTest(count=count):
                key = ' + '.join(['n'] * count)
                command = ("python3 - <<'EOF'\nfrom pathlib import Path\nedits = {'a.md': []}\n"
                           f'for n in {names}:\n    edits[{key}] = []\n'
                           'for name, pairs in edits.items():\n    path = Path(name)\n'
                           "    path.write_text('git push')\nEOF\n && git push origin HEAD")
                self.assertTrue(self.denied(command))

    def test_loop_key_product_limit_accepts_256_and_refuses_512(self):
        def balanced(count):
            if count == 1:
                return 'n'
            left = count // 2
            return f'({balanced(left)} + {balanced(count - left)})'

        for count, expected in ((8, True), (9, False)):
            with self.subTest(count=count):
                body = ("from pathlib import Path\nedits = {'a.md': []}\n"
                        f"for n in ('a', 'b'):\n    edits[{balanced(count)}] = []\n"
                        'for name, pairs in edits.items():\n    path = Path(name)\n'
                        "    path.write_text('git push')\n")
                self.assertEqual(ultraship.inert_python(body), expected)

    def test_writer_bash_classifier_exception_denies_plain_command(self):
        from unittest.mock import patch

        with patch.object(ultraship, 'python_heredoc_shell', side_effect=ValueError('classifier failed')):
            self.assertTrue(self.denied('echo hi'))
            self.assertIn('classifier exception', self.reason)

    def test_read_only_loop_paths_are_file_text(self):
        command = ("python3 - <<'EOF'\nfrom pathlib import Path\n"
                   "for name in ('plugins/ship/hooks/ultraship.py', 'scripts/test_writer_heredoc.py'):\n"
                   "    print(Path(name).read_text().count('git push'))\nEOF\n")
        self.assertFalse(self.denied(command))

    def test_python_writes_that_python_can_import_keep_the_scan(self):
        for path in ('traceback.py', 'traceback/__init__.py', 'Traceback/__init__.py', 'json/decoder.py',
                     '../traceback.py', 'x/../traceback.py', '/tmp/w/traceback.py', 'lib/site.pth', 'x/y.so'):
            for body in ("from pathlib import Path\nPath('" + path + "').write_text('git push origin HEAD')\n1 / 0\n",
                         "open('" + path + "', 'w').write('git push origin HEAD')\n1 / 0\n"):
                with self.subTest(body=body):
                    self.assertTrue(self.denied("python3 - <<'EOF'\n" + body + "EOF\n"))
        for body in ("from pathlib import Path\np = Path('notes.md')\np = Path('traceback.py')\np.write_text('git push')\n",
                     "from pathlib import Path\np = Path('notes.md')\np = 'traceback.py'\nopen(p, 'w').write('git push')\n",
                     "from pathlib import Path\np = Path('notes.md')\nif p.exists():\n    p = Path('traceback.py')\np.write_text('git push')\n",
                     "x = '__import__'  # git push\n", "x = '0.' + '__globals__'  # git push\n",
                     "x = '{0[__builtins__]}'  # git push\n"):
            with self.subTest(body=body):
                self.assertTrue(self.denied("python3 - <<'EOF'\n" + body + "EOF\n"))

    def test_pathlib_writes_that_escape_a_literal_path_keep_the_scan(self):
        for body in (
            "from pathlib import Path\nPath('traceback.py').write_text('git push origin HEAD')\n1 / 0\n",
            "from pathlib import Path\np = Path('x.txt')\np.open('w').write('git push origin HEAD')\n",
            "from pathlib import Path\np = Path('x.txt')\nq = p\nq.replace('traceback.py')  # git push\n",
            "from pathlib import Path\nP = Path\nP('traceback.py').write_text('git push origin HEAD')\n",
            "from pathlib import Path as P\nP('traceback.py').write_text('git push origin HEAD')\n1 / 0\n",
            "from pathlib import Path as Q, Path\nQ('traceback.py').write_text('git push origin HEAD')\n1 / 0\n",
            "from pathlib import Path\n(Path('d') / 'traceback.py').write_text('git push origin HEAD')\n",
            "from pathlib import Path\nn = 'trace' + 'back.py'\nPath(n).write_text('git push origin HEAD')\n",
            "from pathlib import Path\np = Path('x.txt')\np = Path('traceback.py')\np.write_text('git push')\n",
            "from pathlib import Path\nPath('x.txt').write_text('git push', **{'errors': 'strict'})\n",
            "from pathlib import Path\nPath = open\nPath('traceback.py', 'w').write('git push origin HEAD')\n",
            "from pathlib import Path\nPath('x.txt').parent.write_text('git push origin HEAD')\n",
            "from pathlib import Path\nfor p in [Path('x.txt')]:\n    p.replace('traceback.py')  # git push\n",
        ):
            with self.subTest(body=body):
                self.assertTrue(self.denied("python3 - <<'EOF'\n" + body + "EOF\n"))

    def test_publish_commands_beside_file_text_stay_denied(self):
        edit = "python3 - <<'EOF'\nfrom pathlib import Path\nPath('notes.md').write_text('gh pr merge')\nEOF\n"
        for command in (edit + 'gh pr merge 3 --squash', edit + 'cargo publish', edit + 'npm publish',
                        "python3 - <<'EOF'\nimport subprocess\nsubprocess.run(['gh', 'pr', 'merge', '3'])\nEOF\n",
                        "python3 - <<EOF\nprint('$(gh pr merge 3)')\nEOF\n",
                        "cat <<'EOF' | bash\ngh pr merge 3\nEOF\n"):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))

    def test_plain_expansion_beside_a_push_containing_path_is_admitted(self):
        for command in ('head -40 "$S"/prepush-results.txt', 'cat $S/prepush-results.txt && git status'):
            with self.subTest(command=command):
                self.assertFalse(ultraship.git_push(command))
        for command in ('X=prepush; git ${X#pre}', 'X=prepush; git ${X:3}', 'IFS=e; X=.epush; git -C $X',
                        'X=push; git $X', "git $'push'", 'git pus?', 'git {push,}', 'S=". push"; git -C $S',
                        'G=/usr/lib/git-core/git-; "$G"push origin HEAD', 'G=/usr/lib/git-core/git-; ${G}push origin HEAD',
                        'G=/usr/lib/git-core/git-; "$G"pu\\sh origin HEAD', 'G=/usr/lib/git-core/git-; ${G}p\\ush origin HEAD',
                        'printf -v G %spush /usr/lib/git-core/git-; "$G" origin HEAD',
                        'read G <<< %spush; "$G" origin HEAD', 'declare G=x; "$G"push',
                        "p''rintf -v G %spush /usr/lib/git-core/git-; \"$G\" origin HEAD",
                        'pr"i"ntf -v G %spush /usr/lib/git-core/git-; $G origin HEAD',
                        'print -v G -f %spush /usr/lib/git-core/git-; "$G" origin HEAD'):
            with self.subTest(command=command):
                self.assertTrue(ultraship.git_push(command))

    def test_heredoc_remainder_refuses_subscript_evaluating_commands(self):
        for remainder in ("printf -v a 1\n", "test -v a\n", "[ -v a ]\n"):
            with self.subTest(remainder=remainder):
                self.assertFalse(ultraship.read_only_shell(remainder))

    def test_teams_process_filter_with_prior_quoted_output_is_admitted(self):
        command = ("git status --porcelain; printf 'ACTIVE_GIT_WRITERS\\n'; "
                   '''ps -eo pid,ppid,comm,args | awk '$3 == "git" && $0 ~ / (merge|commit|apply|cherry-pick|rebase)( |$)/ {print}' ''')
        self.assertFalse(ultraship.git_push(command))
        self.assertFalse(self.denied(command))

    def test_awk_filter_quote_boundaries_and_expansions_keep_the_scan(self):
        for command in (
            '''echo "a;ps -eo pid,args | awk '$1 ~ /x;git pu${x}sh origin HEAD;/ {print}';echo "''',
            '''ps -eo pid,args | awk '$3 == "git" && $0 ~ / $(git pu${x}sh)/ {print}' ''',
            '''ps -eo pid,args | awk '$3 == "git" && $0 ~ / ${x:-git pu${x}sh}/ {print}' ''',
            '''echo "$(echo ')";ps -eo pid,args | awk '$1 ~ /x| git p[u]sh origin HEAD|/ {print}';echo ')"''',
            ''': >push; echo "${x:-"'"}" 'a;ps -eo pid,args | awk '$1 ~ /x| git p[u]sh origin HEAD|/ {print}';echo ' ''',
        ):
            with self.subTest(command=command):
                self.assertTrue(ultraship.git_push(command))
                self.assertTrue(self.denied(command))

    def test_real_push_after_heredoc_is_denied(self):
        for operator, delimiter, indent in (('<<', "'EOF'", ''), ('<<', 'EOF', ''),
                                            ('<<-', 'EOF', '\t')):
            command = f'python3 - {operator}{delimiter}\n{indent}print(1)\n{indent}EOF\ngit push origin HEAD\n'
            with self.subTest(operator=operator, delimiter=delimiter):
                self.assertTrue(self.denied(command))

    def test_heredoc_boundaries_preserve_executable_shell_text(self):
        commands = (
            "cat <<'ONE' <<-'TWO'\ndata\nONE\n\tdata\n\tTWO\ngit push\n",
            "python3 - <<'EOF'; git push\nprint(1)\nEOF\n",
            "python3 - <<EOF\n$(git push)\nEOF\n",
            "python3 - <<EOF\n`git push`\nEOF\n",
            "python3 - <<EOF\nprint(1)\nE\\\nOF\ngit push origin HEAD\nEOF\n",
            "bash <<'EOF'\ngit push\nEOF\n",
            "python3 - <<'EOF'\nimport subprocess\nsubprocess.run(['git', 'push'])\nEOF\n",
            "python3 - <<'EOF'\nimport os\nos.system('git push')\nEOF\n",
            "python3 - <<'EOF'\nimport os\nos.system('git pu\\\nsh')\nEOF\n",
            "python3 - <<'EOF'\nimport os\nos.environ['X'] = 'u'\nos.system('git p${X}sh origin HEAD')\nEOF\n",
            "python3 - <<'EOF'\nimport os\nos.system('git p{u,}sh origin HEAD')\nEOF\n",
            "python3 - <<'EOF'\nimport os\nos.system('git pu\"\"sh')\nEOF\n",
            "python3 - <<'EOF'\nprint(1)\nEOF git push\n",
            "echo '<<EOF'; git push\n",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))

    def test_partly_quoted_commit_hides_fake_python_header_is_denied(self):
        command = ("git commit -F - <<'E'F\npython3 - <<'FAKE'\ns = \"\"\"\nEF\n"
                   "python3 -I - <<'PY'\nimport subprocess\nsubprocess.run(['git', 'pu' + 'sh'])\n"
                   "PY\n: <<'TAIL'\n\"\"\"\nFAKE\nTAIL\n")
        self.assertTrue(self.denied(command))
        self.assertIn('process-capable heredoc rule (commit message heredoc must be the whole command)',
                      self.reason)

    def test_fake_python_header_in_cat_or_tee_body_is_denied(self):
        for header in ("cat > /dev/null <<'EOF'", "tee x.txt <<'EOF'", 'cat <<EOF >/dev/null'):
            with self.subTest(header=header):
                command = (header + "\npython3 - <<'FAKE'\ns = \"\"\"\nEOF\n"
                           "python3 -I - <<'PY'\nimport subprocess\nsubprocess.run(['git', 'pu' + 'sh'])\n"
                           "PY\n: <<'TAIL'\n\"\"\"\nFAKE\nTAIL\n")
                self.assertTrue(self.denied(command))
                self.assertIn('process-capable heredoc rule (interpreter heredoc must start the command)',
                              self.reason)

    def test_fake_python_header_in_second_line_commit_body_is_denied(self):
        command = ("echo ready\ngit commit -F - <<'EOF'\npython3 - <<'FAKE'\ns = \"\"\"\nEOF\n"
                   "python3 -I - <<'PY'\nimport subprocess\nsubprocess.run(['git', 'pu' + 'sh'])\n"
                   "PY\n: <<'TAIL'\n\"\"\"\nFAKE\nTAIL\n")
        self.assertTrue(self.denied(command))
        self.assertIn('process-capable heredoc rule (interpreter heredoc must start the command)',
                      self.reason)

    def test_fake_python_header_in_open_double_quote_is_denied(self):
        for header in ('echo "python3 - <<\'FAKE\'', 'echo "\npython3 - <<\'FAKE\''):
            with self.subTest(header=header):
                command = (header + '\ns = """\n' + "python3 -I - <<'PY'\nimport subprocess\n"
                           "subprocess.run(['git', 'pu' + 'sh'])\nPY\n: <<'TAIL'\n\"\"\"\nFAKE\nTAIL\n")
                self.assertTrue(self.denied(command))
                self.assertIn('process-capable heredoc rule (interpreter heredoc must start the command)',
                              self.reason)

    def test_unquoted_python_heredoc_command_substitution_is_denied(self):
        command = ("python3 - <<PY\n"
                   "print('''$(python3 -c \"import subprocess; subprocess.run(['git', 'pu' + 'sh'])\")''')\n"
                   "PY\n")
        self.assertTrue(self.denied(command))
        self.assertIn('process-capable heredoc rule (Python heredoc needs a quoted delimiter)', self.reason)

    def test_unquoted_python_heredoc_joined_terminator_is_denied(self):
        command = ("python3 - <<EOF\ns = '''\nE\\\nOF\npython3 -I - <<'PY'\n"
                   "import subprocess\nsubprocess.run(['git', 'pu' + 'sh'])\nPY\n: <<'TAIL'\n'''\nEOF\nTAIL\n")
        self.assertTrue(self.denied(command))
        self.assertIn('process-capable heredoc rule (Python heredoc needs a quoted delimiter)', self.reason)

    def test_commit_cat_delimiter_prefix_early_end_is_denied(self):
        command = ('git commit -m "$(cat <<\'EOF\'\nfix: x\nEOF)"\n'
                   "python3 -I - <<'PY'\nimport subprocess\nsubprocess.run(['git', 'pu' + 'sh'])\n"
                   'PY\n: "\nEOF\n)"\n')
        self.assertTrue(self.denied(command))
        self.assertIn('process-capable heredoc rule (commit message heredoc must be the whole command)',
                      self.reason)

    def test_commit_stdin_delimiter_prefix_message_is_denied(self):
        command = "git commit -F - <<'EOF'\nfix: x\nEOF)\nEOF\n"
        self.assertTrue(self.denied(command))
        self.assertIn('process-capable heredoc rule (commit message heredoc must be the whole command)',
                      self.reason)


if __name__ == '__main__':
    unittest.main()
