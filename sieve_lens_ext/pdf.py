"""
Sieve Lens PDF extension.

Adds PDF support to SieveLensEngine via pypdf.

Extracts:
  - PDF metadata (title, author, subject, keywords, creator, producer) -> H5
  - Page text -> body (H2/H3/H6/H7)
  - Annotations (comments, notes) -> H5
  - Invisible text (Tr 3 rendering mode) -> H4 (format concealment)

Note on text extraction:
  pypdf's page.extract_text() maps characters through the font's encoding
  (e.g. WinAnsi for Helvetica), which drops characters not present in that
  encoding — including zero-width and bidi control characters. To preserve
  those for H2/H3/H7 detection, we additionally parse the raw content
  stream and include that text as a supplementary body segment.

Usage:
    from sieve_lens import SieveLensEngine
    from sieve_lens_ext.pdf import install

    engine = SieveLensEngine()
    install(engine)               # attaches .pdf support
    obs = engine.observe("resume.pdf")

Requires: pypdf >= 4.0
"""

from __future__ import annotations

from pathlib import Path
from typing import List

try:
    from pypdf import PdfReader
    from pypdf.generic import ContentStream
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

from sieve_lens import Segment, INVISIBLE


class PdfExtractor:
    """Extract segments from a PDF file."""

    _METADATA_KEYS = (
        "/Title", "/Author", "/Subject",
        "/Keywords", "/Creator", "/Producer",
    )

    _OOB_MIN_LENGTH = 10

    def extract(self, path: Path) -> List[Segment]:
        if not PYPDF_AVAILABLE:
            raise ImportError(
                "sieve_lens_ext.pdf requires pypdf. "
                "Install with: pip install sieve-lens[pdf]"
            )
        segments: List[Segment] = []
        with open(path, "rb") as f:
            reader = PdfReader(f)
            segments.extend(self._extract_metadata(reader))
            for page_num, page in enumerate(reader.pages, start=1):
                segments.extend(self._extract_page_text(page, page_num, reader))
                segments.extend(self._extract_annotations(page, page_num))
                segments.extend(self._extract_invisible_text(page, page_num, reader))
        return segments

    def _extract_metadata(self, reader) -> List[Segment]:
        try:
            meta = reader.metadata
        except Exception:
            return []
        if not meta:
            return []
        segments = []
        for key in self._METADATA_KEYS:
            try:
                val = meta.get(key)
            except Exception:
                continue
            if isinstance(val, str) and len(val.strip()) >= self._OOB_MIN_LENGTH:
                segments.append(Segment(
                    text=val,
                    visible=False,
                    kind="metadata",
                    location=f"PDF metadata / {key}",
                ))
        return segments

    def _extract_page_text(self, page, page_num: int, reader) -> List[Segment]:
        """Extract visible page text.

        Uses pypdf's standard extract_text for natural reading order,
        and additionally includes raw content stream text when it
        contains invisible characters that the standard extraction lost.
        """
        segments: List[Segment] = []

        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text.strip():
            segments.append(Segment(
                text=text,
                visible=True,
                kind="body",
                location=f"page {page_num}",
            ))

        raw = self._raw_stream_text(page, reader)
        if raw and self._contains_invisible(raw) and not self._contains_invisible(text):
            segments.append(Segment(
                text=raw,
                visible=True,
                kind="body",
                location=f"page {page_num} (raw stream)",
            ))

        return segments

    def _raw_stream_text(self, page, reader) -> str:
        """Extract all text-showing operands from the raw content stream.

        This bypasses the font encoding and preserves characters that
        pypdf's standard extraction would drop (zero-width, bidi, etc.).
        """
        try:
            contents = page.get("/Contents")
        except Exception:
            return ""
        if contents is None:
            return ""
        try:
            stream = ContentStream(contents, reader)
        except Exception:
            return ""

        parts: List[str] = []
        for operands, operator in stream.operations:
            try:
                if operator in (b"Tj", b"'"):
                    parts.append(self._decode(operands[0]))
                elif operator == b'"':
                    parts.append(self._decode(operands[-1]))
                elif operator == b"TJ":
                    items = operands[0]
                    for item in items:
                        if isinstance(item, (bytes, str)):
                            parts.append(self._decode(item))
            except Exception:
                continue
        return "".join(parts)

    @staticmethod
    def _contains_invisible(text: str) -> bool:
        return any(ord(c) in INVISIBLE for c in text)

    def _extract_annotations(self, page, page_num: int) -> List[Segment]:
        segments = []
        try:
            if "/Annots" not in page:
                return segments
            annots = page["/Annots"]
        except Exception:
            return segments
        try:
            annots = list(annots)
        except TypeError:
            return segments
        for idx, annot in enumerate(annots, start=1):
            try:
                obj = annot.get_object()
            except Exception:
                continue
            try:
                contents = obj.get("/Contents")
            except Exception:
                continue
            if isinstance(contents, str) and len(contents.strip()) >= self._OOB_MIN_LENGTH:
                segments.append(Segment(
                    text=contents,
                    visible=False,
                    kind="comment",
                    location=f"page {page_num} annotation #{idx}",
                ))
        return segments

    def _extract_invisible_text(self, page, page_num: int, reader) -> List[Segment]:
        try:
            contents = page.get("/Contents")
        except Exception:
            return []
        if contents is None:
            return []
        try:
            stream = ContentStream(contents, reader)
        except Exception:
            return []

        tr_mode = 0
        buffer: List[str] = []

        for operands, operator in stream.operations:
            try:
                if operator == b"Tr":
                    tr_mode = int(operands[0])
                elif operator in (b"Tj", b"'"):
                    if tr_mode == 3:
                        buffer.append(self._decode(operands[0]))
                elif operator == b'"':
                    if tr_mode == 3:
                        buffer.append(self._decode(operands[-1]))
                elif operator == b"TJ":
                    items = operands[0]
                    for item in items:
                        if isinstance(item, (bytes, str)):
                            if tr_mode == 3:
                                buffer.append(self._decode(item))
            except Exception:
                continue

        hidden = "".join(buffer).strip()
        if not hidden:
            return []
        return [Segment(
            text=hidden,
            visible=False,
            kind="css_hidden",
            location=f"page {page_num} (invisible text, Tr 3)",
        )]

    @staticmethod
    def _decode(s) -> str:
        """Decode a PDF text string.

        PDF text strings may be encoded as:
          - ASCII/Latin-1 byte strings
          - UTF-16BE with a leading BOM (FE FF)

        pypdf may wrap string operands in ByteStringObject or similar
        classes; we unwrap those first.
        """
        # pypdf's ByteStringObject / TextStringObject expose raw bytes
        if hasattr(s, "original_bytes"):
            try:
                s = s.original_bytes
            except Exception:
                pass
        elif hasattr(s, "original"):
            try:
                s = s.original
            except Exception:
                pass

        if isinstance(s, bytes):
            if s.startswith(b"\xfe\xff"):
                try:
                    return s[2:].decode("utf-16-be")
                except Exception:
                    pass
            try:
                return s.decode("latin-1")
            except Exception:
                return ""
        return str(s)


def install(engine) -> None:
    """Attach PDF support to a SieveLensEngine instance."""
    engine.register_extractor([".pdf"], PdfExtractor())