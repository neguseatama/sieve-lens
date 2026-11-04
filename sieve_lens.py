"""
Sieve Lens v0.19.1 - Invisible Prompt Observation Engine

Sieve Lens observes documents for invisible content that may be intended to
influence AI-based evaluation systems. It reports evidence; it does not
judge intent.

Design principles (inherited from the Sieve series):
  - Deterministic : same input yields the same observation, always.
  - Zero deps     : Python standard library only (core).
  - Explainable   : every observation reports evidence with location.
  - Observation   : reports facts, not judgments.

v0.2.0 adds:
  - Public `Extractor` protocol and `register_extractor()` for optional
    format extensions (e.g. sieve_lens_ext.pdf).
"""

from __future__ import annotations

import html
import html.parser
import os
import re
import stat
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


__version__ = "0.19.1"


# ----------------------------------------------------------------------
# 1. Character tables (deterministic definitions)
# ----------------------------------------------------------------------

ZERO_WIDTH = frozenset({
    0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF,
})

BIDI_CONTROL = frozenset({
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
    0x2066, 0x2067, 0x2068, 0x2069,
})

TAG_CHARS = frozenset(range(0xE0000, 0xE0080))
VARIATION_SELECTORS = frozenset(range(0xFE00, 0xFE10)) | frozenset(range(0xE0100, 0xE01F0))

INVISIBLE = ZERO_WIDTH | BIDI_CONTROL | TAG_CHARS | VARIATION_SELECTORS


OOB_KINDS = frozenset({
    "comment", "metadata", "hidden_attr", "header_footer", "footnote",
})


# ----------------------------------------------------------------------
# 2. Data classes
# ----------------------------------------------------------------------

@dataclass
class Segment:
    text: str
    visible: bool
    kind: str
    location: Optional[str] = None


@dataclass
class Observation:
    source: str
    mask: str
    v0_mask: str
    h_states: Dict[str, int]
    segments: List[Segment] = field(default_factory=list)
    evidence: Dict[str, List[str]] = field(default_factory=dict)
    diagnostics: Dict[str, object] = field(default_factory=dict)


# ----------------------------------------------------------------------
# 2.5 Reading limits and refusals (L1: safe reading)
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class ReadLimits:
    """Immutable bounds for document reading (v0.19.0, L1).

    Every value must be a positive integer. Limits are reading policy,
    not judgment: an input beyond a limit is refused with a closed-set
    code (see ``ExtractionRefused``) instead of being read unbounded.
    Accepted inputs are observed exactly as before.
    """

    max_file_bytes: int = 64 * 1024 * 1024    # whole input file
    max_entries: int = 10_000                 # zip entry count
    max_part_bytes: int = 32 * 1024 * 1024    # one expanded part
    max_total_bytes: int = 128 * 1024 * 1024  # expanded parts, summed
    max_elements: int = 1_000_000             # '<' bytes per XML part

    def __post_init__(self):
        for name in ("max_file_bytes", "max_entries", "max_part_bytes",
                     "max_total_bytes", "max_elements"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) \
                    or value <= 0:
                raise ValueError(
                    f"ReadLimits.{name} must be a positive integer, "
                    f"got {value!r}")


REFUSAL_CODES = frozenset({
    "not_regular_file",     # FIFO, device, directory, ...
    "file_too_large",       # beyond max_file_bytes
    "too_many_entries",     # zip entries beyond max_entries
    "part_too_large",       # one part beyond max_part_bytes
    "total_too_large",      # expanded parts beyond max_total_bytes
    "too_many_elements",    # '<' bytes beyond max_elements
    "doctype_not_allowed",  # <!DOCTYPE or <!ENTITY in an XML part
    "unsupported_encoding", # UTF-16 BOM or a non-UTF-8 XML declaration
    "duplicate_part",       # same (case-insensitive) part name twice
    "encrypted",            # encrypted flag on a part we would read
    "malformed_xml",        # a read part is not well-formed
    "main_part_missing",    # word/document.xml absent
})


class ExtractionRefused(Exception):
    """Raised by the core extractors when reading is refused (L1).

    This is an observation, not a judgment: ``code`` is one of the
    closed set ``REFUSAL_CODES`` and evidence strings carry the code
    only — never part names, document content, or paths.
    """

    def __init__(self, code: str):
        if code not in REFUSAL_CODES:
            raise ValueError(f"unknown refusal code: {code!r}")
        super().__init__(code)
        self.code = code


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

class Extractor:
    """Public protocol for document extractors.

    An extractor is any object with an extract(path) method that returns
    a list of Segment objects.
    """
    def extract(self, path: Path) -> List[Segment]:
        raise NotImplementedError


class _Extractor(Extractor):
    pass


def _resolve_limits(read_limits: Optional[ReadLimits]) -> ReadLimits:
    return read_limits if read_limits is not None else ReadLimits()


def _check_regular_file_size(path: Path, limits: ReadLimits) -> None:
    """Refuse non-regular files and oversized inputs before opening.

    os.stat never opens the path, so a FIFO or device is refused
    without waiting for bytes that may never come.
    """
    st = os.stat(path)
    if not stat.S_ISREG(st.st_mode):
        raise ExtractionRefused("not_regular_file")
    if st.st_size > limits.max_file_bytes:
        raise ExtractionRefused("file_too_large")


