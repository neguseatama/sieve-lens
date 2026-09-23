"""
Sieve Lens PDF embedded image analysis extension.

Extracts images embedded in PDF pages and applies OCR + layer analysis
to each one. Complements the text-based PDF extractor in
sieve_lens_ext.pdf.

Requires:
  - pypdf >= 4.0
  - Pillow >= 10.0
  - (optional) pytesseract + tesseract binary for OCR

Install with:
    pip install sieve-lens[pdf-images]

Usage:
    from sieve_lens import SieveLensEngine
    from sieve_lens_ext.pdf_images import install

    engine = SieveLensEngine()
    install(engine)
    obs = engine.observe("report.pdf")
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import List, Optional, Set, Tuple

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from sieve_lens import Segment


# Import sibling extractors lazily to preserve zero-dependency core.
def _make_layer_extractor():
    try:
        from sieve_lens_ext.image_layers import ImageLayersExtractor
        return ImageLayersExtractor()
    except Exception:
        return None


def _make_ocr_extractor():
    try:
        from sieve_lens_ext.ocr import ImageOcrExtractor
        return ImageOcrExtractor()
    except Exception:
        return None


class PdfImagesExtractor:
    """Extract embedded images from PDFs and analyze them."""

    # Skip images smaller than this in either dimension.
    _MIN_DIMENSION = 50

    # Cap the number of images processed per PDF (defensive).
    _MAX_IMAGES_PER_PDF = 200

    # Deduplicate images by content hash.
    def __init__(self):
        self._layer_extractor = _make_layer_extractor()
        self._ocr_extractor = _make_ocr_extractor()

    def extract(self, path: Path) -> List[Segment]:
        if not PYPDF_AVAILABLE:
            raise ImportError(
                "sieve_lens_ext.pdf_images requires pypdf. "
                "Install with: pip install sieve-lens[pdf-images]"
            )
        if not PIL_AVAILABLE:
            raise ImportError(
                "sieve_lens_ext.pdf_images requires Pillow. "
                "Install with: pip install sieve-lens[pdf-images]"
            )

        segments: List[Segment] = []
        seen_hashes: Set[str] = set()
        processed = 0

        with open(path, "rb") as f:
            reader = PdfReader(f)
            for page_num, page in enumerate(reader.pages, start=1):
                if processed >= self._MAX_IMAGES_PER_PDF:
                    break
                images = self._get_page_images(page)

                for img_index, image_file in enumerate(images, start=1):
                    if processed >= self._MAX_IMAGES_PER_PDF:
                        break
                    segs = self._process_image(
                        image_file, page_num, img_index, seen_hashes
                    )
                    if segs is None:
                        continue
                    segments.extend(segs)
                    processed += 1

        return segments

    # ------------------------------------------------------------------
    # Per-image processing
    # ------------------------------------------------------------------

    def _load_image(self, image_file):
        """Load a PIL image from a pypdf ImageFile.

        Handles two cases:
          1. The XObject stream contains an embedded file format
             (PNG, JPEG). We detect the magic number and use PIL directly.
          2. The XObject stream contains raw PDF image data. We fall back
             to pypdf's decoder.
        """
        try:
            data = image_file.data
        except Exception:
            data = None

        if data:
            if data.startswith(b"\x89PNG") or data.startswith(b"\xff\xd8"):
                try:
                    img = Image.open(io.BytesIO(data))
                    img.load()
                    return img
                except Exception:
                    pass

        try:
            img = image_file.image
            if img is not None:
                return img
        except Exception:
            pass

        return None

    def _process_image(
        self,
        image_file,
        page_num: int,
        img_index: int,
        seen_hashes: Set[str],
    ) -> Optional[List[Segment]]:
        img = self._load_image(image_file)
        if img is None:
            return None

        try:
            width, height = img.size
        except Exception:
            return None

        if width < self._MIN_DIMENSION or height < self._MIN_DIMENSION:
            return None

        # Hash the pixel content for deduplication.
        try:
            raw = img.tobytes()
        except Exception:
            return None
        digest = hashlib.sha256(raw).hexdigest()
        if digest in seen_hashes:
            return None
        seen_hashes.add(digest)

        label = f"page {page_num}, image #{img_index} ({width}x{height})"
        segments: List[Segment] = []

        # --- Layer analysis (transparent / low-contrast) -> H4 ---
        if self._layer_extractor is not None:
            try:
                layer_segs = self._layer_extractor._detect_transparent_layer(img)
                for s in layer_segs:
                    segments.append(Segment(
                        text=s.text,
                        visible=False,
                        kind="css_hidden",
                        location=f"{label} [{s.location}]",
                    ))
                layer_segs = self._layer_extractor._detect_low_contrast(img)
                for s in layer_segs:
                    segments.append(Segment(
                        text=s.text,
                        visible=False,
                        kind="css_hidden",
                        location=f"{label} [{s.location}]",
                    ))
            except Exception:
                pass

        # --- OCR -> body ---
        if self._ocr_extractor is not None:
            try:
                ocr_segs = self._ocr_extractor._extract_ocr_text(img)
                for s in ocr_segs:
                    segments.append(Segment(
                        text=s.text,
                        visible=True,
                        kind="body",
                        location=f"{label} [OCR]",
                    ))
            except Exception:
                pass

            # Metadata for the embedded image itself (if any)
            try:
                meta_segs = self._ocr_extractor._extract_metadata(img)
                for s in meta_segs:
                    segments.append(Segment(
                        text=s.text,
                        visible=False,
                        kind=s.kind,
                        location=f"{label} [{s.location}]",
                    ))
            except Exception:
                pass

        return segments


def install(engine) -> None:
    """Attach PDF-with-image-analysis support to a SieveLensEngine."""
    from sieve_lens_ext.pdf import PdfExtractor

    class _CombinedExtractor:
        def __init__(self):
            self._text = PdfExtractor()
            self._images = PdfImagesExtractor()

        def extract(self, path: Path) -> List[Segment]:
            segments: List[Segment] = []
            try:
                segments.extend(self._text.extract(path))
            except Exception:
                pass
            try:
                segments.extend(self._images.extract(path))
            except Exception:
                pass
            return segments

    engine.register_extractor([".pdf"], _CombinedExtractor())


__all__ = ["PdfImagesExtractor", "install"]