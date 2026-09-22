"""
Sieve Lens v0 - Invisible Prompt Observation Engine

Sieve Lens observes documents for invisible content that may be intended to
influence AI-based evaluation systems. It reports evidence; it does not
judge intent.

Design principles (inherited from the Sieve series):
  - Deterministic : same input yields the same observation, always.
  - Zero deps     : Python standard library only.
  - Explainable   : every observation reports evidence with location.
  - Observation   : reports facts, not judgments.
"""

from __future__ import annotations

import html.parser
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ----------------------------------------------------------------------
# 1. Character tables (deterministic definitions)
# ----------------------------------------------------------------------

ZERO_WIDTH = frozenset({
    0x200B,  # ZERO WIDTH SPACE
    0x200C,  # ZERO WIDTH NON-JOINER
    0x200D,  # ZERO WIDTH JOINER
    0x2060,  # WORD JOINER
    0xFEFF,  # ZERO WIDTH NO-BREAK SPACE
})

BIDI_CONTROL = frozenset({
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
    0x2066, 0x2067, 0x2068, 0x2069,
})

TAG_CHARS = frozenset(range(0xE0000, 0xE0080))
VARIATION_SELECTORS = frozenset(range(0xFE00, 0xFE10))

INVISIBLE = ZERO_WIDTH | BIDI_CONTROL | TAG_CHARS | VARIATION_SELECTORS


# ----------------------------------------------------------------------
# 2. Data classes
# ----------------------------------------------------------------------

@dataclass
class Segment:
    """A chunk of text extracted from a document."""
    text: str
    visible: bool
    kind: str                    # "body" | "css_hidden" | "comment" | "metadata" | "hidden_attr"
    location: Optional[str] = None


@dataclass
class Observation:
    """The result of observing a document."""
    source: str
    mask: str                    # "H1H2H3H4-H5H6H7"
    v0_mask: str                 # "H1H2H3H4"
    h_states: Dict[str, int]
    segments: List[Segment] = field(default_factory=list)
    evidence: Dict[str, List[str]] = field(default_factory=dict)
    diagnostics: Dict[str, object] = field(default_factory=dict)


# ----------------------------------------------------------------------
# 3. Detection helpers
# ----------------------------------------------------------------------

def strip_leading_bom(text: str) -> str:
    return text[1:] if text.startswith("\ufeff") else text


def zero_width_density(text: str) -> float:
    if not text:
        return 0.0
    n = sum(1 for c in text if ord(c) in ZERO_WIDTH)
    return n / len(text)


def _find_runs(text: str, charset: frozenset, min_length: int) -> List[Tuple[int, int]]:
    runs = []
    i, n = 0, len(text)
    while i < n:
        if ord(text[i]) in charset:
            start = i
            while i < n and ord(text[i]) in charset:
                i += 1
            if i - start >= min_length:
                runs.append((start, i - start))
        else:
            i += 1
    return runs


def find_invisible_runs(text: str, min_length: int) -> List[Tuple[int, int]]:
    return _find_runs(text, INVISIBLE, min_length)


def has_bidi_control(text: str) -> bool:
    return any(ord(c) in BIDI_CONTROL for c in text)


def _script_of(ch: str) -> Optional[str]:
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return None
    if name.startswith("LATIN"):
        return "LATIN"
    if name.startswith("CYRILLIC"):
        return "CYRILLIC"
    if name.startswith("GREEK"):
        return "GREEK"
    return None


def detect_script_mixing(text: str) -> List[str]:
    """
    Detect Latin+Cyrillic or Latin+Greek mixing within the same token.
    This is the classic homoglyph attack pattern.
    """
    offenders = []
    for token in text.split():
        scripts = set()
        for ch in token:
            s = _script_of(ch)
            if s:
                scripts.add(s)
        if "LATIN" in scripts and ("CYRILLIC" in scripts or "GREEK" in scripts):
            offenders.append(token)
    return offenders


def decode_invisible_payload(text: str) -> str:
    """Best-effort decoding of zero-width payloads (U+200B=0, U+200C=1)."""
    zw = [c for c in text if ord(c) in ZERO_WIDTH]
    if not zw:
        return ""
    bits = "".join("0" if ord(c) == 0x200B else
                   "1" if ord(c) == 0x200C else
                   "_" for c in zw)
    if "_" not in bits and len(bits) % 8 == 0:
        try:
            chars = [chr(int(bits[i:i + 8], 2)) for i in range(0, len(bits), 8)]
            decoded = "".join(chars)
            if all(32 <= ord(c) < 127 for c in decoded):
                return decoded
        except (ValueError, OverflowError):
            pass
    return f"{len(zw)} zero-width chars"


