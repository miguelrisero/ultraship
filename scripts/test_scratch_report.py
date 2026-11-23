"""Test the scratch report reader with isolated filesystem fixtures."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

READER = (
    Path(__file__).resolve().parents[1]
    / "plugins/ship/skills/ship/scripts/read-scratch-report.py"
)
MIB = 1024 * 1024


class ScratchReportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.scratch = self.root / ".scratch"
        self.scratch.mkdir()

    def run_reader(self, *args):
        return subprocess.run(
            [sys.executable, "-I", str(READER), *args],
            cwd=self.root,
            env={**os.environ, "PWD": str(self.root / "unused")},
            capture_output=True,
            encoding="utf-8",
            timeout=5,
        )

    def assert_refused(self, *args, reason):
        result = self.run_reader(*args)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, f"Refused: {reason}\n")

    def test_reads_nested_file_from_physical_cwd(self):
        (self.scratch / "nested").mkdir()
        (self.scratch / "nested" / "report").write_bytes(b"Report text\n")
        result = self.run_reader("nested/report")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "Report text\n")
        self.assertEqual(result.stderr, "")

    def test_requires_one_relative_path(self):
        for args in ((), ("report", "other")):
            with self.subTest(args=args):
                self.assert_refused(*args, reason="expected one report path")
        for path in (
            "", str(self.scratch / "report"), "../report", "./report", "nested/../report"
        ):
            with self.subTest(path=path):
                self.assert_refused(path, reason="expected a relative report path")

    def test_refuses_symlinks_at_each_level(self):
        target = self.root / "target"
        target.mkdir()
        (target / "report").write_bytes(b"Synthetic target\n")
        (self.scratch / "file-link").symlink_to(target / "report")
        (self.scratch / "dir-link").symlink_to(target, target_is_directory=True)
        reason = "cannot open or read the scratch report"
        self.assert_refused("file-link", reason=reason)
        self.assert_refused("dir-link/report", reason=reason)
        self.scratch.rename(self.root / "old-scratch")
        self.scratch.symlink_to(target, target_is_directory=True)
        self.assert_refused("report", reason=reason)

    def test_refuses_hard_links(self):
        target = self.root / "target"
        target.write_bytes(b"Synthetic target\n")
        os.link(target, self.scratch / "report")
        self.assert_refused("report", reason="expected exactly one file link")

    def test_refuses_nonregular_files(self):
        (self.scratch / "directory").mkdir()
        os.mkfifo(self.scratch / "pipe")
        for name in ("directory", "pipe"):
            with self.subTest(name=name):
                self.assert_refused(name, reason="expected a regular file")

    def test_refuses_one_byte_over_the_limit(self):
        report = self.scratch / "report"
        report.write_bytes(b"a" * MIB)
        result = self.run_reader("report")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "a" * 5000)
        with report.open("ab") as handle:
            handle.write(b"a")
        self.assert_refused("report", reason="report exceeds 1 MiB")

    def test_drops_data_image_lines_before_limiting_characters(self):
        text = "é" * 5000
        image = "A" * 6000
        prefix = "First line\n\n"
        report = (
            f"{prefix}![Example](data:image/png;base64,{image})\n"
            f"SVG <DATA:IMAGE/svg+xml,%3Csvg%3E> caption\n{text}end"
        )
        (self.scratch / "report").write_text(report, encoding="utf-8")
        result = self.run_reader("report")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, prefix + text[:5000 - len(prefix)])
        self.assertEqual(result.stderr, "")

    def test_escapes_terminal_controls(self):
        report = "Report\ttext\r\n\x1b[2J\x9b2J" + "a" * 5000
        (self.scratch / "report").write_text(report, encoding="utf-8")
        result = self.run_reader("report")
        self.assertEqual(result.returncode, 0)
        expected_prefix = "Report\ttext\\x0d\n\\x1b[2J\\x9b2J"
        self.assertEqual(result.stdout, expected_prefix + "a" * (5000 - len(expected_prefix)))
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
