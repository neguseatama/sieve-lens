"""Core __version__ and pyproject version must agree.

A silent drift between the two would publish the wrong version to PyPI
(the publish workflow reads pyproject metadata). This pins them together.
"""

import re
import unittest
from pathlib import Path

import sieve_lens

ROOT = Path(__file__).resolve().parent.parent


class VersionConsistency(unittest.TestCase):
    def test_pyproject_version_matches_core(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r'^version = "([^"]+)"', text, re.M)
        assert m, "pyproject version line not found"
        self.assertEqual(m.group(1), sieve_lens.__version__)


if __name__ == "__main__":
    unittest.main()
