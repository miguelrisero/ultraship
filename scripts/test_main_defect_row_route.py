"""Content-free admission tests; protected files and pair text never enter these fixtures."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('main_defect_hook', ROOT / 'plugins/ship/hooks/ultraship.py')
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class MainDefectAdmissionTests(unittest.TestCase):
    """Exercise the real pre boundary with ordinary metadata and mocked filesystem/Git reads."""

    def setUp(self):
        self.root = '/synthetic/repair'
        self.row = self.root + '/tests/mutation/example.toml'
        self.fields = {
            'route': 'single-main-defect', 'repository': 'example/repo',
            'pr': 'https://github.com/example/repo/pull/1', 'branch': 'repair-one-row',
            'worktree': self.root, 'frozen_main': 'a' * 40, 'main_tree': 'b' * 40,
            'final_commit': None, 'row_file': self.row, 'row_id': 'existing-id',
            'extent': [20, 30], 'subject': 'src/example.py', 'designated_test': 'tests/test_example.py',
            'permitted_fields': ['old', 'new'], 'writer_id': 'writer-1', 'reviewer_id': 'reviewer-1',
            'author_id': 'author-1', 'deriver_id': 'writer-1', 'stage': 'proposal',
            'main_defect_receipt_sha256': 'c' * 64, 'existing_row_receipt_sha256': 'd' * 64,
            'row_only': True, 'fresh_writer': True, 'fresh_reviewer': True,
            'effective_refusal': False, 'affected_session_hold': False,
            'authority': {'kind': 'coc-main-defect', 'decision_sha256': 'e' * 64,
                          'scope_sha256': '', 'verified_by': 'coordinator',
                          'verified_at': '2026-11-17T10:00:00Z'},
            'adoption': {'agent_id': 'reviewer-1', 'hook_sha256': 'f' * 64,
                         'contract_sha256': '1' * 64, 'verified': True},
            'access': {'agent_id': 'reviewer-1', 'read': True, 'edit': False,
                       'derive': False, 'loaded': True},
        }
        self.payload = {'agent_type': 'ship:reviewer--sol', 'agent_id': 'reviewer-1',
                        'cwd': self.root, 'tool_name': 'Read',
                        'tool_input': {'file_path': self.row, 'offset': 20, 'limit': 11}}
        self.enterContext(patch.object(hook, 'receipt_custody'))
        self.enterContext(patch.object(hook, 'canonical_row_path', side_effect=lambda p:
                                     isinstance(p, str) and p.startswith('/') and '..' not in p.split('/')))
        self.enterContext(patch.object(hook, 'regular_file', return_value=True))
        self.enterContext(patch.object(hook, 'main_defect_git', side_effect=self.git))
        self.enterContext(patch.object(hook, 'main_defect_runtime', return_value=('f' * 64, '1' * 64)))
        self.enterContext(patch.object(hook, 'row_record', side_effect=self.record))

    def git(self, root, *args):
        self.assertEqual(root, self.root)
        return {
            ('rev-parse', '--show-toplevel'): self.root,
            ('rev-parse', '--abbrev-ref', 'HEAD'): 'repair-one-row',
            ('rev-parse', 'refs/remotes/origin/main'): 'a' * 40,
            ('rev-parse', 'refs/remotes/origin/main^{tree}'): 'b' * 40,
            ('rev-parse', 'HEAD'): '2' * 40 if self.fields['stage'] in ('applied', 'publication') else 'a' * 40,
            ('rev-list', '--parents', '-n', '1', 'HEAD'): '2' * 40 + ' ' + 'a' * 40,
            ('diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD'): 'tests/mutation/example.toml',
        }[args]

    def seal(self):
        self.fields['authority']['scope_sha256'] = hook.main_defect_scope(self.fields)

    def record(self, data, folder, **kwargs):
        error = hook.main_defect_record(data, self.fields)
        return (None, error) if error else (self.fields, 'synthetic admission: ')

    def decision(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            try:
                hook.guarded_pre(self.payload)
            except SystemExit as error:
                self.assertEqual(error.code, 0)
        return json.loads(output.getvalue())['hookSpecificOutput'] if output.getvalue() else {}

    def assert_denied(self):
        decision = self.decision()
        self.assertEqual(decision.get('permissionDecision'), 'deny', decision)
        self.assertIn('single-main-defect', decision.get('permissionDecisionReason', ''))

    def test_exact_read_and_whole_line_id_lookup(self):
        self.seal()
        self.assertEqual(self.decision(), {})
        self.payload.update(tool_name='Grep', tool_input={
            'path': self.row, 'pattern': '^id = "existing-id"$', 'output_mode': 'content',
            '-n': True, 'head_limit': 1})
        self.assertEqual(self.decision(), {})

    def test_missing_authority_and_each_required_binding_fail_closed(self):
        original = copy.deepcopy(self.fields)
        for field in ('authority', 'adoption', 'access', 'repository', 'pr', 'branch', 'worktree',
                      'frozen_main', 'main_tree', 'row_id', 'extent', 'subject', 'designated_test',
                      'permitted_fields', 'main_defect_receipt_sha256', 'existing_row_receipt_sha256',
                      'fresh_writer', 'fresh_reviewer', 'row_only'):
            with self.subTest(field=field):
                self.fields = copy.deepcopy(original)
                self.fields.pop(field)
                self.seal_if_possible()
                self.assert_denied()

    def seal_if_possible(self):
        if 'authority' in self.fields:
            self.seal()

    def test_mismatched_scope_stale_main_and_wrong_actor(self):
        self.seal()
        for field, value in (('frozen_main', '9' * 40), ('main_tree', '9' * 40),
                             ('row_id', 'other-id'), ('extent', [19, 30]),
                             ('permitted_fields', ['old', 'new', 'claim'])):
            with self.subTest(field=field):
                saved = self.fields[field]
                self.fields[field] = value
                self.assert_denied()
                self.fields[field] = saved
        self.payload['agent_id'] = 'other-reviewer'
        self.assert_denied()

    def test_resealed_stale_source_and_invalid_scope_still_fail(self):
        original = copy.deepcopy(self.fields)
        for field, value in (('frozen_main', '9' * 40), ('main_tree', '9' * 40),
                             ('worktree', '/synthetic/other'), ('branch', 'other-branch'),
                             ('row_file', '/synthetic/other/tests/mutation/example.toml'),
                             ('extent', [30, 20]), ('extent', [True, 30]),
                             ('permitted_fields', ['old', 'new', 'test']),
                             ('effective_refusal', True), ('affected_session_hold', True),
                             ('reviewer_id', 'writer-1'), ('deriver_id', 'reviewer-1')):
            with self.subTest(field=field, value=value):
                self.fields = copy.deepcopy(original)
                self.fields[field] = value
                self.seal()
                self.assert_denied()

    def test_whole_file_neighboring_rows_and_broad_search_fail(self):
        self.seal()
        for tool, inputs in (
            ('Read', {'file_path': self.row}),
            ('Read', {'file_path': self.row, 'offset': 19, 'limit': 12}),
            ('Read', {'file_path': self.row, 'offset': 20, 'limit': 12}),
            ('Read', {'file_path': self.root + '/tests/mutation/other.toml', 'offset': 20, 'limit': 11}),
            ('Grep', {'path': self.row, 'pattern': 'id'}),
            ('Grep', {'path': self.row, 'pattern': '^id = "existing-id"$', '-A': 1}),
            ('Glob', {'path': self.row, 'pattern': '*'}),
            ('LSP', {'filePath': self.row, 'operation': 'hover'}),
        ):
            with self.subTest(tool=tool, inputs=inputs):
                self.payload.update(tool_name=tool, tool_input=inputs)
                self.assert_denied()

    def review(self, stage):
        return {'stage': stage, 'reviewer_id': 'reviewer-1', 'scope_sha256': hook.main_defect_scope(self.fields),
                'proposal_sha256': '3' * 64, 'receipt_sha256': '4' * 64,
                'same_operation': True, 'same_claim': True, 'not_weaker': True,
                'frozen_before_sha256': '5' * 64, 'frozen_after_sha256': '5' * 64,
                'context': 'adjacent-unchanged-source', 'verdict': 'pass',
                'commit': self.fields['final_commit'] if stage == 'applied' else self.fields['frozen_main']}

    def publication(self):
        self.fields.update(stage='publication', final_commit='2' * 40, proposal_sha256='3' * 64,
                           proposal_review=self.review('proposal'), applied_review=self.review('applied'))
        self.seal()
        for key in ('proposal_review', 'applied_review'):
            self.fields[key] = self.review('applied' if key == 'applied_review' else 'proposal')
        self.fields['count_evidence'] = {
            'actor': 'CoC', 'commit': '2' * 40, 'scope_sha256': hook.main_defect_scope(self.fields),
            'proposal_sha256': '3' * 64, 'count': 1, 'expected': 1, 'rows_touching': 'pass',
            'gate_sha256': '6' * 64, 'receipt_sha256': '7' * 64}
        self.fields['approval'] = 'Approved: ' + '4' * 64

    def test_publication_requires_exact_review_count_and_approval(self):
        self.publication()
        self.assertEqual(self.decision(), {})
        original = copy.deepcopy(self.fields)
        for field in ('proposal_review', 'applied_review', 'count_evidence', 'approval'):
            with self.subTest(missing=field):
                self.fields = copy.deepcopy(original)
                self.fields.pop(field)
                self.assert_denied()
        for section, key, value in (
            ('proposal_review', 'proposal_sha256', '8' * 64),
            ('applied_review', 'commit', '8' * 40),
            ('applied_review', 'reviewer_id', 'writer-1'),
            ('applied_review', 'frozen_after_sha256', '8' * 64),
            ('applied_review', 'same_operation', False),
            ('count_evidence', 'count', 0), ('count_evidence', 'count', True),
            ('count_evidence', 'actor', 'writer-1'), ('count_evidence', 'commit', '8' * 40),
        ):
            with self.subTest(section=section, key=key):
                self.fields = copy.deepcopy(original)
                self.fields[section][key] = value
                self.assert_denied()
        self.fields = copy.deepcopy(original)
        self.fields['approval'] = 'Approved: ' + '8' * 64
        self.assert_denied()

    def test_writer_native_boundary_refuses_excess_tools_and_unreviewed_edits(self):
        self.fields['adoption']['agent_id'] = self.fields['access']['agent_id'] = 'writer-1'
        self.fields['access'].update(edit=True)
        self.payload.update(agent_type='ship:writer--sol', agent_id='writer-1')
        self.seal()
        self.assertEqual(self.decision(), {})
        for tool, inputs in (('Write', {'file_path': self.row, 'content': ''}),
                             ('NotebookEdit', {'notebook_path': self.row}),
                             ('Edit', {'file_path': self.row, 'replace_all': True}),
                             ('Edit', {'file_path': self.row, 'replace_all': False})):
            with self.subTest(tool=tool):
                self.payload.update(tool_name=tool, tool_input=inputs)
                self.assert_denied()


if __name__ == '__main__':
    unittest.main()