def _read_text_bounded(path: Path, limits: ReadLimits) -> str:
    """Read a UTF-8 text document exactly like read_text, bounded.

    Text mode keeps universal-newline translation (\\r\\n -> \\n), so an
    accepted input yields the very same text that
    ``path.read_text(encoding="utf-8", errors="replace")`` returns.
    With ``errors="replace"`` one byte decodes to at most one character,
    so a character count above the limit implies a byte count above it.
    """
    _check_regular_file_size(path, limits)
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read(limits.max_file_bytes + 1)
    if len(text) > limits.max_file_bytes:
        raise ExtractionRefused("file_too_large")
    return text


_XML_DECL_ENCODING_RE = re.compile(
    rb"^<\?xml\s[^>]*?encoding\s*=\s*[\"']([^\"']+)[\"']")


def _check_xml_bytes(data: bytes, limits: ReadLimits) -> None:
    """Static checks on a bounded XML part, before parsing (L1).

    UTF-16 is refused so that the '<' approximation and the DOCTYPE
    scan stay exact for UTF-8, which every OOXML generator in practice
    emits. Entities are refused outright (an OOXML part carries no
    DOCTYPE), so entity expansion never runs at all.
    """
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        raise ExtractionRefused("unsupported_encoding")
    head = data[3:] if data.startswith(b"\xef\xbb\xbf") else data
    m = _XML_DECL_ENCODING_RE.match(head)
    if m:
        declared = m.group(1).decode("ascii", "replace").strip().lower()
        if declared not in ("utf-8", "utf8"):
            raise ExtractionRefused("unsupported_encoding")
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ExtractionRefused("doctype_not_allowed")
    if data.count(b"<") > limits.max_elements:
        raise ExtractionRefused("too_many_elements")


def _parse_bounded_xml(data: bytes):
    """Parse bytes that already passed the bounded checks.

    A part that fails to parse is an observation, not an empty result:
    the refusal keeps H1 at 0 instead of reporting 'parsed
    successfully' over a part Lens cannot actually read.
    """
    try:
        return ET.fromstring(data)
    except (ET.ParseError, ValueError):
        raise ExtractionRefused("malformed_xml")


def _read_zip_part(zf, name: str, limits: ReadLimits,
                   budget: Dict[str, int]) -> Optional[bytes]:
    """Read one zip part under the L1 bounds.

    Returns None when the part is absent (an optional part); raises
    ExtractionRefused when reading is refused. The declared size is
    not trusted: the decompressed read stops at max_part_bytes, and it
    is read in chunks so a refused part never materializes in memory
    past roughly the limit plus one chunk.
    """
    try:
        info = zf.getinfo(name)
    except KeyError:
        return None
    if info.flag_bits & 0x1:
        raise ExtractionRefused("encrypted")
    if info.file_size > limits.max_part_bytes:
        raise ExtractionRefused("part_too_large")
    chunks: List[bytes] = []
    total = 0
    with zf.open(name) as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > limits.max_part_bytes:
                raise ExtractionRefused("part_too_large")
            chunks.append(chunk)
    data = b"".join(chunks)
    budget["total"] += len(data)
    if budget["total"] > limits.max_total_bytes:
        raise ExtractionRefused("total_too_large")
    _check_xml_bytes(data, limits)
    return data


class _PlainTextExtractor(_Extractor):
    def __init__(self, read_limits: Optional[ReadLimits] = None):
        self.read_limits = read_limits

    def extract(self, path: Path) -> List[Segment]:
        text = _read_text_bounded(path, _resolve_limits(self.read_limits))
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


_VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})


class _HtmlExtractor(html.parser.HTMLParser, _Extractor):
    def __init__(self, read_limits: Optional[ReadLimits] = None):
        super().__init__(convert_charrefs=True)
        self.read_limits = read_limits
        self.segments: List[Segment] = []
        self._stack: List[Tuple[str, bool]] = []
        self._buffer: List[str] = []
        self._in_style_or_script = False

    def extract(self, path: Path) -> List[Segment]:
        text = _read_text_bounded(path, _resolve_limits(self.read_limits))
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
        attr_dict = {k.lower(): (v if v is not None else "") for k, v in attrs}
        style = attr_dict.get("style", "")
        own_hidden = (
            _is_hidden_style(style)
            or "hidden" in attr_dict
            or attr_dict.get("aria-hidden") == "true"
        )
        inherited = bool(self._stack and self._stack[-1][1])
        if tag not in _VOID_ELEMENTS:
            self._stack.append((tag, own_hidden or inherited))
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
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break

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
        hidden = bool(self._stack and self._stack[-1][1])
        line, _ = self.getpos()
        self.segments.append(Segment(
            text=text,
            visible=not hidden,
            kind="css_hidden" if hidden else "body",
            location=f"line {line}",
        ))


_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_CP_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
_DC_NS = "http://purl.org/dc/elements/1.1/"


def _w(tag): return f"{{{_W_NS}}}{tag}"
def _a(tag): return f"{{{_A_NS}}}{tag}"
def _cp(tag): return f"{{{_CP_NS}}}{tag}"
def _dc(tag): return f"{{{_DC_NS}}}{tag}"


# ----------------------------------------------------------------------
# 4.5 DOCX concealment (L2) — closed vocabulary and format resolution
# ----------------------------------------------------------------------

# Why a run's text may be invisible to a human reader while remaining
# machine-readable. Closed set; the order is the evidence order.
CONCEALMENT_REASONS = ("vanish", "low_contrast", "tiny_font",
                       "tracked_deletion")

