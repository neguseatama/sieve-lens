"""
Sieve Lens image OCR extension.

Adds image support via Pillow + pytesseract.

Extracts:
  - Image metadata (EXIF, PNG text chunks, XMP) -> H5
  - OCR-extracted visible text -> body (H2/H3/H6/H7)

Notes on the observation model for images:
  - OCR can only read text that is visually rendered in the image.
    Zero-width and bidi control characters have no visual form and
    therefore cannot be recovered by OCR.
  - The primary "invisible" attack surface for images is metadata:
    EXIF UserComment, ImageDescription, PNG tEXt/iTXt/zTXt chunks,
    and XMP packets. Those are surfaced as H5 segments.

Requires:
  - Pillow >= 10.0            (pip install Pillow)
  - pytesseract >= 0.3.10     (pip install pytesseract)
  - tesseract binary          (system package: e.g. apt install tesseract-ocr)

Usage:
    from sieve_lens import SieveLensEngine
    from sieve_lens_ext.ocr import install

    engine = SieveLensEngine()
    install(engine)               # attaches image support
    obs = engine.observe("resume_screenshot.png")
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False

from sieve_lens import Segment


class ImageOcrExtractor:
    """Extract segments from an image file via metadata + OCR."""

    EXTENSIONS = [
        ".png", ".jpg", ".jpeg", ".gif", ".bmp",
        ".tif", ".tiff", ".webp",
    ]

    _EXIF_TEXT_TAGS = {
        270: "ImageDescription",
        271: "Make",
        272: "Model",
        285: "PageName",
        305: "Software",
        315: "Artist",
        33432: "Copyright",
        37510: "UserComment",
        40091: "XPTitle",
        40092: "XPComment",
        40093: "XPAuthor",
        40094: "XPKeywords",
        40095: "XPSubject",
    }

    _PNG_TEXT_KEYS = (
        "Description", "Author", "Comment",
        "Copyright", "Title", "Software", "Disclaimer", "Warning",
    )

    _OOB_MIN_LENGTH = 10
    _OCR_LANG = "eng"

    def extract(self, path: Path) -> List[Segment]:
        if not PIL_AVAILABLE:
            raise ImportError(
                "sieve_lens_ext.ocr requires Pillow. "
                "Install with: pip install sieve-lens[ocr]"
            )

        segments: List[Segment] = []
        with Image.open(path) as img:
            segments.extend(self._extract_metadata(img))
            segments.extend(self._extract_ocr_text(img))

        return segments

    def _extract_metadata(self, img) -> List[Segment]:
        segments: List[Segment] = []
        segments.extend(self._extract_exif(img))
        segments.extend(self._extract_png_text(img))
        segments.extend(self._extract_xmp(img))
        return segments

    def _extract_exif(self, img) -> List[Segment]:
        segments: List[Segment] = []
        try:
            exif = img.getexif()
        except Exception:
            return segments
        if not exif:
            return segments

        for tag_id, raw in exif.items():
            name = self._EXIF_TEXT_TAGS.get(tag_id)
            if not name:
                continue
            text = self._decode_exif_value(tag_id, raw)
            if text and len(text.strip()) >= self._OOB_MIN_LENGTH:
                segments.append(Segment(
                    text=text.strip(),
                    visible=False,
                    kind="metadata",
                    location=f"EXIF / {name} (tag {tag_id})",
                ))
        return segments

    @staticmethod
    def _decode_exif_value(tag_id: int, raw) -> Optional[str]:
        if isinstance(raw, bytes):
            try:
                if 40091 <= tag_id <= 40095:
                    return raw.decode("utf-16-le", errors="ignore").rstrip("\x00")
                if tag_id == 37510 and len(raw) > 8:
                    header = raw[:8]
                    body = raw[8:]
                    if header.startswith(b"ASCII\x00\x00\x00"):
                        return body.decode("ascii", errors="ignore")
                    if header.startswith(b"UNICODE\x00"):
                        return body.decode("utf-16-be", errors="ignore")
                    if header.startswith(b"JIS\x00\x00\x00\x00\x00"):
                        return body.decode("shift_jis", errors="ignore")
                    return body.decode("latin-1", errors="ignore")
                return raw.decode("latin-1", errors="ignore")
            except Exception:
                return None
        if isinstance(raw, str):
            return raw
        return None

    def _extract_png_text(self, img) -> List[Segment]:
        segments: List[Segment] = []
        info = getattr(img, "info", None) or {}
        for key in self._PNG_TEXT_KEYS:
            val = info.get(key)
            if isinstance(val, (bytes, str)):
                text = val.decode("latin-1", errors="ignore") if isinstance(val, bytes) else val
                if len(text.strip()) >= self._OOB_MIN_LENGTH:
                    segments.append(Segment(
                        text=text.strip(),
                        visible=False,
                        kind="metadata",
                        location=f"PNG tEXt / {key}",
                    ))
        return segments

    def _extract_xmp(self, img) -> List[Segment]:
        segments: List[Segment] = []
        info = getattr(img, "info", None) or {}
        xmp = info.get("xmp") or info.get("XML:com.adobe.xmp")
        if isinstance(xmp, bytes):
            try:
                xmp = xmp.decode("utf-8", errors="ignore")
            except Exception:
                return segments
        if isinstance(xmp, str) and len(xmp.strip()) >= self._OOB_MIN_LENGTH:
            segments.append(Segment(
                text=xmp.strip(),
                visible=False,
                kind="metadata",
                location="XMP packet",
            ))
        return segments

    def _extract_ocr_text(self, img) -> List[Segment]:
        if not PYTESSERACT_AVAILABLE:
            return []
        try:
            text = pytesseract.image_to_string(img, lang=self._OCR_LANG) or ""
        except Exception:
            return []
        if not text.strip():
            return []
        return [Segment(
            text=text,
            visible=True,
            kind="body",
            location=f"OCR (lang={self._OCR_LANG})",
        )]


def install(engine) -> None:
    """Attach image OCR support to a SieveLensEngine instance."""
    engine.register_extractor(ImageOcrExtractor.EXTENSIONS, ImageOcrExtractor())