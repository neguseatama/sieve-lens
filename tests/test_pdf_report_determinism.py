"""Byte-determinism check for the PDF report (verifies P8, issue #16).

Two identical builds must produce byte-identical PDFs. Runs only where
weasyprint is importable (pango present) - i.e. in CI. Locally it skips
gracefully thanks to the OSError-aware guard (#36).
"""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

try:
    from weasyprint import HTML  # noqa: F401
    WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    WEASYPRINT_AVAILABLE = False

from sieve_lens_ext.pdf_report import build_pdf_report


@unittest.skipUnless(
    WEASYPRINT_AVAILABLE, "weasyprint not importable (pango missing?)"
)
class TestPdfReportDeterminism(unittest.TestCase):
    def test_byte_identical(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "in"
            base.mkdir()
            (base / "a.txt").write_text("Hello world", encoding="utf-8")
            o1 = Path(d) / "r1.pdf"
            o2 = Path(d) / "r2.pdf"
            build_pdf_report(
                input_dir=base, output_path=o1, include_charts=False
            )
            build_pdf_report(
                input_dir=base, output_path=o2, include_charts=False
            )
            self.assertEqual(
                hashlib.sha256(o1.read_bytes()).hexdigest(),
                hashlib.sha256(o2.read_bytes()).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