# ----------------------------------------------------------------------
# 4. Extractors
# ----------------------------------------------------------------------

class _Extractor:
    def extract(self, path: Path) -> List[Segment]:
        raise NotImplementedError


class _PlainTextExtractor(_Extractor):
    def extract(self, path: Path) -> List[Segment]:
        text = path.read_text(encoding="utf-8", errors="replace")
        text = strip_leading_bom(text)
        return [Segment(text=text, visible=True, kind="body")]


_HIDDEN_CSS_PATTERNS = [
    re.compile(r"display\s*:\s*none", re.IGNORECASE),
    re.compile(r"visibility\s*:\s*hidden", re.IGNORECASE),
    re.compile(r"opacity\s*:\s*0(?:\.0+)?\s*(?:;|$)", re.IGNORECASE),
    re.compile(r"font-size\s*:\s*0(?:px|pt|em|rem)?\s*(?:;|$)", re.IGNORECASE),
    re.compile(r"(?:left|top|right|bottom)\s*:\s*-\d{4,}", re.IGNORECASE),
]


def _is_hidden_style(style: str) -> bool:
    return any(p.search(style) for p in _HIDDEN_CSS_PATTERNS)


class _HtmlExtractor(html.parser.HTMLParser, _Extractor):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.segments: List[Segment] = []
        self._stack: List[bool] = []
        self._buffer: List[str] = []
        self._in_style_or_script = False

    def extract(self, path: Path) -> List[Segment]:
        text = path.read_text(encoding="utf-8", errors="replace")
        text = strip_leading_bom(text)
        self._reset()
        self.feed(text)
        self.close()
        self._flush()
        return self.segments

    def _reset(self):
        self.segments = []
        self._stack = []
        self._buffer = []
        self._in_style_or_script = False

    def handle_starttag(self, tag, attrs):
        self._flush()
        if tag in ("style", "script"):
            self._in_style_or_script = True
        attr_dict = {k.lower(): v for k, v in attrs if v is not None}
        style = attr_dict.get("style", "")
        hidden = (
            _is_hidden_style(style)
            or "hidden" in attr_dict
            or attr_dict.get("aria-hidden") == "true"
        )
        self._stack.append(hidden)
        line, _ = self.getpos()
        for attr_name in ("alt", "title", "aria-label"):
            val = attr_dict.get(attr_name)
            if val and len(val.strip()) >= 10:
                self.segments.append(Segment(
                    text=val, visible=False, kind="hidden_attr",
                    location=f"line {line}, <{tag}> @{attr_name}",
                ))

    def handle_endtag(self, tag):
        self._flush()
        if tag in ("style", "script"):
            self._in_style_or_script = False
        if self._stack:
            self._stack.pop()

    def handle_data(self, data):
        if self._in_style_or_script:
            return
        self._buffer.append(data)

    def handle_comment(self, data):
        self._flush()
        stripped = data.strip()
        if len(stripped) >= 10:
            line, _ = self.getpos()
            self.segments.append(Segment(
                text=stripped, visible=False, kind="comment",
                location=f"line {line}",
            ))

    def _flush(self):
        if not self._buffer:
            return
        text = "".join(self._buffer)
        self._buffer = []
        if not text.strip():
            return
        hidden = bool(self._stack and self._stack[-1])
        line, _ = self.getpos()
        self.segments.append(Segment(
            text=text,
            visible=not hidden,
            kind="css_hidden" if hidden else "body",
            location=f"line {line}",
        ))


_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_CP_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
_DC_NS = "http://purl.org/dc/elements/1.1/"


def _w(tag): return f"{{{_W_NS}}}{tag}"
def _cp(tag): return f"{{{_CP_NS}}}{tag}"
def _dc(tag): return f"{{{_DC_NS}}}{tag}"


