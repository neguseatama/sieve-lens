"""The public-text watch: the checker and the baseline.

The watch keeps the user-facing files (the two README files, the docs
directory, pyproject.toml, AGENTS.md, the newest CHANGELOG section) at
zero findings, and the Python sources' comment and docstring counts at
their recorded per-file baseline (the counts only ever shrink).
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(_ROOT))
sys.path.append(str(_ROOT / "tools"))

import check_public_text as cpt  # noqa: E402

_BASELINE = json.loads(
    (_ROOT / "tests" / "public_text_baseline.json").read_text(
        encoding="utf-8"))


class TestPublicTextWatch(unittest.TestCase):

    # --- LN3-T14 --------------------------------------------------------

    def test_scan_text_flags_each_kind(self):
        cases = [
            ("design chat", "design chat", False, False),
            ("dev chat", "dev chat", False, False),
            ("design request", "design request", False, False),
            ("red-first", "red-first", False, False),
            ("golden", "golden", False, False),
            ("mold", "mold", False, False),
            ("sandbox", "sandbox", False, False),
            ("chat_ja", "設計チャット", False, False),
            ("request_ja", "依頼書", False, False),
            ("decision_ja", "裁定", False, False),
            ("nickname_ja", "金型", False, False),
            ("absolute_path", "see /home/user/notes", False, False),
            ("section_mark", "see §3.1 of the plan", False, False),
        ]
        for name, line, test_numbers, dates in cases:
            with self.subTest(case=name):
                self.assertEqual(len(cpt.scan_text(line)), 1)

        # the scoped items only fire on their own targets
        self.assertEqual(len(cpt.scan_text("pin LN3-T14",
                                           test_numbers=True)), 1)
        self.assertEqual(cpt.scan_text("pin LN3-T14"), [])
        self.assertEqual(len(cpt.scan_text("fixed on 2026-11-24",
                                           dates=True)), 1)
        self.assertEqual(cpt.scan_text("fixed on 2026-11-24"), [])

    def test_required_targets_are_at_zero(self):
        findings, _noted, mismatches = cpt.scan_repository()
        self.assertEqual(findings, [])
        self.assertEqual(mismatches, [])

    def test_text_mode_checks_one_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "note.txt"
            p.write_text("a clean line\n", encoding="utf-8")
            self.assertEqual(cpt.scan_text(p.read_text(encoding="utf-8")),
                             [])
            p.write_text("mentions the dev chat\n", encoding="utf-8")
            findings = cpt.scan_text(p.read_text(encoding="utf-8"))
            self.assertEqual(len(findings), 1)

    # --- LN3-T15 --------------------------------------------------------

    def test_baseline_matches_the_actual_counts(self):
        from check_public_text import (_iter_python_files,
                                       _python_scan_lines, scan_text)
        counted = {}
        for path in _iter_python_files(_ROOT):
            rel = str(path.relative_to(_ROOT))
            text = path.read_text(encoding="utf-8", errors="replace")
            counted[rel] = sum(len(scan_text(line))
                               for line in _python_scan_lines(text))
        for rel, expected in _BASELINE.items():
            self.assertEqual(counted.get(rel, 0), expected, rel)
        for rel, actual in counted.items():
            if actual:
                self.assertIn(rel, _BASELINE, rel)

    def test_a_stale_or_missing_baseline_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# ok\n", encoding="utf-8")
            (root / "README.ja.md").write_text("# ok\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\n",
                                                 encoding="utf-8")
            (root / "AGENTS.md").write_text("# ok\n", encoding="utf-8")
            (root / "pkg.py").write_text(
                '# a golden mention\nx = 1\n', encoding="utf-8")
            (root / "tests").mkdir()
            baseline = root / "baseline.json"
            cpt_scan = cpt.scan_repository

            baseline.write_text(json.dumps({"pkg.py": 1}),
                                encoding="utf-8")
            cpt._BASELINE = baseline
            try:
                findings, _noted, mismatches = cpt_scan(root)
                self.assertEqual(findings, [])
                self.assertEqual(mismatches, [])

                baseline.write_text(json.dumps({"pkg.py": 2}),
                                    encoding="utf-8")
                _f, _n, mismatches = cpt_scan(root)
                self.assertEqual(mismatches,
                                 [("pkg.py", 2, 1)])

                baseline.write_text(json.dumps({}), encoding="utf-8")
                _f, _n, mismatches = cpt_scan(root)
                self.assertEqual(mismatches, [("pkg.py", 0, 1)])
            finally:
                cpt._BASELINE = _ROOT / "tests" / "public_text_baseline.json"


if __name__ == "__main__":
    unittest.main(verbosity=2)
