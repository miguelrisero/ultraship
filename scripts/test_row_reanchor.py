"""Synthetic re-anchor and exact-command admission guarantees."""
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
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
        self.invoke()
        self.head_sha = self.commit()
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
                      'mutant_unchanged': True, 'changed_statements': 0,
                      'base_lines': [4, 10], 'lines': [4, 10]}],
        })

    def test_printed_fields_match_the_record_entry(self):
        self.setup_pair(literal=True, extra='[row.mutant]\noperator = "replace"\n')
        self.invoke()
        self.head_sha = self.commit()
        _, output = self.invoke()
        record = self.record_path()
        data = json.loads(record.read_bytes())
        entry, = data.pop('rows')
        self.assertEqual(entry['base_lines'], [4, 39])
        self.assertEqual(entry['lines'], [4, 12])
        fields = dict(line.split('=', 1) for line in output.splitlines()[1:])
        for key, value in {**data, **entry, 'record': str(record)}.items():
            self.assertEqual(fields[key], value if isinstance(value, str) else json.dumps(value))

    def test_edit_does_not_create_or_change_a_record(self):
        self.setup_pair()
        record = self.record_path()
        prior = b'{"schema": 1, "lane": "expired", "rows": []}'
        for exists in (False, True):
            with self.subTest(existing_record=exists):
                if exists:
                    record.write_bytes(prior)
                before, output = self.invoke()
                self.assertEqual(output.splitlines()[-1], 'record=none')
                self.assertIn('changed_statements=2', output.splitlines())
                self.assertNotEqual(self.row.read_bytes(), before)
                if exists:
                    self.assertEqual(record.read_bytes(), prior)
                else:
                    self.assertFalse(record.exists())
                self.row.write_bytes(before)

    def test_record_expires_on_new_head_and_rerun_changes_zero_statements(self):
        self.setup_pair()
        self.invoke()
        self.head_sha = self.commit()
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
        self.invoke()
        self.invoke(**{'row-file': str(other_row), 'row-id': 'other'})
        self.git('add', '--', other_row.name)
        self.head_sha = self.commit()
        with ThreadPoolExecutor(max_workers=2) as writers:
            first = writers.submit(self.invoke)
            second = writers.submit(self.invoke, **{'row-file': str(other_row), 'row-id': 'other'})
            first.result()
            second.result()
        entries = json.loads(self.record_path().read_bytes())['rows']
        self.assertCountEqual([(row['row_file'], row['row_id']) for row in entries],
                              [('rows.toml', 'target'), ('other.toml', 'other')])

    def restoration_fixture(self):
        old = SENTINEL + '\nstart\nend\n'
        self.setup_pair(old, old.replace('end', 'inserted\nend'), old,
                        extra='[row.mutant]\noperator = "replace"\n')
        prefix, header, tail = self.row.read_text().partition('[[row]]\n')
        table, next_header, suffix = tail.partition('[[hand_run]]\n')
        return prefix, header + table, next_header + suffix

    def commit_rows(self, text):
        self.row.write_text(text)
        self.head_sha = self.commit()
        return self.head_sha

    def test_restoration_inserts_deleted_row_at_base_position(self):
        prefix, table, suffix = self.restoration_fixture()
        starting = self.commit_rows(prefix + suffix)
        restoration = self.commit_rows(prefix + table + suffix)
        before, output = self.invoke(restoration=restoration)
        self.assertEqual(self.row.read_bytes(), before)
        # The restored hunk includes the separator before the row.
        fields = {'restoration': restoration, 'restoration_parent': starting,
                  'restoration_lines': [4, 12], 'starting_lines': None, 'insert_after': 2,
                  'restored_rows': 1, 'restoration_base_equal': True, 'restoration_outside_equal': True,
                  'changed_statements': 0}
        record = self.record_path()
        entry, = json.loads(record.read_bytes())['rows']
        for key, value in fields.items():
            self.assertEqual(entry[key], value)
            printed = value if isinstance(value, str) else json.dumps(value)
            self.assertIn(f'{key}={printed}', output.splitlines())
        self.assertEqual(output.splitlines()[-1], f'record={record}')

    def test_restoration_accepts_plain_revert_and_preserves_unrelated_edit(self):
        prefix, table, suffix = self.restoration_fixture()
        deletion = self.commit_rows(prefix + suffix)
        edited_suffix = suffix.replace('id = "retired"', 'id = "lane-retired"')
        starting = self.commit_rows(prefix + edited_suffix)
        self.git('revert', '--no-edit', deletion)
        self.head_sha = self.git('rev-parse', 'HEAD')
        self.assertEqual(self.row.read_text(), prefix + table + edited_suffix)
        _, output = self.invoke(restoration=self.head_sha)
        self.assertEqual(self.row.read_text(), prefix + table + edited_suffix)
        self.assertIn(f'restoration_parent={starting}', output.splitlines())
        self.assertIn('restoration_outside_equal=true', output.splitlines())

    def test_restoration_with_empty_net_row_diff_only_writes_record(self):
        prefix, table, suffix = self.restoration_fixture()
        edited = self.commit_rows(prefix + table.replace('claim =', 'claim  =') + suffix)
        self.subject.write_text('# outside the pair\n' + self.subject.read_text())
        starting = self.commit()
        self.git('revert', '--no-edit', edited)
        self.head_sha = self.git('rev-parse', 'HEAD')
        self.git('diff', '--quiet', self.base, self.head_sha, '--', self.row.name)
        self.assertEqual(self.git('--no-optional-locks', 'status', '--porcelain'), '')
        index = self.root / self.git('rev-parse', '--git-path', 'index')
        index_before = index.read_bytes()
        row_inode = self.row.stat().st_ino
        record = self.record_path()
        self.assertFalse(record.exists())

        before, output = self.invoke(restoration=self.head_sha)

        self.assertIn('changed_statements=0', output.splitlines())
        self.assertIn(f'record={record}', output.splitlines())
        data = json.loads(record.read_bytes())
        entry, = data['rows']
        self.assertEqual(data['head'], self.head_sha)
        self.assertEqual(entry['row_id'], 'target')
        self.assertEqual(entry['changed_statements'], 0)
        self.assertEqual(entry['restoration'], self.head_sha)
        self.assertEqual(entry['restoration_parent'], starting)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.head_sha)
        self.assertEqual(index.read_bytes(), index_before)
        self.assertEqual(self.row.stat().st_ino, row_inode)
        self.assertEqual(self.row.read_bytes(), before)
        self.assertEqual(self.git('--no-optional-locks', 'status', '--porcelain'), '')

    def test_restoration_missing_head_subject_reports_only_git_operation_and_exit(self):
        prefix, table, suffix = self.restoration_fixture()
        deletion = self.commit_rows(prefix + suffix)
        self.git('revert', '--no-edit', deletion)
        restoration = self.git('rev-parse', 'HEAD')
        self.git('rm', '--', self.subject.name)
        self.git('commit', '-qm', 'remove fixture subject')
        self.head_sha = self.git('rev-parse', 'HEAD')

        reason = 'read head subject blob (Git exit 128)'
        _, output = self.invoke(2, reason, restoration=restoration)

        self.assertEqual(output, f'REFUSED: {reason}\n')
        self.assertFalse(self.record_path().exists())

    def test_restoration_keeps_lane_edit_in_the_deleted_row_hunk(self):
        prefix, table, suffix = self.restoration_fixture()
        base_prefix = prefix.removesuffix('\n') + '# base comment\n'
        self.base = self.commit_rows(base_prefix + table + suffix)
        lane_prefix = base_prefix.replace('# base comment', '# lane comment')
        self.commit_rows(lane_prefix + suffix)
        restoration = self.commit_rows(lane_prefix + table + suffix)
        _, output = self.invoke(restoration=restoration)
        self.assertEqual(self.row.read_text(), lane_prefix + table + suffix)
        self.assertIn('insert_after=3', output.splitlines())

    def test_restoration_removes_child_table_appended_to_the_row(self):
        prefix, table, suffix = self.restoration_fixture()
        child = '[row.extra]\nvalue = "lane"\n'
        self.commit_rows(prefix + table.rstrip('\n') + '\n' + child + '\n' + suffix)
        restoration = self.commit_rows(prefix + table + suffix)
        _, output = self.invoke(restoration=restoration)
        self.assertEqual(self.row.read_text(), prefix + table + suffix)
        self.assertIn('starting_lines=[4, 14]', output.splitlines())

    def test_restoration_positions_two_deleted_rows_with_identical_headers(self):
        prefix, table, suffix = self.restoration_fixture()
        other = table.replace('id = "target"', 'id = "second"')
        middle = '[marker]\nname = "between"\n\n'
        self.base = self.commit_rows(prefix + table + middle + other + suffix)
        self.commit_rows(prefix + middle + suffix)
        restoration = self.commit_rows(prefix + table + middle + other + suffix)
        for row_id, position in (('target', 2), ('second', 5)):
            _, output = self.invoke(restoration=restoration, **{'row-id': row_id})
            self.assertIn(f'insert_after={position}', output.splitlines())
        entries = json.loads(self.record_path().read_bytes())['rows']
        self.assertEqual([(entry['row_id'], entry['insert_after']) for entry in entries],
                         [('target', 2), ('second', 5)])

    def test_restoration_accepts_revert_of_whole_row_file_deletion(self):
        _, table, _ = self.restoration_fixture()
        self.base = self.commit_rows(table)
        self.git('rm', '--', self.row.name)
        self.git('commit', '-qm', 'delete row file')
        starting = self.git('rev-parse', 'HEAD')
        self.git('revert', '--no-edit', starting)
        self.head_sha = self.git('rev-parse', 'HEAD')
        _, output = self.invoke(restoration=self.head_sha)
        self.assertEqual(self.row.read_text(), table)
        self.assertIn('starting_lines=null', output.splitlines())
        self.assertIn('insert_after=0', output.splitlines())

    def test_restoration_rerun_at_later_head_uses_restoration_parent(self):
        prefix, table, suffix = self.restoration_fixture()
        starting = self.commit_rows(prefix + table.replace('claim =', 'claim  =') + suffix)
        restoration = self.commit_rows(prefix + table + suffix)
        self.invoke(restoration=restoration)
        self.head_sha = self.commit()
        _, output = self.invoke(restoration=restoration)
        record = json.loads(self.record_path().read_bytes())
        entry, = record['rows']
        self.assertEqual(record['head'], self.head_sha)
        self.assertEqual(entry['restoration'], restoration)
        self.assertEqual(entry['restoration_parent'], starting)
        self.assertEqual(entry['starting_lines'], [4, 12])
        self.assertIn('changed_statements=0', output.splitlines())

    def test_restoration_refuses_one_changed_row_byte(self):
        prefix, table, suffix = self.restoration_fixture()
        self.commit_rows(prefix + suffix)
        restoration = self.commit_rows(prefix + table.replace('"replace"', '"replacE"') + suffix)
        self.invoke(2, 'restored row differs from the merge base', restoration=restoration)
        self.assertFalse(self.record_path().exists())

    def test_restoration_refuses_blank_line_change_inside_row(self):
        prefix, table, suffix = self.restoration_fixture()
        table = table.replace('claim = "same guarantee"', "claim = '''same\n\nguarantee'''")
        self.base = self.commit_rows(prefix + table + suffix)
        self.commit_rows(prefix + suffix)
        restoration = self.commit_rows(prefix + table.replace('same\n\n', 'same\n') + suffix)
        self.invoke(2, 'restored row differs from the merge base', restoration=restoration)
        self.assertFalse(self.record_path().exists())

    def test_restoration_refuses_adjacent_nonblank_change_in_same_hunk(self):
        prefix, table, suffix = self.restoration_fixture()
        self.commit_rows(prefix.removesuffix('\n') + '# lane comment\n' + suffix)
        restoration = self.commit_rows(prefix + table + suffix)
        self.invoke(2, 'restoration changed bytes outside restored rows', restoration=restoration)
        self.assertFalse(self.record_path().exists())

    def test_restoration_refuses_a_comment_in_the_deleted_rows_place(self):
        prefix, table, suffix = self.restoration_fixture()
        lane_prefix = prefix.removesuffix('\n') + '# lane comment\n'
        self.commit_rows(lane_prefix + suffix)
        restoration = self.commit_rows(lane_prefix + table + suffix)
        self.invoke(2, 'restored row position is ambiguous', restoration=restoration)
        self.assertFalse(self.record_path().exists())

    def test_restoration_refuses_a_leading_blank_when_restoring_a_deleted_file(self):
        _, table, _ = self.restoration_fixture()
        self.base = self.commit_rows(table)
        self.git('rm', '--', self.row.name)
        self.git('commit', '-qm', 'delete row file')
        restoration = self.commit_rows('\n' + table)
        self.invoke(2, 'restoration changed bytes outside restored rows', restoration=restoration)
        self.assertFalse(self.record_path().exists())

    def test_restoration_refuses_an_extra_blank_next_to_the_row(self):
        prefix, table, suffix = self.restoration_fixture()
        self.commit_rows(prefix + suffix)
        restoration = self.commit_rows(prefix + '\n' + table + suffix)
        self.invoke(2, 'restoration changed bytes outside restored rows', restoration=restoration)
        self.assertFalse(self.record_path().exists())

    def test_restoration_refuses_dropping_a_starting_head_separator(self):
        prefix, table, suffix = self.restoration_fixture()
        self.commit_rows(prefix + suffix)
        restoration = self.commit_rows(prefix + table.removesuffix('\n') + suffix)
        self.invoke(2, 'restoration changed bytes outside restored rows', restoration=restoration)
        self.assertFalse(self.record_path().exists())

    def test_restoration_refuses_outside_edit_and_misplaced_row(self):
        prefix, table, suffix = self.restoration_fixture()
        starting = self.commit_rows(prefix + suffix)
        for case, restored in (
            ('outside edit', prefix + table + suffix.replace('id = "retired"', 'id = "retireD"')),
            ('misplaced row', prefix + suffix + '\n' + table),
        ):
            with self.subTest(case=case):
                self.git('checkout', '-qb', case.replace(' ', '-'), starting)
                restoration = self.commit_rows(restored)
                self.invoke(2, 'restoration changed bytes outside restored rows', restoration=restoration)
                self.assertFalse(self.record_path().exists())

    def test_restoration_records_both_rows_from_one_commit(self):
        prefix, table, suffix = self.restoration_fixture()
        other = table.replace('id = "target"', 'id = "second"')
        original = prefix + table + other + suffix
        self.base = self.commit_rows(original)
        self.commit_rows(prefix + suffix)
        restoration = self.commit_rows(original)
        for row_id in ('target', 'second'):
            _, output = self.invoke(restoration=restoration, **{'row-id': row_id})
            self.assertIn('restored_rows=2', output.splitlines())
        entries = json.loads(self.record_path().read_bytes())['rows']
        self.assertEqual([(entry['row_id'], entry['restored_rows']) for entry in entries],
                         [('target', 2), ('second', 2)])
        self.assertEqual(self.row.read_text(), original)

    def test_restoration_refuses_unchanged_row(self):
        prefix, table, suffix = self.restoration_fixture()
        self.commit_rows(prefix + table + suffix.replace('"retired"', '"lane-retired"'))
        self.invoke(2, 'restoration commit leaves the row unchanged', restoration=self.head_sha)
        self.assertFalse(self.record_path().exists())

    def test_restoration_refuses_another_changed_path(self):
        prefix, table, suffix = self.restoration_fixture()
        self.commit_rows(prefix + suffix)
        (self.root / 'other.txt').write_text('another edit\n')
        restoration = self.commit_rows(prefix + table + suffix)
        self.invoke(2, 'restoration commit must change only the row file', restoration=restoration)
        self.assertFalse(self.record_path().exists())

    def test_restoration_refuses_a_file_mode_change_back_to_base(self):
        prefix, table, suffix = self.restoration_fixture()
        self.git('config', 'core.filemode', 'true')
        base_mode = self.row.stat().st_mode & 0o777
        self.row.chmod(base_mode | 0o100)
        self.commit_rows(prefix + suffix)
        self.row.chmod(base_mode)
        restoration = self.commit_rows(prefix + table + suffix)
        self.invoke(2, 'restoration commit must change only the row file', restoration=restoration)
        self.assertFalse(self.record_path().exists())

    def test_restoration_refuses_replacing_a_symlink_with_a_row_file(self):
        prefix, table, suffix = self.restoration_fixture()
        self.row.unlink()
        # Use valid TOML in the link so only the path guard can refuse it.
        os.symlink(prefix + suffix, self.row)
        self.commit()
        self.row.unlink()
        restoration = self.commit_rows(prefix + table + suffix)
        self.invoke(2, 'restoration commit must change only the row file', restoration=restoration)
        self.assertFalse(self.record_path().exists())

    def test_restoration_refuses_a_row_moved_in_its_starting_head(self):
        prefix, table, suffix = self.restoration_fixture()
        self.commit_rows(prefix + suffix + '\n' + table.replace('claim =', 'claim  ='))
        restoration = self.commit_rows(prefix + table + suffix)
        self.invoke(2, 'restored row moved', restoration=restoration)
        self.assertFalse(self.record_path().exists())

    def test_restoration_refuses_a_deleted_row_between_two_changed_lines(self):
        prefix, table, suffix = self.restoration_fixture()
        self.base = self.commit_rows(prefix + '# first\n' + table + '# last\n' + suffix)
        self.commit_rows(prefix + '# lane\n' + suffix)
        restoration = self.commit_rows(prefix + '# lane\n' + table + suffix)
        self.invoke(2, 'restored row position is ambiguous', restoration=restoration)
        self.assertFalse(self.record_path().exists())

    def test_restoration_refuses_the_merge_base_itself(self):
        prefix, table, suffix = self.restoration_fixture()
        self.commit_rows(prefix + suffix)
        self.base = self.commit_rows(prefix + table + suffix)
        self.head_sha = self.commit()
        self.invoke(2, 'merge base must be an ancestor of the restoration parent', restoration=self.base)
        self.assertFalse(self.record_path().exists())

    def test_restoration_refuses_merge_commit(self):
        prefix, table, suffix = self.restoration_fixture()
        starting = self.commit_rows(prefix + suffix)
        lane = self.git('branch', '--show-current')
        self.git('checkout', '-qb', 'restore-side', starting)
        self.commit_rows(prefix + table + suffix)
        self.git('checkout', '-q', lane)
        self.git('merge', '--no-ff', '--no-edit', 'restore-side')
        self.head_sha = self.git('rev-parse', 'HEAD')
        self.invoke(2, 'restoration must have exactly one parent', restoration=self.head_sha)
        self.assertFalse(self.record_path().exists())

    def test_restoration_refuses_commit_outside_head_history(self):
        prefix, table, suffix = self.restoration_fixture()
        starting = self.commit_rows(prefix + suffix)
        restoration = self.commit_rows(prefix + table + suffix)
        self.git('checkout', '-qb', 'different-lane', starting)
        self.head_sha = self.commit()
        self.invoke(2, 'restoration must be HEAD or an ancestor of HEAD', restoration=restoration)
        self.assertFalse(self.record_path().exists())

    def test_restoration_reports_fatal_git_ancestry_failures(self):
        prefix, table, suffix = self.restoration_fixture()
        starting = self.commit_rows(prefix + suffix)
        restoration = self.commit_rows(prefix + table + suffix)
        self.head_sha = self.commit()
        original = self.row.read_bytes()
        record = self.record_path()
        record.parent.mkdir(mode=0o700)
        prior = b'{"schema": 1, "lane": "expired", "rows": []}'
        record.write_bytes(prior)
        argv = [str(TOOL), '--row-file', str(self.row), '--row-id', 'target', '--subject', 'subject.txt',
                '--base', self.base, '--head', self.head_sha, '--restoration', restoration]
        env = {'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}
        run = subprocess.run

        for operation, commits in (('check restoration ancestry', [restoration, self.head_sha]),
                                   ('check base ancestry', [self.base, starting])):
            with self.subTest(operation=operation):
                def fail_ancestry(command, **kwargs):
                    if command[-4:] == ['merge-base', '--is-ancestor', *commits]:
                        result = subprocess.CompletedProcess(command, 128, SENTINEL.encode(), SENTINEL.encode())
                        if kwargs.get('check'):
                            result.check_returncode()
                        return result
                    return run(command, **kwargs)

                stdout, stderr = io.StringIO(), io.StringIO()
                with patch.dict(os.environ, env), patch('sys.argv', argv), \
                        patch.object(reanchor.subprocess, 'run', side_effect=fail_ancestry), \
                        contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    self.assertEqual(reanchor.main(), 2)
                self.assertTrue(stdout.getvalue() == f'REFUSED: {operation} (Git exit 128)\n',
                                'stdout must contain only the fixed refusal')
                self.assertFalse(stderr.getvalue(), 'stderr must be empty')
                self.assertEqual(self.row.read_bytes(), original)
                self.assertEqual(record.read_bytes(), prior)

    def test_restoration_refuses_duplicate_row_id(self):
        prefix, table, suffix = self.restoration_fixture()
        self.commit_rows(prefix + suffix)
        restoration = self.commit_rows(prefix + table + table + suffix)
        self.commit_rows(prefix + table + suffix)
        self.invoke(2, 'row ID must match exactly once', restoration=restoration)
        self.assertFalse(self.record_path().exists())

    def test_restoration_refuses_duplicate_row_id_under_quoted_header(self):
        prefix, table, suffix = self.restoration_fixture()
        self.commit_rows(prefix + suffix)
        restored = prefix + table + suffix
        restoration = self.commit_rows(restored + '\n[["row"]]\nid = "target"\n')
        self.commit_rows(restored)
        self.invoke(2, 'row ID must match exactly once', restoration=restoration)
        self.assertFalse(self.record_path().exists())

    def run_with_lock_held(self, while_locked):
        record = self.record_path()
        record.parent.mkdir(mode=0o700, exist_ok=True)
        output = io.StringIO()
        args = Namespace(row_file=str(self.row), row_id='target', subject='subject.txt',
                         base=self.base, head=self.head_sha, restoration=None)
        lock_checked_or_done = Event()
        flock = fcntl.flock

        def observe_lock(descriptor, operation):
            self.assertEqual(operation, fcntl.LOCK_EX)
            with self.assertRaises(BlockingIOError):
                flock(descriptor, operation | fcntl.LOCK_NB)
            lock_checked_or_done.set()
            return flock(descriptor, operation)

        env = {'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}
        with patch.dict(os.environ, env), contextlib.redirect_stdout(output), \
                ThreadPoolExecutor(max_workers=1) as writer:
            with record.with_suffix('.lock').open('a+b') as lock:
                flock(lock.fileno(), fcntl.LOCK_EX)
                with patch.object(reanchor.fcntl, 'flock', side_effect=observe_lock):
                    deadline = time.monotonic() + 5
                    result = writer.submit(reanchor.run, args)
                    result.add_done_callback(lambda _: lock_checked_or_done.set())
                    self.assertTrue(lock_checked_or_done.wait(deadline - time.monotonic()),
                                    'tool did not attempt to acquire the lock')
                    if result.done():
                        result.result()
                        self.fail('tool finished while the record lock was held')
                    while_locked()
            result.result(timeout=deadline - time.monotonic())
        return output.getvalue()

    def test_record_write_waits_for_exclusive_lock(self):
        self.setup_pair()
        self.invoke()
        self.head_sha = self.commit()
        record = self.record_path()
        prior = json.dumps({'schema': 1, 'lane': self.git('branch', '--show-current'),
                            'base': self.base, 'head': self.head_sha, 'rows': []}).encode()
        record.write_bytes(prior)
        self.run_with_lock_held(lambda: self.assertEqual(record.read_bytes(), prior))
        entry, = json.loads(record.read_bytes())['rows']
        self.assertEqual((entry['row_file'], entry['row_id']), ('rows.toml', 'target'))

    def test_row_edit_waits_for_exclusive_lock_before_checking_bytes(self):
        self.setup_pair()
        original = self.row.read_bytes()
        read_bytes = Path.read_bytes
        replace = os.replace
        flock = fcntl.flock
        row_reads = []
        lock_path = self.record_path().with_suffix('.lock')

        def observe_read(path):
            if path == self.row:
                row_reads.append(path)
            return read_bytes(path)

        def observe_replace(source, target):
            if target == self.row:
                with lock_path.open('r+b') as lock, self.assertRaises(BlockingIOError):
                    flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            replace(source, target)

        def check_waiting_edit():
            self.assertEqual(row_reads, [self.row])
            self.assertEqual(read_bytes(self.row), original)

        with patch.object(Path, 'read_bytes', observe_read), patch.object(os, 'replace', observe_replace):
            output = self.run_with_lock_held(check_waiting_edit)
        row, = tomllib.loads(self.row.read_text())['row']
        self.assertEqual(row['old'], self.head)
        self.assertIn('record=none', output.splitlines())
        self.assertFalse(self.record_path().exists())

    def test_subject_commit_while_waiting_for_lock_refuses_without_writing(self):
        self.setup_pair()
        original = self.row.read_bytes()
        record = self.record_path()
        record.parent.mkdir(mode=0o700)
        prior = b'{"schema": 1, "lane": "expired", "rows": []}'
        record.write_bytes(prior)

        def commit_subject_change():
            self.subject.write_text(self.subject.read_text().replace('grown_b()', 'new_at_head()'))
            self.assertNotEqual(self.commit(), self.head_sha)
            self.assertEqual(self.row.read_bytes(), original)

        with self.assertRaisesRegex(reanchor.Refused, '^HEAD changed during derivation$'):
            self.run_with_lock_held(commit_subject_change)
        self.assertEqual(self.row.read_bytes(), original)
        self.assertEqual(record.read_bytes(), prior)

    def test_subject_commit_after_staging_refuses_both_replacements(self):
        self.setup_pair()
        record = self.record_path()
        record.parent.mkdir(mode=0o700)
        prior = b'{"schema": 1, "lane": "expired", "rows": []}'
        record.write_bytes(prior)
        staged_bytes = reanchor.staged_bytes
        output = io.StringIO()
        env = {'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}

        for destination in (self.row, record):
            with self.subTest(destination=destination):
                if destination == record:
                    self.invoke()
                    self.head_sha = self.commit()
                original = self.row.read_bytes()
                args = Namespace(row_file=str(self.row), row_id='target', subject='subject.txt',
                                 base=self.base, head=self.head_sha, restoration=None)

                @contextlib.contextmanager
                def stage_then_commit(path, data, mode):
                    with staged_bytes(path, data, mode) as stage:
                        self.assertEqual(path, destination)
                        with self.subject.open('a') as subject:
                            subject.write('subject changed during staging\n')
                        self.assertNotEqual(self.commit(), self.head_sha)
                        yield stage

                with patch.dict(os.environ, env), contextlib.redirect_stdout(output), \
                        patch.object(reanchor, 'staged_bytes', stage_then_commit):
                    with self.assertRaisesRegex(reanchor.Refused, '^HEAD changed during staged write$'):
                        reanchor.run(args)
                self.assertEqual(self.row.read_bytes(), original)
                self.assertEqual(record.read_bytes(), prior)
                self.head_sha = self.git('rev-parse', 'HEAD')
        self.assertEqual(output.getvalue(), '')

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

    def test_record_replace_failure_preserves_original_row_and_prior_record(self):
        self.setup_pair()
        self.invoke()
        self.head_sha = self.commit()
        record = self.record_path()
        prior = b'{"schema": 1, "lane": "expired", "rows": []}'
        record.write_bytes(prior)
        original = self.row.read_bytes()
        argv = [str(TOOL), '--row-file', str(self.row), '--row-id', 'target', '--subject', 'subject.txt',
                '--base', self.base, '--head', self.head_sha]
        replace = os.replace

        def fail_record_replace(source, target):
            if target == record:
                self.assertEqual(self.row.read_bytes(), original)
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

    def test_exact_restoration_suffix(self):
        sha = 'a' * 40
        suffix = f' --restoration {sha}'
        self.assertFalse(self.denied(self.command + suffix), self.reason)
        for command in (self.command + ' --restoration', self.command + suffix * 2,
                        self.command + f' --restoration "{sha}"',
                        self.command.replace(' --head', suffix + ' --head')):
            with self.subTest(command=command):
                self.assertTrue(self.denied(command), self.reason)
                self.assertIn('[--restoration <commit>]', self.reason)

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