class _DocxExtractor(_Extractor):
    def extract(self, path: Path) -> List[Segment]:
        segments: List[Segment] = []
        with zipfile.ZipFile(path) as zf:
            segments.extend(self._extract_body(zf))
            segments.extend(self._extract_comments(zf))
            segments.extend(self._extract_core_props(zf))
        return segments

    def _extract_body(self, zf) -> List[Segment]:
        try:
            with zf.open("word/document.xml") as f:
                tree = ET.parse(f)
        except (KeyError, ET.ParseError):
            return []
        segments = []
        para_idx = 0
        for para in tree.getroot().iter(_w("p")):
            texts = [(t.text or "") for t in para.iter(_w("t"))]
            text = "".join(texts)
            para_idx += 1
            if text.strip():
                segments.append(Segment(
                    text=text, visible=True, kind="body",
                    location=f"paragraph {para_idx}",
                ))
        return segments

    def _extract_comments(self, zf) -> List[Segment]:
        try:
            with zf.open("word/comments.xml") as f:
                tree = ET.parse(f)
        except (KeyError, ET.ParseError):
            return []
        segments = []
        for idx, comment in enumerate(tree.getroot().iter(_w("comment")), start=1):
            texts = [(t.text or "") for t in comment.iter(_w("t"))]
            text = "".join(texts).strip()
            if len(text) >= 10:
                segments.append(Segment(
                    text=text, visible=False, kind="comment",
                    location=f"comment #{idx}",
                ))
        return segments

    def _extract_core_props(self, zf) -> List[Segment]:
        try:
            with zf.open("docProps/core.xml") as f:
                tree = ET.parse(f)
        except (KeyError, ET.ParseError):
            return []
        segments = []
        for tag, label in ((_dc("subject"), "dc:subject"),
                           (_dc("description"), "dc:description"),
                           (_cp("keywords"), "cp:keywords")):
            for elem in tree.getroot().iter(tag):
                val = (elem.text or "").strip()
                if len(val) >= 10:
                    segments.append(Segment(
                        text=val, visible=False, kind="metadata",
                        location=f"core.xml / {label}",
                    ))
        return segments


# ----------------------------------------------------------------------
# 5. Engine
# ----------------------------------------------------------------------

class SieveLensEngine:
    """Sieve Lens v0 observation engine."""

    def __init__(
        self,
        zero_width_density_threshold: float = 0.01,
        payload_min_length: int = 16,
        oob_min_length: int = 10,
    ):
        self.zero_width_density_threshold = zero_width_density_threshold
        self.payload_min_length = payload_min_length
        self.oob_min_length = oob_min_length
        self._extractors: Dict[str, _Extractor] = {
            ".txt": _PlainTextExtractor(),
            ".md": _PlainTextExtractor(),
            ".html": _HtmlExtractor(),
            ".htm": _HtmlExtractor(),
            ".docx": _DocxExtractor(),
        }

    def observe(self, path) -> Observation:
        path = Path(path)
        extractor = self._extractors.get(path.suffix.lower())
        if extractor is None:
            return self._null_observation(str(path), f"Unsupported format: {path.suffix}")
        try:
            segments = extractor.extract(path)
        except Exception as e:
            return self._null_observation(str(path), f"Extraction failed: {type(e).__name__}")
        return self._analyze(segments, source=str(path))

    def observe_text(self, text: str) -> Observation:
        text = strip_leading_bom(text)
        segments = [Segment(text=text, visible=True, kind="body")]
        return self._analyze(segments, source="<text>")

    def _analyze(self, segments: List[Segment], source: str) -> Observation:
        body_text = "".join(s.text for s in segments if s.kind in ("body", "css_hidden"))
        oob_segments = [s for s in segments
                        if s.kind in ("comment", "metadata", "hidden_attr")]

        h1 = 1
        zw_density = zero_width_density(body_text)
        h2 = 1 if zw_density >= self.zero_width_density_threshold else 0
        h3 = 1 if has_bidi_control(body_text) else 0
        h4 = 1 if any(s.kind == "css_hidden" for s in segments) else 0
        meaningful_oob = [s for s in oob_segments
                          if len(s.text.strip()) >= self.oob_min_length]
        h5 = 1 if meaningful_oob else 0
        mixed_tokens = detect_script_mixing(body_text)
        h6 = 1 if mixed_tokens else 0
        payload_runs = find_invisible_runs(body_text, self.payload_min_length)
        h7 = 1 if payload_runs else 0

        v0_mask = f"{h1}{h2}{h3}{h4}"
        full_mask = f"{v0_mask}-{h5}{h6}{h7}"

        evidence = self._collect_evidence(
            body_text, segments, meaningful_oob, mixed_tokens, payload_runs
        )

        return Observation(
            source=source,
            mask=full_mask,
            v0_mask=v0_mask,
            h_states={"H1": h1, "H2": h2, "H3": h3, "H4": h4,
                      "H5": h5, "H6": h6, "H7": h7},
            segments=segments,
            evidence=evidence,
            diagnostics={
                "zero_width_density": round(zw_density, 4),
                "zero_width_threshold": self.zero_width_density_threshold,
                "payload_min_length": self.payload_min_length,
            },
        )

    def _collect_evidence(self, body_text, segments, oob, mixed_tokens, payload_runs):
        ev: Dict[str, List[str]] = {"H1": ["parsed successfully"]}

        zw_by_seg = []
        for s in segments:
            if s.kind in ("body", "css_hidden"):
                n = sum(1 for c in s.text if ord(c) in ZERO_WIDTH)
                if n > 0:
                    loc = f" ({s.location})" if s.location else ""
                    zw_by_seg.append(f"{n} zero-width chars{loc}")
        ev["H2"] = zw_by_seg or ["none"]

        ev["H3"] = (
            ["bidi control characters present"]
            if any(ord(c) in BIDI_CONTROL for c in body_text)
            else ["none"]
        )

        css_hidden = [s for s in segments if s.kind == "css_hidden"]
        ev["H4"] = [
            f"{s.location or 'unknown'}: {s.text.strip()[:80]}"
            for s in css_hidden
        ] or ["none"]

        ev["H5"] = [
            f"[{s.kind}] {s.location or ''}: {s.text.strip()[:120]}"
            for s in oob
        ] or ["none"]

        ev["H6"] = [f"token: {t!r}" for t in mixed_tokens] or ["none"]

        h7_lines = []
        for start, length in payload_runs:
            raw = body_text[start:start + length]
            decoded = decode_invisible_payload(raw)
            h7_lines.append(
                f"{length} contiguous invisible chars at offset {start} -> {decoded}"
            )
        ev["H7"] = h7_lines or ["none"]

        return ev

    def _null_observation(self, source: str, reason: str) -> Observation:
        return Observation(
            source=source,
            mask="0000-000",
            v0_mask="0000",
            h_states={"H1": 0, "H2": 0, "H3": 0, "H4": 0,
                      "H5": 0, "H6": 0, "H7": 0},
            segments=[],
            evidence={"H1": [reason]},
            diagnostics={},
        )


