"""Tests for Sieve Lens dashboard extension.

Skipped automatically if Jinja2 or Plotly is not installed.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

try:
    import jinja2
    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False

try:
    import plotly
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

from sieve_lens_ext.dashboard import (
    build_dashboard,
    scan_directory,
    analyze_batch,
    build_summary,
    render_dashboard,
    _DEFAULT_EXTENSIONS,
)


@unittest.skipUnless(
    JINJA2_AVAILABLE and PLOTLY_AVAILABLE,
    "Jinja2 or Plotly not installed",
)
class TestDashboardScanning(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, name, content):
        p = self.base / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def test_empty_directory(self):
        files = scan_directory(self.base)
        self.assertEqual(files, [])

    def test_scan_returns_supported_files(self):
        self._write("a.txt", "hello")
        self._write("b.md", "# title")
        self._write("c.bin", "binary")
        files = scan_directory(self.base)
        names = [f.name for f in files]
        self.assertIn("a.txt", names)
        self.assertIn("b.md", names)
        self.assertNotIn("c.bin", names)

    def test_scan_is_sorted(self):
        self._write("z.txt", "hello")
        self._write("a.txt", "hello")
        self._write("m.txt", "hello")
        files = scan_directory(self.base)
        names = [f.name for f in files]
        self.assertEqual(names, ["a.txt", "m.txt", "z.txt"])

    def test_recursive_scan(self):
        self._write("root.txt", "hello")
        self._write("sub/nested.txt", "hello")
        files = scan_directory(self.base, recursive=True)
        names = [f.name for f in files]
        self.assertIn("root.txt", names)
        self.assertIn("nested.txt", names)

    def test_non_recursive_scan(self):
        self._write("root.txt", "hello")
        self._write("sub/nested.txt", "hello")
        files = scan_directory(self.base, recursive=False)
        names = [f.name for f in files]
        self.assertIn("root.txt", names)
        self.assertNotIn("nested.txt", names)


@unittest.skipUnless(
    JINJA2_AVAILABLE and PLOTLY_AVAILABLE,
    "Jinja2 or Plotly not installed",
)
class TestDashboardAnalysis(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, name, content):
        p = self.base / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def test_analyze_batch_empty(self):
        results = analyze_batch([])
        self.assertEqual(results, [])

    def test_analyze_batch_clean_file(self):
        self._write("clean.txt", "Hello world")
        files = scan_directory(self.base)
        observations = analyze_batch(files, max_workers=1)
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].h_states["H1"], 1)

    def test_build_summary_counts(self):
        self._write("clean.txt", "Hello world")
        self._write("zw.txt", "Hello" + ("\u200b" * 20) + "world")
        files = scan_directory(self.base)
        observations = analyze_batch(files, max_workers=1)
        summary = build_summary(observations)
        self.assertEqual(summary.total_files, 2)
        self.assertEqual(summary.parsed_files, 2)
        self.assertEqual(summary.flagged_files, 1)
        self.assertEqual(summary.clean_files, 1)

    def test_summary_hypothesis_counts(self):
        self._write("zw.txt", "Hello" + ("\u200b" * 20) + "world")
        files = scan_directory(self.base)
        observations = analyze_batch(files, max_workers=1)
        summary = build_summary(observations)
        self.assertGreaterEqual(summary.hypothesis_counts["H2"], 1)
        self.assertGreaterEqual(summary.hypothesis_counts["H7"], 1)

    def test_summary_mask_counts_sorted(self):
        self._write("a.txt", "Hello world")
        self._write("b.txt", "Hello" + ("\u200b" * 20) + "world")
        files = scan_directory(self.base)
        observations = analyze_batch(files, max_workers=1)
        summary = build_summary(observations)
        keys = list(summary.mask_counts.keys())
        self.assertEqual(keys, sorted(keys))

    def test_summary_extension_counts(self):
        self._write("a.txt", "Hello")
        self._write("b.md", "# Title")
        self._write("c.txt", "World")
        files = scan_directory(self.base)
        observations = analyze_batch(files, max_workers=1)
        summary = build_summary(observations)
        self.assertEqual(summary.extension_counts.get(".txt"), 2)
        self.assertEqual(summary.extension_counts.get(".md"), 1)


@unittest.skipUnless(
    JINJA2_AVAILABLE and PLOTLY_AVAILABLE,
    "Jinja2 or Plotly not installed",
)
class TestDashboardRendering(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, name, content):
        p = self.base / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def test_build_dashboard_creates_file(self):
        self._write("a.txt", "Hello world")
        with tempfile.TemporaryDirectory() as out_dir:
            out = Path(out_dir) / "dashboard.html"
            result = build_dashboard(
                input_dir=self.base,
                output_path=out,
                standalone=False,
            )
            self.assertTrue(result.exists())
            self.assertGreater(result.stat().st_size, 0)

    def test_dashboard_contains_summary(self):
        self._write("a.txt", "Hello world")
        self._write("b.txt", "Hello" + ("\u200b" * 20) + "world")
        with tempfile.TemporaryDirectory() as out_dir:
            out = Path(out_dir) / "dashboard.html"
            build_dashboard(input_dir=self.base, output_path=out)
            content = out.read_text(encoding="utf-8")
            self.assertIn("Sieve Lens Dashboard", content)
            self.assertIn("mask-distribution-chart", content)
            self.assertIn("hypothesis-activation-chart", content)

    def test_dashboard_is_deterministic(self):
        self._write("a.txt", "Hello world")
        self._write("b.txt", "Hello" + ("\u200b" * 20) + "world")
        with tempfile.TemporaryDirectory() as out_dir:
            out1 = Path(out_dir) / "d1.html"
            out2 = Path(out_dir) / "d2.html"
            build_dashboard(input_dir=self.base, output_path=out1)
            build_dashboard(input_dir=self.base, output_path=out2)
            c1 = out1.read_text(encoding="utf-8")
            c2 = out2.read_text(encoding="utf-8")
            self.assertEqual(c1, c2)

    def test_dashboard_self_contained_option(self):
        self._write("a.txt", "Hello world")
        with tempfile.TemporaryDirectory() as out_dir:
            out_cdn = Path(out_dir) / "cdn.html"
            out_inline = Path(out_dir) / "inline.html"
            build_dashboard(
                input_dir=self.base, output_path=out_cdn, standalone=False,
            )
            build_dashboard(
                input_dir=self.base, output_path=out_inline, standalone=True,
            )
            cdn_size = out_cdn.stat().st_size
            inline_size = out_inline.stat().st_size
            # Standalone embeds ~3MB of Plotly.js
            self.assertGreater(inline_size, cdn_size)
            self.assertGreater(inline_size, 1_000_000)

    def test_empty_directory_produces_valid_dashboard(self):
        with tempfile.TemporaryDirectory() as out_dir:
            out = Path(out_dir) / "empty.html"
            build_dashboard(input_dir=self.base, output_path=out)
            self.assertTrue(out.exists())
            content = out.read_text(encoding="utf-8")
            self.assertIn("Sieve Lens Dashboard", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)