# L2 core thresholds (design answers 2026-11-04). Integer arithmetic
# only; the geometry lane thresholds and their digest stay untouched.
_LOW_CONTRAST_MAX_LUMA_STEP = 20   # D = |dY| // 10000 < 20 (<= 19 fires)
_TINY_FONT_MAX_HALF_POINTS = 2     # w:sz / w:szCs <= 2 (<= 1 pt)
_STYLE_CHAIN_MAX_DEPTH = 100       # basedOn chain length; over -> refuse

# Word's actual highlight palette (design answer 5). ECMA-376 5th ed.
# prose lists CSS-derived values for the dark*/gray names; the values
# below follow Word's rendering values (WdColorIndex / [MS-OE376]),
# fixed by the design answer. Looked up case-insensitively.
_WORD_HIGHLIGHT_COLORS = {
    "black": "000000", "blue": "0000FF", "cyan": "00FFFF",
    "darkblue": "000080", "darkcyan": "008080", "darkgray": "808080",
    "darkgreen": "008000", "darkmagenta": "800080", "darkred": "800000",
    "darkyellow": "808000", "green": "008000", "lightgray": "C0C0C0",
    "magenta": "FF00FF", "red": "FF0000", "white": "FFFFFF",
    "yellow": "FFFF00",
}

# Internal marker for w:t elements whose run is concealed; cleaned
# before every scan and never serialized.
_CONCEAL_MARK = "_l2_concealed"


def _docx_hex6(value):
    """Uppercase 6-digit hex, or None (auto/invalid/unset -> None)."""
    if value is None:
        return None
    v = value.strip()
    if len(v) != 6:
        return None
    try:
        int(v, 16)
    except ValueError:
        return None
    return v.upper()


def _docx_onoff(el):
    """True/False for an on/off element; None when unresolved."""
    if el is None:
        return None
    raw = el.get(_w("val"))
    if raw is None:
        return True
    v = raw.strip().lower()
    if v in ("1", "true", "on"):
        return True
    if v in ("0", "false", "off"):
        return False
    return None


def _docx_luma(hex6):
    """Rec.709 luma on the 0..255000 scale (no gamma, integer only)."""
    r = int(hex6[0:2], 16)
    g = int(hex6[2:4], 16)
    b = int(hex6[4:6], 16)
    return 2126 * r + 7152 * g + 722 * b


def _interpret_shd(shd_el):
    """(hex, state) for one w:shd element; state in resolved/next/stop.

    clear -> the fill colour; solid -> the pattern (w:color) colour;
    nil -> paints nothing and falls through (design answer 6); any
    pattern value only when fill and colour agree, otherwise the run
    makes no low_contrast claim at all (design 3.4)."""
    if shd_el is None:
        return None, "next"
    val = shd_el.get(_w("val"))
    if val is None or val == "clear":
        hexv = _docx_hex6(shd_el.get(_w("fill")))
        return (hexv, "resolved") if hexv else (None, "next")
    if val == "solid":
        hexv = _docx_hex6(shd_el.get(_w("color")))
        return (hexv, "resolved") if hexv else (None, "next")
    if val == "nil":
        return None, "next"
    fill = _docx_hex6(shd_el.get(_w("fill")))
    color = _docx_hex6(shd_el.get(_w("color")))
    if fill and color and fill == color:
        return fill, "resolved"
    return None, "stop"


def _resolve_background(run_shd, para_shd, cell_shd, page_hex):
    """(hex, src) from the shading stages, nearest first (design 3.4
    with answer 5: the highlight stage is handled by the caller)."""
    for el, src in ((run_shd, "run_shading"),
                    (para_shd, "paragraph_shading"),
                    (cell_shd, "cell_shading")):
        hexv, state = _interpret_shd(el)
        if state == "stop":
            return None, None
        if hexv:
            return hexv, src
    if page_hex:
        return page_hex, "page_background"
    return "FFFFFF", "default"


