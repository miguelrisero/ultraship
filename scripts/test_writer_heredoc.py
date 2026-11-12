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
    BYTECODE_FLAGS = ('-I -B', '-B -I', '-B', '-IB', '-BI')

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


if __name__ == '__main__':
    unittest.main()
