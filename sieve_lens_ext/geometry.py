"""Sieve Lens geometry lane (structural concealment observation, H8).

Observes documents for *geometric* concealment that keeps text present in
the content (and therefore readable by parsers and LLM ingest pipelines)
while rendering it invisible to human readers.

HTML side (H8 html):

  - font-size at or below a sub-pixel threshold (e.g. font-size: 0.1px)
  - opacity at or below a near-zero threshold (e.g. opacity: 0.005)
  - transform scale factors at or below a near-zero threshold
    (e.g. transform: scale(0), scaleY(0.001))
  - line-height collapsed to zero (e.g. line-height: 0)

PDF side (H8 pdf, v2 thresholds onward):

  - text operators with a font size at or below the tiny threshold
    (e.g. ``/F1 0.05 Tf``)
  - text placement (``Tm``) at coordinates outside the page MediaBox

  Tr 3 invisible text is NOT re-observed here: the PDF extension already
  routes it into H4 segments (v0.15), and the lane never double-counts
  another lane's coverage.

The built-in HTML/CSS extension (H4) reports exact-zero cases such as
``opacity: 0`` as css_hidden segments. This lane covers the *threshold
gap*: near-zero values (0.1px, 0.005, ...) plus the transform and
line-height rules the exact-match tables do not implement. It emits its
own receipt and never touches segments, so H1-H7 semantics are
unchanged.

Sieve stance (enforced structurally):
  - The lane NEVER declares an attack or intent. It records facts only:
    which rule matched, the property, the raw value, the measured
    number, the threshold that fired, and where the declaration sits.
  - No verdict field exists in the receipt; there is nothing to agree
    or disagree with, only positions and numbers.

Design principles (inherited from the Sieve series):
  - Deterministic : same input + same thresholds -> same receipt, always.
  - Zero deps     : inline style attributes are scanned with the
                    standard library only. <style> blocks and local
                    <link> stylesheets are parsed with tinycss2 when it
                    is installed (the same optional dependency
                    sieve_lens_ext.html_css uses); without it those
                    sources are skipped and the receipt records that
                    fact (block_css_parsed: false).
  - Explainable   : every observation reports rule, property, value,
                    measured value, threshold, origin, and location.
  - Observation   : reports facts, not judgments.

Scan order (deterministic):
  inline style attributes (document order) -> <style> blocks (document
  order of their start tag, CSS rule order within) -> local <link>
  stylesheets (link order). Findings are NOT re-sorted: encounter order
  is the receipt order.

Thresholds (house rules, mirrors the control-vocab convention):
  - Embedded defaults (v1) are the runtime default.
  - An optional thresholds file overrides them wholesale; a missing,
    unreadable, or invalid-JSON file falls back to the embedded
    defaults. A parseable-but-malformed file raises ValueError.
  - The receipt records thresholds_sha256 -- a digest of the threshold
    CONTENT (canonical JSON), not of its path label -- so any receipt
    stays reproducible against the exact thresholds that produced it.
  - A repo-root reference copy ships as geometry_thresholds_v2.json.

Thresholds JSON shape (v2, adds the PDF key):
    {"version": "2", "lane": "geometry",
     "thresholds": {
       "font_size_px_max": 0.5,      # HTML: 0 <= font-size <= max (px/unitless)
       "opacity_max": 0.01,          # HTML: 0 <= opacity <= max (unitless)
       "scale_max": 0.01,            # HTML: any unitless scale axis in [0, max]
       "line_height_max": 0.0,       # HTML: 0 <= line-height <= max (px/unitless)
       "pdf_font_size_pt_max": 0.5}} # PDF: 0 <= Tf size <= max (pt)

Known scope limits (v2):
  - only px and unitless lengths are measured (em/rem/%/pt are skipped)
  - negative or malformed values are skipped
  - exponents (1e-3px) are not parsed
  - scale() percentage arguments are not converted (unitless only)
  - @media blocks and nested rules are not descended into
  - matrix(...) collapse is not observed (future vocabulary)
  - PDF out-of-bounds checks the Tm operands of the un-transformed text
    space; relative moves (Td/TD/T*/TL accumulation) and the graphics
    CTM (cm) are not composed into the position (future vocabulary)
  - PDF same-color-as-background fills are not observed (future
    vocabulary; highest operator cost)

Usage:
    from sieve_lens_ext.geometry import audit_geometry, audit_pdf_geometry

    report = audit_geometry(html_text, source="page.html")
    report = audit_pdf_geometry(path, source="doc.pdf")
    print(report_json(report))

CLI:
    python -m sieve_lens_ext.geometry IN OUT.json [THRESHOLDS.json]
    .pdf inputs take the PDF subscan; everything else is scanned as HTML.
    Exit codes: 0 = receipt written / 1 = failure (usage, read, or
    invalid thresholds file).

Requires: Python standard library; tinycss2 >= 1.1 for <style> and
<link> sources (optional, same extra as sieve_lens_ext.html_css);
pypdf >= 4.0 for PDF inputs (optional, same extra as
sieve_lens_ext.pdf).
"""

