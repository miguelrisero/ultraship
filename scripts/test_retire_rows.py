"""Retirement appends preserve existing bytes and refuse invalid records."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHIP = ROOT / 'plugins/ship'
SCRIPT = SHIP / 'skills/ship/scripts/retire-rows.py'
spec = importlib.util.spec_from_file_location('retire_rows_hook', SHIP / 'hooks/ultraship.py')
ultraship = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ultraship)


class RetireRowsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.path = self.directory / 'tests/mutation/x.toml'
        self.path.parent.mkdir(parents=True)
        self.old = b'title = "existing"'
        self.path.write_bytes(self.old)
        self.rows = [{'id': 'R1', 'reason': 'removed "guard"\\\n\t\x7f'},
                     {'id': 'R2', 'reason': 'removed other behavior'}]
        self.record = {'row_file': str(self.path), 'rows': self.rows}
        self.record_path = self.directory / 'record.json'

    def run_script(self, record=None):
        self.record_path.write_text(json.dumps(self.record if record is None else record),
                                    encoding='utf-8')
        return subprocess.run([sys.executable, '-I', str(SCRIPT), str(self.record_path)],
                              capture_output=True, text=True)

    def test_appends_round_trip_records_and_preserves_existing_bytes(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        content = self.path.read_bytes()
        self.assertTrue(content.startswith(self.old + b'\n[[retired]]\n'))
        self.assertEqual(tomllib.loads(content.decode()),
                         {'title': 'existing', 'retired': self.rows})
        self.assertEqual(result.stdout,
                         f'appended 2 [[retired]] tables to {self.path}: R1, R2\n')
        self.assertEqual(result.stderr, '')

    @unittest.skipIf(os.geteuid() == 0, 'root bypasses file read permissions')
    def test_write_only_row_file_succeeds(self):
        self.path.chmod(0o200)
        try:
            result = self.run_script()
        finally:
            self.path.chmod(0o600)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(tomllib.loads(self.path.read_text())['retired'], self.rows)

    def test_invalid_records_refuse_without_writing(self):
        outside = self.directory / 'outside.toml'
        outside.write_bytes(self.old)
        link = self.path.with_name('link.toml')
        link.symlink_to(self.path)
        records = [
            {'row_file': 'tests/mutation/x.toml', 'rows': self.rows},
            {'row_file': str(outside), 'rows': self.rows},
            {'row_file': str(self.path.with_name('missing.toml')), 'rows': self.rows},
            {'row_file': str(link), 'rows': self.rows},
            {'row_file': str(self.path), 'rows': [self.rows[0], self.rows[0]]},
            {'row_file': str(self.path), 'rows': [{'id': 'R1', 'reason': ''}]},
            {**self.record, 'extra': True},
            {'rows': self.rows},
            {'row_file': 1, 'rows': self.rows},
            {**self.record, 'rows': []},
            {**self.record, 'rows': {}},
            {**self.record, 'rows': [{'id': '', 'reason': 'removed'}]},
            {**self.record, 'rows': [{'id': 'R1', 'reason': 1}]},
            {**self.record, 'rows': [{'id': 'R1', 'reason': 'removed', 'extra': True}]},
        ]
        for record in records:
            with self.subTest(record=record):
                result = self.run_script(record)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertTrue(result.stderr.startswith('REFUSE '), result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(self.path.read_bytes(), self.old)
                self.assertEqual(outside.read_bytes(), self.old)
        self.assertFalse(self.path.with_name('missing.toml').exists())

    def test_unreadable_or_invalid_json_refuses_without_writing(self):
        for content in (None, '{', '[]'):
            with self.subTest(content=content):
                if content is not None:
                    self.record_path.write_text(content)
                result = subprocess.run(
                    [sys.executable, '-I', str(SCRIPT), str(self.record_path)],
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertTrue(result.stderr.startswith('REFUSE '), result.stderr)
                self.assertEqual(self.path.read_bytes(), self.old)

    def test_wrong_argument_count_prints_usage(self):
        for args in ([], ['one', 'two']):
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, '-I', str(SCRIPT), *args],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stderr, 'usage: retire-rows.py <record-file>\n')
                self.assertEqual(self.path.read_bytes(), self.old)

    def test_writer_hook_admits_record_file_command(self):
        output = io.StringIO()
        payload = {'agent_type': 'ship:writer--sol', 'tool_name': 'Bash',
                   'tool_input': {'command': 'python3 -I "/abs/plugin/skills/ship/scripts/'
                                 'retire-rows.py" /abs/scratch/record.json'}}
        with contextlib.redirect_stdout(output):
            try:
                ultraship.pre(payload)
            except SystemExit as error:
                self.assertEqual(error.code, 0)
        result = json.loads(output.getvalue())['hookSpecificOutput'] if output.getvalue() else {}
        self.assertNotEqual(result.get('permissionDecision'), 'deny',
                            result.get('permissionDecisionReason', ''))


if __name__ == '__main__':
    unittest.main()
