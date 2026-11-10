"""Writer publication decisions for heredoc data and executable shell text."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ultraship_heredoc', ROOT / 'plugins/ship/hooks/ultraship.py')
ultraship = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ultraship)


class WriterHeredocTests(unittest.TestCase):
    def denied(self, command):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            try:
                ultraship.pre({'agent_type': 'ship:writer--sol', 'tool_name': 'Bash',
                               'tool_input': {'command': command}})
            except SystemExit as error:
                self.assertEqual(error.code, 0)
        text = output.getvalue()
        return bool(text and json.loads(text)['hookSpecificOutput']['permissionDecision'] == 'deny')

    def test_python_helper_in_heredoc_is_data(self):
        body = "def git(*args):\n    return subprocess.check_output(['git', *args])\n"
        for operator, delimiter, indent in (('<<', 'EOF', ''), ('<<', "'EOF'", ''),
                                            ('<<', '"EOF"', ''), ('<<', '\\EOF', ''),
                                            ('<<-', "'EOF'", '\t')):
            with self.subTest(operator=operator, delimiter=delimiter):
                script = indent + body.replace('\n', '\n' + indent).rstrip('\t')
                self.assertFalse(self.denied(f'python3 - {operator}{delimiter}\n{script}{indent}EOF\n'))

    def test_inert_python_file_edit_is_file_text(self):
        body = ("p = '.github/scripts/merge-queue-gate-status.test.mjs'\n"
                "s = open(p).read()\n"
                "s = s.replace('hits.push(a)', 'signals.push({ b: `${c}` })')  # an auto-merge request can merge\n"
                "open(p, 'w').write(s)\n")
        for header in ("python3 - <<'EOF'", 'python3 - <<"EOF"', 'python3 - <<\\EOF', "python3 -I - <<'EOF'",
                       "cd /w/lane-1 && python3 - <<'EOF'"):
            with self.subTest(header=header):
                self.assertFalse(self.denied(f'{header}\nimport re, json\n{body}EOF\n'))

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
                          "sed -n '1p;1e' x", 'echo x >x', "sed -n '1'p x", "ec'h'o x", 'cat x"y"'):
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


if __name__ == '__main__':
    unittest.main()