from __future__ import annotations

import hashlib
import html.parser
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

try:
    import tinycss2
    from tinycss2.ast import Declaration, QualifiedRule
    TINYCSS2_AVAILABLE = True
except ImportError:
    TINYCSS2_AVAILABLE = False

try:
    from pypdf import PdfReader
    from pypdf.generic import ContentStream
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

from sieve_lens import strip_leading_bom


LANE_NAME = "geometry"
SCHEMA = "sieve-lens.geometry/1"

_DEFAULT_THRESHOLDS_JSON = """{
  "version": "2",
  "lane": "geometry",
  "description": "Sieve Lens geometry concealment thresholds (default, v2)",
  "thresholds": {
    "font_size_px_max": 0.5,
    "opacity_max": 0.01,
    "scale_max": 0.01,
    "line_height_max": 0.0,
    "pdf_font_size_pt_max": 0.5
  }
}
"""

_THRESHOLD_KEYS = ("font_size_px_max", "opacity_max", "scale_max",
                   "line_height_max", "pdf_font_size_pt_max")
_THRESHOLD_BOUNDS = {
    "font_size_px_max": (0.0, 10.0),
    "opacity_max": (0.0, 1.0),
    "scale_max": (0.0, 1.0),
    "line_height_max": (0.0, 1.0),
    "pdf_font_size_pt_max": (0.0, 10.0),
}

_SCALE_FUNC = re.compile(
    r"(?P<fn>scale[xyz]?|scale3d)\s*\((?P<args>[^)]*)\)", re.IGNORECASE
)
_LENGTH_VALUE = re.compile(
    r"^\s*(?P<num>[0-9]*\.?[0-9]+)\s*(?P<unit>[a-zA-Z%]*)\s*$"
)
_NUMBER_ONLY = re.compile(r"^\s*(?P<num>[0-9]*\.?[0-9]+)\s*$")


# ----------------------------------------------------------------------
# Thresholds
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class Thresholds:
    """Validated geometry thresholds plus their provenance."""
    font_size_px_max: float
    opacity_max: float
    scale_max: float
    line_height_max: float
    pdf_font_size_pt_max: float
    sha256: str
    source: str

    def as_dict(self) -> Dict[str, float]:
        return {
            "font_size_px_max": self.font_size_px_max,
            "opacity_max": self.opacity_max,
            "scale_max": self.scale_max,
            "line_height_max": self.line_height_max,
            "pdf_font_size_pt_max": self.pdf_font_size_pt_max,
        }


