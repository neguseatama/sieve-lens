"""Tests for Sieve Lens PDF report extension.

Skipped automatically if weasyprint is not installed.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

try:
    import plotly  # noqa: F401
    import kaleido  # noqa: F401
    CHARTS_AVAILABLE = True
except ImportError:
    CHARTS_AVAILABLE = False

from sieve_lens_ext.pdf_report import (
    build_pdf_report,
    render_pdf_report_html,
)
from sieve_lens_ext.dashboard import (
    scan_directory,
    analyze_batch,
    build_summary,
)


@unittest.skipUnless(WEASYPRINT_AVAILABLE, "weasyprint not installed")
class TestPdfReportBuilding(unittest.TestCase):

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

    # -- HTML rendering ------------------------------------------------

    def test_render_html_contains_summary(self):
        self._write("a.txt", "Hello world")
        self._write("b.txt", "Hello" + ("\u200b" * 20) + "world")
        files = scan_directory(self.base)
        observations = analyze_batch(files, max_workers=1)
        summary = build_summary(observations)
        html_text = render_pdf_report_html(
            summary=summary,
            observations=observations,
            input_dir=str(self.base),
            base_dir=self.base,
        )
        self.assertIn("Sieve Lens Observation Report", html_text)
        self.assertIn("Summary", html_text)
        self.assertIn("Hypothesis Activation", html_text)
        self.assertIn("Mask Distribution", html_text)

    def test_render_html_includes_statement(self):
        self._write("a.txt", "Hello")
        files = scan_directory(self.base)
        observations = analyze_batch(files, max_workers=1)
        summary = build_summary(observations)
        html_text = render_pdf_report_html(
            summary=summary,
            observations=observations,
            input_dir=str(self.base),
            base_dir=self.base,
        )
        self.assertIn("not a judgment of intent", html_text)

    # -- PDF generation ------------------------------------------------

    def test_build_pdf_creates_file(self):
        self._write("a.txt", "Hello world")
        with tempfile.TemporaryDirectory() as out_dir:
            out = Path(out_dir) / "report.pdf"
            result = build_pdf_report(
                input_dir=self.base,
                output_path=out,
                include_charts=False,
            )
            self.assertTrue(result.exists())
            self.assertGreater(result.stat().st_size, 1000)
            # Verify it starts with %PDF-
            with open(result, "rb") as f:
                header = f.read(5)
            self.assertEqual(header, b"%PDF-")

    def test_build_pdf_with_clean_and_flagged(self):
        self._write("a.txt", "Hello world")
        self._write("b.txt", "Hello" + ("\u200b" * 20) + "world")
        with tempfile.TemporaryDirectory() as out_dir:
            out = Path(out_dir) / "report.pdf"
            build_pdf_report(
                input_dir=self.base,
                output_path=out,
                include_charts=False,
            )
            self.assertTrue(out.exists())

    def test_build_pdf_empty_directory(self):
        with tempfile.TemporaryDirectory() as out_dir:
            out = Path(out_dir) / "empty.pdf"
            build_pdf_report(
                input_dir=self.base,
                output_path=out,
                include_charts=False,
            )
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 500)


@unittest.skipUnless(
    WEASYPRINT_AVAILABLE and PYPDF_AVAILABLE,
    "weasyprint or pypdf not installed",
)
class TestPdfReportContent(unittest.TestCase):

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

    def _extract_text(self, pdf_path: Path) -> str:
        reader = PdfReader(str(pdf_path))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return "\n".join(pages)

    def test_pdf_contains_title(self):
        self._write("a.txt", "Hello world")
        with tempfile.TemporaryDirectory() as out_dir:
            out = Path(out_dir) / "report.pdf"
            build_pdf_report(
                input_dir=self.base,
                output_path=out,
                include_charts=False,
            )
            text = self._extract_text(out)
            self.assertIn("Sieve Lens Observation Report", text)

    def test_pdf_contains_file_names(self):
        self._write("alpha.txt", "Hello world")
        self._write("beta.txt", "Another file")
        with tempfile.TemporaryDirectory() as out_dir:
            out = Path(out_dir) / "report.pdf"
            build_pdf_report(
                input_dir=self.base,
                output_path=out,
                include_charts=False,
            )
            text = self._extract_text(out)
            self.assertIn("alpha.txt", text)
            self.assertIn("beta.txt", text)

    def test_pdf_contains_statement(self):
        self._write("a.txt", "Hello world")
        with tempfile.TemporaryDirectory() as out_dir:
            out = Path(out_dir) / "report.pdf"
            build_pdf_report(
                input_dir=self.base,
                output_path=out,
                include_charts=False,
            )
            text = self._extract_text(out)
            self.assertIn("not a judgment of intent", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)