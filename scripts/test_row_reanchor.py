"""Synthetic re-anchor and exact-command admission guarantees."""
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import contextlib
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from threading import Event
import time
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'plugins/ship/skills/ship/scripts/row_reanchor.py'
spec = importlib.util.spec_from_file_location('reanchor_tool', TOOL)
reanchor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reanchor)
spec = importlib.util.spec_from_file_location('reanchor_hook', ROOT / 'plugins/ship/hooks/ultraship.py')
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)
SENTINEL = 'PRIVATE_SENTINEL_8ac7'


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.row = self.root / 'rows.toml'
        self.subject = self.root / 'subject.txt'
        self.git('init', '-q')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), '-c', 'user.name=t',
                                        '-c', 'user.email=t@example.invalid', *args], stderr=subprocess.PIPE,
                                       env={**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull,
                                            'GIT_CONFIG_NOSYSTEM': '1'}).decode().strip()

    def commit(self):
        self.git('add', '--', 'rows.toml', 'subject.txt', 'other.txt')
        self.git('commit', '--allow-empty', '-qm', 'fixture')
        return self.git('rev-parse', 'HEAD')

    def setup_pair(self, old=None, new=None, head=None, literal=False, extra='', row_id='target'):
        block = ''.join('    deleted_%s()\n' % i for i in range(11))
        self.old = old if old is not None else SENTINEL + '\nbegin()\n' + block + 'middle()\ncall(\n    argument,\n)\nend()\n'
        self.new = new if new is not None else self.old.replace(block, '').replace('    argument,\n', '    replacement,\n')
        self.head = head if head is not None else self.old.replace('middle()\n', 'middle()\ngrown_a()\ngrown_b()\n')
        old_field = "'''\n" + self.old + "'''" if literal else reanchor.basic(self.old)
        new_field = "'''\n" + self.new + "'''" if literal else reanchor.basic(self.new)
        self.row.write_text('[project]\nname = "' + SENTINEL + '"\n\n[[row]]\nid = ' + reanchor.basic(row_id)
                            + '\nclaim = "same guarantee"\nfile = "subject.txt"\nold = ' + old_field
                            + '\nnew = ' + new_field + '\ntest = "test_subject"\n' + extra
                            + '\n[[hand_run]]\nid = "hand"\n[[retired]]\nid = "retired"\n')
        (self.root / 'other.txt').write_text('other subject\n')
        self.subject.write_text('outside_before\n' + self.old + 'outside_after\n')
        self.base = self.commit()
        self.subject.write_text('outside_before\n' + self.head + 'outside_after\n')
        self.head_sha = self.commit()

    def invoke(self, expected=0, reason=None, **overrides):
        before = self.row.read_bytes()
        options = {'row-file': str(self.row), 'row-id': 'target', 'subject': 'subject.txt',
                   'base': self.base, 'head': self.head_sha}
        options.update(overrides)
        result = subprocess.run(['python3', '-I', str(TOOL), *[word for key, value in options.items()
                                 for word in ('--' + key, value)]], capture_output=True, text=True,
                                env={**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'})
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertNotIn(SENTINEL, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '')
        if expected:
            self.assertTrue(result.stdout.startswith('REFUSED: '))
            self.assertIsNotNone(reason)
            self.assertIn('REFUSED: ' + reason, result.stdout)
            self.assertEqual(self.row.read_bytes(), before)
        else:
            self.assertTrue(result.stdout.startswith('PASS\n'))
        return before, result.stdout

    def test_long_span_preserves_interior_and_all_other_bytes(self):
        self.setup_pair()
        self.assertEqual(self.head.count(self.old), 0)
        before, output = self.invoke()
        after = self.row.read_bytes()
        parsed_before, parsed_after = tomllib.loads(before.decode()), tomllib.loads(after.decode())
        row = parsed_after['row'][0]
        self.assertEqual(self.subject.read_text().count(row['old']), 1)
        self.assertIn('grown_a()\ngrown_b()', row['new'])
        self.assertNotIn('deleted_0()', row['new'])
        self.assertIn('replacement,', row['new'])
        row['old'], row['new'] = parsed_before['row'][0]['old'], parsed_before['row'][0]['new']
        self.assertEqual(parsed_before, parsed_after)
        _, before_fields, _ = reanchor.row_statements(before.decode(), 'target')
        _, after_fields, _ = reanchor.row_statements(after.decode(), 'target')
        for key in ('old', 'new'):
            self.assertNotEqual(before_fields[key][2], after_fields[key][2])
        def without_pair(text, fields):
            source = reanchor.lines(text)
            for start, end, _ in sorted((fields['old'], fields['new']), reverse=True):
                source[start:end] = []
            return ''.join(source)
        self.assertEqual(without_pair(before.decode(), before_fields), without_pair(after.decode(), after_fields))
        self.assertIn('changed_statements=2', output)
        self.assertIn('tomllib=PASS', output)

    def record_path(self):
        return self.root / self.git('rev-parse', '--git-path', 'ship/row-auth.json')

    def test_record_schema_path_and_permissions_in_linked_worktree(self):
        self.setup_pair()
        original_record = self.record_path()
        linked = self.root / 'linked'
        self.git('worktree', 'add', '-qb', 'linked-lane', str(linked), self.head_sha)
        self.root, self.row = linked, linked / self.row.name
        record = self.record_path()
        _, output = self.invoke()
        self.assertEqual(output.splitlines()[-1], f'record={record}')
        self.assertTrue(record.is_absolute())
        self.assertFalse(original_record.exists())
        self.assertEqual(record.stat().st_mode & 0o777, 0o600)
        self.assertEqual(record.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(json.loads(record.read_bytes()), {
            'schema': 1, 'lane': 'linked-lane', 'base': self.base, 'head': self.head_sha,
            'rows': [{'row_file': 'rows.toml', 'row_id': 'target', 'subject': 'subject.txt',
                      'expected_count': 1, 'head_old_count': 1, 'hunk_count': 2,
                      'mutant_unchanged': True, 'changed_statements': 2,
                      'base_lines': [4, 10], 'lines': [4, 10]}],
        })

    def test_printed_fields_match_the_record_entry(self):
        self.setup_pair(literal=True, extra='[row.mutant]\noperator = "replace"\n')
        _, output = self.invoke()
        record = self.record_path()
        data = json.loads(record.read_bytes())
        entry, = data.pop('rows')
        self.assertEqual(entry['base_lines'], [4, 39])
        self.assertEqual(entry['lines'], [4, 12])
        fields = dict(line.split('=', 1) for line in output.splitlines()[1:])
        for key, value in {**data, **entry, 'record': str(record)}.items():
            self.assertEqual(fields[key], value if isinstance(value, str) else json.dumps(value))

    def test_record_expires_on_new_head_and_rerun_changes_zero_statements(self):
        self.setup_pair()
        self.invoke()
        record = self.record_path()
        old_record = json.loads(record.read_bytes())
        target = old_record['rows'][0]
        old_record['rows'].append({**target, 'row_id': 'other'})
        record.write_text(json.dumps(old_record))
        self.head_sha = self.commit()
        before, output = self.invoke()
        self.assertEqual(self.row.read_bytes(), before)
        self.assertIn('changed_statements=0', output.splitlines())
        self.assertEqual(json.loads(record.read_bytes()), {
            **old_record, 'head': self.head_sha, 'rows': [{**target, 'changed_statements': 0}],
        })

    def test_same_head_replaces_one_entry_and_keeps_other_rows(self):
        self.setup_pair('start\nend\n', 'start\ninserted\nend\n', 'start\nend\n', literal=True)
        other_row = self.row.with_name('other.toml')
        other_row.write_bytes(self.row.read_bytes())
        self.git('add', '--', other_row.name)
        self.base = self.head_sha = self.commit()
        self.invoke()
        self.invoke(**{'row-file': str(other_row)})
        record = self.record_path()
        before = json.loads(record.read_bytes())
        self.assertEqual([(row['row_file'], row['row_id']) for row in before['rows']],
                         [('rows.toml', 'target'), ('other.toml', 'target')])
        expected = {**before, 'rows': [dict(row) for row in before['rows']]}
        before['rows'][0]['changed_statements'] = 2
        record.write_text(json.dumps(before))
        original, output = self.invoke()
        self.assertEqual(self.row.read_bytes(), original)
        self.assertIn('changed_statements=0', output.splitlines())
        self.assertEqual(json.loads(record.read_bytes()), expected)

    def test_concurrent_tool_writers_keep_both_entries(self):
        self.setup_pair()
        other_row = self.row.with_name('other.toml')
        other_row.write_bytes(self.row.read_bytes().replace(b'id = "target"', b'id = "other"'))
        head_subject = self.subject.read_bytes()
        self.subject.write_text(self.old)
        self.git('add', '--', other_row.name)
        self.base = self.commit()
        self.subject.write_bytes(head_subject)
        self.head_sha = self.commit()
        with ThreadPoolExecutor(max_workers=2) as writers:
            first = writers.submit(self.invoke)
            second = writers.submit(self.invoke, **{'row-file': str(other_row), 'row-id': 'other'})
            first.result()
            second.result()
        entries = json.loads(self.record_path().read_bytes())['rows']
        self.assertCountEqual([(row['row_file'], row['row_id']) for row in entries],
                              [('rows.toml', 'target'), ('other.toml', 'other')])

    def test_record_write_waits_for_exclusive_lock(self):
        self.setup_pair()
        record = self.record_path()
        record.parent.mkdir(mode=0o700)
        prior = json.dumps({'schema': 1, 'lane': self.git('branch', '--show-current'),
                            'base': self.base, 'head': self.head_sha, 'rows': []}).encode()
        record.write_bytes(prior)
        args = Namespace(row_file=str(self.row), row_id='target', subject='subject.txt',
                         base=self.base, head=self.head_sha)
        attempted = Event()
        flock = fcntl.flock

        def observe_lock(descriptor, operation):
            attempted.set()
            return flock(descriptor, operation)

        env = {'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}
        with patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()), \
                ThreadPoolExecutor(max_workers=1) as writer:
            with record.with_suffix('.lock').open('a+b') as lock:
                flock(lock.fileno(), fcntl.LOCK_EX)
                with patch.object(reanchor.fcntl, 'flock', side_effect=observe_lock):
                    result = writer.submit(reanchor.run, args)
                    self.assertTrue(attempted.wait(timeout=5), 'tool did not attempt to acquire the lock')
                    with self.assertRaises(TimeoutError):
                        result.result(timeout=0.1)
                    self.assertEqual(record.read_bytes(), prior)
            result.result(timeout=5)
        entry, = json.loads(record.read_bytes())['rows']
        self.assertEqual((entry['row_file'], entry['row_id']), ('rows.toml', 'target'))

    def test_detached_head_refuses_before_writing(self):
        self.setup_pair()
        self.git('checkout', '--detach', '-q', self.head_sha)
        self.invoke(2, 'lane branch required')
        self.assertFalse(self.record_path().parent.exists())

    def test_control_characters_quotes_backslashes_and_unicode_round_trip(self):
        old = 'unique_start\nremove_first()\n' + SENTINEL + ' "café" \\path\t\x01\x7f\u2028\nremove()\nend\n'
        new = old.replace('remove_first()\n', '').replace('remove()', 'replace()')
        self.setup_pair(old, new, old.replace('remove()', 'extra()\nremove()'))
        self.invoke()
        values = tomllib.loads(self.row.read_text())['row'][0]
        self.assertIn('"café" \\path\t\x01\x7f\u2028', values['new'])
        self.assertIn('\\u0001', self.row.read_text())
        self.assertIn('\\u007F', self.row.read_text())

    def test_multiline_literal_pair(self):
        self.setup_pair(literal=True)
        self.invoke()

    def test_pure_insertion(self):
        self.setup_pair('start\nmiddle\nend\n', 'start\ninserted\nmiddle\nend\n', 'start\nmiddle\nend\n')
        self.invoke()
        self.assertIn('inserted\n', tomllib.loads(self.row.read_text())['row'][0]['new'])

    def test_pure_insertion_at_start(self):
        self.setup_pair('start\nend\n', 'inserted\nstart\nend\n', 'start\nend\n')
        self.invoke()

    def test_missing_id(self):
        self.setup_pair()
        self.invoke(2, 'row ID must match exactly once', **{'row-id': 'missing'})

    def test_duplicate_id(self):
        self.setup_pair()
        text = self.row.read_text()
        self.row.write_text(text + '\n[[row]]\nid = "target"\n')
        self.head_sha = self.commit()
        self.invoke(2, 'row ID must match exactly once')

    def test_subject_mismatch(self):
        self.setup_pair()
        self.invoke(2, 'subject mismatch', subject='other.txt')

    def test_head_must_equal_current_head(self):
        self.setup_pair()
        self.invoke(2, 'head must equal HEAD', head=self.base)

    def test_dirty_row_file(self):
        self.setup_pair()
        self.row.write_bytes(self.row.read_bytes() + b'\n')
        self.invoke(2, 'working row file differs from head')

    def test_base_old_count_must_equal_one(self):
        self.setup_pair()
        self.git('checkout', '-qb', 'duplicate-base', self.base)
        self.subject.write_text(self.old + self.old)
        self.base = self.commit()
        self.head_sha = self.base
        self.invoke(2, 'base old count must be 1')

    def test_first_anchor_must_be_unique_at_head(self):
        self.setup_pair()
        block = SENTINEL + '\nbegin()\n' + ''.join('    deleted_%s()\n' % i for i in range(11))
        self.subject.write_text(self.subject.read_text() + block)
        self.head_sha = self.commit()
        self.invoke(2, 'anchor 1 must be unique')

    def test_edit_site_must_exist_at_head(self):
        self.setup_pair()
        self.subject.write_text(self.subject.read_text().replace('    argument,\n', '    absent,\n'))
        self.head_sha = self.commit()
        self.invoke(2, 'edit site missing at head')

    def test_expect_two(self):
        self.setup_pair(extra='expect = 2\n')
        self.invoke(2, 'expect must be 1')

    def test_later_anchor_must_be_first_occurrence_on_main(self):
        old = 'start\nremove_first\nkeep\nduplicate\nspacer\nduplicate\nafter\nremove_last\nend\n'
        new = 'start\nkeep\nduplicate\nspacer\nchanged\nafter\nend\n'
        self.setup_pair(old, new, old)
        self.invoke(2, 'anchor is not the first occurrence on main')

    def test_frozen_row_statement_must_be_byte_identical(self):
        self.setup_pair()
        self.row.write_text(self.row.read_text().replace('claim =', 'claim  ='))
        self.head_sha = self.commit()
        self.invoke(2, 'frozen row statements differ')

    def test_symlink_row_file(self):
        self.setup_pair()
        link = self.root / 'link.toml'
        link.symlink_to(self.row)
        self.invoke(2, 'row file must be absolute, regular and canonical without links', **{'row-file': str(link)})

    def test_wrong_whole_file_hunks_refuse(self):
        self.setup_pair('start\nremove_first\nmiddle\nremove_last\nend\n', 'start\nmiddle\nend\n',
                        'start\nremove_first\nremove_last\nend\n')
        _, output = self.invoke(2, 'whole-file mutant hunks differ')
        self.assertIn('whole-file mutant hunks differ', output)

    def test_nested_table_stays_equal(self):
        self.setup_pair(extra='[row.mutant]\noperator = "replace"\n')
        self.invoke()
        self.assertEqual(tomllib.loads(self.row.read_text())['row'][0]['mutant'], {'operator': 'replace'})

    def test_disjoint_child_table_refuses_without_recording_a_partial_range(self):
        self.setup_pair(extra='[other]\nkey = "value"\n["row".mutant]\noperator = "replace"\n')
        self.invoke(2, 'row table is not contiguous')
        self.assertFalse(self.record_path().exists())

    def test_nested_statement_is_frozen(self):
        self.setup_pair(extra='[row.mutant]\noperator = "replace"\n')
        self.row.write_text(self.row.read_text().replace('operator =', 'operator  ='))
        self.head_sha = self.commit()
        _, output = self.invoke(2, 'frozen row statements differ')
        self.assertIn('frozen row statements differ', output)

    def test_moved_copy_refuses(self):
        old, new = 'A\nr1\nB\nr2\nC\n', 'A\nB\nC\n'
        head = 'A\nr1\nB2\nr2\nC\nB\nr2\nC\n'
        self.setup_pair(old, new, head)
        self.invoke(2, 'anchor does not map to its base equal block')

    def test_three_hunks_with_insertion_preserve_grown_interior(self):
        old = 'A\nr1\nB\nD\nE\nF\nr2\nC\n'
        new = 'A\nB\nD\ninserted\nE\nF\nC\n'
        head = 'A\nr1\nB\ngrown\nD\nE\nF\nr2\nC\n'
        self.setup_pair(old, new, head)
        self.invoke()
        row = tomllib.loads(self.row.read_text())['row'][0]
        self.assertEqual(self.subject.read_text().replace(row['old'], row['new'], 1),
                         'outside_before\nA\nB\ngrown\nD\ninserted\nE\nF\nC\noutside_after\n')

    def test_staged_write_failure_preserves_original_and_removes_stage(self):
        self.setup_pair()
        original = self.row.read_bytes()
        argv = [str(TOOL), '--row-file', str(self.row), '--row-id', 'target', '--subject', 'subject.txt',
                '--base', self.base, '--head', self.head_sha]
        output = io.StringIO()
        with patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}), \
                patch('sys.argv', argv), patch.object(reanchor.os, 'fsync', side_effect=OSError(SENTINEL)), \
                contextlib.redirect_stdout(output):
            self.assertEqual(reanchor.main(), 2)
        self.assertEqual(output.getvalue(), 'REFUSED: OSError\n')
        self.assertEqual(self.row.read_bytes(), original)
        self.assertEqual(list(self.root.glob('.row-reanchor-*')), [])

    def test_record_replace_failure_restores_original_row_and_keeps_prior_record(self):
        self.setup_pair()
        record = self.record_path()
        record.parent.mkdir(mode=0o700)
        prior = b'{"schema": 1, "lane": "expired", "rows": []}'
        record.write_bytes(prior)
        original = self.row.read_bytes()
        argv = [str(TOOL), '--row-file', str(self.row), '--row-id', 'target', '--subject', 'subject.txt',
                '--base', self.base, '--head', self.head_sha]
        replace = os.replace

        def fail_record_replace(source, target):
            if target == record:
                self.assertNotEqual(self.row.read_bytes(), original)
                raise OSError(SENTINEL)
            replace(source, target)

        output = io.StringIO()
        with patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}), \
                patch('sys.argv', argv), patch.object(reanchor.os, 'replace', side_effect=fail_record_replace), \
                contextlib.redirect_stdout(output):
            self.assertEqual(reanchor.main(), 2)
        self.assertEqual(output.getvalue(), 'REFUSED: OSError\n')
        self.assertEqual(self.row.read_bytes(), original)
        self.assertEqual(record.read_bytes(), prior)
        self.assertCountEqual(record.parent.iterdir(), [record, record.with_suffix('.lock')])
        self.assertEqual(list(self.root.glob('.row-reanchor-*')), [])


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.state = self.root / 'state'
        self.row = self.root / 'tests/mutation/rows.toml'
        self.row.parent.mkdir(parents=True)
        self.row.write_text('synthetic')
        self.record = self.state / 'row-reanchor/agent-1.json'
        self.record.parent.mkdir(parents=True)
        self.fields = {'pr': 'https://github.com/example/repo/pull/1', 'agent_id': 'agent-1',
                       'row_file': str(self.row), 'row_id': 'target',
                       'expires_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() + 3600))}
        self.write_record()
        self.command = ('python3 -I ' + str(TOOL) + ' --row-file ' + str(self.row)
                        + ' --row-id target --subject subject.py --base main --head HEAD')

    def write_record(self):
        self.record.write_text(json.dumps(self.fields))
        self.record.chmod(0o600)

    def denied(self, command=None, agent_type='ship:writer--sol', tool='Bash', tin=None):
        payload = {'agent_type': agent_type, 'agent_id': 'agent-1', 'cwd': str(self.root),
                   'tool_name': tool, 'tool_input': tin if tin is not None else {'command': command or self.command}}
        output = io.StringIO()
        with patch.object(hook, 'STATE', self.state), contextlib.redirect_stdout(output):
            try:
                hook.pre(payload)
            except SystemExit as error:
                self.assertEqual(error.code, 0)
        result = output.getvalue()
        decision = json.loads(result)['hookSpecificOutput'] if result else {}
        self.reason = decision.get('permissionDecisionReason', '')
        return decision.get('permissionDecision') == 'deny'

    def test_exact_writer_form(self):
        self.assertFalse(self.denied(), self.reason)

    def test_record_conditions(self):
        for condition in ('missing', 'wrong_id', 'wrong_file', 'expired', 'group_write', 'future', 'link', 'array'):
            with self.subTest(condition=condition):
                if self.record.is_symlink():
                    self.record.unlink()
                self.write_record()
                if condition == 'missing':
                    self.record.unlink()
                elif condition == 'group_write':
                    self.record.chmod(0o620)
                elif condition == 'link':
                    actual = self.root / 'record.json'
                    actual.write_text(self.record.read_text())
                    self.record.unlink()
                    self.record.symlink_to(actual)
                elif condition == 'array':
                    self.record.write_text('[]')
                else:
                    fields = dict(self.fields)
                    if condition == 'wrong_id':
                        fields['row_id'] = 'other'
                    elif condition == 'wrong_file':
                        fields['row_file'] = str(self.row.parent / 'other.toml')
                    else:
                        fields['expires_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(
                            time.time() + (5 * 3600 if condition == 'future' else -1)))
                    self.record.write_text(json.dumps(fields))
                self.assertTrue(self.denied(), self.reason)
                self.assertIn('admission record', self.reason)
                self.assertIn('must exist and meet this condition', self.reason)

    def test_exact_command_boundary(self):
        for command in (
            self.command.replace(str(TOOL), '/another/row_reanchor.py'),
            self.command.replace(str(TOOL), 'row_reanchor.py'),
            self.command.replace(str(self.row), 'tests/mutation/rows.toml'),
            self.command.replace(' -I ', ' '), self.command + ' --extra x',
            self.command + ' && true', self.command + ' | cat', 'X=1 ' + self.command,
            self.command.replace('target', '"target"'), self.command.replace('python3 ', 'python3  '),
            self.command + '\n', self.command.replace('--row-id target', '--row-id other'),
        ):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command), self.reason)
                self.assertIn('Row re-anchor gate', self.reason)

    def test_disguised_options_and_tool_copies_trigger_gate(self):
        self.record.unlink()
        for command in (self.command.replace('--row-file', '--"row-file"'),
                        self.command.replace('--row-file', r'--row\-file'),
                        self.command.replace(str(TOOL), '/another/copied.py'),
                        self.command.replace(str(TOOL), '/another/copied.py')
                        .replace('--row-file', '--"row-file"').replace('--row-id', '--"row-id"'),
                        self.command.replace(str(TOOL), '/another/copied.py')
                        .replace('--row-file', r'--\row-file').replace('--row-id', r'--\row-id'),
                        'python3 -I /another/copied.py --row-id target'):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))
                self.assertIn('Row re-anchor gate', self.reason)

    def test_other_callers(self):
        for caller in ('ship:reviewer--sol', 'ship:driver--sol', ''):
            with self.subTest(caller=caller):
                self.assertTrue(self.denied(agent_type=caller))

    def test_unrelated_commands_keep_their_decision(self):
        for command in ('git add -- plugins/ship/skills/ship/scripts/row_reanchor.py',
                        'python3 -m unittest discover -s scripts -p test_row_reanchor.py'):
            with self.subTest(command=command):
                self.assertFalse(self.denied(command), self.reason)

    def test_record_custody(self):
        for tool, tin in (
            ('Write', {'file_path': str(self.record), 'content': '{}'}),
            ('Edit', {'file_path': str(self.record), 'old_string': 'x', 'new_string': 'y'}),
            ('NotebookEdit', {'notebook_path': str(self.record)}),
            ('Bash', {'command': 'cat /x/ultraship/row-reanchor/agent-1.json'}),
        ):
            with self.subTest(tool=tool):
                self.assertTrue(self.denied(tool=tool, tin=tin))
                self.assertIn('Only the driver and the main session', self.reason)


if __name__ == '__main__':
    unittest.main()
