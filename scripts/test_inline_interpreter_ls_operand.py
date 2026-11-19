"""Interpreter names remain data only in proven read-only ls calls."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ultraship_ls_operand', ROOT / 'plugins/ship/hooks/ultraship.py')
ultraship = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ultraship)


class LsOperandTests(unittest.TestCase):
    def denied(self, command):
        output = io.StringIO()
        payload = {'agent_type': 'ship:writer--sol', 'tool_name': 'Bash', 'tool_input': {'command': command}}
        with contextlib.redirect_stdout(output):
            try:
                ultraship.pre(payload)
            except SystemExit as error:
                self.assertEqual(error.code, 0)
        text = output.getvalue()
        self.reason = json.loads(text)['hookSpecificOutput']['permissionDecisionReason'] if text else ''
        return bool(text and json.loads(text)['hookSpecificOutput']['permissionDecision'] == 'deny')

    def test_combined_git_searches_and_ls_operand_are_admitted(self):
        """Protect combined read-only admission; operand misclassification fails; existing glob tests omit a bare interpreter operand."""
        command = ('git -C /w/repo grep -n -e alpha -- src/a | head -20; '
                   'git -C /w/repo grep -n -e beta -- src/b | head -20; '
                   'ls -la /w/repo/.venv/bin/python3')
        self.assertFalse(self.denied(command), self.reason)

    def test_piped_ls_interpreter_operand_is_admitted(self):
        """Protect piped ls data; treating its operand as a program fails; existing glob coverage omits literal interpreter paths."""
        self.assertFalse(self.denied('ls /w/repo/.venv/bin/python3 | head -5'), self.reason)

    def test_cd_and_multiple_ls_interpreter_operands_are_admitted(self):
        """Protect literal cd and multiple ls operands; program classification fails; existing tests omit this Python and Node combination."""
        command = ('cd /w/repo && ls -l /w/repo/.venv/bin/python3.13 '
                   '/w/repo/node_modules/.bin/node | head -5')
        self.assertFalse(self.denied(command), self.reason)

    def test_git_grep_context_after_directory_prefix_is_admitted(self):
        """Protect grep context after a directory prefix; consuming the wrong -C fails; existing tests omit both option positions."""
        command = 'git -C /w/repo grep -C 3 needle -- src | head -5; ls /w/bin/python3'
        self.assertFalse(self.denied(command), self.reason)

    def test_git_directory_prefix_preserves_joined_code_data(self):
        """Protect globbed search data; joined-code refusal fails; existing admission coverage omits git's literal directory prefix."""
        command = 'git -C /w/repo grep -n needle /w/repo/lib/python*/a | head -3'
        self.assertFalse(self.denied(command), self.reason)

    def test_git_configuration_keeps_ls_operand_refused(self):
        """Protect configuration refusal across the call; partial read-only proof fails; existing controls omit a paired ls interpreter operand."""
        for search in (
            'git -c core.pager=less grep needle',
            'git -C /w -c core.pager=less grep needle',
            'git -c x=y -C /w grep needle',
        ):
            with self.subTest(search=search):
                self.assertTrue(self.denied(search + '; ls /w/bin/python3 | head -5'))
                self.assertEqual(self.reason.split('\n', 1)[0].split('Rule: ', 1)[1].removesuffix('.'),
                                 'inline interpreter code rule (program from a pipe)')

    def test_git_global_options_keep_ls_operand_refused(self):
        """Protect exact global-option scope; accepting extra options fails; existing global-option controls omit the new ls exemption."""
        for search in (
            'git --no-pager -C /w grep needle',
            'git -C /w --no-pager grep needle',
            'git --git-dir /w grep needle',
            'git -C /w --git-dir /x grep needle',
        ):
            with self.subTest(search=search):
                self.assertTrue(self.denied(search + '; ls /w/bin/python3 | head -5'))
                self.assertEqual(self.reason.split('\n', 1)[0].split('Rule: ', 1)[1].removesuffix('.'),
                                 'inline interpreter code rule (program from a pipe)')

    def test_git_pager_options_keep_ls_operand_refused(self):
        """Protect executable pager refusal; skipping grep-option checks fails; existing pager controls omit a directory prefix and ls operand."""
        for search in (
            'git -C /w grep -O/w/pager needle',
            'git -C /w grep --open-files-in-pager=/w/pager needle',
        ):
            with self.subTest(search=search):
                self.assertTrue(self.denied(search + '; ls /w/bin/python3 | head -5'))
                self.assertEqual(self.reason.split('\n', 1)[0].split('Rule: ', 1)[1].removesuffix('.'),
                                 'inline interpreter code rule (program from a pipe)')

    def test_repeated_and_attached_git_directories_keep_ls_operand_refused(self):
        """Protect the single literal prefix; repeated or attached prefix admission fails; existing tests omit these paired ls calls."""
        for search in (
            'git -C /a -C /b grep needle',
            'git -C/w grep needle',
        ):
            with self.subTest(search=search):
                self.assertTrue(self.denied(search + '; ls /w/bin/python3 | head -5'))
                self.assertEqual(self.reason.split('\n', 1)[0].split('Rule: ', 1)[1].removesuffix('.'),
                                 'inline interpreter code rule (program from a pipe)')

    def test_unproven_git_directories_keep_ls_operand_refused(self):
        """Protect literal directory proof; dynamic or quoted directory admission fails; existing coverage omits these git-prefix and ls combinations."""
        for directory in ("'/w'", '"/w"', '~/w', "''", '-w'):
            with self.subTest(directory=directory):
                command = f'git -C {directory} grep needle; ls /w/bin/python3 | head -5'
                self.assertTrue(self.denied(command))
                self.assertEqual(self.reason.split('\n', 1)[0].split('Rule: ', 1)[1].removesuffix('.'),
                                 'inline interpreter code rule (program from a pipe)')

    def test_executable_sinks_keep_ls_operand_refused(self):
        """Protect whole-call sink checks; trusting only the ls segment fails; existing sink tests omit literal ls interpreter operands."""
        for command in (
            'ls /w/bin/python3 | sh',
            'ls /w/bin/python3 | head -5 | sh',
            'git -C /w grep needle | sh; ls /w/bin/python3 | head -5',
        ):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertEqual(self.reason.split('\n', 1)[0].split('Rule: ', 1)[1].removesuffix('.'),
                                 'inline interpreter code rule (program from a pipe)')

    def test_assignments_and_redefinitions_keep_ls_operand_refused(self):
        """Protect literal command identity; trusting assigned or redefined ls fails; existing controls omit the bare operand exemption."""
        for prefix in (
            'X=1 ',
            'alias ls=cat; ',
            'function ls { cat; }; ',
            'hash -p /bin/cat ls; ',
        ):
            with self.subTest(prefix=prefix):
                self.assertTrue(self.denied(prefix + 'ls /w/bin/python3 | head -5'))
                self.assertEqual(self.reason.split('\n', 1)[0].split('Rule: ', 1)[1].removesuffix('.'),
                                 'inline interpreter code rule (program from a pipe)')

    def test_prefixed_ls_keeps_interpreter_operand_refused(self):
        """Protect raw ls identity; normalized command exemptions fail; existing coverage omits these prefixed forms with a bare interpreter operand."""
        for executable in ('command ls', r'\ls', 'env ls', '/bin/ls', "'ls'", 'builtin ls'):
            with self.subTest(executable=executable):
                self.assertTrue(self.denied(executable + ' /w/bin/python3 | head -5'))
                self.assertEqual(self.reason.split('\n', 1)[0].split('Rule: ', 1)[1].removesuffix('.'),
                                 'inline interpreter code rule (program from a pipe)')

    def test_nested_shell_keeps_ls_operand_refused(self):
        """Protect nested-call proof; trusting outer tokens fails; existing coverage omits a nested ls interpreter operand with a safe sink."""
        command = "bash -c 'ls /w/bin/python3 | head -5'"
        self.assertTrue(self.denied(command))
        self.assertEqual(self.reason.split('\n', 1)[0].split('Rule: ', 1)[1].removesuffix('.'),
                         'inline interpreter code rule (program from a pipe)')


if __name__ == '__main__':
    unittest.main()