class _DocxStyleResolver:
    """Effective run properties for one document (L2, design 3.3).

    Priority, low to high: docDefaults -> paragraph style chain
    (w:pStyle, w:basedOn) -> character style chain (w:rStyle) -> direct
    run formatting. Toggle properties use the declared override
    simplification (design 3.8-1): the last explicit level wins. The
    chain is memoized per style id; a cycle or a chain longer than
    _STYLE_CHAIN_MAX_DEPTH is refused as malformed_xml (design 3.2).
    """

    _SLOT_OF_INDEX = {"dark1": "dk1", "light1": "lt1", "dark2": "dk2",
                      "light2": "lt2", "hyperlink": "hlink",
                      "followedHyperlink": "folHlink"}
    _ATTR_OF_THEME_COLOR = {
        "background1": "bg1", "light1": "bg1",
        "text1": "t1", "dark1": "t1",
        "background2": "bg2", "light2": "bg2",
        "text2": "t2", "dark2": "t2",
    }
    _MAPPING_DEFAULTS = {"bg1": "light1", "t1": "dark1",
                         "bg2": "light2", "t2": "dark2"}

    def __init__(self, styles_root, theme_root, settings_root):
        self._styles = {}
        if styles_root is not None:
            for st in styles_root.iter(_w("style")):
                sid = st.get(_w("styleId"))
                if not sid:
                    continue
                based = st.find(_w("basedOn"))
                self._styles[sid] = (
                    based.get(_w("val")) if based is not None else None,
                    st.find(_w("rPr")),
                )
        dd_rpr = None
        if styles_root is not None:
            dd = styles_root.find(_w("docDefaults"))
            if dd is not None:
                rprd = dd.find(_w("rPrDefault"))
                if rprd is not None:
                    dd_rpr = rprd.find(_w("rPr"))
        self._doc_defaults = self._direct_props(dd_rpr)
        self._chain_cache: Dict[str, Dict[str, object]] = {}
        self._theme_slots = {}
        if theme_root is not None:
            elements = theme_root.find(_a("themeElements"))
            scheme = (elements.find(_a("clrScheme"))
                      if elements is not None else None)
            if scheme is not None:
                for slot in scheme:
                    name = slot.tag.rsplit("}", 1)[-1]
                    for child in slot:
                        cname = child.tag.rsplit("}", 1)[-1]
                        hexv = None
                        if cname == "srgbClr":
                            hexv = _docx_hex6(child.get("val"))
                        elif cname == "sysClr":
                            hexv = _docx_hex6(child.get("lastClr"))
                        if hexv:
                            self._theme_slots[name] = hexv
                            break
        # w:clrSchemeMapping (settings.xml); omitted entries keep the
        # ECMA defaults (17.18.103 via 17.15.1.20).
        self._mapping = dict(self._MAPPING_DEFAULTS)
        for i in range(1, 7):
            self._mapping[f"accent{i}"] = f"accent{i}"
        self._mapping["hyperlink"] = "hyperlink"
        self._mapping["followedHyperlink"] = "followedHyperlink"
        self._display_bg = False
        if settings_root is not None:
            mapping = settings_root.find(_w("clrSchemeMapping"))
            if mapping is not None:
                for attr in self._mapping:
                    value = mapping.get(_w(attr))
                    if value:
                        self._mapping[attr] = value
            flag = settings_root.find(_w("displayBackgroundShape"))
            if flag is not None and _docx_onoff(flag) is not False:
                self._display_bg = True

    @staticmethod
    def _direct_props(rpr):
        props: Dict[str, object] = {}
        if rpr is not None:
            for child in rpr:
                props[child.tag.rsplit("}", 1)[-1]] = child
        return props

    def _chain_props(self, sid, depth=1, visiting=None):
        if visiting is None:
            visiting = set()
        cached = self._chain_cache.get(sid)
        if cached is not None:
            return cached
        if depth > _STYLE_CHAIN_MAX_DEPTH or sid in visiting:
            raise ExtractionRefused("malformed_xml")
        based, rpr = self._styles.get(sid, (None, None))
        props = {}
        if based and based in self._styles:
            visiting.add(sid)
            props.update(self._chain_props(based, depth + 1, visiting))
            visiting.discard(sid)
        props.update(self._direct_props(rpr))
        self._chain_cache[sid] = props
        return props

    def effective(self, run_rpr, pstyle_id, rstyle_id):
        """Direct-children-only property map for one run."""
        props = dict(self._doc_defaults)
        if pstyle_id and pstyle_id in self._styles:
            props.update(self._chain_props(pstyle_id))
        if rstyle_id and rstyle_id in self._styles:
            props.update(self._chain_props(rstyle_id))
        if run_rpr is not None:
            for child in run_rpr:
                props[child.tag.rsplit("}", 1)[-1]] = child
        return props

    def resolve_fg(self, color_el):
        """(hex|None) for a w:color element (design 3.4, answer 7)."""
        if color_el is None:
            return None
        val = _docx_hex6(color_el.get(_w("val")))
        theme = color_el.get(_w("themeColor"))
        if (theme and theme != "none"
                and not color_el.get(_w("themeTint"))
                and not color_el.get(_w("themeShade"))):
            attr = self._ATTR_OF_THEME_COLOR.get(theme)
            if attr is None and (theme.startswith("accent")
                                 or theme in ("hyperlink",
                                              "followedHyperlink")):
                attr = theme
            if attr:
                index = self._mapping.get(attr)
                slot = self._SLOT_OF_INDEX.get(index, index)
                hexv = self._theme_slots.get(slot)
                if hexv:
                    return hexv
        return val

    def page_background_hex(self, root):
        """Page background colour, only when displayBackgroundShape
        allows it (design 3.4)."""
        if not self._display_bg:
            return None
        bg = root.find(_w("background"))
        if bg is None:
            return None
        return _docx_hex6(bg.get(_w("color")))


