"""Version claims across the distribution must agree with __version__.

A silent drift between the two would publish the wrong version to PyPI
(the publish workflow reads pyproject metadata). This pins them together.

Extended in v0.19.1 (L-1): the user-facing version claims are pinned too —
the README title lines (en/ja) and the sieve_lens.py module/engine
docstrings. At 0.19.0 these still read v0.17.0 / v0.2.0 while
pyproject/__version__ said 0.19.0; the guard now fails before the next
release can repeat that.
"""

import re
import unittest
from pathlib import Path

import sieve_lens

ROOT = Path(__file__).resolve().parent.parent

_VERSION_RE = r"(\d+\.\d+\.\d+)"


def _readme_title_version(path: Path) -> str:
    """Return the version in the '# Sieve Lens vX.Y.Z' title line."""
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^# Sieve Lens v" + _VERSION_RE + r"\s*$", line)
        if m:
            return m.group(1)
    raise AssertionError(f"'# Sieve Lens vX.Y.Z' title not found in {path.name}")


def _docstring_version(doc) -> str:
    m = re.search(r"Sieve Lens v" + _VERSION_RE, doc or "")
    assert m, "docstring carries no 'Sieve Lens vX.Y.Z' claim"
    return m.group(1)


class VersionConsistency(unittest.TestCase):
    def test_pyproject_version_matches_core(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r'^version = "([^"]+)"', text, re.M)
        assert m, "pyproject version line not found"
        self.assertEqual(m.group(1), sieve_lens.__version__)

    def test_readme_titles_match_version(self):
        for name in ("README.md", "README.ja.md"):
            with self.subTest(readme=name):
                self.assertEqual(
                    _readme_title_version(ROOT / name), sieve_lens.__version__
                )

    def test_module_docstring_matches_version(self):
        self.assertEqual(_docstring_version(sieve_lens.__doc__), sieve_lens.__version__)

    def test_engine_docstring_matches_version(self):
        from sieve_lens import SieveLensEngine

        self.assertEqual(
            _docstring_version(SieveLensEngine.__doc__), sieve_lens.__version__
        )


if __name__ == "__main__":
    unittest.main()
