"""
Sieve Lens PDF extension.

Adds PDF support to SieveLensEngine via pypdf.

Extracts:
  - PDF metadata (title, author, subject, keywords, creator, producer) -> H5
  - Page text -> body (H2/H3/H6/H7)
  - Annotations (comments, notes) -> H5
  - Hidden text -> H4 (format concealment).  Since 0.23.0 the hidden
    kinds are: render mode 3 (invisible), render mode 7 (clip only,
    newly REPORTED - 0.22.1 only excluded it), tiny text (effective
    font size below 2.0 pt), text drawn outside the page's view box
    (origin outside /CropBox, else /MediaBox), text governed by an
    optional-content group that is off in the default configuration
    (/OCProperties /D), and white (near-white) text with no non-white
    paint beneath it.

v0.22.1 - the visible page text no longer contains invisible text.
  One shared classification of the content stream (the text render mode
  state machine: Tr sets it, q/Q save and restore it, it persists across
  BT/ET, and a Form XObject invoked by Do inherits the state at its
  invocation) produces BOTH outputs: the observation's hidden text
  (render mode 3, as in 0.22.0) and the visible text (every show
  operation the classification marks hidden is removed from the content
  stream before pypdf's own extraction runs on the remainder).

v0.23.0 - the shared state machine widens from the render mode to the
  full drawing state the five kinds need: the CTM (cm), the font size
  (Tf), the text matrix (Tm/Td/TD/T*/TL; BT resets it), the fill and
  stroke colors (g/G/rg/RG/k/K/cs/CS/sc/scn - and SC/SCN, added for
  stroke-lane symmetry), and the marked-content stack (BDC/BMC/EMC,
  /OC resolved through /Properties).  The same classification rules
  (one _classify_show) produce the observation's hidden pieces and the
  visible side's drop set - never two judgments.  A page whose state
  cannot be determined (unreadable content stream, a state-tracking
  failure, form nesting beyond the walk limit, a form re-invoked under
  a different state, an unresolvable /OC reference, an unsupported /VE)
  fails closed: no visible text is emitted for that page and the
  suppression is recorded with the engine's existing unobserved reason
  word, "Extraction failed", in the page location of an empty body
  segment.  Other pages are unaffected.

  The hidden pieces of one page (and of one form) join into one
  css_hidden segment per label, in the order the labels first occur -
  the 0.22.1 shape extended to the new labels.  The labels ride the
  existing vocabulary: "invisible text, Tr N" for render modes 3 and 7,
  the existing DOCX word "tiny_font" for tiny text (its PDF sense is
  documented in docs/ARCHITECTURE.md), and the three new words
  "off_page", "off_layer '<name>'" and "white_text".

  The would-be-white and the undecidable-color shows are counted in the
  observation diagnostics as "white_on_painted" and "color_unresolved"
  (keys appear only when the count is greater than zero, so the 0.22.1
  samples' diagnostics stay unchanged).

Note on text extraction:
  pypdf's page.extract_text() maps characters through the font's encoding
  (e.g. WinAnsi for Helvetica), which drops characters not present in that
  encoding — including zero-width and bidi control characters. To preserve
  those for H2/H3/H7 detection, we additionally parse the raw content
  stream and include that text as a supplementary body segment.  Since
  0.22.1 the raw rescue is built from the same classification (hidden
  show operations are never part of it); 0.23.0 keeps that rule for the
  per-form rescue as well.

Usage:
    from sieve_lens import SieveLensEngine
    from sieve_lens_ext.pdf import install

    engine = SieveLensEngine()
    install(engine)               # attaches .pdf support
    obs = engine.observe("resume.pdf")

Requires: pypdf >= 4.0
"""

from __future__ import annotations

from math import sqrt
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    from pypdf import PdfReader
    from pypdf.generic import (
        ContentStream, DecodedStreamObject, DictionaryObject, NameObject,
    )
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

from sieve_lens import Segment, INVISIBLE

_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _mat_mul(m2, m1):
    """Row-vector composition m2 x m1 (m2 maps the point first)."""
    a2, b2, c2, d2, e2, f2 = m2
    a1, b1, c1, d1, e1, f1 = m1
    return (a2 * a1 + b2 * c1, a2 * b1 + b2 * d1,
            c2 * a1 + d2 * c1, c2 * b1 + d2 * d1,
            e2 * a1 + f2 * c1 + e1, e2 * b1 + f2 * d1 + f1)


def _mat_apply(m, x, y):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def _scale2(m4):
    """The scale factor of a 2x2 matrix: sqrt(|det|) (the geometric-mean
    scale; for an isotropic scale it IS the scale)."""
    a, b, c, d = m4
    return sqrt(abs(a * d - b * c))


def _floats(operands):
    out = []
    for op in operands:
        out.append(float(op))
    return out


# ----------------------------------------------------------------------
# Module-level constants of the five kinds (documented in
# docs/ARCHITECTURE.md, PDF section).
# ----------------------------------------------------------------------

# LN2-T02: the effective-font-size threshold (2.0 pt, this release's
# constant).  Effective size = Tf x scale(text matrix) x scale(CTM).
TINY_FONT_MAX_PT = 2.0

# LN2-T05: "near white".  DeviceGray >= 0.98, DeviceRGB all >= 0.98,
# DeviceCMYK all <= 0.02.  Other color spaces are not judged
# (color_unresolved).
WHITE_GRAY_MIN = 0.98
WHITE_RGB_MIN = 0.98
WHITE_CMYK_MAX = 0.02

# LN2-T06: the width fallback when the font's /Widths are unavailable:
# 1.0 x the font size per character (a deliberate over-estimate).
WIDTH_FALLBACK_FACTOR = 1.0

# LN2-T18 (the design chat's pre-publication check, 2026-11-20): the
# off_layer label never carries PDF-authored name text raw.  The
# group's /Name and the BDC property key are cleaned before they enter
# the label - printable characters only (control and format characters
# removed, whitespace runs collapsed to one space) - and a name longer
# than this many characters is capped (an ellipsis marker follows a
# capped name).
LAYER_LABEL_MAX_CHARS = 40