# ----------------------------------------------------------------------
# 6. Report formatter
# ----------------------------------------------------------------------

_LABELS = {
    "H1": "Parseability",
    "H2": "Zero-Width Density",
    "H3": "Bidi Controls",
    "H4": "Format Concealment",
    "H5": "Out-of-Band Channel",
    "H6": "Script Mixing",
    "H7": "Contiguous Payload",
}


def format_report(obs: Observation) -> str:
    lines = []
    lines.append("=" * 66)
    lines.append("  SIEVE-LENS OBSERVATION REPORT")
    lines.append(f"  Source : {obs.source}")
    lines.append(f"  Mask   : {obs.mask}   (H1H2H3H4-H5H6H7)")
    lines.append("=" * 66)
    lines.append("")
    for key in ("H1", "H2", "H3", "H4", "H5", "H6", "H7"):
        mark = "DETECTED" if obs.h_states[key] else "not detected"
        lines.append(f"[{key}] {_LABELS[key]:<22} {mark}")
    lines.append("")
    lines.append("-" * 66)
    lines.append("  EVIDENCE")
    lines.append("-" * 66)
    for key in ("H1", "H2", "H3", "H4", "H5", "H6", "H7"):
        lines.append(f"[{key}] {_LABELS[key]}")
        for line in obs.evidence.get(key, []):
            lines.append(f"  - {line}")
        lines.append("")
    lines.append("-" * 66)
    lines.append("  NOTE")
    lines.append("  This is an observation report, not a judgment of intent.")
    lines.append("  Human review is required to determine whether the detected")
    lines.append("  invisible content is legitimate or abusive.")
    lines.append("=" * 66)
    return "\n".join(lines)


__all__ = [
    "SieveLensEngine",
    "Observation",
    "Segment",
    "format_report",
    "zero_width_density",
    "has_bidi_control",
    "detect_script_mixing",
    "find_invisible_runs",
    "decode_invisible_payload",
]