class _DocxExtractor(_Extractor):
    def __init__(self, read_limits: Optional[ReadLimits] = None):
        self.read_limits = read_limits

    def extract(self, path: Path) -> List[Segment]:
        limits = _resolve_limits(self.read_limits)
        _check_regular_file_size(path, limits)
        segments: List[Segment] = []
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > limits.max_entries:
                raise ExtractionRefused("too_many_entries")
            seen = set()
            for info in infos:
                lowered = info.filename.lower()
                if lowered in seen:
                    raise ExtractionRefused("duplicate_part")
                seen.add(lowered)
            budget = {"total": 0}
            doc = _read_zip_part(zf, "word/document.xml", limits, budget)
            if doc is None:
                raise ExtractionRefused("main_part_missing")
            # L2 formatting sources ride the same L1 bounds and the
            # same budget; any of them may be absent (a minimal .docx
            # carries none of them), and a malformed one is an
            # observation, not an empty result (design 3.2).
            styles_root = self._read_optional_part(
                zf, "word/styles.xml", limits, budget)
            theme_root = self._read_optional_part(
                zf, "word/theme/theme1.xml", limits, budget)
            settings_root = self._read_optional_part(
                zf, "word/settings.xml", limits, budget)
            resolver = _DocxStyleResolver(
                styles_root, theme_root, settings_root)
            root = _parse_bounded_xml(doc)
            segments.extend(self._body_segments(
                root, resolver, visible_kind="body",
                location_prefix="paragraph"))
            segments.extend(self._headers_footers(zf, limits, budget,
                                                  resolver))
            segments.extend(self._notes(zf, limits, budget))
            segments.extend(self._comments_part(zf, limits, budget))
            segments.extend(self._core_props_part(zf, limits, budget))
        return segments

    @staticmethod
    def _read_optional_part(zf, name, limits, budget):
        data = _read_zip_part(zf, name, limits, budget)
        if data is None:
            return None
        return _parse_bounded_xml(data)

    def _headers_footers(self, zf, limits, budget,
                         resolver) -> List[Segment]:
        segments = []
        for name in sorted(zf.namelist()):
            if name.startswith("word/header") and name.endswith(".xml"):
                label = name.replace("word/", "").replace(".xml", "")
                segments.extend(self._part_segments(
                    zf, name, limits, budget, resolver,
                    visible_kind="header_footer", location_prefix=label))
            elif name.startswith("word/footer") and name.endswith(".xml"):
                label = name.replace("word/", "").replace(".xml", "")
                segments.extend(self._part_segments(
                    zf, name, limits, budget, resolver,
                    visible_kind="header_footer", location_prefix=label))
        return segments

    def _notes(self, zf, limits, budget) -> List[Segment]:
        segments = []
        for part, label, tag in (
            ("word/footnotes.xml", "footnote", "footnote"),
            ("word/endnotes.xml", "endnote", "endnote"),
        ):
            data = _read_zip_part(zf, part, limits, budget)
            if data is None:
                continue
            root = _parse_bounded_xml(data)
            for idx, note in enumerate(root.iter(_w(tag)), start=1):
                if note.get(_w("type")):
                    continue
                texts = [(t.text or "") for t in note.iter(_w("t"))]
                text = "".join(texts).strip()
                if len(text) >= 10:
                    segments.append(Segment(
                        text=text,
                        visible=False,
                        kind="footnote",
                        location=f"{label} #{idx}",
                    ))
        return segments

    def _comments_part(self, zf, limits, budget) -> List[Segment]:
        data = _read_zip_part(zf, "word/comments.xml", limits, budget)
        if data is None:
            return []
        root = _parse_bounded_xml(data)
        segments = []
        for idx, comment in enumerate(root.iter(_w("comment")), start=1):
            texts = [(t.text or "") for t in comment.iter(_w("t"))]
            text = "".join(texts).strip()
            if len(text) >= 10:
                segments.append(Segment(
                    text=text, visible=False, kind="comment",
                    location=f"comment #{idx}",
                ))
        return segments

    def _core_props_part(self, zf, limits, budget) -> List[Segment]:
        data = _read_zip_part(zf, "docProps/core.xml", limits, budget)
        if data is None:
            return []
        root = _parse_bounded_xml(data)
        segments = []
        for tag, label in ((_dc("subject"), "dc:subject"),
                           (_dc("description"), "dc:description"),
                           (_cp("keywords"), "cp:keywords")):
            for elem in root.iter(tag):
                val = (elem.text or "").strip()
                if len(val) >= 10:
                    segments.append(Segment(
                        text=val, visible=False, kind="metadata",
                        location=f"core.xml / {label}",
                    ))
        return segments

    def _part_segments(self, zf, name, limits, budget, resolver,
                       visible_kind, location_prefix) -> List[Segment]:
        data = _read_zip_part(zf, name, limits, budget)
        if data is None:
            return []
        root = _parse_bounded_xml(data)
        return self._body_segments(root, resolver,
                                   visible_kind=visible_kind,
                                   location_prefix=location_prefix)

    def _body_segments(self, root, resolver, visible_kind="body",
                       location_prefix="paragraph") -> List[Segment]:
        """Paragraph segments for one body part, with L2 concealment.

        Visible runs keep the v0.19.0 segment shape (same boundaries
        and the same concatenation, nested content included); concealed
        runs are split out as kind="docx_hidden" segments. Per
        paragraph the visible segment comes first, then the concealed
        groups in run order (design 3.5); a whitespace-only concealed
        run stays in the visible text (design answer 10)."""
        for t in root.iter(_w("t")):
            t.attrib.pop(_CONCEAL_MARK, None)
        page_hex = resolver.page_background_hex(root)
        para_events: Dict[int, list] = {}

        def break_at(idx):
            if idx is not None:
                para_events.setdefault(idx, []).append(None)

        def walk(el, para_idx, pstyle, para_shd, cell_shd,
                 in_del, in_move):
            tag = el.tag
            if tag == _w("p"):
                if para_idx is not None:
                    break_at(para_idx)  # nested paragraph ends adjacency
                para_counter[0] += 1
                idx = para_counter[0]
                ppr = el.find(_w("pPr"))
                pstyle2 = None
                pshd2 = None
                if ppr is not None:
                    ps = ppr.find(_w("pStyle"))
                    pstyle2 = ps.get(_w("val")) if ps is not None else None
                    pshd2 = ppr.find(_w("shd"))
                for child in el:
                    walk(child, idx, pstyle2, pshd2, cell_shd,
                         in_del, in_move)
                return
            if tag == _w("tbl"):
                break_at(para_idx)
                for child in el:
                    walk(child, para_idx, pstyle, para_shd, cell_shd,
                         in_del, in_move)
                return
            if tag == _w("tc"):
                tcpr = el.find(_w("tcPr"))
                cshd = tcpr.find(_w("shd")) if tcpr is not None else None
                for child in el:
                    walk(child, para_idx, pstyle, para_shd, cshd,
                         in_del, in_move)
                return
            if tag in (_w("del"), _w("moveFrom")):
                is_del = tag == _w("del")
                for child in el:
                    walk(child, para_idx, pstyle, para_shd, cell_shd,
                         in_del or is_del, in_move or not is_del)
                return
            if tag == _w("r"):
                if para_idx is None:
                    return
                res = self._run_reasons(el, resolver, pstyle, para_shd,
                                        cell_shd, page_hex,
                                        in_del, in_move)
                events = para_events.setdefault(para_idx, [])
                if res is None or not res[2].strip():
                    # visible run, or whitespace-only concealed run
                    # (stays in the visible text): adjacency ends
                    events.append(None)
                    return
                reasons, detail, text = res
                for t in el.iter(_w("t")):
                    t.set(_CONCEAL_MARK, "1")
                events.append((reasons, detail, text))
                return
            if tag == _w("t"):
                # bare text outside any run still ends adjacency
                break_at(para_idx)
                return
            for child in el:
                walk(child, para_idx, pstyle, para_shd, cell_shd,
                     in_del, in_move)

        para_counter = [0]
        walk(root, None, None, None, None, False, False)

        segments: List[Segment] = []
        for idx, para in enumerate(root.iter(_w("p")), start=1):
            loc = f"{location_prefix} {idx}"
            visible = "".join(
                (t.text or "") for t in para.iter(_w("t"))
                if t.get(_CONCEAL_MARK) is None)
            if visible.strip():
                segments.append(Segment(text=visible, visible=True,
                                        kind=visible_kind, location=loc))
            current = None
            for event in para_events.get(idx, []):
                if event is None:
                    current = None
                    continue
                reasons, detail, text = event
                if current is not None and current[0] == reasons:
                    current[3].text += text
                    continue
                seg = Segment(text=text, visible=False,
                              kind="docx_hidden", location=loc)
                seg._concealment = detail
                current = [reasons, detail, text, seg]
                segments.append(seg)
        return segments

    def _run_reasons(self, r_el, resolver, pstyle, para_shd, cell_shd,
                     page_hex, in_del, in_move):
        """(reasons, detail, text) for one run, or None when the run
        makes no concealment claim (design 3.3/3.4/3.5)."""
        rpr = r_el.find(_w("rPr"))
        rstyle = None
        if rpr is not None:
            rs = rpr.find(_w("rStyle"))
            if rs is not None:
                rstyle = rs.get(_w("val"))
        props = resolver.effective(rpr, pstyle, rstyle)
        flags = set()
        if _docx_onoff(props.get("vanish")) is True:
            flags.add("vanish")
        for key in ("sz", "szCs"):
            el = props.get(key)
            if el is None:
                continue
            try:
                half_points = int(el.get(_w("val")))
            except (TypeError, ValueError):
                continue
            if half_points <= _TINY_FONT_MAX_HALF_POINTS:
                flags.add("tiny_font")
                break
        if in_del or in_move or r_el.find(_w("delText")) is not None:
            flags.add("tracked_deletion")
        fg = resolver.resolve_fg(props.get("color"))
        bg = src = None
        highlight = props.get("highlight")
        if highlight is not None:
            name = (highlight.get(_w("val")) or "").strip().lower()
            hexv = _WORD_HIGHLIGHT_COLORS.get(name) if name else None
            if hexv:
                bg, src = hexv, "highlight"
        if bg is None:
            bg, src = _resolve_background(props.get("shd"), para_shd,
                                          cell_shd, page_hex)
        if fg and bg and src:
            step = abs(_docx_luma(fg) - _docx_luma(bg)) // 10000
            if step < _LOW_CONTRAST_MAX_LUMA_STEP:
                flags.add("low_contrast")
        if not flags:
            return None
        reasons = tuple(r for r in CONCEALMENT_REASONS if r in flags)
        detail = ",".join(reasons)
        if "low_contrast" in flags:
            detail += f" (fg={fg},bg={bg},src={src})"
        text = "".join(
            (c.text or "") for c in r_el
            if c.tag in (_w("t"), _w("delText")))
        return reasons, detail, text


