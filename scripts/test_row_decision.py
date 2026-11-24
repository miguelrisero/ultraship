"""Test the read-only CoC preflight with synthetic version pins."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'plugins/ship/skills/ship/scripts/row-decision.py'


class RowDecisionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name).resolve() / '.scratch/coc/rows/version-pin.json'
        self.path.parent.mkdir(parents=True)
        self.data = {
            'schema_version': 1,
            'authority': 'coc-standing-grant',
            'pr_url': 'https://github.com/bettergroupinc/fixture/pull/1',
            'lane': 'fixture-lane', 'writer': 'writer--sol',
            'checkout': '/workspace/draft', 'branch': 'fix/fixture-version',
            'base': 'a' * 40, 'head': 'b' * 40, 'head_tree': 'c' * 40,
            'rows_file': 'tests/mutation/example.toml', 'row_id': 'R1',
            'base_row_extent': [4, 12], 'head_row_extent': [4, 12],
            'base_rows_blob': 'd' * 40, 'head_rows_blob': 'd' * 40,
            'subject': 'release.yaml', 'base_subject_blob': '1' * 40, 'head_subject_blob': '2' * 40,
            'test': 'tests/test_release.py::test_version',
            'claim': 'The manifest uses the required version.',
            'old_before': '  version: 1.2.3', 'old_after': '  version: 1.2.4',
            'new_unchanged': '  version: 1.0.0',
            'diagnostic': {
                'run_id': 21, 'job_id': 22, 'attempt': 1, 'head': 'b' * 40,
                'tested_commit': 'e' * 40, 'tested_tree': 'c' * 40,
                'row_id': 'R1', 'observed': 0, 'expected': 1,
            },
            'correction': {
                'prior_path': '/workspace/coc/prior.json', 'prior_sha256': 'f' * 64,
                'refusal': 'I refused because the decision omitted the draft URL.',
                'refusal_source': 'writer session earlier-writer',
                'defect': 'The draft URL was missing.',
            },
        }

    def run_preflight(self, *, content=None, digest=None, mode=0o444, decision_path=None):
        content = json.dumps(self.data).encode() if content is None else content
        decision_path = self.path if decision_path is None else decision_path
        decision_path.unlink(missing_ok=True)
        decision_path.write_bytes(content)
        decision_path.chmod(mode)
        digest = hashlib.sha256(content).hexdigest() if digest is None else digest
        return subprocess.run([sys.executable, '-I', str(SCRIPT), str(decision_path), digest,
                               '--coc-workspace', str(self.path.parents[3])], text=True, capture_output=True)

    def assert_refused(self, result, field):
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(field, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertNotIn(self.data.get('old_before', 'fixture version'), result.stderr)

    def test_corrected_file_validates_with_prior_writer_as_provenance_only(self):
        result = self.run_preflight()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('preflight passed', result.stdout)
        self.assertIn('zero write or retry authority', result.stdout)
        self.assertNotIn('earlier-writer', result.stdout)

    def test_missing_draft_url_or_ci_diagnostic_fails_before_dispatch(self):
        for field in ('pr_url', 'diagnostic'):
            with self.subTest(field=field):
                saved = self.data.pop(field)
                self.assert_refused(self.run_preflight(), field)
                self.data[field] = saved

    def test_stale_or_unrelated_ci_evidence_fails(self):
        for field, invalid in [('head', 'a' * 40), ('tested_tree', 'a' * 40),
                               ('row_id', 'R2'), ('observed', 1), ('expected', True)]:
            with self.subTest(field=field):
                original = self.data['diagnostic'][field]
                self.data['diagnostic'][field] = invalid
                self.assert_refused(self.run_preflight(), f'diagnostic.{field}')
                self.data['diagnostic'][field] = original

    def test_rejects_unbound_or_repeated_decision_content(self):
        self.assert_refused(self.run_preflight(digest='0' * 64), 'SHA-256')
        duplicate = json.dumps(self.data).replace('"schema_version":', '"schema_version": 1, "schema_version":')
        self.assert_refused(self.run_preflight(content=duplicate.encode()), 'duplicate')

    def test_rejects_noncanonical_draft_url_and_unfrozen_file(self):
        self.data['pr_url'] = 'https://github.com/bettergroupinc/../pull/1'
        self.assert_refused(self.run_preflight(), 'pr_url')
        self.data['pr_url'] = 'https://github.com/bettergroupinc/fixture/pull/1'
        result = self.run_preflight(mode=0o644)
        self.assert_refused(result, 'mode 0444')

    def test_rejects_other_workspace_even_with_matching_digest(self):
        other = self.path.parents[3] / 'elsewhere' / '.scratch/coc/rows/other.json'
        other.parent.mkdir(parents=True)
        self.assert_refused(self.run_preflight(decision_path=other), 'CoC workspace')

    def test_rejects_unchanged_base_or_subject(self):
        self.data['base'] = self.data['head']
        self.assert_refused(self.run_preflight(), 'base:')
        self.data['base'] = 'a' * 40
        self.data['base_subject_blob'] = self.data['head_subject_blob']
        self.assert_refused(self.run_preflight(), 'head_subject_blob:')

    def test_rejects_base_commit_as_failed_ci_target(self):
        self.data['diagnostic']['tested_commit'] = self.data['base']
        self.assert_refused(self.run_preflight(), 'diagnostic.tested_commit')

    def test_rejects_conflicting_extents_for_one_row_blob(self):
        self.data['head_row_extent'] = [5, 13]
        self.assert_refused(self.run_preflight(), 'head_row_extent')

    def test_rejects_quoted_pin_outside_the_bare_yaml_contract(self):
        self.data['old_after'] = '  version: "1.2.4"'
        self.assert_refused(self.run_preflight(), 'old_after')

    def test_rejects_edit_outside_version_pin(self):
        self.data['old_after'] = '  enabled: false'
        self.assert_refused(self.run_preflight(), 'old_after')
        self.data['old_after'] = '  version: 1.2.4'
        self.data['new_unchanged'] = '  version: 1.2.4'
        self.assert_refused(self.run_preflight(), 'new_unchanged')


if __name__ == '__main__':
    unittest.main()