# The paint operators whose fill counts as a background (design request
# 3.1-5, literal list: f / F / f* / B / b, widened by the paint-op
# review to the two missing fill+stroke even-odd forms B* / b*) plus
# the image Do.
PAINT_FILL_OPS = (b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*")

# The state operators the shared state machine applies.
_STATE_OPS = (b"Tr", b"q", b"Q", b"cm", b"BT", b"Tm", b"Td", b"TD",
              b"T*", b"TL", b"Tf", b"g", b"G", b"rg", b"RG", b"k", b"K",
              b"cs", b"CS", b"sc", b"SC", b"scn", b"SCN")

_PATH_OPS = (b"m", b"l", b"c", b"v", b"y", b"re")

# Every path-painting operator (the path ends there; only the fills of
# PAINT_FILL_OPS can become a background).
_PATH_END_OPS = (b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*", b"S",
                 b"s", b"n")

_DEVICE_SPACES = ("/DeviceGray", "/DeviceRGB", "/DeviceCMYK")

# The closed vocabulary of the hidden-kind words: the structured `how`
# field of a hidden PDF segment (documented in docs/ARCHITECTURE.md).
# The location label keeps the 0.23 wording; this field is the
# machine-readable side of the same judgment.
PDF_HIDDEN_HOWS = ("tr3", "tr7", "tiny_font", "off_page", "off_layer",
                   "white_text", "transparent", "clipped", "same_color")

# The two render-mode kinds keep their internal reason words (the
# location label and the existing classification predate the
# structured field); the field carries the vocabulary word.
_HOW_OF_REASON = {"mode3": "tr3", "mode7": "tr7"}

# LN3 (the new kinds' thresholds, documented in docs/ARCHITECTURE.md):
# an opacity at or below ALPHA_MAX_HIDDEN hides the text; a text color
# within SAME_COLOR_MAX_DELTA of its background's color (per component)
# is the same_color kind.
ALPHA_MAX_HIDDEN = 0.02
SAME_COLOR_MAX_DELTA = 0.02

# The blend modes that compose the text unchanged; every other /BM
# leaves the drawing result undecidable (the soft-mask and blend-mode
# deferral only fires ABOVE the alpha threshold).
_BM_TRANSPARENT_MODES = ("/Normal", "/Compatible")

_THE_MISSING = object()


def _color_initial(space):
    """The initial color of a device color space (all black)."""
    if space == "/DeviceGray":
        return ("gray", 0.0)
    if space == "/DeviceRGB":
        return ("rgb", (0.0, 0.0, 0.0))
    return ("cmyk", (0.0, 0.0, 0.0, 0.0))


def _color_near_white(color):
    """True/False for a decidable color, None when undecidable."""
    kind, value = color
    if kind == "other":
        return None
    if kind == "gray":
        return value >= WHITE_GRAY_MIN
    if kind == "rgb":
        return all(v >= WHITE_RGB_MIN for v in value)
    return all(v <= WHITE_CMYK_MAX for v in value)


def _color_from_operands(operands, space):
    """Interpret sc/scn operands in the current color space."""
    try:
        values = _floats(operands)
    except Exception:
        return ("other", None)   # a named pattern or malformed operands
    if space == "/DeviceGray" and len(values) == 1:
        return ("gray", values[0])
    if space == "/DeviceRGB" and len(values) == 3:
        return ("rgb", tuple(values))
    if space == "/DeviceCMYK" and len(values) == 4:
        return ("cmyk", tuple(values))
    return ("other", None)       # count mismatch -> undecidable


def _matrix_operand(operands):
    """A 6-number matrix operand, or None when malformed."""
    try:
        values = _floats(operands)
    except Exception:
        return None
    if len(values) != 6:
        return None
    return tuple(values)


def _color_delta(kind_a, value_a, kind_b, value_b):
    """The maximum per-component difference of two colors of the same
    family: Gray and RGB compare in the (g, g, g) conversion, CMYK
    compares against CMYK only.  None when the families differ or a
    value is missing (the color is then unresolved, never hidden)."""
    if kind_a == "gray" and kind_b == "gray":
        return abs(value_a - value_b)
    if kind_a == "gray" and kind_b == "rgb":
        value_a = (value_a,) * 3
        kind_a = "rgb"
    elif kind_a == "rgb" and kind_b == "gray":
        value_b = (value_b,) * 3
        kind_b = "rgb"
    if kind_a == kind_b and kind_a in ("rgb", "cmyk") \
            and value_a is not None and value_b is not None:
        return max(abs(x - y) for x, y in zip(value_a, value_b))
    return None


def _axis_aligned_rect(points):
    """The shape judgment of one clip path, made once, on the
    CTM-transformed points: four points that are the (x, y)
    combinations of at most two x values and at most two y values.
    Two values on both axes give the rectangle; a degenerate axis
    (one value) gives the empty region.  Everything else - diagonals,
    curves (the control points ride the list), arbitrary polygons -
    is None (undecidable)."""
    if len(points) != 4:
        return None
    xs = sorted({p[0] for p in points})
    ys = sorted({p[1] for p in points})
    if len(xs) > 2 or len(ys) > 2:
        return None
    if set(points) != {(x, y) for x in xs for y in ys}:
        return None
    if len(xs) == 2 and len(ys) == 2:
        return ("rect", (xs[0], ys[0], xs[1], ys[1]))
    return "empty"


def _clip_intersect(a, b):
    """The intersection of two clip states.  None is the unclipped
    page; an unknown (unresolved) region can never be narrowed."""
    if a is None:
        return b
    if b is None:
        return a
    if a == "empty" or b == "empty":
        return "empty"
    if a == "unresolved" or b == "unresolved":
        return "unresolved"
    (ax0, ay0, ax1, ay1) = a[1]
    (bx0, by0, bx1, by1) = b[1]
    nx0, ny0 = max(ax0, bx0), max(ay0, by0)
    nx1, ny1 = min(ax1, bx1), min(ay1, by1)
    if nx0 >= nx1 or ny0 >= ny1:
        return "empty"
    return ("rect", (nx0, ny0, nx1, ny1))


class _PdfSegments(list):
    """The PDF extractor's segment list, carrying the file-level
    diagnostic counts the engine merges into the observation (only
    counts greater than zero are set, so the 0.22.1 samples' diagnostics
    stay unchanged)."""

    __slots__ = ("pdf_diagnostics",)

    def __init__(self):
        super().__init__()
        self.pdf_diagnostics = {}


class PdfExtractor:
    """Extract segments from a PDF file."""

    _METADATA_KEYS = (
        "/Title", "/Author", "/Subject",
        "/Keywords", "/Creator", "/Producer",
    )

    _OOB_MIN_LENGTH = 10

    # Cycle defense: the record set (per page walk) is the primary
    # guard; this depth cap is insurance against malformed graphs.
    _MAX_FORM_DEPTH = 8

    # Render modes that draw nothing a human reader can see
    # (PDF 32000-1 Table 51): 3 = invisible, 7 = clip only.  Since
    # 0.23.0 both are REPORTED as hidden text (labels "Tr 3" / "Tr 7").
    _INVISIBLE_MODES = (3, 7)

    # The engine's existing unobserved-reason word, reused for the
    # fail-closed page location (no new vocabulary).
    _WITHHELD_REASON = "Extraction failed"

    # OCMD nesting guard (a membership dictionary referring to another
    # membership dictionary).  Beyond the cap: fail closed.
    _MAX_OC_NESTING = 8

    # Sentinel for "the key did not exist" in the restore log.
    _MISSING = object()

    def extract(self, path: Path) -> List[Segment]:
        if not PYPDF_AVAILABLE:
            raise ImportError(
                "sieve_lens_ext.pdf requires pypdf. "
                "Install with: pip install sieve-lens[pdf]"
            )
        segments = _PdfSegments()
        counters = {"color_unresolved": 0, "white_on_painted": 0,
                    "alpha_unresolved": 0, "clip_unresolved": 0}
        with open(path, "rb") as f:
            reader = PdfReader(f)
            segments.extend(self._extract_metadata(reader))
            for page_num, page in enumerate(reader.pages, start=1):
                segments.extend(self._extract_page_text(
                    page, page_num, reader, counters))
                segments.extend(self._extract_annotations(page, page_num))
        for key, value in counters.items():
            if value:
                segments.pdf_diagnostics[key] = value
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
                    location=(f"PDF metadata / "
                              f"{self._clean_label_text(key)}"),
                ))
        return segments

    # ------------------------------------------------------------------
    # Page geometry and the optional-content default configuration
    # ------------------------------------------------------------------

    def _page_box(self, page):
        """The page's view box: /CropBox when present, else /MediaBox.

        /Rotate does not affect the judgment (the comparison happens in
        the default user space, per the design request).  Unavailable
        box -> None (the off-page check is skipped for that page).
        """
        try:
            if page.get("/CropBox") is not None:
                box = page.cropbox
            else:
                box = page.mediabox
            return (float(box.left), float(box.bottom),
                    float(box.right), float(box.top))
        except Exception:
            return None

    def _oc_default_config(self, reader):
        """The catalog's /OCProperties /D (the default configuration),
        or None when the document declares none (every group is on)."""
        try:
            root = reader.trailer["/Root"]
            ocp = root.get("/OCProperties")
            if ocp is None:
                return None
            ocp = ocp.get_object()
            d = ocp.get("/D")
            return d.get_object() if d is not None else None
        except Exception:
            return None

    def _oc_in_array(self, item, array):
        """Membership of one resolved OC object in an /OFF or /ON
        array, by indirect object number (identity as fallback)."""
        if array is None:
            return False
        try:
            array = array.get_object()
            item_id = getattr(getattr(item, "indirect_reference", None),
                              "idnum", None)
            for entry in array:
                try:
                    obj = entry.get_object()
                except Exception:
                    continue
                if obj is item:
                    return True
                if item_id is not None and \
                        getattr(getattr(obj, "indirect_reference", None),
                                "idnum", None) == item_id:
                    return True
        except Exception:
            return False
        return False

    def _oc_item_off(self, item, cfg, depth=0):
        """True when the resolved OC item is OFF in the default
        configuration.  Raises _StateError for unresolvable references,
        unsupported /VE and OCMD nesting beyond the cap."""
        if not isinstance(item, DictionaryObject) and \
                not isinstance(item, dict):
            raise _StateError("OC reference cannot be resolved")
        try:
            if item.get("/OCGs") is not None:
                # an optional-content membership dictionary
                if item.get("/VE") is not None:
                    raise _StateError("unsupported /VE")
                if depth > self._MAX_OC_NESTING:
                    raise _StateError("OC nesting too deep")
                members = item.get("/OCGs")
                members = members.get_object() if members is not None \
                    else None
                if members is None:
                    raise _StateError("OC reference cannot be resolved")
                states = []
                for entry in members:
                    try:
                        obj = entry.get_object()
                    except Exception:
                        raise _StateError(
                            "OC reference cannot be resolved")
                    states.append(self._oc_item_off(obj, cfg, depth + 1))
                policy = str(item.get("/P", NameObject("/AnyOn")))
                if policy == "/AnyOn":
                    return all(states)
                if policy == "/AllOn":
                    return any(states)
                if policy == "/AnyOff":
                    return all(not s for s in states)
                if policy == "/AllOff":
                    return any(not s for s in states)
                raise _StateError("unsupported OCMD policy")
            # a plain optional-content group
            if cfg is None:
                return False
            off = cfg.get("/OFF")
            if off is not None and self._oc_in_array(item, off):
                return True
            base = cfg.get("/BaseState")
            if base is not None and str(base) == "/OFF":
                on = cfg.get("/ON")
                return not (on is not None and self._oc_in_array(item, on))
            return False
        except _StateError:
            raise
        except Exception:
            raise _StateError("OC reference cannot be resolved")

    def _oc_item_pair(self, oc_ref, key):
        """Resolve one /OC reference to (item, key) and validate it
        (/VE and unresolvable references fail closed)."""
        try:
            item = oc_ref.get_object() if hasattr(oc_ref, "get_object") \
                else oc_ref
        except Exception:
            raise _StateError("OC reference cannot be resolved")
        if item is None:
            raise _StateError("OC reference cannot be resolved")
        if isinstance(item, dict) and item.get("/VE") is not None:
            raise _StateError("unsupported /VE")
        return (item, key)

    def _resolve_properties(self, resources, key):
        """The /Properties entry named by a BDC operand, or None."""
        if resources is None:
            return None
        try:
            props = resources.get("/Properties")
            props = props.get_object() if props is not None else None
            if not props:
                return None
            entry = props.get(key, None)
            if entry is None:
                return None
            return entry.get_object()
        except Exception:
            return None

    def _apply_marking(self, operator, operands, resources, state, cfg):
        """BDC / BMC / EMC: the marked-content stack.  BDC /OC entries
        resolve through /Properties; an unresolvable reference or an
        unsupported /VE fails closed (a _StateError).  The stack is
        lexical in the stream and independent of q/Q."""
        if operator == b"BDC":
            if len(operands) < 2:
                state.oc = state.oc + ((None, None),)
                return
            props = operands[1]
            key = str(props) if hasattr(props, "original_bytes") or \
                isinstance(props, str) else None
            if key is not None:
                resolved = self._resolve_properties(resources, key)
                if resolved is None:
                    raise _StateError(
                        "OC reference cannot be resolved")
                props = resolved
            try:
                oc_ref = props.get("/OC")
            except Exception:
                oc_ref = None
            if oc_ref is None:
                # the practical producer form: the property entry IS
                # the optional-content group or membership dictionary
                try:
                    if props.get("/OCGs") is not None or \
                            str(props.get("/Type")) == "/OCG":
                        state.oc = state.oc + (
                            self._oc_item_pair(props, key),)
                        return
                except _StateError:
                    raise
                except Exception:
                    pass
                state.oc = state.oc + ((None, None),)
                return
            state.oc = state.oc + (self._oc_item_pair(oc_ref, key),)
        elif operator == b"BMC":
            state.oc = state.oc + ((None, None),)
        elif operator == b"EMC":
            if state.oc:
                state.oc = state.oc[:-1]

    # ------------------------------------------------------------------
    # The one shared classification (observation and visible text are
    # both built from it - never from two separate judgments).
    # ------------------------------------------------------------------

    def _classify_page(self, page, reader) -> "_PageClassification":
        """Classify one page's content stream (the shared drawing-state
        state machine).

        Walks the page stream with the shared state, descending into
        every Form XObject the page invokes (Do) with the state at the
        invocation.  The observation's own form scan is separate
        (declaration-based, 0.22.0 semantics) and shares only this
        state machine and the show classification.
        """
        cls = _PageClassification()
        contents = None
        try:
            contents = page.get("/Contents")
        except Exception:
            cls.failed = True
        if contents is None:
            return cls
        try:
            stream = ContentStream(contents, reader)
        except Exception:
            cls.failed = True
            return cls
        cls.page_stream = stream
        cls.page_contents = contents
        resources = self._inherited_resources(page)
        cls.box = self._page_box(page)
        cls.oc_cfg = self._oc_default_config(reader)
        state = _TrState()
        try:
            self._walk_stream(
                stream, state, resources, cls, reader,
                parent_record=None, depth=0, paints=cls.page_paints)
        except _StateError:
            cls.failed = True
        except Exception:
            # an unexpected failure inside the walk also leaves the
            # drawing state undetermined for the rest of the page
            cls.failed = True
        return cls

    def _inherited_resources(self, page):
        """The page's /Resources, walking the /Parent chain (PDF spec:
        a page's own /Resources override the inherited ones entirely)."""
        node = page
        for _ in range(64):
            if node is None:
                return None
            try:
                res = node.get("/Resources")
            except Exception:
                return None
            if res is not None:
                try:
                    res = res.get_object()
                except Exception:
                    return None
                if res:
                    return res
            try:
                parent = node.get("/Parent")
            except Exception:
                return None
            try:
                node = parent.get_object() if parent is not None else None
            except Exception:
                return None
        return None

    def _resolve_xobject(self, resources, name):
        """The XObject for one Do operand, or None."""
        if resources is None:
            return None
        try:
            xobjs = resources.get("/XObject")
            xobjs = xobjs.get_object() if xobjs is not None else None
            if not xobjs:
                return None
            entry = xobjs.get(name, None)
            if entry is None:
                return None
            return entry.get_object()
        except Exception:
            return None

    def _decode_show_texts(self, operator, operands):
        """The decoded strings of one show operation (raises on
        undecodable operands, as 0.22.1 did)."""
        if operator == b"TJ":
            return [self._decode(item)
                    for item in operands[0]
                    if isinstance(item, (bytes, str))]
        if operator == b'"':
            return [self._decode(operands[-1])]
        return [self._decode(operands[0])]

    def _classify_show(self, state, texts, resources, cls, box, paints):
        """The one judgment for one show operation.

        Returns (reason, label) for the fixed reason order: render
        mode 3, render mode 7, tiny_font, off_page, off_layer,
        transparent, clipped, white_text, same_color.  (None, None)
        when the text is visible.  Raises _StateError when the
        optional-content context or an /ExtGState reference cannot be
        evaluated (fail closed).
        """
        if state.mode == 3:
            return "mode3", "invisible text, Tr 3"
        if state.mode == 7:
            return "mode7", "invisible text, Tr 7"
        # tiny text: the effective font size
        if state.size is not None:
            effective = (state.size * _scale2(state.tm[:4])
                         * _scale2(state.ctm[:4]))
            if effective < TINY_FONT_MAX_PT:
                return "tiny_font", "tiny_font"
        # off-page: the drawing origin against the page's view box
        if box is not None:
            origin = _mat_apply(state.ctm, state.tm[4], state.tm[5])
            if not (box[0] <= origin[0] <= box[2]
                    and box[1] <= origin[1] <= box[3]):
                return "off_page", "off_page"
        # hidden layers: any governing optional-content group off
        for item_pair in state.oc:
            item, key = item_pair
            if item is None:
                continue
            if self._oc_item_off(item, cls.oc_cfg):
                return "off_layer", self._layer_label(item, key)
        # transparent: the threshold judgment comes first - at or
        # below the threshold the text draws nothing, whatever a soft
        # mask or a blend mode would compose on top of it.  Only an
        # opacity above the threshold with a soft mask or a non-normal
        # blend mode in effect stays undecidable (visible, counted).
        if state.mode in (0, 4):
            alphas = (state.alpha_fill,)
        elif state.mode in (1, 5):
            alphas = (state.alpha_stroke,)
        else:
            alphas = (state.alpha_fill, state.alpha_stroke)
        if all(a <= ALPHA_MAX_HIDDEN for a in alphas):
            return "transparent", "transparent"
        if state.smask or state.bm:
            cls.alpha_unresolved += 1
            return None, None
        # clipped: the text's range against the current clip region
        # (the empty region hides everything; an undecidable region
        # stays visible and is counted)
        if state.clip is not None:
            if state.clip == "empty":
                return "clipped", "clipped"
            if state.clip == "unresolved":
                cls.clip_unresolved += 1
                return None, None
            cx0, cy0, cx1, cy1 = state.clip[1]
            clip_bbox = self._text_bbox(state, "".join(texts),
                                        resources)
            if not (clip_bbox[0] < cx1 and cx0 < clip_bbox[2]
                    and clip_bbox[1] < cy1 and cy0 < clip_bbox[3]):
                return "clipped", "clipped"
        # white text: the fill/stroke color per the render mode
        white, resolved = self._show_color_white(state)
        if not resolved:
            cls.color_unresolved += 1
            return None, None
        if white:
            joined = "".join(texts)
            bbox = self._text_bbox(state, joined, resources)
            if self._inside_any_paint(bbox, paints):
                cls.white_on_painted += 1
                return None, None
            return "white_text", "white_text"
        # same color: one non-white painted rectangle contains the
        # text's range, no later paint overlaps it, and the text color
        # matches the rectangle's color within the threshold
        reason = self._same_color_reason(state, texts, resources,
                                         paints, cls)
        if reason is not None:
            return reason, reason
        return None, None

    def _same_color_reason(self, state, texts, resources, paints, cls):
        """The same_color judgment: the last fill whose box contains
        the text's range is the background candidate (the fills of
        PAINT_FILL_OPS with a decidable, non-white color).  Any later
        paint overlapping the text's range - a second fill, an image,
        a shading, a pattern fill - means the background is not one
        solid color and cancels the judgment (visible, the
        fail-closed direction).  Shadings and pattern fills never ARE
        the candidate (their color is not one decidable color); they
        only cancel, which leans visible."""
        joined = "".join(texts)
        bbox = self._text_bbox(state, joined, resources)
        if state.mode in (0, 4):
            text_color = state.fill
        elif state.mode in (1, 5):
            text_color = state.stroke
        else:
            text_color = state.fill
        candidate = None
        candidate_index = -1
        for index, entry in enumerate(paints):
            if entry[3] != "fill":
                continue
            if _color_near_white(entry[1]) is not False:
                continue
            box = entry[0]
            if (box[0] <= bbox[0] and box[1] <= bbox[1]
                    and bbox[2] <= box[2] and bbox[3] <= box[3]):
                candidate = entry
                candidate_index = index
        if candidate is None:
            return None
        for entry in paints[candidate_index + 1:]:
            box = entry[0]
            if box is None:
                return None
            if (box[0] < bbox[2] and bbox[0] < box[2]
                    and box[1] < bbox[3] and bbox[1] < box[3]):
                return None
        delta = _color_delta(text_color[0], text_color[1],
                             candidate[1][0], candidate[1][1])
        if delta is None:
            cls.color_unresolved += 1
            return None
        if delta <= SAME_COLOR_MAX_DELTA:
            return "same_color"
        return None

    def _clean_label_text(self, text):
        """The name text of a PDF-authored label part: printable
        characters only (control and format characters are removed,
        every whitespace run collapses to one space), capped at
        LAYER_LABEL_MAX_CHARS with an ellipsis marker.  The PDF's own
        name text is never emitted raw (LN2-T18); every PDF-authored
        label part - layer names, form names and the metadata keys -
        rides this one entry point (LN3-T02, LN3-T03)."""
        spaced = "".join(
            " " if ch.isspace() else ch
            for ch in text if ch.isspace() or ch.isprintable())
        cleaned = " ".join(spaced.split())
        if len(cleaned) > LAYER_LABEL_MAX_CHARS:
            cleaned = cleaned[:LAYER_LABEL_MAX_CHARS] + "..."
        return cleaned

    def _layer_label(self, item, key):
        """The off_layer label: the group's cleaned /Name when present,
        else the cleaned BDC property key, else the bare word."""
        try:
            name = item.get("/Name")
        except Exception:
            name = None
        if isinstance(name, str) and name:
            cleaned = self._clean_label_text(name)
            if cleaned:
                return "off_layer '%s'" % cleaned
        if key:
            cleaned = self._clean_label_text(key)
            if cleaned:
                return "off_layer '%s'" % cleaned
        return "off_layer"

    def _form_location(self, page_num: int, form_name: str,
                       label: str) -> str:
        """The form location: the cleaned form name between quotes, or
        the bare word when the name cleans to nothing."""
        if form_name:
            return f"page {page_num} (form '{form_name}', {label})"
        return f"page {page_num} (form, {label})"

    def _show_color_white(self, state):
        """(white, resolved) for the show's color under its render
        mode: 0/4 fill, 1/5 stroke, 2/6 both.  3/7 never reach here."""
        if state.mode in (0, 4):
            colors = (state.fill,)
        elif state.mode in (1, 5):
            colors = (state.stroke,)
        else:
            colors = (state.fill, state.stroke)
        white = True
        resolved = True
        for color in colors:
            near = _color_near_white(color)
            if near is None:
                resolved = False
            elif not near:
                white = False
        return (white and resolved, resolved)

    def _estimated_width(self, state, text, resources):
        """The text-space width: the font's /Widths when resolvable,
        else 1.0 x the font size per character (over-estimate)."""
        size = state.size
        if size is None or not text:
            return 0.0
        widths = None
        first = None
        if state.font_name and resources is not None:
            try:
                fonts = resources.get("/Font")
                fonts = fonts.get_object() if fonts is not None else None
                font = fonts.get(state.font_name, None) if fonts else None
                font = font.get_object() if font is not None else None
                if font is not None:
                    w = font.get("/Widths")
                    if w is not None:
                        widths = [float(x) for x in w.get_object()]
                    f = font.get("/FirstChar")
                    first = int(f) if f is not None else 0
            except Exception:
                widths = None
        total = 0.0
        for char in text:
            code = ord(char)
            if widths is not None and first is not None \
                    and first <= code < first + len(widths):
                total += widths[code - first] / 1000.0 * size
            else:
                total += WIDTH_FALLBACK_FACTOR * size
        return total

    def _font_ascent(self, state, resources):
        """The font's /Ascent as a fraction of the font size (per mille
        of the /FontDescriptor, taken from the descendant font of a
        Type0), or None when unavailable - the width fallback and the
        height keep their previous values then."""
        if not state.font_name or resources is None:
            return None
        try:
            fonts = resources.get("/Font")
            fonts = fonts.get_object() if fonts is not None else None
            font = fonts.get(state.font_name, None) if fonts else None
            font = font.get_object() if font is not None else None
            if font is not None and str(font.get("/Subtype")) == "/Type0":
                descendants = font.get("/DescendantFonts")
                if descendants is not None:
                    first = list(descendants.get_object())[0].get_object()
                    font = first
            descriptor = font.get("/FontDescriptor") if font is not None \
                else None
            if descriptor is not None:
                ascent = descriptor.get_object().get("/Ascent")
                if ascent is not None:
                    value = float(ascent)
                    if value > 0:
                        return value / 1000.0
        except Exception:
            return None
        return None

    def _text_bbox(self, state, text, resources):
        """The text's bounding box in the page space: the corners of
        (0, 0), (w, 0), (0, h), (w, h) in the text space through
        (text matrix x CTM); height = the font size, tightened to the
        font's own /Ascent when the descriptor carries one (the glyph
        extent above the baseline; fonts without a descriptor keep the
        full size, as 0.23 measured)."""
        w = self._estimated_width(state, text, resources)
        size = state.size if state.size is not None else 0.0
        ascent = self._font_ascent(state, resources)
        h = size * ascent if (size and ascent) else size
        full = _mat_mul(state.ctm, state.tm)
        corners = [_mat_apply(full, 0.0, 0.0), _mat_apply(full, w, 0.0),
                   _mat_apply(full, 0.0, h), _mat_apply(full, w, h)]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        return (min(xs), min(ys), max(xs), max(ys))

    @staticmethod
    def _inside_any_paint(bbox, paints):
        """The slide-style guard (the 0.23 semantics): the text's
        bounding box is fully inside ONE painted box - a decidable
        non-white path fill or an image.  Shadings and pattern fills
        are not white-text backgrounds in this release (admitting one
        is a measured, evidenced change); white and undecidable fills
        never were."""
        for entry in paints:
            kind = entry[3]
            if kind == "image":
                pass
            elif kind == "fill":
                if _color_near_white(entry[1]) is not False:
                    continue
            else:
                continue
            box = entry[0]
            if (box[0] <= bbox[0] and box[1] <= bbox[1]
                    and bbox[2] <= box[2] and bbox[3] <= box[3]):
                return True
        return False

    def _record_path_point(self, operator, operands, state, path_points):
        """Accumulate the path-construction points, transformed by the
        current CTM (bezier control points included: a deterministic
        over-approximation of the painted area)."""
        try:
            if operator in (b"m", b"l"):
                x, y = _floats(operands[:2])
                path_points.append(_mat_apply(state.ctm, x, y))
            elif operator == b"c":
                pts = _floats(operands[:6])
                for i in (0, 2, 4):
                    path_points.append(
                        _mat_apply(state.ctm, pts[i], pts[i + 1]))
            elif operator in (b"v", b"y"):
                pts = _floats(operands[:4])
                for i in (0, 2):
                    path_points.append(
                        _mat_apply(state.ctm, pts[i], pts[i + 1]))
            elif operator == b"re":
                x, y, w, h = _floats(operands[:4])
                for px, py in ((x, y), (x + w, y),
                               (x, y + h), (x + w, y + h)):
                    path_points.append(_mat_apply(state.ctm, px, py))
        except Exception:
            pass

    def _apply_extgstate(self, state, operands, resources):
        """The gs operator: the named /ExtGState entry carries the fill
        and stroke opacities (/ca, /CA) and the soft-mask and blend
        mode annotations.  Only the entries the dictionary names change
        the state (PDF 32000-1 7.2.2); a missing name or an unreadable
        dictionary or operand fails closed."""
        if not operands:
            raise _StateError("gs operand is missing")
        name = str(operands[0])
        entry = None
        if resources is not None:
            try:
                gs_res = resources.get("/ExtGState")
                gs_res = (gs_res.get_object()
                          if gs_res is not None else None)
                if gs_res:
                    ref = gs_res.get(name, None)
                    entry = (ref.get_object()
                             if ref is not None else None)
            except Exception:
                entry = None
        if entry is None:
            raise _StateError("ExtGState reference cannot be resolved")
        try:
            ca = entry.get("/ca")
            if ca is not None:
                state.alpha_fill = float(ca)
            cA = entry.get("/CA")
            if cA is not None:
                state.alpha_stroke = float(cA)
            smask = entry.get("/SMask")
            if smask is not None:
                state.smask = str(smask) != "/None"
            bm = entry.get("/BM")
            if bm is not None:
                state.bm = str(bm) not in _BM_TRANSPARENT_MODES
        except _StateError:
            raise
        except Exception:
            raise _StateError("ExtGState is not readable")

    def _apply_clip_state(self, state, points):
        """W / W* followed by n: the path becomes the clip.  The shape
        judgment runs once, on the CTM-transformed points; several
        clips intersect; a shape the judgment cannot read leaves the
        region unresolved (visible, counted)."""
        shape = _axis_aligned_rect(points)
        if shape is None:
            shape = "unresolved"
        state.clip = _clip_intersect(state.clip, shape)

    def _record_shading(self, state, paints):
        """A sh operator paints its shading inside the current clip.
        The paint joins the history as a color-unknown background: its
        extent is the clip rectangle when the clip is judgeable, else
        unknown (an unknown extent cancels a same_color judgment -
        the visible-leaning direction).  A shading never becomes the
        white-text background in this release; admitting one is a
        measured, evidenced change (the clip rectangle plus both
        /Extend flags true)."""
        if state.clip == "empty":
            return
        if isinstance(state.clip, tuple) and state.clip[0] == "rect":
            paints.append((state.clip[1], None, None, "sh"))
        else:
            paints.append((None, None, None, "sh"))

    def _form_bbox_shape(self, form, state):
        """The form's /BBox as a clip shape in the page space under
        the invocation CTM (x the form /Matrix when present).  A
        missing /BBox leaves the clip unchanged; a malformed box or
        matrix fails closed."""
        try:
            bbox = form.get("/BBox")
        except Exception:
            bbox = None
        if bbox is None:
            return None
        try:
            values = _floats(list(bbox.get_object()))
            if len(values) != 4:
                raise _StateError("form /BBox is malformed")
        except _StateError:
            raise
        except Exception:
            raise _StateError("form /BBox is not readable")
        ctm = state.ctm
        try:
            matrix_ref = form.get("/Matrix")
        except Exception:
            matrix_ref = None
        if matrix_ref is not None:
            try:
                matrix = _matrix_operand(list(matrix_ref.get_object()))
            except Exception:
                matrix = None
            if matrix is None:
                raise _StateError("form /Matrix is malformed")
            ctm = _mat_mul(matrix, state.ctm)
        x0, y0, w, h = values
        corners = [_mat_apply(ctm, x0, y0), _mat_apply(ctm, x0 + w, y0),
                   _mat_apply(ctm, x0, y0 + h),
                   _mat_apply(ctm, x0 + w, y0 + h)]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        nx0, nx1 = min(xs), max(xs)
        ny0, ny1 = min(ys), max(ys)
        if nx0 >= nx1 or ny0 >= ny1:
            return "empty"
        return ("rect", (nx0, ny0, nx1, ny1))

    def _end_path(self, operator, state, path_points, paints):
        """A path-painting operator ends the path.  Every fill of
        PAINT_FILL_OPS (f / F / f* / B / B* / b / b*) joins the paint
        history with its fill color; the slide-style guard counts a
        history entry only when it is a decidable non-white fill or an
        image (the 0.23 semantics), and the same_color judgment only
        accepts a decidable non-white fill as the candidate."""
        if operator in PAINT_FILL_OPS and path_points:
            xs = [p[0] for p in path_points]
            ys = [p[1] for p in path_points]
            box = (min(xs), min(ys), max(xs), max(ys))
            paints.append((box, state.fill, state.fill_space, "fill"))
        path_points.clear()

    def _walk_stream(self, stream, state: "_TrState", resources, cls,
                     reader, parent_record: Optional["_FormRecord"],
                     depth: int, paints: List) -> None:
        """One classification pass over a content stream.

        Appends a _Piece per decoded show operand and records the show
        operation indexes (all of them, and the ones the visible side
        must drop).  Descends into invoked Form XObjects with the state
        at the Do (implicit save and restore around the form) and
        merges their paints back into the caller's list.  Raises
        _StateError when the drawing state cannot be tracked.
        """
        path_points: List[Tuple[float, float]] = []
        pending_clip = None
        for op_index, (operands, operator) in enumerate(stream.operations):
            if pending_clip is not None:
                # W / W* must be followed by n for the clip to take
                # effect; any other operator discards the pending path
                if operator == b"n":
                    self._apply_clip_state(state, pending_clip)
                pending_clip = None
            if operator == b"gs":
                self._apply_extgstate(state, operands, resources)
                continue
            if operator in _STATE_OPS:
                state.apply(operator, operands)
                continue
            if operator in (b"BDC", b"BMC", b"EMC"):
                self._apply_marking(operator, operands, resources,
                                    state, cls.oc_cfg)
                continue
            if operator in (b"W", b"W*"):
                pending_clip = list(path_points)
                continue
            if operator == b"sh":
                self._record_shading(state, paints)
                continue
            if operator in _PATH_OPS:
                self._record_path_point(operator, operands, state,
                                        path_points)
                continue
            if operator in _PATH_END_OPS:
                self._end_path(operator, state, path_points, paints)
                continue
            if operator in (b"Tj", b"'", b'"', b"TJ"):
                cls.page_show_indexes_add(parent_record, op_index)
                try:
                    texts = self._decode_show_texts(operator, operands)
                except Exception:
                    # the text of this operation is unknown; it is
                    # omitted from both outputs and never shown
                    cls.page_drop_add(parent_record, op_index)
                    continue
                reason, label = self._classify_show(
                    state, texts, resources, cls, cls.box, paints)
                if reason is not None:
                    cls.page_drop_add(parent_record, op_index)
                target = (parent_record.pieces if parent_record
                          is not None else cls.page_pieces)
                for text in texts:
                    target.append(_Piece(text, reason is not None,
                                         op_index, reason, label))
                continue
            if operator == b"Do" and operands:
                name = str(operands[0])
                form = self._resolve_xobject(resources, name)
                if form is None:
                    continue
                subtype = str(form.get("/Subtype"))
                if subtype == "/Image":
                    # an image paints its unit square under the CTM
                    corners = [_mat_apply(state.ctm, 0.0, 0.0),
                               _mat_apply(state.ctm, 1.0, 0.0),
                               _mat_apply(state.ctm, 0.0, 1.0),
                               _mat_apply(state.ctm, 1.0, 1.0)]
                    xs = [c[0] for c in corners]
                    ys = [c[1] for c in corners]
                    paints.append(((min(xs), min(ys), max(xs), max(ys)),
                                   None, None, "image"))
                    continue
                if subtype != "/Form":
                    continue
                # the form's /BBox narrows the clip for the walk (and
                # for the declaration walk's seed, which restores the
                # same state); a malformed box fails closed
                bbox_shape = self._form_bbox_shape(form, state)
                if bbox_shape is not None:
                    state.clip = _clip_intersect(state.clip,
                                                 bbox_shape)
                existing = cls.records_by_obj.get(id(form))
                if existing is not None:
                    # already walked (cycle or alias): reuse the record,
                    # but only under the same invocation state
                    if existing.entry_state != state.snapshot():
                        raise _StateError(
                            "form re-invoked under a different state")
                    record = existing
                else:
                    if depth + 1 > self._MAX_FORM_DEPTH:
                        raise _StateError("form nesting too deep")
                    record = _FormRecord(
                        entry_state=state.snapshot(), obj=form,
                        source_contents=form,
                        paints_at_entry=list(paints))
                    cls.records_by_obj[id(form)] = record
                    if parent_record is None:
                        record.site_name = name
                        record.site_xobjs = self._resources_xobjs(
                            resources)
                    else:
                        parent_record.children.append((name, record))
                    form_resources = None
                    try:
                        fres = form.get("/Resources")
                        form_resources = (fres.get_object()
                                          if fres is not None else None)
                    except Exception:
                        form_resources = None
                    # the form's own /OC joins the governing context
                    form_oc = None
                    try:
                        oc_ref = form.get("/OC")
                    except Exception:
                        oc_ref = None
                    if oc_ref is not None:
                        form_oc = self._oc_item_pair(oc_ref, None)
                    saved = state.snapshot()
                    saved_oc = state.oc
                    if form_oc is not None:
                        state.oc = state.oc + (form_oc,)
                    try:
                        self._walk_stream(
                            ContentStream(form, reader), state,
                            form_resources, cls, reader,
                            parent_record=record, depth=depth + 1,
                            paints=record.paints_at_entry)
                    finally:
                        # implicit save/restore around the form
                        # (PDF 32000-1 8.10.2): the invocation state
                        # continues after the Do
                        state.restore(saved)
                        state.oc = saved_oc
                    # the declaration walk's seed: the invocation state
                    # WITH the form's own /OC in the governing context
                    seed = saved
                    if form_oc is not None:
                        seed = list(saved)
                        seed[_TrState._OC_SNAPSHOT_INDEX] = \
                            seed[_TrState._OC_SNAPSHOT_INDEX] + (form_oc,)
                        seed = tuple(seed)
                    cls.drawn_states[id(form)] = (seed,
                                                  record.paints_at_entry)
                    if len(record.paints_at_entry) > len(paints):
                        # the form's own paints render on the page too
                        paints.extend(
                            record.paints_at_entry[len(paints):])
                if parent_record is None:
                    cls.top_sites.append((record, xobjs_of(resources),
                                          name))
                    cls.forms.setdefault(name, record)
                continue

    def _resources_xobjs(self, resources):
        try:
            xobjs = resources.get("/XObject")
            return xobjs.get_object() if xobjs is not None else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Visible text (filtered extraction on the classified remainder)
    # ------------------------------------------------------------------

    def _iter_records(self, cls: "_PageClassification"):
        for record in cls.records_by_obj.values():
            yield record

    def _page_has_hidden(self, cls: "_PageClassification") -> bool:
        if any(pc.hidden for pc in cls.page_pieces):
            return True
        return any(any(pc.hidden for pc in record.pieces)
                   for record in self._iter_records(cls))

    def _extract_filtered(self, page, reader,
                          cls: "_PageClassification") -> str:
        """extract_text on the page with the hidden show operations
        removed (the remainder runs through pypdf's own machinery
        unchanged). Every mutation is restored before returning."""
        saved: List[Tuple[object, object, object]] = []
        try:
            new_contents = DecodedStreamObject()
            new_contents.set_data(
                self._filtered_data(cls.page_contents, cls.page_drop,
                                    reader))
            saved.append((page, NameObject("/Contents"),
                          page.get("/Contents", self._MISSING)))
            page[NameObject("/Contents")] = new_contents

            memo: Dict[int, DecodedStreamObject] = {}
            for record, xobjs, name in cls.top_sites:
                if xobjs is None:
                    continue
                filtered = self._filtered_form(record, memo, reader)
                saved.append((xobjs, NameObject(name),
                              xobjs.get(name, self._MISSING)))
                xobjs[NameObject(name)] = filtered
            return self._extract_text_quiet(page)
        finally:
            for container, key, old in saved:
                try:
                    if old is self._MISSING:
                        del container[key]
                    else:
                        container[key] = old
                except Exception:
                    pass

    def _filtered_data(self, source_contents, drop: Set[int],
                       reader) -> bytes:
        """Re-serialize one content stream without the dropped show
        operations (the original source is parsed again, so nothing but
        the removed operations differs)."""
        filtered = ContentStream(source_contents, reader)
        filtered.operations = [op for i, op in enumerate(filtered.operations)
                               if i not in drop]
        return filtered.get_data()

    def _filtered_form(self, record: "_FormRecord",
                       memo: Dict[int, DecodedStreamObject],
                       reader) -> DecodedStreamObject:
        """A stream-object copy of the form with its hidden show
        operations removed; children referenced from the copy's own
        resources are filtered copies as well (children first)."""
        memo_key = id(record.obj)
        if memo_key in memo:
            return memo[memo_key]
        new = DecodedStreamObject()
        new.set_data(self._filtered_data(record.source_contents,
                                         record.drop, reader))
        for key in ("/Type", "/Subtype", "/BBox", "/Matrix", "/Group",
                    "/OC"):
            try:
                value = record.obj.get(key)
            except Exception:
                value = None
            if value is not None:
                new[NameObject(key)] = value
        try:
            res = record.obj.get("/Resources")
            res = res.get_object() if res is not None else None
        except Exception:
            res = None
        if res is not None:
            res_copy = DictionaryObject()
            res_copy.update(res)
            try:
                xobjs = res.get("/XObject")
                xobjs = xobjs.get_object() if xobjs is not None else None
            except Exception:
                xobjs = None
            if xobjs is not None:
                xo_copy = DictionaryObject()
                xo_copy.update(xobjs)
                for child_name, child_record in record.children:
                    xo_copy[NameObject(child_name)] = self._filtered_form(
                        child_record, memo, reader)
                res_copy[NameObject("/XObject")] = xo_copy
            new[NameObject("/Resources")] = res_copy
        memo[memo_key] = new
        return new

    @staticmethod
    def _extract_text_quiet(page) -> str:
        try:
            return page.extract_text() or ""
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Page text segments (0.22.0 shapes; the visible sources lose the
    # text the shared classification marks invisible)
    # ------------------------------------------------------------------

    def _group_hidden(self, pieces):
        """[(label, reason, joined text)] for the hidden pieces of one
        source, grouped per label in the order the labels first occur.
        One label maps to one reason (the label is the location side
        of the same judgment), so the structured kind word rides the
        group."""
        order: List[str] = []
        groups: Dict[str, List[str]] = {}
        reasons: Dict[str, str] = {}
        for pc in pieces:
            if pc.reason is None:
                continue
            if pc.label not in groups:
                groups[pc.label] = []
                order.append(pc.label)
                reasons[pc.label] = pc.reason
            groups[pc.label].append(pc.text)
        return [(label, reasons[label], "".join(groups[label]))
                for label in order]

    @staticmethod
    def _set_kind_fields(seg, reason, page_num):
        """Attach the structured kind fields to a hidden PDF segment.
        The fields exist only when a value exists: a segment without a
        kind word never gains the attributes, so no serialization of
        an existing sample or a non-PDF lane changes shape."""
        seg.how = _HOW_OF_REASON.get(reason, reason)
        seg.page = page_num

    def _extract_page_text(self, page, page_num: int, reader,
                           counters=None) -> List[Segment]:
        """Extract visible page text.

        Uses pypdf's standard extract_text for natural reading order,
        and additionally includes raw content stream text when it
        contains invisible characters that the standard extraction lost.
        The visible text comes from the same classification that reports
        the hidden text (the five kinds since 0.23.0): show operations
        the classification marks hidden never reach the visible side,
        and a page whose drawing state cannot be determined emits no
        visible text at all (fail closed, "Extraction failed").
        """
        segments: List[Segment] = []

        cls = self._classify_page(page, reader)

        if cls.failed:
            # fail closed: no visible text from this page; report what
            # the classification did establish before the failure
            return self._withheld_segments(page_num, cls)

        if self._page_has_hidden(cls):
            try:
                text = self._extract_filtered(page, reader, cls)
            except Exception:
                # the filtered extraction itself failed: the page's
                # visible text cannot be delivered - fail closed too
                return self._withheld_segments(page_num, cls)
        else:
            text = self._extract_text_quiet(page)
        if text.strip():
            segments.append(Segment(
                text=text,
                visible=True,
                kind="body",
                location=f"page {page_num}",
            ))

        raw = "".join(pc.text for pc in cls.page_pieces
                      if pc.reason is None)
        if raw and self._contains_invisible(raw) \
                and not self._contains_invisible(text):
            segments.append(Segment(
                text=raw,
                visible=True,
                kind="body",
                location=f"page {page_num} (raw stream)",
            ))
        for label, reason, joined in self._group_hidden(cls.page_pieces):
            seg = Segment(
                text=joined,
                visible=False,
                kind="css_hidden",
                location=f"page {page_num} ({label})",
            )
            self._set_kind_fields(seg, reason, page_num)
            segments.append(seg)

        for form_name, form_raw, hidden_groups in self._scan_form_streams(
                page, reader, cls):
            for label, reason, joined in hidden_groups:
                seg = Segment(
                    text=joined,
                    visible=False,
                    kind="css_hidden",
                    location=self._form_location(page_num, form_name,
                                                 label),
                )
                self._set_kind_fields(seg, reason, page_num)
                segments.append(seg)
            if (form_raw and self._contains_invisible(form_raw)
                    and not self._contains_invisible(text)):
                segments.append(Segment(
                    text=form_raw,
                    visible=True,
                    kind="body",
                    location=(f"page {page_num} (form '{form_name}', "
                              f"raw stream)"),
                ))

        if counters is not None:
            counters["color_unresolved"] += cls.color_unresolved
            counters["white_on_painted"] += cls.white_on_painted
            counters["alpha_unresolved"] += cls.alpha_unresolved
            counters["clip_unresolved"] += cls.clip_unresolved
        return segments

    def _withheld_segments(self, page_num: int,
                           cls: "_PageClassification") -> List[Segment]:
        """The fail-closed page output: an empty body segment carrying
        the existing unobserved-reason word in the page location, plus
        the hidden text the classification did establish before the
        failure (observation side)."""
        segments: List[Segment] = [Segment(
            text="",
            visible=True,
            kind="body",
            location=f"page {page_num} ({self._WITHHELD_REASON})",
        )]
        for label, reason, joined in self._group_hidden(cls.page_pieces):
            seg = Segment(
                text=joined,
                visible=False,
                kind="css_hidden",
                location=f"page {page_num} ({label})",
            )
            self._set_kind_fields(seg, reason, page_num)
            segments.append(seg)
        return segments

    # ------------------------------------------------------------------
    # Observation-side scans (0.22.0 semantics; they share only the
    # state machine and the show classification with the visible side)
    # ------------------------------------------------------------------

    def _scan_stream_object(self, contents, reader, state, resources,
                            box, paints, cls):
        """Scan one content-stream object (a Form XObject) for the
        observation: returns (raw_text, [(label, text), ...]).

        raw_text keeps the rescue role (preserve zero-width and bidi
        characters the font encoding drops) but never contains hidden
        show operations (the same classification as the visible side -
        since 0.22.1 for the page level, since 0.23.0 also here, which
        closes the raw-rescue leak a drawn form's hidden text could
        produce in 0.22.1).  box=None skips the off-page check (an
        unreferenced form has no page transform to check against).
        """
        try:
            stream = ContentStream(contents, reader)
        except Exception:
            return "", []
        raw_parts: List[str] = []
        groups: Dict[str, List[str]] = {}
        order: List[str] = []
        group_reasons: Dict[str, str] = {}
        path_points: List[Tuple[float, float]] = []
        pending_clip = None
        for operands, operator in stream.operations:
            try:
                if pending_clip is not None:
                    # W / W* must be followed by n for the clip to
                    # take effect; any other operator discards it
                    if operator == b"n":
                        self._apply_clip_state(state, pending_clip)
                    pending_clip = None
                if operator == b"gs":
                    self._apply_extgstate(state, operands, resources)
                    continue
                if operator in _STATE_OPS:
                    state.apply(operator, operands)
                    continue
                if operator in (b"BDC", b"BMC", b"EMC"):
                    self._apply_marking(operator, operands, resources,
                                        state, cls.oc_cfg)
                    continue
                if operator in (b"W", b"W*"):
                    pending_clip = list(path_points)
                    continue
                if operator == b"sh":
                    self._record_shading(state, paints)
                    continue
                if operator in _PATH_OPS:
                    self._record_path_point(operator, operands, state,
                                            path_points)
                    continue
                if operator in _PATH_END_OPS:
                    self._end_path(operator, state, path_points, paints)
                    continue
                if operator in (b"Tj", b"'", b'"', b"TJ"):
                    texts = self._decode_show_texts(operator, operands)
                    reason, label = self._classify_show(
                        state, texts, resources, cls, box, paints)
                    if reason is None:
                        raw_parts.extend(texts)
                    else:
                        if label not in groups:
                            groups[label] = []
                            order.append(label)
                            group_reasons[label] = reason
                        groups[label].extend(texts)
                # Do inside a form's stream is not descended here: the
                # declaration walk covers the declared children with
                # their own seeds (0.22.0 semantics).
            except _StateError:
                raise
            except Exception:
                continue
        return ("".join(raw_parts),
                [(label, group_reasons[label], "".join(groups[label]))
                 for label in order])

    def _scan_form_streams(self, page, reader, cls):
        """Walk Form XObjects declared in the page's /Resources.

        Coverage principle (same as metadata/annotations): every Form
        declared in /Resources is scanned, whether or not it is drawn
        via /Do.  Since 0.22.1 a form the page invokes (Do) is scanned
        with the state at its invocation (the shared classification);
        0.23.0 seeds the FULL invocation state (mode, CTM, colors,
        sizes, governing OC context and the page's paint history before
        the Do) recorded by the draw walk, so the observation and the
        visible side classify identically.  Unreferenced forms keep the
        default state (mode 0, unit CTM, black, the form's own /OC
        only) and skip the off-page check (no page transform).  All
        existing samples invoke forms at the default state, so their
        observation is unchanged.

        Cycle defense: the visited set of indirect object numbers is
        the primary guard; _MAX_FORM_DEPTH is insurance against
        malformed deep graphs, not the primary defense.
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
                seed = _TrState()
                paints: List = []
                box = None
                snap = cls.drawn_states.get(id(obj))
                if snap is not None:
                    seed.restore(snap[0])
                    paints = list(snap[1])
                    box = cls.box
                else:
                    # unreferenced form: the default state plus the
                    # form's own /OC (validated; failure skips it)
                    try:
                        oc_ref = obj.get("/OC")
                    except Exception:
                        oc_ref = None
                    if oc_ref is not None:
                        try:
                            pair = self._oc_item_pair(oc_ref, None)
                        except _StateError:
                            continue
                        seed.oc = (pair,)
                try:
                    form_resources = None
                    fres = obj.get("/Resources")
                    form_resources = (fres.get_object()
                                      if fres is not None else None)
                    raw, hidden_groups = self._scan_stream_object(
                        obj, reader, seed, form_resources, box,
                        paints, cls)
                except Exception:
                    continue
                results.append((self._clean_label_text(str(key)), raw,
                                hidden_groups))
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

        if isinstance(s, (bytes, bytearray)):
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


class _TrState:
    """The drawing state the hidden kinds need (PDF 32000-1 sections
    4 through 9).

    One instance classifies a whole page walk; the observation and the
    visible text are both derived from it (one judgment, two outputs).
    Tracked state: the text render mode (Tr), the CTM (cm, composed as
    cm x CTM), the font size and font name (Tf), the text matrix
    (Tm/Td/TD/T*/TL; BT resets it to the identity), the fill and stroke
    colors and color spaces (g/G/rg/RG/k/K/cs/CS/sc/SC/scn/SCN), the
    fill and stroke opacities with their soft-mask and blend-mode
    annotations (gs; an unresolvable or unreadable /ExtGState fails
    closed), the clip region (W / W* before n, intersected; the shape
    is judged on the CTM-transformed points), and the marked-content
    stack (BDC/BMC/EMC, managed by the walk).  q/Q save and restore
    everything except the text matrix (BT resets it before the next
    show) and the marked-content stack (which is lexical in the
    stream, not graphics state).  Tz (horizontal scaling) is
    deliberately NOT applied to Td offsets: pypdf 4.0.0 and 6.6.0 both
    measure Td offsets unscaled (the visible side is pypdf's own
    machinery, so the origin formula follows its measured behavior).
    A Form XObject invoked by Do inherits the state at its invocation
    (the caller saves and restores around the form).

    The clip state is None (unclipped), ("rect", box), "empty" (every
    show is hidden) or "unresolved" (the shape judgment failed; the
    shows stay visible and are counted).  A paint-history entry is
    (box, color, color space, kind): box is the painted rectangle in
    the page space (None when the extent is unknown), color is the
    resolved fill color or None, kind is "fill", "image" or "sh".
    """

    __slots__ = ("mode", "ctm", "tm", "size", "font_name", "fill",
                 "stroke", "fill_space", "stroke_space", "tl", "oc",
                 "stack", "alpha_fill", "alpha_stroke", "smask", "bm",
                 "clip")

    def __init__(self, mode: int = 0):
        self.mode = mode
        self.ctm = _IDENTITY
        self.tm = _IDENTITY
        self.size: Optional[float] = None
        self.font_name: Optional[str] = None
        self.fill = ("gray", 0.0)
        self.stroke = ("gray", 0.0)
        self.fill_space = "/DeviceGray"
        self.stroke_space = "/DeviceGray"
        self.tl = 0.0
        self.oc: Tuple = ()
        self.stack: List[Tuple] = []
        self.alpha_fill = 1.0
        self.alpha_stroke = 1.0
        self.smask = False
        self.bm = False
        self.clip = None

    # The oc slot's position in snapshot() (the declaration walk's
    # seed extends the governing context with the form's own /OC).
    _OC_SNAPSHOT_INDEX = 10

    # -- snapshots -------------------------------------------------------

    def snapshot(self):
        """Everything that shapes a form's classification, including
        the marked-content context, the opacities and the clip
        (re-invocation compare and the declaration walk's seed)."""
        return (self.mode, self.ctm, self.tm, self.size, self.font_name,
                self.fill, self.stroke, self.fill_space,
                self.stroke_space, self.tl, self.oc, self.alpha_fill,
                self.alpha_stroke, self.smask, self.bm, self.clip)

    def restore(self, snap):
        (self.mode, self.ctm, self.tm, self.size, self.font_name,
         self.fill, self.stroke, self.fill_space, self.stroke_space,
         self.tl, oc, self.alpha_fill, self.alpha_stroke, self.smask,
         self.bm, self.clip) = snap
        self.oc = oc

    def _gfx_snapshot(self):
        return (self.mode, self.ctm, self.size, self.font_name,
                self.fill, self.stroke, self.fill_space,
                self.stroke_space, self.tl, self.alpha_fill,
                self.alpha_stroke, self.smask, self.bm, self.clip)

    def _gfx_restore(self, snap):
        (self.mode, self.ctm, self.size, self.font_name, self.fill,
         self.stroke, self.fill_space, self.stroke_space,
         self.tl, self.alpha_fill, self.alpha_stroke, self.smask,
         self.bm, self.clip) = snap

    # -- operator application --------------------------------------------

    def apply(self, operator: bytes, operands) -> None:
        if operator == b"Tr":
            try:
                self.mode = int(operands[0])
            except (IndexError, TypeError, ValueError):
                raise _StateError("Tr operand is not a number")
        elif operator == b"q":
            self.stack.append(self._gfx_snapshot())
        elif operator == b"Q":
            if self.stack:
                self._gfx_restore(self.stack.pop())
        elif operator == b"cm":
            matrix = _matrix_operand(operands)
            if matrix is None:
                raise _StateError("cm operand is not a matrix")
            self.ctm = _mat_mul(matrix, self.ctm)
        elif operator == b"BT":
            self.tm = _IDENTITY
        elif operator == b"Tm":
            matrix = _matrix_operand(operands)
            if matrix is None:
                raise _StateError("Tm operand is not a matrix")
            self.tm = matrix
        elif operator == b"Td":
            try:
                tx, ty = _floats(operands[:2])
            except Exception:
                raise _StateError("Td operands are not numbers")
            self.tm = _mat_mul((1.0, 0.0, 0.0, 1.0, tx, ty), self.tm)
        elif operator == b"TD":
            try:
                tx, ty = _floats(operands[:2])
            except Exception:
                raise _StateError("TD operands are not numbers")
            self.tl = -ty
            self.tm = _mat_mul((1.0, 0.0, 0.0, 1.0, tx, ty), self.tm)
        elif operator == b"T*":
            self.tm = _mat_mul((1.0, 0.0, 0.0, 1.0, 0.0, -self.tl),
                               self.tm)
        elif operator == b"TL":
            try:
                self.tl = float(operands[0])
            except Exception:
                raise _StateError("TL operand is not a number")
        elif operator == b"Tf":
            try:
                self.size = float(operands[1])
                self.font_name = str(operands[0])
            except (IndexError, TypeError, ValueError):
                raise _StateError("Tf operands are not well formed")
        elif operator == b"g":
            self.fill = self._color(operands, "/DeviceGray")
            self.fill_space = "/DeviceGray"
        elif operator == b"G":
            self.stroke = self._color(operands, "/DeviceGray")
            self.stroke_space = "/DeviceGray"
        elif operator == b"rg":
            self.fill = self._color(operands, "/DeviceRGB")
            self.fill_space = "/DeviceRGB"
        elif operator == b"RG":
            self.stroke = self._color(operands, "/DeviceRGB")
            self.stroke_space = "/DeviceRGB"
        elif operator == b"k":
            self.fill = self._color(operands, "/DeviceCMYK")
            self.fill_space = "/DeviceCMYK"
        elif operator == b"K":
            self.stroke = self._color(operands, "/DeviceCMYK")
            self.stroke_space = "/DeviceCMYK"
        elif operator == b"cs":
            self.fill_space = self._space(operands)
            self.fill = self._space_color(self.fill_space)
        elif operator == b"CS":
            self.stroke_space = self._space(operands)
            self.stroke = self._space_color(self.stroke_space)
        elif operator in (b"sc", b"scn"):
            self.fill = _color_from_operands(operands, self.fill_space)
        elif operator in (b"SC", b"SCN"):
            self.stroke = _color_from_operands(operands,
                                               self.stroke_space)
        # ET: nothing to do; Tz is deliberately not tracked (see the
        # class docstring)

    @staticmethod
    def _color(operands, space):
        try:
            return _color_from_operands(_floats(operands), space)
        except Exception:
            return ("other", None)

    @staticmethod
    def _space(operands):
        try:
            name = str(operands[0])
        except Exception:
            return "other"
        return name if name in _DEVICE_SPACES else "other"

    @staticmethod
    def _space_color(space):
        if space == "other":
            return ("other", None)
        return _color_initial(space)


class _StateError(Exception):
    """The drawing state could not be tracked (fail closed)."""


class _Piece:
    """One decoded show operand with its classification."""

    __slots__ = ("text", "hidden", "op_index", "reason", "label")

    def __init__(self, text: str, hidden: bool, op_index: int,
                 reason: Optional[str] = None,
                 label: Optional[str] = None):
        self.text = text
        self.hidden = hidden
        self.op_index = op_index
        self.reason = reason
        self.label = label


class _FormRecord:
    """The classification of one drawn Form XObject."""

    __slots__ = ("entry_state", "obj", "source_contents", "pieces",
                 "drop", "show_indexes", "children", "site_name",
                 "site_xobjs", "paints_at_entry")

    def __init__(self, entry_state, obj, source_contents,
                 paints_at_entry):
        self.entry_state = entry_state
        self.obj = obj
        self.source_contents = source_contents
        self.pieces: List[_Piece] = []
        self.drop: Set[int] = set()
        self.show_indexes: Set[int] = set()
        self.children: List[Tuple[str, "_FormRecord"]] = []
        self.site_name: Optional[str] = None
        self.site_xobjs = None
        self.paints_at_entry = paints_at_entry


class _PageClassification:
    """The classification of one page (the shared judgment).

    ``forms`` maps the first resource name each drawn form was invoked
    under to its record (used by the tests to tie the observation's
    per-form report to the classification); ``records_by_obj`` maps
    every reached form object to its record (cycle and alias guard);
    ``top_sites`` lists the page-level Do sites for the filtered
    extraction's resource replacement; ``drawn_states`` maps every
    reached form object to (entry state, paint history at the Do) for
    the declaration walk's seeds; ``page_paints`` is the page's
    background-paint history in stream order; ``box`` is the page's
    view box and ``oc_cfg`` the document's default optional-content
    configuration; the two counters feed the observation diagnostics.
    """

    __slots__ = ("page_pieces", "page_drop", "page_show_indexes",
                 "forms", "records_by_obj", "top_sites", "failed",
                 "page_stream", "page_contents", "drawn_states",
                 "page_paints", "box", "oc_cfg", "color_unresolved",
                 "white_on_painted", "alpha_unresolved",
                 "clip_unresolved")

    def __init__(self):
        self.page_pieces: List[_Piece] = []
        self.page_drop: Set[int] = set()
        self.page_show_indexes: Set[int] = set()
        self.forms: Dict[str, _FormRecord] = {}
        self.records_by_obj: Dict[int, _FormRecord] = {}
        self.top_sites: List[Tuple[_FormRecord, object, str]] = []
        self.failed: bool = False
        self.page_stream = None
        self.page_contents = None
        self.drawn_states: Dict[int, Tuple] = {}
        self.page_paints: List[Tuple] = []
        self.box: Optional[Tuple] = None
        self.oc_cfg = None
        self.color_unresolved = 0
        self.white_on_painted = 0
        self.alpha_unresolved = 0
        self.clip_unresolved = 0

    def page_show_indexes_add(self, parent_record, op_index: int) -> None:
        if parent_record is not None:
            parent_record.show_indexes.add(op_index)
        else:
            self.page_show_indexes.add(op_index)

    def page_drop_add(self, parent_record, op_index: int) -> None:
        if parent_record is not None:
            parent_record.drop.add(op_index)
        else:
            self.page_drop.add(op_index)


def xobjs_of(resources):
    """The /XObject dictionary of a resources dictionary (or None)."""
    try:
        xobjs = resources.get("/XObject")
        return xobjs.get_object() if xobjs is not None else None
    except Exception:
        return None


def install(engine) -> None:
    """Attach PDF support to a SieveLensEngine instance."""
    engine.register_extractor([".pdf"], PdfExtractor())