# ----------------------------------------------------------------------
# 5. Engine
# ----------------------------------------------------------------------

class SieveLensEngine:
    """Sieve Lens v0.19.1 observation engine."""

    def __init__(
        self,
        zero_width_density_threshold: float = 0.01,
        payload_min_length: int = 16,
        oob_min_length: int = 10,
        read_limits: Optional[ReadLimits] = None,
    ):
        self.zero_width_density_threshold = zero_width_density_threshold
        self.payload_min_length = payload_min_length
        self.oob_min_length = oob_min_length
        self.read_limits = (
            read_limits if read_limits is not None else ReadLimits())
        self._extractors: Dict[str, _Extractor] = {
            ".txt": _PlainTextExtractor(self.read_limits),
            ".md": _PlainTextExtractor(self.read_limits),
            ".html": _HtmlExtractor(self.read_limits),
            ".htm": _HtmlExtractor(self.read_limits),
            ".docx": _DocxExtractor(self.read_limits),
        }

    def get_extractor(self, extension: str) -> Optional[Extractor]:
        """Return the currently registered extractor for an extension,
        or None. Enables chained installs (e.g. image_layers layered
        on top of ocr)."""
        if not extension.startswith("."):
            extension = "." + extension
        return self._extractors.get(extension.lower())

    def register_extractor(self, extensions, extractor: Extractor) -> None:
        """Register a custom extractor for one or more file extensions.

        Args:
            extensions: File suffixes, e.g. [".pdf", ".PDF"]. Case-insensitive.
                        A leading dot is added automatically if missing.
            extractor: An object with an extract(path) -> List[Segment] method.
        """
        for ext in extensions:
            if not ext.startswith("."):
                ext = "." + ext
            self._extractors[ext.lower()] = extractor

    def observe(self, path) -> Observation:
        path = Path(path)
        extractor = self._extractors.get(path.suffix.lower())
        if extractor is None:
            return self._null_observation(str(path), f"Unsupported format: {path.suffix}")
        try:
            segments = extractor.extract(path)
        except ExtractionRefused as e:
            return self._null_observation(
                str(path), f"Extraction refused: {e.code}")
        except Exception as e:
            return self._null_observation(
                str(path), f"Extraction failed: {type(e).__name__}")
        return self._analyze(segments, source=str(path))

    def observe_text(self, text: str) -> Observation:
        text = strip_leading_bom(text)
        segments = [Segment(text=text, visible=True, kind="body")]
        return self._analyze(segments, source="<text>")

    def _analyze(self, segments: List[Segment], source: str) -> Observation:
        body_text = "".join(
            s.text for s in segments
            if s.kind in ("body", "css_hidden", "docx_hidden"))
        oob_segments = [s for s in segments if s.kind in OOB_KINDS]

        h1 = 1
        zw_density = zero_width_density(body_text)
        h2 = 1 if zw_density >= self.zero_width_density_threshold else 0
        h3 = 1 if has_bidi_control(body_text) else 0
        h4 = 1 if any(s.kind in ("css_hidden", "docx_hidden")
                      for s in segments) else 0
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
                "oob_min_length": self.oob_min_length,
                "version": __version__,
            },
        )

    def _collect_evidence(self, body_text, segments, oob, mixed_tokens, payload_runs):
        ev: Dict[str, List[str]] = {"H1": ["parsed successfully"]}

        zw_by_seg = []
        for s in segments:
            if s.kind in ("body", "css_hidden", "docx_hidden"):
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

        h4_lines = []
        for s in segments:
            if s.kind == "docx_hidden":
                detail = getattr(s, "_concealment", "unknown")
                h4_lines.append(
                    f"{s.location or 'unknown'}: DOCX concealment: "
                    f"{detail}")
            elif s.kind == "css_hidden":
                h4_lines.append(
                    f"{s.location or 'unknown'}: {s.text.strip()[:80]}")
        ev["H4"] = h4_lines or ["none"]

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
            diagnostics={"version": __version__},
        )