def _thresholds_digest(values: Dict[str, float]) -> str:
    """Content digest over canonical JSON (NOT a digest of the path)."""
    payload = json.dumps(values, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_thresholds(data, source: str) -> Thresholds:
    """Validate a parsed thresholds document; raises ValueError if malformed."""
    if not isinstance(data, dict):
        raise ValueError(f"{source}: thresholds document must be a JSON object")
    raw = data.get("thresholds")
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: 'thresholds' must be an object")
    if set(raw) != set(_THRESHOLD_KEYS):
        raise ValueError(
            f"{source}: 'thresholds' must have exactly the keys "
            f"{list(_THRESHOLD_KEYS)} (got {sorted(raw)})")
    values: Dict[str, float] = {}
    for key in _THRESHOLD_KEYS:
        val = raw[key]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ValueError(f"{source}: '{key}' must be a number")
        val = float(val)
        if val != val or val in (float("inf"), float("-inf")):
            raise ValueError(f"{source}: '{key}' must be finite")
        lo, hi = _THRESHOLD_BOUNDS[key]
        if not (lo <= val <= hi):
            raise ValueError(
                f"{source}: '{key}' must be within [{lo}, {hi}] (got {val})")
        values[key] = val
    return Thresholds(sha256=_thresholds_digest(values), source=source,
                      **values)


def load_thresholds(thresholds_path: Optional[str] = None) -> Thresholds:
    """Load geometry thresholds.

    House rules (control-vocab convention): without a path, the embedded
    defaults are used. A missing, unreadable, or invalid-JSON file falls
    back to the embedded defaults. A parseable-but-malformed file raises
    ValueError. The sha256 digests the threshold content, so identical
    content yields the same digest from any path.
    """
    if thresholds_path:
        path = Path(thresholds_path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass  # fall back to the embedded defaults
        else:
            return _validate_thresholds(data, str(path))
    return _validate_thresholds(json.loads(_DEFAULT_THRESHOLDS_JSON),
                                "embedded")


# ----------------------------------------------------------------------
# Value parsers
# ----------------------------------------------------------------------

def _parse_length(value: str) -> Optional[Tuple[float, str]]:
    """Parse a non-negative CSS length number; returns (num, unit) or None.

    Negative, malformed, or exponential values return None (outside the
    observation scope, see module docstring).
    """
    m = _LENGTH_VALUE.match(value)
    if not m:
        return None
    return float(m.group("num")), m.group("unit").lower()


def _parse_number(value: str) -> Optional[float]:
    """Parse a bare unitless number; returns None otherwise."""
    m = _NUMBER_ONLY.match(value)
    if not m:
        return None
    return float(m.group("num"))


# ----------------------------------------------------------------------
# Rule evaluation
# ----------------------------------------------------------------------

def _eval_declaration(name: str, value: str, t: Thresholds) -> List[dict]:
    """Evaluate one declaration against the geometry rules.

    Returns observation dicts (facts only): scalar rules yield 0 or 1
    entries; transform yields one entry per collapsing scale function.
    """
    key = name.strip().lower()
    out: List[dict] = []

    if key == "font-size":
        parsed = _parse_length(value)
        if (parsed and parsed[1] in ("", "px")
                and 0.0 <= parsed[0] <= t.font_size_px_max):
            out.append({
                "rule": "font_size_tiny", "property": "font-size",
                "value": value, "measured": parsed[0],
                "threshold": t.font_size_px_max,
            })

    elif key == "opacity":
        parsed = _parse_length(value)
        if (parsed and parsed[1] == ""
                and 0.0 <= parsed[0] <= t.opacity_max):
            out.append({
                "rule": "opacity_near_zero", "property": "opacity",
                "value": value, "measured": parsed[0],
                "threshold": t.opacity_max,
            })

    elif key == "line-height":
        parsed = _parse_length(value)
        if (parsed and parsed[1] in ("", "px")
                and 0.0 <= parsed[0] <= t.line_height_max):
            out.append({
                "rule": "line_height_zero", "property": "line-height",
                "value": value, "measured": parsed[0],
                "threshold": t.line_height_max,
            })

    elif key == "transform":
        for m in _SCALE_FUNC.finditer(value):
            hit = False
            measured: List[float] = []
            for part in m.group("args").split(","):
                num = _parse_number(part)
                if num is None:
                    continue  # percent / malformed args stay unmeasured
                measured.append(num)
                if 0.0 <= num <= t.scale_max:
                    hit = True
            if hit:
                out.append({
                    "rule": "scale_collapse", "property": "transform",
                    "value": value, "matched": m.group(0).strip(),
                    "measured": measured, "threshold": t.scale_max,
                })

    return out


# ----------------------------------------------------------------------
# HTML collection (stdlib html.parser)
# ----------------------------------------------------------------------

def _split_inline_style(style: str) -> List[Tuple[str, str]]:
    """Split an inline style attribute into (name, value) pairs (stdlib)."""
    out: List[Tuple[str, str]] = []
    for chunk in style.split(";"):
        if ":" not in chunk:
            continue
        name, _, value = chunk.partition(":")
        name = name.strip()
        if name:
            out.append((name, value.strip()))
    return out


class _GeometryHTMLParser(html.parser.HTMLParser):
    """Collects inline style declarations, <style> blocks, and <link> hrefs."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inline_decls: List[dict] = []      # tag/id/class/line/name/value
        self.style_blocks: List[Tuple[int, str]] = []  # (html_line, css)
        self.link_hrefs: List[Tuple[int, str]] = []    # (html_line, href)
        self._style_buf: List[str] = []
        self._style_line: Optional[int] = None
        self._in_style_tag = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr = {k.lower(): (v if v is not None else "") for k, v in attrs}
        line, _ = self.getpos()

        if tag == "style":
            self._in_style_tag = True
            self._style_buf = []
            self._style_line = line
            return

        if tag == "link":
            rel = attr.get("rel", "").lower()
            href = attr.get("href", "")
            if "stylesheet" in rel and href:
                self.link_hrefs.append((line, href))
            return

        style = attr.get("style", "")
        if style and style.strip():
            for name, value in _split_inline_style(style):
                self.inline_decls.append({
                    "tag": tag,
                    "id": attr.get("id") or None,
                    "class": attr.get("class") or None,
                    "line": line,
                    "name": name,
                    "value": value,
                })

    def handle_endtag(self, tag):
        if tag.lower() == "style":
            self._in_style_tag = False
            css = "".join(self._style_buf)
            if css.strip() and self._style_line is not None:
                self.style_blocks.append((self._style_line, css))
            self._style_buf = []
            self._style_line = None

    def handle_data(self, data):
        if self._in_style_tag:
            self._style_buf.append(data)


# ----------------------------------------------------------------------
# CSS block parsing (tinycss2, optional)
# ----------------------------------------------------------------------

def _iter_css_rule_declarations(css_text: str):
    """Yield (selector, [(name, value, css_line), ...]) for top-level rules."""
    if not TINYCSS2_AVAILABLE:
        return
    try:
        rules = tinycss2.parse_stylesheet(css_text, skip_comments=True,
                                          skip_whitespace=True)
    except Exception:
        return
    for rule in rules:
        if not isinstance(rule, QualifiedRule):
            continue
        selector = tinycss2.serialize(rule.prelude).strip()
        if not selector:
            continue
        decls: List[Tuple[str, str, int]] = []
        try:
            parsed = tinycss2.parse_declaration_list(
                rule.content, skip_comments=True, skip_whitespace=True)
        except Exception:
            parsed = []
        for decl in parsed:
            if not isinstance(decl, Declaration):
                continue
            decls.append((
                decl.name,
                tinycss2.serialize(decl.value).strip(),
                getattr(decl, "source_line", None) or 0,
            ))
        yield selector, decls


def _resolve_local_css(href: str, base_dir: Optional[Path]) -> Optional[Path]:
    """Resolve a <link> href to a local file inside base_dir.

    Same v0.11.0 hardening as sieve_lens_ext.html_css: remote schemes are
    rejected, ../ escapes and absolute paths outside the specimen's
    directory tree are refused, so a specimen cannot make the scanner
    read arbitrary local files.
    """
    if base_dir is None:
        return None
    parsed = urlparse(href)
    if parsed.scheme in ("http", "https", "data", "javascript"):
        return None
    if parsed.scheme == "file":
        candidate = Path(unquote(parsed.path))
    else:
        candidate = Path(unquote(href))
    base = base_dir
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        candidate = candidate.resolve()
        base_root = base.resolve()
    except Exception:
        return None
    if not candidate.is_file():
        return None
    try:
        if not candidate.is_relative_to(base_root):
            return None
    except Exception:
        return None
    return candidate


# ----------------------------------------------------------------------
# Audit
# ----------------------------------------------------------------------

@dataclass
class GeometryReport:
    """Deterministic receipt of the geometry lane."""
    source: str
    observations: List[dict] = field(default_factory=list)
    thresholds: Dict[str, float] = field(default_factory=dict)
    thresholds_sha256: str = ""
    thresholds_source: str = "embedded"
    block_css_parsed: bool = False
    scanned: Dict[str, int] = field(default_factory=dict)


def audit_geometry(html_text: str, thresholds: Optional[Thresholds] = None,
                   thresholds_path: Optional[str] = None,
                   base_dir: Optional[str] = None,
                   source: Optional[str] = None) -> GeometryReport:
    """Audit raw HTML text for geometric concealment styles (facts only).

    Works on any HTML-ish text. Observations are collected in scan order
    (see module docstring) and are never re-sorted. H1-H7 observation
    spaces and masks are not read or modified.
    """
    if thresholds is None:
        thresholds = load_thresholds(thresholds_path)
    base = Path(base_dir) if base_dir else None

    parser = _GeometryHTMLParser()
    parser.feed(strip_leading_bom(html_text))
    parser.close()

    report = GeometryReport(
        source=source if source is not None else "",
        thresholds=thresholds.as_dict(),
        thresholds_sha256=thresholds.sha256,
        thresholds_source=thresholds.source,
        block_css_parsed=TINYCSS2_AVAILABLE,
        scanned={
            "inline_declarations": 0,
            "style_blocks": 0,
            "style_blocks_skipped": 0,
            "linked_css_files": 0,
            "linked_css_unresolved": 0,
            "linked_css_skipped": 0,
        },
    )

    # 1) inline style attributes, document order
    for decl in parser.inline_decls:
        report.scanned["inline_declarations"] += 1
        for obs in _eval_declaration(decl["name"], decl["value"], thresholds):
            obs.update({
                "origin": "inline_style",
                "location": f"line {decl['line']}, <{decl['tag']}>",
                "tag": decl["tag"],
                "id": decl["id"],
                "class": decl["class"],
            })
            report.observations.append(obs)

    # 2) <style> blocks, document order
    for html_line, css_text in parser.style_blocks:
        if not TINYCSS2_AVAILABLE:
            report.scanned["style_blocks_skipped"] += 1
            continue
        report.scanned["style_blocks"] += 1
        for selector, decls in _iter_css_rule_declarations(css_text):
            for name, value, css_line in decls:
                for obs in _eval_declaration(name, value, thresholds):
                    obs.update({
                        "origin": "style_block",
                        "location": (
                            f"inline <style> (html line {html_line}), "
                            f"css line {css_line}, selector: {selector}"),
                    })
                    report.observations.append(obs)

    # 3) local <link> stylesheets, link order (same hardening as html_css)
    for _html_line, href in parser.link_hrefs:
        local = _resolve_local_css(href, base)
        if local is None:
            report.scanned["linked_css_unresolved"] += 1
            continue
        try:
            css_text = local.read_text(encoding="utf-8", errors="replace")
        except OSError:
            report.scanned["linked_css_unresolved"] += 1
            continue
        if not TINYCSS2_AVAILABLE:
            report.scanned["linked_css_skipped"] += 1
            continue
        report.scanned["linked_css_files"] += 1
        for selector, decls in _iter_css_rule_declarations(css_text):
            for name, value, css_line in decls:
                for obs in _eval_declaration(name, value, thresholds):
                    obs.update({
                        "origin": "linked_css",
                        "location": (
                            f"<link> {local.name}, css line {css_line}, "
                            f"selector: {selector}"),
                    })
                    report.observations.append(obs)

    return report


# ----------------------------------------------------------------------
# PDF subscan (pypdf, optional)
# ----------------------------------------------------------------------

_MAX_PDF_FORM_DEPTH = 8


def _pdf_mediabox(page) -> Optional[Tuple[float, float, float, float]]:
    """Return the page MediaBox as (x0, y0, x1, y1), or None if unusable."""
    try:
        box = page.mediabox
        x0, y0 = float(box.left), float(box.bottom)
        x1, y1 = float(box.right), float(box.top)
    except Exception:
        return None
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0  # defensive, degenerate boxes
    return x0, y0, x1, y1


def _pdf_num(operand) -> Optional[float]:
    """Return a float for a pypdf numeric operand, else None.

    Non-numeric, boolean, NaN, and infinite operands are outside the
    observation scope (determinism and explainability, like the HTML
    parser skipping malformed values).
    """
    if isinstance(operand, bool) or not isinstance(operand, (int, float)):
        return None
    value = float(operand)
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _pdf_num_str(value: float) -> str:
    """Deterministic, compact string form of a measured operator number."""
    if value == int(value) and abs(value) < 1e16:
        return str(int(value))
    return repr(value)


def _eval_pdf_tiny_tfs(operands, t: Thresholds) -> List[dict]:
    """Rule pdf_font_size_tiny: a Tf declaration at or below the threshold.

    HTML-side convention: the declaration itself is the fact -- whether
    any text is later shown with this font is not judged.
    """
    size = _pdf_num(operands[1])
    if size is None or not (0.0 <= size <= t.pdf_font_size_pt_max):
        return []
    return [{
        "rule": "pdf_font_size_tiny", "property": "Tf font size",
        "value": _pdf_num_str(size), "measured": size,
        "threshold": t.pdf_font_size_pt_max,
    }]


def _eval_pdf_oob_tm(operands, mediabox) -> List[dict]:
    """Rule pdf_text_out_of_bounds: Tm placement outside the MediaBox.

    Checked against the un-transformed text-space operands (see module
    docstring, known scope limits). Exactly on the box is inside; any
    side strictly outside fires once per out-of-bounds Tm.

    Operand shapes: pypdf's ContentStream folds the 6-operand text
    matrix into its (e, f) translation tail; raw operator walks may
    also see the full 6 operands. Both shapes are handled, the full
    form via its e/f indices 4 and 5.
    """
    if mediabox is None:
        return []
    if len(operands) >= 6:
        e, f = _pdf_num(operands[4]), _pdf_num(operands[5])
    elif len(operands) == 2:
        e, f = _pdf_num(operands[0]), _pdf_num(operands[1])
    else:
        return []
    if e is None or f is None:
        return []
    x0, y0, x1, y1 = mediabox
    if x0 <= e <= x1 and y0 <= f <= y1:
        return []
    return [{
        "rule": "pdf_text_out_of_bounds", "property": "Tm position",
        "value": f"{_pdf_num_str(e)} {_pdf_num_str(f)}",
        "measured": [e, f],
        "threshold": [x0, y0, x1, y1],
    }]


def _scan_pdf_stream_object(contents, reader, mediabox, t: Thresholds,
                            observations, scanned) -> None:
    """Walk one content stream (page /Contents or Form XObject).

    Same ContentStream operator enumeration as sieve_lens_ext.pdf.
    Observations are appended in stream order and never re-sorted; they
    carry the rule facts (plus the font resource for Tf), and the caller
    stamps origin/location immediately after the scan.
    """
    try:
        stream = ContentStream(contents, reader)
    except Exception:
        scanned["streams_unreadable"] += 1
        return
    for operands, operator in stream.operations:
        try:
            scanned["operators_seen"] += 1
            if operator == b"Tf" and len(operands) >= 2:
                for obs in _eval_pdf_tiny_tfs(operands, t):
                    obs["font"] = str(operands[0]).strip()
                    observations.append(obs)
            elif operator == b"Tm":
                for obs in _eval_pdf_oob_tm(operands, mediabox):
                    observations.append(obs)
        except Exception:
            continue


def _pdf_form_walk(resources, page_label: str, reader, mediabox,
                   t: Thresholds, observations, scanned) -> None:
    """Walk Form XObjects declared in /Resources (pdf.py coverage rule).

    Every form declared in /Resources is scanned whether or not it is
    drawn via /Do. The visited set of indirect object numbers (fresh per
    page, same as sieve_lens_ext.pdf) is the primary cycle guard;
    _MAX_PDF_FORM_DEPTH is insurance against malformed deep graphs.
    """
    try:
        resources = resources.get_object() if resources is not None else None
        xobjs = resources.get("/XObject") if resources is not None else None
        xobjs = xobjs.get_object() if xobjs is not None else None
    except Exception:
        return
    if not xobjs:
        return
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
            if depth > _MAX_PDF_FORM_DEPTH:
                continue
            scanned["form_xobjects"] += 1
            base = len(observations)
            _scan_pdf_stream_object(obj, reader, mediabox, t, observations,
                                    scanned)
            for obs in observations[base:]:
                obs["origin"] = "form_stream"
                obs["location"] = f"{page_label} (form '{str(key)}')"
            try:
                fres = obj.get("/Resources")
                child = fres.get("/XObject") if fres is not None else None
                child = child.get_object() if child is not None else None
            except Exception:
                continue
            if child:
                _walk(child, depth + 1)

    _walk(xobjs, 0)


def audit_pdf_geometry(path, thresholds: Optional[Thresholds] = None,
                       thresholds_path: Optional[str] = None,
                       source: Optional[str] = None) -> GeometryReport:
    """Audit a PDF file for geometric concealment operators (facts only).

    Walks every page content stream and every Form XObject declared in
    /Resources (same coverage rule as sieve_lens_ext.pdf), in page order,
    collecting Tf / Tm observations in encounter order. Emits its own
    receipt and never touches segments, so H1-H7 semantics are unchanged.
    Tr 3 invisible text is intentionally not re-observed here (already
    routed to H4 by sieve_lens_ext.pdf since v0.15).
    """
    if not PYPDF_AVAILABLE:
        raise ImportError(
            "sieve_lens_ext.geometry PDF subscan requires pypdf. "
            "Install with: pip install sieve-lens[pdf]")
    if thresholds is None:
        thresholds = load_thresholds(thresholds_path)

    report = GeometryReport(
        source=source if source is not None else str(path),
        thresholds=thresholds.as_dict(),
        thresholds_sha256=thresholds.sha256,
        thresholds_source=thresholds.source,
        block_css_parsed=False,
        scanned={
            "pages": 0,
            "page_streams": 0,
            "form_xobjects": 0,
            "streams_unreadable": 0,
            "operators_seen": 0,
        },
    )
    observations = report.observations

    with open(path, "rb") as f:
        reader = PdfReader(f)
        for page_num, page in enumerate(reader.pages, start=1):
            report.scanned["pages"] += 1
            mediabox = _pdf_mediabox(page)
            page_label = f"page {page_num}"

            base = len(observations)
            try:
                contents = page.get_contents()
            except Exception:
                contents = None
            if contents is not None:
                report.scanned["page_streams"] += 1
                _scan_pdf_stream_object(contents, reader, mediabox,
                                        thresholds, observations,
                                        report.scanned)
                for obs in observations[base:]:
                    obs["origin"] = "page_stream"
                    obs["location"] = page_label

            try:
                resources = page.get("/Resources")
            except Exception:
                resources = None
            if resources is not None:
                _pdf_form_walk(resources, page_label, reader, mediabox,
                               thresholds, observations, report.scanned)

    return report


def report_json(report: GeometryReport) -> str:
    """Deterministic JSON receipt (trailing newline included)."""
    payload = {
        "lane": LANE_NAME,
        "schema": SCHEMA,
        "source": report.source,
        "thresholds": report.thresholds,
        "thresholds_source": report.thresholds_source,
        "thresholds_sha256": report.thresholds_sha256,
        "block_css_parsed": report.block_css_parsed,
        "scanned": report.scanned,
        "observation_count": len(report.observations),
        "observations": report.observations,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def format_geometry_report(report: GeometryReport) -> str:
    """Human-readable text receipt (facts only, no judgment)."""
    lines = []
    lines.append("=" * 66)
    lines.append("  SIEVE-LENS GEOMETRY LANE — OBSERVATION RECEIPT (H8)")
    lines.append(f"  Source  : {report.source}")
    th = report.thresholds
    lines.append(
        "  Thresholds: font-size<={font_size_px_max}px, "
        "opacity<={opacity_max}, scale<={scale_max}, "
        "line-height<={line_height_max}px, "
        "pdf Tf<={pdf_font_size_pt_max}pt".format(**th))
    lines.append(f"  Thresholds src: {report.thresholds_source} "
                 f"(sha256 {report.thresholds_sha256})")
    lines.append(f"  Block CSS parsed: {report.block_css_parsed}")
    scanned = ", ".join(f"{k}={v}" for k, v in report.scanned.items())
    lines.append(f"  Scanned: {scanned}")
    lines.append(f"  Observations (receipt): {len(report.observations)}")
    lines.append("=" * 66)
    for idx, obs in enumerate(report.observations, start=1):
        lines.append(f"[{idx}] rule {obs['rule']}: "
                     f"{obs['property']}: {obs['value']}")
        lines.append(f"    measured : {obs['measured']} "
                     f"(threshold {obs['threshold']})")
        lines.append(f"    where    : origin={obs['origin']}, "
                     f"{obs['location']}")
    if report.observations:
        lines.append("-" * 66)
    lines.append("  NOTE")
    lines.append("  This lane records style declarations and positions.")
    lines.append("  It does not judge intent or declare an attack.")
    lines.append("=" * 66)
    return "\n".join(lines)


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def main(argv=None) -> int:
    """CLI: IN OUT.json [THRESHOLDS.json]. 0 = success / 1 = failure.

    .pdf inputs take the PDF subscan; everything else is scanned as HTML.
    """
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) not in (2, 3):
        print("usage: python -m sieve_lens_ext.geometry IN OUT.json "
              "[THRESHOLDS.json]", file=sys.stderr)
        return 1
    src, dst = argv[0], argv[1]
    th_path = argv[2] if len(argv) == 3 else None
    src_path = Path(src)
    if not src_path.is_file():
        print(f"geometry: cannot read {src}", file=sys.stderr)
        return 1
    try:
        if src_path.suffix.lower() == ".pdf":
            report = audit_pdf_geometry(src_path, thresholds_path=th_path,
                                        source=str(src_path))
        else:
            html_text = strip_leading_bom(
                src_path.read_text(encoding="utf-8", errors="replace"))
            report = audit_geometry(html_text, thresholds_path=th_path,
                                    base_dir=str(src_path.parent),
                                    source=str(src_path))
    except ValueError as exc:
        print(f"geometry: {exc}", file=sys.stderr)
        return 1
    except ImportError as exc:
        print(f"geometry: {exc}", file=sys.stderr)
        return 1
    try:
        Path(dst).write_bytes(report_json(report).encode("utf-8"))
    except OSError as exc:
        print(f"geometry: cannot write {dst}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
