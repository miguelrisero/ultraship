"""Inline interpreter decisions for relative scripts after an env directory change."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

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

    def test_env_directory_admits_verbatim_repository_script(self):
        command = 'env -C /home/miguel/.vk-worktrees/.bettercoding-workspaces/188e-pati-pr-backlog/lanes/pr-7890/backend/api API_ENVIRONMENT=testing uv run --frozen python scripts/integration_shards.py --refresh'
        self.assertFalse(self.denied(command), self.reason)

    def test_env_directory_literal_forms_admit_relative_scripts(self):
        with tempfile.TemporaryDirectory() as directory:
            for option in (f'-C {directory}', f'-C{directory}',
                           f'--chdir {directory}', f'--chdir={directory}'):
                for script in ('python3 scripts/x.py', 'node ./x.js'):
                    with self.subTest(option=option, script=script):
                        self.assertFalse(self.denied(f'env {option} {script}'), self.reason)

    def test_env_directory_missing_literal_directory_is_admitted(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(self.denied(f'env -C {directory}/missing python3 scripts/x.py'), self.reason)

    def test_env_directory_script_symlinks_into_proc_are_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'link').symlink_to('/proc/self/fd', target_is_directory=True)
            for script in ('python3 link/0', 'node ./link'):
                with self.subTest(script=script):
                    self.assertTrue(self.denied(f'env -C {directory} {script}'))
                    self.assertIn('inline interpreter code rule (program from a pipe)', self.reason)

    def test_env_directory_original_cwd_script_symlinks_are_denied(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as cwd:
            (Path(cwd) / 'link').symlink_to('/proc/self/fd', target_is_directory=True)
            for script in ('python3 link/0', 'node ./link'):
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
            'cd /safe; env -C /other python3 x.py',
            'env -C /safe sh -c "cd /other; python3 x.py"',
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

    def test_env_directory_unproven_change_label_names_the_check(self):
        for command in ('cd $X && python3 scripts/x.py',
                        'env -C "$D" python3 scripts/x.py'):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('inline interpreter code rule (program from a pipe): relative script after an unproven directory change', self.reason)


if __name__ == '__main__':
    unittest.main()