# ----------------------------------------------------------------------
# 6. Text report
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
    lines.append(f"  Version : {obs.diagnostics.get('version', 'unknown')}")
    lines.append(f"  Source  : {obs.source}")
    lines.append(f"  Mask    : {obs.mask}   (H1H2H3H4-H5H6H7)")
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


# ----------------------------------------------------------------------
# 7. HTML report
# ----------------------------------------------------------------------

_INVISIBLE_CLASS = {
    "zero_width": "zw",
    "bidi": "bidi",
    "tag": "tag",
    "vs": "vs",
    "control": "ctrl",
}


def _classify_invisible(cp: int) -> Optional[str]:
    if cp in ZERO_WIDTH:
        return "zero_width"
    if cp in BIDI_CONTROL:
        return "bidi"
    if cp in TAG_CHARS:
        return "tag"
    if cp in VARIATION_SELECTORS:
        return "vs"
    if cp < 0x20 and cp not in (0x09, 0x0A, 0x0D):
        return "control"
    return None


def render_markers_html(text: str) -> str:
    """Render text for HTML, replacing invisible characters with markers."""
    out = []
    for ch in text:
        cp = ord(ch)
        kind = _classify_invisible(cp)
        if kind:
            cls = _INVISIBLE_CLASS[kind]
            out.append(f'<span class="inv {cls}">U+{cp:04X}</span>')
        elif ch == "\n":
            out.append("<br>")
        elif ch == "\t":
            out.append("&nbsp;&nbsp;&nbsp;&nbsp;")
        else:
            out.append(html.escape(ch))
    return "".join(out)


def render_markers_text(text: str) -> str:
    """Render text for terminal, replacing invisible characters with markers."""
    out = []
    for ch in text:
        cp = ord(ch)
        kind = _classify_invisible(cp)
        if kind:
            out.append(f"[U+{cp:04X}]")
        else:
            out.append(ch)
    return "".join(out)


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sieve Lens Observation Report</title>
<style>
:root {{
  --fg: #1a1a1a;
  --bg: #fafafa;
  --card: #ffffff;
  --border: #dddddd;
  --muted: #6a737d;
  --warn: #d73a49;
  --warn-bg: #fff5f5;
  --ok: #22863a;
  --accent: #0366d6;
}}
* {{ box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  max-width: 920px;
  margin: 2rem auto;
  padding: 0 1rem;
  color: var(--fg);
  background: var(--bg);
  line-height: 1.5;
}}
h1 {{ font-size: 1.5rem; margin: 0 0 1rem; }}
h2 {{ font-size: 1.1rem; margin: 2rem 0 .5rem; }}
.meta {{
  font-size: .875rem;
  color: var(--muted);
  margin-bottom: 1rem;
}}
.mask {{
  font-family: "SF Mono", Menlo, Consolas, monospace;
  font-size: 1.75rem;
  letter-spacing: .15em;
  padding: .5rem 1rem;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  display: inline-block;
  margin: .5rem 0 1rem;
}}
.mask .detected {{ color: var(--warn); font-weight: 700; }}
.mask .not-detected {{ color: var(--muted); }}
table {{
  width: 100%;
  border-collapse: collapse;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}}
