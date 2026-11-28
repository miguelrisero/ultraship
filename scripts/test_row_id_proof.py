"""Exercise driver lookups with synthetic Patricia receipts and no row checkout."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'plugins/ship/skills/ship/scripts/row-id-proof.py'
REPOSITORY = 'bettergroupinc/patricia-monorepo'
PR_URL = f'https://github.com/{REPOSITORY}/pull/1'
ROW_ID = 'exact-fixture-id'
ROW_FILE = 'tests/mutation/fixture-proof.toml'
SUBJECT = 'backend/api/fixture_subject.py'
BASE = 'a' * 40
HEAD = 'b' * 40


class RowIdProofTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.receipt = Path(directory.name).resolve() / 'row-id-proof.json'
        self.record = {
            'schema': 'row-id-proof/v1', 'repository': REPOSITORY, 'pr': 1,
            'row_id': ROW_ID, 'row_file': ROW_FILE, 'subject': SUBJECT,
            'base': {'commit': BASE, 'tree': 'c' * 40, 'blob': 'd' * 40, 'count': 1},
            'head': {'commit': HEAD, 'tree': 'e' * 40, 'blob': 'f' * 40, 'count': 1, 'active_count': 1},
        }

    def run_lookup(self, records, *, sha256=None, repository=REPOSITORY, pr_url=PR_URL,
                   base=BASE, head=HEAD, row_id=ROW_ID):
        content = json.dumps(records).encode('utf-8')
        self.receipt.write_bytes(content)
        self.receipt.chmod(0o600)
        digest = hashlib.sha256(content).hexdigest() if sha256 is None else sha256
        return subprocess.run(
            [sys.executable, '-I', str(SCRIPT), '--receipt', str(self.receipt), '--sha256', digest,
             '--repository', repository, '--pr-url', pr_url, '--base', base, '--head', head, '--row-id', row_id],
            cwd=self.receipt.parent, text=True, capture_output=True,
        )

    def assert_refused(self, result):
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, '')
        for value in (ROW_ID, ROW_FILE, SUBJECT):
            self.assertNotIn(value, result.stderr)

    def test_exact_id_returns_only_paths_without_a_row_file(self):
        other = {**self.record, 'row_id': f'{ROW_ID}-other', 'subject': 'backend/api/other.py'}
        result = self.run_lookup([other, self.record])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(json.loads(result.stdout), {'row_file': ROW_FILE, 'subject': SUBJECT})
        self.assertEqual(list(self.receipt.parent.iterdir()), [self.receipt])

    def test_refuses_mismatched_digest_or_scope(self):
        for field, value in (
            ('sha256', '0' * 64),
            ('repository', 'bettergroupinc/other'),
            ('pr_url', f'https://github.com/{REPOSITORY}/pull/2'),
            ('pr_url', 'https://github.com/bettergroupinc/other/pull/1'),
            ('base', '1' * 40),
            ('head', '2' * 40),
        ):
            with self.subTest(field=field, value=value):
                self.assert_refused(self.run_lookup([self.record], **{field: value}))
        other = {**self.record, 'repository': 'bettergroupinc/other'}
        self.assert_refused(self.run_lookup([other]))

    def test_refuses_missing_or_duplicate_id(self):
        other_id = {**self.record, 'row_id': f'{ROW_ID}-other'}
        other_file = {**self.record, 'row_file': 'tests/mutation/other.toml'}
        for case, records in (
            ('missing', [other_id]),
            ('duplicate', [self.record, self.record]),
            ('competing', [self.record, other_file]),
        ):
            with self.subTest(case=case):
                self.assert_refused(self.run_lookup(records))

    def test_refuses_malformed_receipt(self):
        self.assert_refused(self.run_lookup(self.record))
        for field, value in (
            ('pr', True), ('pr', 1.0), ('pr', '1'),
            ('row_file', 'tests/mutation/../fixture-proof.toml'),
            ('subject', 'backend//api/fixture_subject.py'),
        ):
            with self.subTest(field=field, value=value):
                self.assert_refused(self.run_lookup([{**self.record, field: value}]))
        self.assert_refused(self.run_lookup(
            [{**self.record, 'pr': 0}], pr_url=f'https://github.com/{REPOSITORY}/pull/0',
        ))

    def test_refuses_conflicting_tree_or_blob_identity(self):
        for side, field in (('base', 'tree'), ('head', 'tree'), ('base', 'blob'), ('head', 'blob')):
            with self.subTest(side=side, field=field):
                other = {**self.record, 'row_id': f'{ROW_ID}-other',
                         side: {**self.record[side], field: '1' * 40}}
                self.assert_refused(self.run_lookup([self.record, other]))

    def test_refuses_different_blobs_at_the_same_tree_and_path(self):
        base = {**self.record['base'], 'tree': self.record['head']['tree']}
        self.assert_refused(self.run_lookup([{**self.record, 'base': base}]))

    def test_refuses_different_counts_for_identical_row_bytes(self):
        base = {**self.record['base'], 'blob': self.record['head']['blob'], 'count': 0}
        self.assert_refused(self.run_lookup([{**self.record, 'base': base}]))

    def test_refuses_a_receipt_beneath_a_symlink(self):
        root = self.receipt.parent
        directory = root / 'real'
        directory.mkdir()
        alias = root / 'alias'
        alias.symlink_to(directory, target_is_directory=True)
        self.receipt = alias / self.receipt.name
        self.assert_refused(self.run_lookup([self.record]))

    def test_requires_one_total_and_one_active_head_declaration(self):
        for field, value in (('count', 0), ('count', 2), ('count', True),
                             ('active_count', 0), ('active_count', 2), ('active_count', True)):
            with self.subTest(field=field, value=value):
                head = {**self.record['head'], field: value}
                self.assert_refused(self.run_lookup([{**self.record, 'head': head}]))


if __name__ == '__main__':
    unittest.main()
