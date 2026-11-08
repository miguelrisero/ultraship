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
            "python3 - <<'EOF'\nprint(1)\nEOF git push\n",
            "echo '<<EOF'; git push\n",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))


if __name__ == '__main__':
    unittest.main()