th, td {{
  text-align: left;
  padding: .55rem .8rem;
  border-bottom: 1px solid var(--border);
  font-size: .9rem;
}}
th {{ background: #f0f0f0; font-weight: 600; }}
tr:last-child td {{ border-bottom: none; }}
tr.detected-row {{ background: var(--warn-bg); }}
tr.detected-row td:first-child {{ border-left: 3px solid var(--warn); }}
.status-yes {{ color: var(--warn); font-weight: 600; }}
.status-no {{ color: var(--muted); }}
.section {{
  margin: 1.5rem 0;
  padding: 1rem;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
}}
.section h3 {{
  font-size: 1rem;
  margin: 0 0 .5rem;
  font-family: "SF Mono", Menlo, Consolas, monospace;
}}
.evidence-item {{
  font-family: "SF Mono", Menlo, Consolas, monospace;
  font-size: .85rem;
  padding: .35rem .5rem;
  margin: .25rem 0;
  background: #f6f8fa;
  border-radius: 4px;
  word-break: break-all;
  white-space: pre-wrap;
}}
.inv {{
  display: inline-block;
  padding: 0 .25em;
  margin: 0 .1em;
  border-radius: 3px;
  font-size: .75em;
  font-family: "SF Mono", Menlo, Consolas, monospace;
}}
.inv.zw   {{ background: #ffe5e5; color: #b00020; }}
.inv.bidi {{ background: #e5ecff; color: #0050b3; }}
.inv.tag  {{ background: #e5ffe5; color: #006000; }}
.inv.vs   {{ background: #fff5e5; color: #a05000; }}
.inv.ctrl {{ background: #eee; color: #666; }}
footer {{
  margin-top: 2rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: .85rem;
}}
footer p {{ margin: .5rem 0; }}
</style>
</head>
<body>

<h1>Sieve Lens Observation Report</h1>

<div class="meta">
  <div>Version: <strong>{version}</strong></div>
  <div>Source: <code>{source}</code></div>
</div>

<div class="mask" data-mask="{mask_plain}">{mask_html}<span class="mask-plain" hidden>{mask_plain}</span></div>

<h2>Observation Space</h2>
<table>
<thead>
<tr><th>Bit</th><th>Hypothesis</th><th>Status</th></tr>
</thead>
<tbody>
{hypothesis_rows}
</tbody>
</table>

<h2>Evidence</h2>
{evidence_sections}

<footer>
<p><strong>This is an observation report, not a judgment of intent.</strong></p>
<p>Human review is required to determine whether the detected invisible
content is legitimate or abusive.</p>
<p>Generated deterministically by Sieve Lens v{version}. No timestamps,
randomness, or external resources are included.</p>
</footer>

</body>
</html>
"""


def _render_mask_html(mask: str) -> str:
    parts = []
    for ch in mask:
        if ch == "-":
            parts.append("&ndash;")
        elif ch == "1":
            parts.append('<span class="detected">1</span>')
        elif ch == "0":
            parts.append('<span class="not-detected">0</span>')
        else:
            parts.append(html.escape(ch))
    return "".join(parts)


def format_report_html(obs: Observation) -> str:
    rows = []
    for key in ("H1", "H2", "H3", "H4", "H5", "H6", "H7"):
        detected = obs.h_states[key] == 1
        cls = ' class="detected-row"' if detected else ""
        status = ('<span class="status-yes">DETECTED</span>'
                  if detected else
                  '<span class="status-no">not detected</span>')
        rows.append(
            f'<tr{cls}><td><code>{key}</code></td>'
            f'<td>{html.escape(_LABELS[key])}</td>'
            f'<td>{status}</td></tr>'
        )
    hypothesis_rows = "\n".join(rows)

    sections = []
    for key in ("H1", "H2", "H3", "H4", "H5", "H6", "H7"):
        items = obs.evidence.get(key, [])
        if items:
            body = "\n".join(
                f'<div class="evidence-item">{render_markers_html(item)}</div>'
                for item in items
            )
        else:
            body = '<div class="evidence-item">(no evidence)</div>'
        sections.append(
            f'<div class="section"><h3>[{key}] {html.escape(_LABELS[key])}</h3>{body}</div>'
        )
    evidence_sections = "\n".join(sections)

    return _HTML_TEMPLATE.format(
        version=html.escape(str(obs.diagnostics.get("version", "unknown"))),
        source=html.escape(obs.source),
        mask_plain=html.escape(obs.mask),
        mask_html=_render_mask_html(obs.mask),
        hypothesis_rows=hypothesis_rows,
        evidence_sections=evidence_sections,
    )


def write_report_html(obs: Observation, path) -> None:
    Path(path).write_text(format_report_html(obs), encoding="utf-8")


# ----------------------------------------------------------------------
# 8. Public API
# ----------------------------------------------------------------------

__all__ = [
    "SieveLensEngine",
    "Observation",
    "Segment",
    "Extractor",
    "ReadLimits",
    "ExtractionRefused",
    "CONCEALMENT_REASONS",
    "format_report",
    "format_report_html",
    "write_report_html",
    "render_markers_html",
    "render_markers_text",
    "zero_width_density",
    "has_bidi_control",
    "detect_script_mixing",
    "find_invisible_runs",
    "decode_invisible_payload",
    "__version__",
]