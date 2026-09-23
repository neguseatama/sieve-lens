"""Tests for Sieve Lens PDF embedded image analysis extension.

Note on pypdf's SMask behavior:
    pypdf multiplies RGB by alpha during SMask decoding, so a pixel
    of (255, 0, 0, alpha=0) becomes (0, 0, 0, 0). To test the
    transparent layer detection reliably, we verify the extractor's
    internal logic with a mock ImageFile that returns a real RGBA
    PIL image directly.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from sieve_lens import SieveLensEngine

try:
    from pypdf import PdfWriter
    from pypdf.generic import (
        DecodedStreamObject, DictionaryObject, FloatObject, NameObject,
    )
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

try:
    from PIL import Image  # noqa: F401
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from sieve_lens_ext.pdf_images import PdfImagesExtractor, install


def _make_pdf_with_rgb_image(
    path: Path,
    width: int = 60,
    height: int = 60,
    rgb: tuple = (255, 255, 255),
    alpha: int = 255,
) -> None:
    """Build a PDF with a raw RGB image and optional SMask."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)

    r, g, b = rgb
    rgb_data = bytes([r, g, b]) * (width * height)

    img_stream = DecodedStreamObject()
    img_stream.set_data(rgb_data)
    img_stream[NameObject("/Type")] = NameObject("/XObject")
    img_stream[NameObject("/Subtype")] = NameObject("/Image")
    img_stream[NameObject("/Width")] = FloatObject(width)
    img_stream[NameObject("/Height")] = FloatObject(height)
    img_stream[NameObject("/ColorSpace")] = NameObject("/DeviceRGB")
    img_stream[NameObject("/BitsPerComponent")] = FloatObject(8)

    if alpha < 255:
        smask_stream = DecodedStreamObject()
        smask_stream.set_data(bytes([alpha]) * (width * height))
        smask_stream[NameObject("/Type")] = NameObject("/XObject")
        smask_stream[NameObject("/Subtype")] = NameObject("/Image")
        smask_stream[NameObject("/Width")] = FloatObject(width)
        smask_stream[NameObject("/Height")] = FloatObject(height)
        smask_stream[NameObject("/ColorSpace")] = NameObject("/DeviceGray")
        smask_stream[NameObject("/BitsPerComponent")] = FloatObject(8)
        smask_ref = writer._add_object(smask_stream)
        img_stream[NameObject("/SMask")] = smask_ref

    img_ref = writer._add_object(img_stream)

    xobjects = DictionaryObject()
    xobjects[NameObject("/Im1")] = img_ref
    resources = DictionaryObject()
    resources[NameObject("/XObject")] = xobjects
    page[NameObject("/Resources")] = resources

    content_stream = DecodedStreamObject()
    content_stream.set_data(
        f"q {width} 0 0 {height} 100 500 cm /Im1 Do Q".encode()
    )
    page[NameObject("/Contents")] = writer._add_object(content_stream)

    with open(path, "wb") as f:
        writer.write(f)


class _MockImageFile:
    """A minimal stand-in for pypdf's ImageFile.

    Exposes .image (a PIL.Image) and raises on .data, matching one of
    the two cases that PdfImagesExtractor._load_image handles.
    """

    def __init__(self, img):
        self._img = img

    @property
    def image(self):
        return self._img

    @property
    def data(self):
        raise AttributeError("mock has no raw data")


