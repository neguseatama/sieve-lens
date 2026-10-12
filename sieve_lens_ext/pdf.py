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
from typing import List, Tuple

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

    # Cycle defense: the visited set (per page walk) is the primary
    # guard; this depth cap is insurance against malformed graphs.
    _MAX_FORM_DEPTH = 8


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

        v0.11.0 perf: the content stream is built and walked once,
        collecting both the full operand text and the Tr-3 invisible
        text in a single pass (previously two full scans per page).
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

        raw, hidden = self._scan_stream_once(page, reader)
        if raw and self._contains_invisible(raw) and not self._contains_invisible(text):
            segments.append(Segment(
                text=raw,
                visible=True,
                kind="body",
                location=f"page {page_num} (raw stream)",
            ))
        if hidden:
            segments.append(Segment(
                text=hidden,
                visible=False,
                kind="css_hidden",
                location=f"page {page_num} (invisible text, Tr 3)",
            ))

        for form_name, form_raw, form_hidden in self._scan_form_streams(page, reader):
            if form_hidden:
                segments.append(Segment(
                    text=form_hidden,
                    visible=False,
                    kind="css_hidden",
                    location=f"page {page_num} (form '{form_name}', invisible text, Tr 3)",
                ))
            if (form_raw and self._contains_invisible(form_raw)
                    and not self._contains_invisible(text)):
                segments.append(Segment(
                    text=form_raw,
                    visible=True,
                    kind="body",
                    location=f"page {page_num} (form '{form_name}', raw stream)",
                ))

        return segments

    def _scan_stream_once(self, page, reader) -> Tuple[str, str]:
        """Single pass over the content stream (perf, v0.11.0).

        Returns (raw_text, tr3_text):
          raw_text -- every text-showing operand, bypassing the font
                      encoding (preserves zero-width/bidi characters
                      that pypdf's standard extraction would drop);
          tr3_text -- only operands shown in rendering mode Tr 3
                      (invisible text).
        """
        try:
            contents = page.get("/Contents")
        except Exception:
            return "", ""
        if contents is None:
            return "", ""
        return self._scan_stream_object(contents, reader)

    def _scan_stream_object(self, contents, reader) -> Tuple[str, str]:
        """Scan one content-stream object (page /Contents or Form XObject).

        _scan_stream_once delegates here so Form XObject streams get the
        identical raw-rescue and Tr 3 semantics as page content streams.
        """
        try:
            stream = ContentStream(contents, reader)
        except Exception:
            return "", ""

        raw_parts: List[str] = []
        tr3_parts: List[str] = []
        tr_mode = 0
        for operands, operator in stream.operations:
            try:
                if operator == b"Tr":
                    tr_mode = int(operands[0])
                elif operator in (b"Tj", b"'"):
                    s = self._decode(operands[0])
                    raw_parts.append(s)
                    if tr_mode == 3:
                        tr3_parts.append(s)
                elif operator == b'"':
                    s = self._decode(operands[-1])
                    raw_parts.append(s)
                    if tr_mode == 3:
                        tr3_parts.append(s)
                elif operator == b"TJ":
                    items = operands[0]
                    for item in items:
                        if isinstance(item, (bytes, str)):
                            s = self._decode(item)
                            raw_parts.append(s)
                            if tr_mode == 3:
                                tr3_parts.append(s)
            except Exception:
                continue
        return "".join(raw_parts), "".join(tr3_parts)

    def _scan_form_streams(self, page, reader):
        """Walk Form XObjects declared in the page's /Resources.

        Coverage principle (same as metadata/annotations): every Form
        declared in /Resources is scanned, whether or not it is drawn
        via /Do. Survey basis (pypdf 6.19.0, measured): page.images
        already enumerates form/inline images and extract_text already
        returns form-internal text, but nothing scanned form content
        streams - Tr 3 text inside forms was reported as visible body
        only (H4 false negative) and the raw-stream rescue never
        reached forms.

        Cycle defense: the visited set of indirect object numbers is
        the primary guard (pypdf defends its own extract_text walk,
        but this observer must not rely on that); _MAX_FORM_DEPTH is
        insurance against malformed deep graphs, not the primary
        defense.
        """
        results = []
        try:
            resources = page.get("/Resources")
            resources = resources.get_object() if resources is not None else None
            xobjs = resources.get("/XObject") if resources is not None else None
            xobjs = xobjs.get_object() if xobjs is not None else None
        except Exception:
            return results
        if not xobjs:
            return results
        visited = set()

        def _walk(container, depth):
            try:
                keys = list(container.keys())
            except Exception:
                return
            for key in keys:
                try:
                    obj = container[key].get_object()
                except Exception:
                    continue
                if str(obj.get("/Subtype")) != "/Form":
                    continue
                idnum = getattr(getattr(obj, "indirect_reference", None),
                                "idnum", None)
                if idnum is not None:
                    if idnum in visited:
                        continue
                    visited.add(idnum)
                if depth > self._MAX_FORM_DEPTH:
                    continue
                try:
                    form_raw, form_hidden = self._scan_stream_object(obj, reader)
                except Exception:
                    continue
                results.append((str(key), form_raw, form_hidden))
                try:
                    fres = obj.get("/Resources")
                    fres = fres.get_object() if fres is not None else None
                    child = fres.get("/XObject") if fres is not None else None
                    child = child.get_object() if child is not None else None
                except Exception:
                    continue
                if child:
                    _walk(child, depth + 1)

        _walk(xobjs, 0)
        return results

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