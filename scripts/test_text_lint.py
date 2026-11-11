"""Outgoing prose lint: glued word-number shorthand and restated-hold walls."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ship_text_lint', ROOT / 'plugins/ship/hooks/text_lint.py')
text_lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(text_lint)


class TextLintTests(unittest.TestCase):
    def test_self_test(self):
        text_lint.self_test()


if __name__ == '__main__':
    unittest.main()
