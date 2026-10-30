"""Ledger directory overrides preserve branch filenames and reject relative paths."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ledger', ROOT / 'plugins/ship/skills/ship/scripts/ledger.py')
ledger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger)


class LedgerDirTests(unittest.TestCase):
    def test_directory_override_preserves_branch_filename(self):
        override = ROOT.parent / '.scratch/ship-ledger-dir-test'
        git_results = {
            ('rev-parse', '--git-common-dir'): '.git',
            ('rev-parse', '--abbrev-ref', 'HEAD'): 'feat/nested/x',
        }
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
                ledger, 'git', side_effect=lambda cwd, *args: git_results[args]):
            self.assertEqual(ledger.ledger_path(ROOT), ROOT / '.git/ship/ledger/feat__nested__x.tsv')
            with mock.patch.dict(os.environ, {'SHIP_LEDGER_DIR': str(override)}):
                self.assertEqual(ledger.ledger_path(ROOT), override / 'feat__nested__x.tsv')
            for value in ('relative/ledger', ''):
                with self.subTest(override=value), mock.patch.dict(os.environ, {'SHIP_LEDGER_DIR': value}):
                    with self.assertRaises(ValueError):
                        ledger.ledger_path(ROOT)
