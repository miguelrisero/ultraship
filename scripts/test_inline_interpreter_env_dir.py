"""Inline interpreter decisions for relative scripts after an env directory change."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ultraship_env_dir', ROOT / 'plugins/ship/hooks/ultraship.py')
ultraship = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ultraship)


class EnvDirectoryTests(unittest.TestCase):
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

    def test_python_version_after_independent_pipeline_is_admitted(self):
        for command in (
            'python3 --version',
            'printf sample | cat; python3 --version',
            'printf sample | cat && python3 --version',
        ):
            with self.subTest(command=command):
                self.assertFalse(self.denied(command), self.reason)

    def test_python_version_exemption_preserves_program_refusals(self):
        for command, rule in (
            ('printf sample | python3', 'inline interpreter code rule (program from a pipe)'),
            ('printf sample | python3 -', 'inline interpreter code rule (program from a pipe)'),
            ('printf x | python3 --version', 'inline interpreter code rule (program from a pipe)'),
            ('printf x | xargs python3 --version', 'inline interpreter code rule (program from a pipe)'),
            ('printf x | xargs node --version', 'inline interpreter code rule (program from a pipe)'),
            ('printf x | env python3 --version', 'inline interpreter code rule (program from a pipe)'),
            ('printf x | cat; env python3 --version', 'inline interpreter code rule (program from a pipe)'),
            ("printf x | sh -c 'python3 --version'", 'inline interpreter code rule (program from a pipe)'),
            ('< input python3 --version', 'inline interpreter code rule (program from a pipe)'),
            ('python3 --version < input', 'inline interpreter code rule (program from a pipe)'),
            ('printf sample | cat; python3 --version < input',
             'inline interpreter code rule (program from a pipe)'),
            ('printf sample | cat; python3 --version -',
             'inline interpreter code rule (program from a pipe)'),
            ("python3 --version -c 'print(1)'", 'process-capable python -c rule'),
            ("printf sample | cat; python3 --version -c 'print(1)'",
             'process-capable python -c rule'),
            ('python3 --version; printf x | python3',
             'inline interpreter code rule (program from a pipe)'),
            ("python3 --version && python3 -c 'import sys; print(sys.argv)'",
             'process-capable python -c rule'),
        ):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertEqual(self.reason.splitlines()[0].split('Rule: ', 1)[1], rule + '.')

    def test_python_version_after_path_change_is_denied(self):
        self.assertTrue(self.denied('PATH=/usr/bin; printf sample | cat; python3 --version'))
        self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_python_version_in_piped_case_is_denied(self):
        self.assertTrue(self.denied('printf sample | (case x in x) python3 --version;; esac)'))
        self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_env_directory_admits_verbatim_repository_script(self):
        command = 'env -C /home/miguel/.vk-worktrees/.bettercoding-workspaces/188e-pati-pr-backlog/lanes/pr-7890/backend/api API_ENVIRONMENT=testing uv run --frozen python scripts/integration_shards.py --refresh'
        isdir = ultraship.os.path.isdir
        directory = '/home/miguel/.vk-worktrees/.bettercoding-workspaces/188e-pati-pr-backlog/lanes/pr-7890/backend/api'
        with patch.object(ultraship.os.path, 'isdir', side_effect=lambda path: path == directory or isdir(path)):
            self.assertFalse(self.denied(command), self.reason)

    def test_env_directory_literal_forms_admit_relative_scripts(self):
        with tempfile.TemporaryDirectory() as directory:
            for option in (f'-C {directory}', f'-C{directory}',
                           f'--chdir {directory}', f'--chdir={directory}'):
                for script in ('python3 scripts/x.py', 'node ./x.js'):
                    with self.subTest(option=option, script=script):
                        self.assertFalse(self.denied(f'env {option} {script}'), self.reason)

    def test_env_directory_missing_literal_directory_is_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(self.denied(f'env -C {directory}/missing python3 scripts/x.py'))
            self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_env_directory_script_symlinks_into_proc_are_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'link').symlink_to('/proc/self/fd', target_is_directory=True)
            for script in ('python3 link', 'node ./link'):
                with self.subTest(script=script):
                    self.assertTrue(self.denied(f'env -C {directory} {script}'))
                    self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_env_directory_original_cwd_script_symlinks_are_denied(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as cwd:
            (Path(cwd) / 'link').symlink_to('/proc/self/fd', target_is_directory=True)
            for script in ('python3 link', 'node ./link'):
                with self.subTest(script=script):
                    self.assertTrue(self.denied(f'env -C {directory} {script}', cwd=cwd))
                    self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_env_directory_unproven_changes_are_denied(self):
        for command in (
            'env -C "$D" python3 scripts/x.py',
            'env -C rel/dir python3 x.py',
            'env -C /safe/../other python3 x.py',
            'env -C /safe env -C /other python3 x.py',
            'env -C /safe -C /other python3 x.py',
            'env -C /safe sh -c "env -C /other python3 x.py"',
            'env -C /safe sudo --unknownopt python3 x.py',
            'env -C /safe -S "python3 x.py"',
            'env -C /safe --split-string="python3 x.py"',
        ):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_env_directory_pipe_and_stdin_refusals_keep_the_pipe_label(self):
        for command in (
            'printf data | env -C /safe python3 -',
            'env -C /safe python3 x.py < input',
            'env -C /safe node /proc/self/fd/0',
            'env -C /safe node <(printf data)',
        ):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)
                self.assertNotIn(': relative script after an unproven directory change', self.reason)

    def test_env_directory_preserves_unsafe_original_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(self.denied(f'env -C {directory} true; node 0', cwd='/dev/fd'))
            self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_env_directory_unsafe_target_is_denied(self):
        for directory in ('/proc/self/fd', '/dev/fd'):
            with self.subTest(directory=directory):
                self.assertTrue(self.denied(f'env -C {directory} node 0'))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_env_directory_with_real_cd_is_denied(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            for command in (f'cd {a}; env -C {b} python3 x.py',
                            f'env -C {a} sh -c "cd {b}; python3 x.py"'):
                with self.subTest(command=command):
                    self.assertTrue(self.denied(command))
                    self.assertIn(': relative script after an unproven directory change', self.reason)

    def test_env_directory_repeated_nested_text_is_denied(self):
        with tempfile.TemporaryDirectory() as a:
            command = f'env -C {a} python3 scripts/report.py --from "$(date +%F)" --to "$(date +%F)"'
            self.assertTrue(self.denied(command))
            self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_env_directory_input_pipe_keeps_the_pipe_label(self):
        for command in ('printf x | env -C "$D" python3 x.py',
                        'printf x | env -C "$D" node x.js'):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)
                self.assertNotIn(': relative script after an unproven directory change', self.reason)

    def test_env_directory_unproven_change_label_names_the_check(self):
        for command in ('cd $X && python3 scripts/x.py',
                        'env -C "$D" python3 scripts/x.py',
                        'env -C "$D" node x.js',
                        'env -C "$D" python3 scripts/x.py | tail -n 20',
                        'printf x | cat; cd "$X"; python3 x.py'):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe): relative script after an unproven directory change', self.reason)

    def test_env_directory_requires_first_segment_and_existing_target(self):
        with tempfile.TemporaryDirectory() as directory:
            for command in (
                'ln -sfn /dev/fd /tmp/d && env -C /tmp/d python3 0',
                f'true; env -C {directory} python3 x.py',
                f'sh -c "env -C {directory} python3 x.py"',
            ):
                with self.subTest(command=command):
                    self.assertTrue(self.denied(command))
                    self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)
            self.assertFalse(self.denied(f'env -C {directory} python3 scripts/x.py'), self.reason)

    def test_piped_groups_keep_input_for_every_segment(self):
        for command, label in (
            ("printf x | (eval 'cd /proc/self/fd'; node 0)", 'program from a pipe'),
            ('printf x | (echo }; node 0)', 'program from a pipe'),
            ('printf x | { true; python3; }', 'unresolved command word'),
            ('printf x |& { true; node scripts/x.js; }', 'unresolved command word'),
            ("printf x | { eval 'cd /proc/self/fd'; node 0; }", 'unresolved command word'),
        ):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn(f'inline interpreter code rule ({label})', self.reason)
        self.assertFalse(self.denied('python3 scripts/x.py 2>&1 | tail -n 20'), self.reason)

    def test_relative_scripts_refuse_earlier_path_changes(self):
        for command in (
            'ln -sfn /dev/stdin x.js && node x.js',
            'mv link x.js; node x.js',
            'cp link x.py; python3 x.py',
            'mkfifo x.py; python3 x.py',
            'rm x.py; python3 x.py',
            'mkdir scripts; python3 scripts/x.py',
            'install link x.py; python3 x.py',
            'touch x.py; python3 x.py',
            'mknod x.py p; python3 x.py',
            'printf data > x.py; python3 x.py',
            'printf data >> x.py; python3 x.py',
            'ln -sfn /dev/stdin x.js; sh -c "node x.js"',
            'ln -sfn /dev/stdin x.js; echo $(node x.js)',
        ):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)
        for command in (
            'python3 scripts/x.py > out.json',
            'true; python3 scripts/x.py',
            'echo ready; python3 scripts/x.py',
            'printf ready; python3 scripts/x.py',
        ):
            with self.subTest(command=command):
                self.assertFalse(self.denied(command), self.reason)

    def test_relative_scripts_refuse_unlisted_writers(self):
        for command in (
            'printf code | tee x.py; python3 x.py',
            'dd if=payload of=x.py; python3 x.py',
            "sed -i 's/a/b/' x.py; python3 x.py",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_relative_scripts_refuse_nested_path_changes(self):
        for command in (
            "eval 'ln -sfn /dev/stdin x.js'; node x.js",
            "sh -c 'ln -sfn /dev/stdin x.js'; node x.js",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_relative_scripts_refuse_paths_changed_in_substitutions(self):
        command = 'echo "$(ln -sfn /dev/stdin x.js)"; node x.js'
        self.assertTrue(self.denied(command))
        self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_relative_scripts_refuse_descriptor_file_redirection(self):
        command = 'printf code >&x.py; python3 x.py'
        self.assertTrue(self.denied(command))
        self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_relative_scripts_refuse_runtime_reordering(self):
        for command in (
            "true () ( node x.js ); ln -sfn /dev/stdin x.js; printf 'console.log(1)' | true",
            "until python3 x.py; do printf 'print(1)' > x.py; done",
            "python3 x.py | (mkfifo x.py; printf 'print(1)' > x.py)",
            "python3 x.py & printf 'print(1)' > x.py",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_stderr_piped_groups_keep_input(self):
        for command in (
            'printf x |& (true; node scripts/x.js)',
            'printf x |& ( (true; node scripts/x.js) )',
        ):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)
        with tempfile.TemporaryDirectory() as directory:
            sub = Path(directory) / 'sub'
            sub.mkdir()
            (sub / 'fd').symlink_to('/dev/fd', target_is_directory=True)
            command = "printf 'print(1)' |& (cd sub && python3 fd/0)"
            self.assertTrue(self.denied(command, cwd=directory))
            self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_directory_target_script_symlinks_are_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            sub = Path(directory) / 'sub'
            sub.mkdir()
            (sub / 'fd').symlink_to('/dev/fd', target_is_directory=True)
            for command in ('cd sub && python3 fd/0', 'pushd sub && python3 fd/0'):
                with self.subTest(command=command):
                    self.assertTrue(self.denied(command, cwd=directory))
                    self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)
            for command in (f'cd {sub} && python3 fd/0', f'pushd {sub} && python3 fd/0'):
                with self.subTest(command=command):
                    self.assertTrue(self.denied(command, cwd=directory))
                    self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)
                    self.assertNotIn(': relative script after an unproven directory change', self.reason)
            (sub / 'x.js').symlink_to('/dev/stdin')
            self.assertTrue(self.denied(f'cd {sub} && node x.js', cwd=directory))
            self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_trap_code_cannot_supply_interpreter_programs(self):
        # Process-capable payloads are classifier input only; these tests never execute them.
        for command in (
            "trap 'python3 -c \"import os; os.system(chr(103))\"' EXIT",
            "trap -- 'python3 -c \"import os; os.system(chr(103))\"' EXIT",
            "printf 'print(1)' | (trap 'cd /proc/self/fd; python3 0' EXIT; true)",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('process-capable python -c rule' if 'python3 -c' in command
                              else 'inline interpreter code rule (program from a pipe)', self.reason)

    def test_existing_env_targets_keep_wrapper_refusals(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            for command in (
                f'env -C {a} env -C {b} python3 x.py',
                f'env -C {a} -C {b} python3 x.py',
                f'env -C {a} sh -c "env -C {b} python3 x.py"',
                f'env -C {a} sudo --unknownopt python3 x.py',
                f'env -C {a} -S "python3 x.py"',
                f'env -C {a} --split-string="python3 x.py"',
            ):
                with self.subTest(command=command):
                    self.assertTrue(self.denied(command))
                    self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_read_only_segments_and_boolean_or_remain_admitted(self):
        for command in (
            'set -euo pipefail; python3 scripts/x.py',
            'python3 scripts/x.py | grep ok',
            'python3 scripts/x.py 2>&1 | tail -n 20',
        ):
            with self.subTest(command=command):
                self.assertFalse(self.denied(command), self.reason)
        with tempfile.TemporaryDirectory() as directory:
            command = f'true || (cd {directory} && python3 scripts/x.py)'
            self.assertFalse(self.denied(command), self.reason)

    def test_absolute_scripts_refuse_runtime_path_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            for interpreter, filename, program in (
                ('node', 'p.js', 'console.log(1)'),
                ('python3', 'p.py', 'print(1)'),
            ):
                with self.subTest(interpreter=interpreter):
                    script = Path(directory) / filename
                    self.assertFalse(script.exists())
                    command = f"ln -sfn /dev/stdin {script}; printf '{program}' | {interpreter} {script}"
                    self.assertTrue(self.denied(command))
                    self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_absolute_scripts_refuse_same_segment_launcher_path_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            for interpreter, filename, program in (
                ('node', 'p.js', 'console.log(1)'),
                ('python3', 'p.py', 'print(1)'),
            ):
                with self.subTest(interpreter=interpreter):
                    script = Path(directory) / filename
                    self.assertFalse(script.exists())
                    command = (f"printf '{program}' | find . -maxdepth 0 "
                               f'-exec ln -sfn /dev/stdin {script} \\; '
                               f'-exec {interpreter} {script} \\;')
                    self.assertTrue(self.denied(command))
                    self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)
            self.assertFalse(self.denied('timeout 5 python3 scripts/x.py', cwd=directory), self.reason)

    def test_piped_launcher_with_opaque_job_is_denied(self):
        self.assertTrue(self.denied("printf input | parallel 'printf %s'"))
        self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_pipeline_wrapper_requires_a_proven_child_command(self):
        self.assertTrue(self.denied('printf input | timeout 5 "$CONSUMER"'))
        self.assertIn('inline interpreter code rule (unresolved command word)', self.reason)
        self.assertFalse(self.denied('printf input | timeout 5 cat'), self.reason)

    def test_unknown_pipeline_consumer_cannot_prove_launcher_is_data(self):
        self.assertTrue(self.denied('printf input | fixture-consumer xargs'))
        self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_pipeline_launcher_names_as_data_stay_admitted(self):
        for command in ('printf input | tee xargs', 'printf input | timeout 5 grep xargs',
                        'printf input | cat xargs'):
            with self.subTest(command=command):
                self.assertFalse(self.denied(command), self.reason)

    def test_pipeline_nice_attached_adjustments_stay_admitted(self):
        for option in ('-n5', '-5'):
            with self.subTest(option=option):
                self.assertFalse(self.denied(f'printf input | nice {option} cat'), self.reason)

    def test_directory_names_as_script_arguments_stay_admitted(self):
        for word in ('cd', 'pushd'):
            with self.subTest(word=word):
                self.assertFalse(self.denied(f'python3 scripts/x.py --label {word} frontend'), self.reason)

    def test_launcher_names_as_script_arguments_stay_admitted(self):
        with tempfile.TemporaryDirectory() as directory:
            for command in ('python3 scripts/x.py --label xargs',
                            'timeout 5 python3 scripts/x.py --label xargs',
                            'X+=1 python3 scripts/x.py --label xargs',
                            'git grep xargs', 'rg find',
                            'python3 scripts/x.py parallel', 'node x.js -exec'):
                with self.subTest(command=command):
                    self.assertFalse(self.denied(command, cwd=directory), self.reason)
            script = Path(directory) / 'p.js'
            self.assertFalse(script.exists())
            command = (f'timeout 5 find . -maxdepth 0 '
                       f'-exec ln -sfn /dev/stdin {script} \\; '
                       f'-exec node {script} \\;')
            self.assertTrue(self.denied(command, cwd=directory))
            self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_quoted_assignment_like_commands_do_not_hide_launchers(self):
        for word in ("'X=1'", '"X=1"'):
            with self.subTest(word=word):
                self.assertTrue(self.denied(f'{word} python3 scripts/x.py --label xargs'))
                self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_launchers_behind_unknown_wrappers_and_redirections_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'p.js'
            self.assertFalse(script.exists())
            find = (f'find . -maxdepth 0 -exec ln -sfn /dev/stdin {script} \\; '
                    f'-exec node {script} \\;')
            for command in (
                f'sudo -Eu root {find}',
                f'env -iu X {find}',
                f'sudo -Eu root xargs node {script}',
                f'stdbuf -oL {find}',
                f'ionice -c3 {find}',
                f'nice 2>/dev/null {find}',
                f'timeout 5 2>err {find}',
                f'env >/dev/null {find}',
                f'sudo ionice -t xargs node {script}',
                f'doas -u node /usr/bin/{find}',
            ):
                with self.subTest(command=command):
                    self.assertTrue(self.denied(command, cwd=directory))
                    self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_launcher_inherits_path_check_into_env_split_string(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'p.js'
            self.assertTrue(self.denied(f"stdbuf -oL xargs env -S 'node {script}'", cwd=directory))
            self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_relative_directory_is_unproven_without_hook_cdpath(self):
        with tempfile.TemporaryDirectory() as directory:
            sub = Path(directory) / 'sub'
            sub.mkdir()
            with patch.dict(ultraship.os.environ):
                ultraship.os.environ.pop('CDPATH', None)
                for target in ('sub', './sub'):
                    with self.subTest(target=target):
                        command = f'cd {target} && python3 scripts/x.py'
                        self.assertTrue(self.denied(command, cwd=directory))
                        self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)
                self.assertFalse(self.denied(f'cd {sub} && python3 scripts/x.py', cwd=directory), self.reason)


if __name__ == '__main__':
    unittest.main()