@unittest.skipUnless(
    PYPDF_AVAILABLE and PIL_AVAILABLE,
    "pypdf or Pillow not installed",
)
class TestPdfImagesExtension(unittest.TestCase):

    def setUp(self):
        self.engine = SieveLensEngine()
        install(self.engine)
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmpdir.cleanup()

    def _path(self, name):
        return Path(self._tmpdir.name) / name

    def test_pdf_is_registered(self):
        self.assertIn(".pdf", self.engine._extractors)

    def test_clean_pdf_no_images(self):
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        p = self._path("clean.pdf")
        with open(p, "wb") as f:
            writer.write(f)
        obs = self.engine.observe(p)
        self.assertEqual(obs.h_states["H1"], 1)
        self.assertEqual(obs.h_states["H4"], 0)

    def test_pdf_with_clean_image(self):
        p = self._path("clean_image.pdf")
        _make_pdf_with_rgb_image(
            p, width=60, height=60, rgb=(200, 200, 200), alpha=255,
        )
        obs = self.engine.observe(p)
        self.assertEqual(obs.h_states["H1"], 1)
        self.assertEqual(obs.h_states["H4"], 0)

    def test_deterministic(self):
        p = self._path("det.pdf")
        _make_pdf_with_rgb_image(
            p, width=60, height=60, rgb=(200, 200, 200), alpha=255,
        )
        results = [self.engine.observe(p) for _ in range(3)]
        for r in results[1:]:
            self.assertEqual(r.mask, results[0].mask)
            self.assertEqual(r.h_states, results[0].h_states)

    def test_small_image_skipped(self):
        p = self._path("tiny.pdf")
        _make_pdf_with_rgb_image(
            p, width=30, height=30, rgb=(255, 0, 0), alpha=0,
        )
        obs = self.engine.observe(p)
        self.assertEqual(obs.h_states["H4"], 0)


@unittest.skipUnless(PIL_AVAILABLE, "Pillow not installed")
class TestPdfImagesInternalLogic(unittest.TestCase):
    """Unit tests for PdfImagesExtractor internal logic, bypassing pypdf."""

    def test_transparent_layer_detected(self):
        from PIL import Image as _Image

        img = _Image.new("RGBA", (60, 60), (255, 0, 0, 0))
        mock = _MockImageFile(img)

        extractor = PdfImagesExtractor()
        segs = extractor._process_image(mock, 1, 1, set())
        self.assertIsNotNone(segs)
        self.assertTrue(
            any("transparent layer" in s.text for s in segs),
            f"segments: {[s.text for s in segs]}",
        )
        self.assertTrue(any(s.kind == "css_hidden" for s in segs))

    def test_low_contrast_detected(self):
        from PIL import Image as _Image

        img = _Image.new("RGB", (200, 200), (255, 255, 255))
        # Paint a large low-contrast rectangle
        for y in range(20, 180):
            for x in range(20, 180):
                img.putpixel((x, y), (240, 240, 240))
        mock = _MockImageFile(img)

        extractor = PdfImagesExtractor()
        segs = extractor._process_image(mock, 1, 1, set())
        self.assertIsNotNone(segs)
        self.assertTrue(
            any("low contrast" in s.text for s in segs),
            f"segments: {[s.text for s in segs]}",
        )

    def test_small_image_skipped_internally(self):
        from PIL import Image as _Image

        img = _Image.new("RGBA", (30, 30), (255, 0, 0, 0))
        mock = _MockImageFile(img)

        extractor = PdfImagesExtractor()
        segs = extractor._process_image(mock, 1, 1, set())
        self.assertIsNone(segs)

    def test_duplicate_image_skipped(self):
        from PIL import Image as _Image

        img = _Image.new("RGBA", (60, 60), (255, 0, 0, 0))
        mock1 = _MockImageFile(img)
        mock2 = _MockImageFile(img)

        extractor = PdfImagesExtractor()
        seen = set()
        segs1 = extractor._process_image(mock1, 1, 1, seen)
        self.assertIsNotNone(segs1)
        # Second call with the same content should be skipped
        segs2 = extractor._process_image(mock2, 1, 2, seen)
        self.assertIsNone(segs2)

    def test_clean_image_no_segments(self):
        from PIL import Image as _Image

        img = _Image.new("RGB", (200, 200), (200, 200, 200))
        mock = _MockImageFile(img)

        extractor = PdfImagesExtractor()
        segs = extractor._process_image(mock, 1, 1, set())
        # No OCR, no metadata, no transparent, no low contrast.
        self.assertTrue(segs is None or len(segs) == 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
