"""LN2 tests (v0.23.0): the five new hidden kinds of PDF text.

Red-first (design request 2026-11-19): LN2-T01 (render mode 7 must be
REPORTED as hidden text, not merely excluded), LN2-T02 (text whose
effective font size is below 2.0 pt is hidden; the text matrix and the
CTM scale it), LN2-T06 (white text is hidden only when no non-white
paint sits beneath it - the slide-style false-positive regression) and
LN2-T09 (the position invariant of LN-T06 widened to the new kinds)
enter the suite BEFORE the implementation and fail on the
0.22.1 tree.

LN2-T18 (the off_layer label hardening) enters later, red on the
0.23.0 tip 8156131, per the design chat's pre-publication check of
2026-11-20: a PDF-authored layer name must not ride raw into a
segment location.

The one judgment rule (design request section 1, carried over from
0.22.1): the observation and the visible text are built from the SAME
classification of the content stream - never from two separate
judgments. The axes stay H1..H7; the new kinds ride inside H4 with
labels in the segment location. The hidden pieces of one page (and of
one form) are joined into one css_hidden segment per label, in the
order the labels first occur - the 0.22.1 shape (all mode-3 pieces of
a page join into one segment) extended to the new labels.

Skipped automatically if pypdf is not installed.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from sieve_lens import SieveLensEngine, visible_text  # noqa: E402

try:
    from pypdf import PdfReader, PdfWriter  # noqa: E402
    from pypdf.generic import (  # noqa: E402
        DecodedStreamObject, DictionaryObject, NameObject, NumberObject,
    )
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

from test_sieve_lens_pdf_visible import _s  # noqa: E402

from sieve_lens_ext.pdf import install  # noqa: E402


def _num(value):
    if float(value) == int(float(value)):
        return b"%d" % int(float(value))
    return b"%.4g" % float(value)


def _text_show(text, *, size=12, mode=None, x=50, y=700, color=None,
               tm=None):
    """One BT..ET block: optional color ops, Tf size, Td or Tm, Tr, Tj."""
    color_ops = (color + b" ") if color else b""
    tr = b"" if mode is None else b"%d Tr " % mode
    pos = (b"%s Tm " % b" ".join(_num(v) for v in tm)) if tm else (
        b"%s %s Td " % (_num(x), _num(y)))
    return (b"BT " + color_ops + b"/F1 " + _num(size) + b" Tf " + pos
            + tr + _s(text) + b" Tj ET")


_RED_RECT = b"0.8 0.1 0.1 rg 50 650 400 60 re f "
_BLACK = b"0 0 0 rg "
_WHITE = b"1 1 1 rg "


def _slide(order, *, overflow=False, image=False):
    """The slide-style page: a colored rectangle and white text.

    order "rect_then_text": paint first, white text second (visible,
    white_on_painted counted).  order "text_then_rect": white text
    first, paint after (hidden).  overflow=True: white text wider than
    the rectangle (hidden).  image=True: an image Do paints the region
    instead of a path (visible).
    """
    banner = "W" * 40 if overflow else "White banner."
    parts = []
    if image:
        parts.append(b"q 400 0 0 60 50 650 cm /Im0 Do Q")
    elif order == "rect_then_text":
        parts.append(_RED_RECT)
    parts.append(_text_show(banner, color=_WHITE, y=680))
    if order == "text_then_rect":
        parts.append(_RED_RECT)
    parts.append(_text_show("Black body text.", color=_BLACK, y=600))
    return b" ".join(parts)


_SAMPLES = {
    # LN2-T01: one visible line + one 7 Tr line
    "mode7":
        _text_show("Yamada Taro.") + b" "
        + _text_show("Clip only memo.", mode=7, y=680),

    # LN2-T02: 1.9 pt is hidden, 2.0 pt is visible (the boundary)
    "tiny":
        _text_show("tiny text.", size=1.9, y=700) + b" "
        + _text_show("boundary two.", size=2, y=680),

    # LN2-T02: the text matrix and the CTM scale the effective size.
    # (a) 3 x 0.5 x 0.5 = 0.75 -> hidden;  (b) 12 x 0.5 x 0.5 = 3.0 ->
    # visible;  (c) 3 x 0.5 (Tm only) = 1.5 -> hidden;  (d) 3 x 0.5
    # (CTM only) = 1.5 -> hidden.  All origins stay on the page.
    "tiny_scaled": b" ".join([
        b"q 0.5 0 0 0.5 0 0 cm "
        + _text_show("scaled tiny.", size=3,
                     tm=(0.5, 0, 0, 0.5, 200, 1400)) + b" Q",
        b"q 0.5 0 0 0.5 0 0 cm "
        + _text_show("scaled visible.", size=12,
                     tm=(0.5, 0, 0, 0.5, 200, 1400)) + b" Q",
        _text_show("tm tiny.", size=3, tm=(0.5, 0, 0, 0.5, 100, 500)),
        b"q 0.5 0 0 0.5 0 0 cm "
        + _text_show("ctm tiny.", size=3, x=200, y=1400) + b" Q",
    ]),

    # LN2-T06 / LN2-T09: the slide samples
    "slide_painted": _slide("rect_then_text"),
    "slide_unpainted": _slide("text_then_rect"),
    "slide_overflow": _slide("rect_then_text", overflow=True),
    "slide_image": _slide("rect_then_text", image=True),
}


def _build_ln2(path, content, image=False):
    """One-page PDF with a font resource and (optionally) a 1x1 image."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica")})
    font_ref = writer._add_object(font)
    resources = DictionaryObject({
        NameObject("/Font"): DictionaryObject(
            {NameObject("/F1"): font_ref})})
    if image:
        img = DecodedStreamObject()
        img.set_data(b"\x00")
        img[NameObject("/Type")] = NameObject("/XObject")
        img[NameObject("/Subtype")] = NameObject("/Image")
        img[NameObject("/Width")] = NumberObject(1)
        img[NameObject("/Height")] = NumberObject(1)
        img[NameObject("/ColorSpace")] = NameObject("/DeviceGray")
        img[NameObject("/BitsPerComponent")] = NumberObject(8)
        resources[NameObject("/XObject")] = DictionaryObject({
            NameObject("/Im0"): writer._add_object(img)})
    stream = DecodedStreamObject()
    stream.set_data(content)
    page[NameObject("/Contents")] = writer._add_object(stream)
    page[NameObject("/Resources")] = resources
    with open(path, "wb") as f:
        writer.write(f)


@unittest.skipUnless(PYPDF_AVAILABLE, "pypdf not installed")
class TestHiddenKindsLN2(unittest.TestCase):

    def setUp(self):
        self.engine = SieveLensEngine()
        install(self.engine)
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmpdir.cleanup()

    def _path(self, name):
        return Path(self._tmpdir.name) / name

    def _observe(self, name):
        p = self._path(name + ".pdf")
        _build_ln2(p, _SAMPLES[name], image=(name == "slide_image"))
        return self.engine.observe(p)

    # --- LN2-T01 --------------------------------------------------------

    def test_ln2t01_mode7_reported_and_excluded(self):
        obs = self._observe("mode7")
        vis = visible_text(obs).text
        # the visible line survives
        self.assertIn("Yamada Taro.", vis)
        # the clip-only line never shows up in the visible text
        self.assertNotIn("Clip only memo.", vis)
        # NEW: the observation reports it, exactly like mode 3
        hidden = [s for s in obs.segments if s.kind == "css_hidden"]
        self.assertEqual(len(hidden), 1)
        self.assertEqual(hidden[0].text, "Clip only memo.")
        self.assertEqual(hidden[0].location,
                         "page 1 (invisible text, Tr 7)")
        self.assertEqual(obs.mask, "1001-000")

    # --- LN2-T02 --------------------------------------------------------

    def test_ln2t02_tiny_font_boundary_and_transforms(self):
        obs = self._observe("tiny")
        vis = visible_text(obs).text
        hidden = [s for s in obs.segments if s.kind == "css_hidden"]
        self.assertEqual(len(hidden), 1)
        self.assertEqual(hidden[0].text, "tiny text.")
        self.assertEqual(hidden[0].location, "page 1 (tiny_font)")
        self.assertNotIn("tiny text.", vis)
        # the boundary: 2.0 pt stays visible
        self.assertIn("boundary two.", vis)
        self.assertEqual(obs.mask, "1001-000")

    def test_ln2t02_text_matrix_and_ctm_scale_the_size(self):
        obs = self._observe("tiny_scaled")
        vis = visible_text(obs).text
        hidden = [s for s in obs.segments if s.kind == "css_hidden"]
        # one joined segment per label, in first-occurrence order
        self.assertEqual(len(hidden), 1)
        self.assertEqual(hidden[0].location, "page 1 (tiny_font)")
        self.assertEqual(hidden[0].text,
                         "scaled tiny.tm tiny.ctm tiny.")
        self.assertNotIn("scaled tiny.", vis)
        self.assertNotIn("tm tiny.", vis)
        self.assertNotIn("ctm tiny.", vis)
        # (b) 12 x 0.5 x 0.5 = 3.0 pt stays visible
        self.assertIn("scaled visible.", vis)

    # --- LN2-T06 --------------------------------------------------------

    def test_ln2t06_white_on_painted_is_visible(self):
        obs = self._observe("slide_painted")
        vis = visible_text(obs).text
        self.assertIn("White banner.", vis)
        self.assertIn("Black body text.", vis)
        self.assertEqual(obs.mask, "1000-000")
        self.assertEqual(obs.diagnostics.get("white_on_painted"), 1)

    def test_ln2t06_white_over_image_is_visible(self):
        obs = self._observe("slide_image")
        self.assertIn("White banner.", visible_text(obs).text)
        self.assertEqual(obs.mask, "1000-000")
        self.assertEqual(obs.diagnostics.get("white_on_painted"), 1)

    def test_ln2t06_white_without_paint_is_hidden(self):
        obs = self._observe("slide_unpainted")
        vis = visible_text(obs).text
        self.assertNotIn("White banner.", vis)
        self.assertIn("Black body text.", vis)
        hidden = [s for s in obs.segments if s.kind == "css_hidden"]
        self.assertEqual(len(hidden), 1)
        self.assertEqual(hidden[0].text, "White banner.")
        self.assertEqual(hidden[0].location, "page 1 (white_text)")
        self.assertEqual(obs.mask, "1001-000")

    def test_ln2t06_white_overflowing_the_rect_is_hidden(self):
        obs = self._observe("slide_overflow")
        vis = visible_text(obs).text
        self.assertNotIn("W" * 40, vis)
        hidden = [s for s in obs.segments if s.kind == "css_hidden"]
        self.assertEqual([s.location for s in hidden],
                         ["page 1 (white_text)"])
        self.assertEqual(obs.mask, "1001-000")

    # --- LN2-T09 --------------------------------------------------------

    def _position_invariants(self, name):
        """The LN-T06 invariant widened to the new kinds.

        The shared classification's pieces carry a reason; the drop set
        of the visible path is exactly the reasoned pieces, the
        observation reports exactly the reasoned pieces per label, and
        the position sets never intersect.
        """
        p = self._path(name + ".pdf")
        _build_ln2(p, _SAMPLES[name], image=(name == "slide_image"))
        reader = PdfReader(str(p))
        extractor = self.engine.get_extractor(".pdf")
        cls = extractor._classify_page(reader.pages[0], reader)
        obs = self.engine.observe(p)

        pieces = cls.page_pieces
        hidden = [pc for pc in pieces
                  if getattr(pc, "reason", None) is not None]
        visible = [pc for pc in pieces
                   if getattr(pc, "reason", None) is None]

        # the drop set is exactly the reasoned pieces
        self.assertEqual(cls.page_drop,
                         {pc.op_index for pc in hidden})
        # the kept show-ops are exactly the visible pieces
        self.assertEqual(cls.page_show_indexes - cls.page_drop,
                         {pc.op_index for pc in visible})

        # the observation reports the reasoned pieces per label
        by_label = {}
        for pc in hidden:
            by_label.setdefault(pc.reason, []).append(pc.text)
        label_locations = {
            "mode3": "page 1 (invisible text, Tr 3)",
            "mode7": "page 1 (invisible text, Tr 7)",
            "tiny_font": "page 1 (tiny_font)",
            "off_page": "page 1 (off_page)",
            "white_text": "page 1 (white_text)",
        }
        reported = {loc: "".join(s.text for s in obs.segments
                                 if s.kind == "css_hidden"
                                 and s.location == loc)
                    for loc in label_locations.values()}
        for reason, texts in by_label.items():
            self.assertEqual(reported[label_locations[reason]],
                             "".join(texts))
        # nothing is reported outside the reasoned labels
        expected_locs = {label_locations[r] for r in by_label}
        all_reported = [s.location for s in obs.segments
                        if s.kind == "css_hidden"]
        self.assertTrue(set(all_reported).issubset(expected_locs),
                        all_reported)

        # the position sets of visible and hidden never intersect
        v = {(pc.op_index, i) for pc in visible
             for i in range(len(pc.text))}
        h = {(pc.op_index, i) for pc in hidden
             for i in range(len(pc.text))}
        self.assertTrue(v.isdisjoint(h))

    def test_ln2t09_positions_of_visible_and_hidden_never_intersect(self):
        for name in ("mode7", "tiny", "slide_painted",
                     "slide_unpainted", "slide_overflow"):
            with self.subTest(sample=name):
                self._position_invariants(name)


_ROOT = Path(__file__).resolve().parent.parent

# ======================================================================
# LN2-T03..T15, T17 (the remaining kinds' pins, green phase of the
# implementation; T15 and T17 turn green with the release and the docs
# commits respectively, as LN-T10 did in 0.22.1) plus LN2-T18, the
# off_layer label hardening (red on the 0.23.0 tip 8156131 per the
# design chat's pre-publication check of 2026-11-20).
# ======================================================================

from pypdf.generic import (  # noqa: E402
    ArrayObject, FloatObject, RectangleObject, TextStringObject,
)

_M = _num  # shorthand for matrix/coordinate bytes


def _ocg_ref(writer, name):
    """One optional-content group (named) as an indirect object."""
    ocg = DictionaryObject({
        NameObject("/Type"): NameObject("/OCG"),
        NameObject("/Name"): NameObject(name)})
    return writer._add_object(ocg)


def _form_stream(writer, font_ref, content, oc_ref=None):
    """A Form XObject (shared font /F1, optional /OC)."""
    s = DecodedStreamObject()
    s.set_data(content)
    s[NameObject("/Type")] = NameObject("/XObject")
    s[NameObject("/Subtype")] = NameObject("/Form")
    s[NameObject("/BBox")] = ArrayObject([
        FloatObject(0), FloatObject(0), FloatObject(612), FloatObject(792)])
    res = DictionaryObject({NameObject("/Font"): DictionaryObject(
        {NameObject("/F1"): font_ref})})
    s[NameObject("/Resources")] = res
    if oc_ref is not None:
        s[NameObject("/OC")] = oc_ref
    return writer._add_object(s)


def _build_full(path, pages, *, cropbox=None, rotate=None,
                off_groups=(), on_groups=(), base_state=None,
                properties=None, colorspaces=None, forms=None, draws=()):
    """One- or two-page PDF with the full 0.23.0 feature surface.

    pages: 1 or 2 content-stream byte strings (the second page only
    receives the font).  off/on_groups and base_state build the
    catalog's /OCProperties /D.  properties maps /Properties names to
    specs built with THIS writer: ("ocg", name) | ("ocg_ve", name) |
    ("ocmd", (member names...), policy) | ("ocmd_deep", depth).
    colorspaces maps names to ("icc", n).  forms maps /XName to
    (content, spec | None) drawn on page 1 via draws.
    """
    writer = PdfWriter()
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica")})
    font_ref = writer._add_object(font)

    group_refs = {}

    def _group(name, ve=False):
        if name not in group_refs:
            ocg = DictionaryObject({
                NameObject("/Type"): NameObject("/OCG"),
                NameObject("/Name"): NameObject(name)})
            if ve:
                ocg[NameObject("/VE")] = ArrayObject([])
            group_refs[name] = writer._add_object(ocg)
        return group_refs[name]

    def _spec_obj(spec):
        if spec[0] == "ocg":
            return _group(spec[1])
        if spec[0] == "ocg_ve":
            return _group(spec[1], ve=True)
        if spec[0] == "ocmd":
            members = [_group(name) for name in spec[1]]
            cmd = DictionaryObject({
                NameObject("/Type"): NameObject("/OCMD"),
                NameObject("/OCGs"): ArrayObject(members),
                NameObject("/P"): NameObject(spec[2])})
            return writer._add_object(cmd)
        if spec[0] == "ocmd_deep":
            node = _group("/Deep")
            for _ in range(spec[1]):
                cmd = DictionaryObject({
                    NameObject("/Type"): NameObject("/OCMD"),
                    NameObject("/OCGs"): ArrayObject([node]),
                    NameObject("/P"): NameObject("/AllOn")})
                node = writer._add_object(cmd)
            return node
        raise ValueError(spec)

    all_groups = []
    for name in set(off_groups) | set(on_groups):
        all_groups.append(_group(name))

    xobjs = None
    if forms:
        xobjs = DictionaryObject()
        for name, (content, spec) in forms.items():
            oc_ref = _spec_obj(spec) if spec is not None else None
            xobjs[NameObject(name)] = _form_stream(
                writer, font_ref, content, oc_ref)

    for index, content in enumerate(pages):
        page = writer.add_blank_page(width=612, height=792)
        if cropbox and index == 0:
            page.cropbox = RectangleObject(
                [FloatObject(v) for v in cropbox])
        if rotate and index == 0:
            page.rotation = rotate
        resources = DictionaryObject({
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): font_ref})})
        if properties and index == 0:
            props = DictionaryObject()
            for key, spec in properties.items():
                props[NameObject(key)] = _spec_obj(spec)
            resources[NameObject("/Properties")] = props
        if colorspaces and index == 0:
            spaces = DictionaryObject()
            for key, (kind, components) in colorspaces.items():
                icc = DecodedStreamObject()
                icc.set_data(b"\x00" * 8)
                icc[NameObject("/N")] = NumberObject(components)
                spaces[NameObject(key)] = ArrayObject(
                    [writer._add_object(icc)])
            resources[NameObject("/ColorSpace")] = spaces
        if xobjs is not None:
            resources[NameObject("/XObject")] = DictionaryObject(xobjs)
        page[NameObject("/Resources")] = resources
        parts = []
        if content:
            parts.append(content)
        if index == 0:
            for name in draws:
                parts.append(b"/" + name[1:].encode("ascii") + b" Do")
        stream = DecodedStreamObject()
        stream.set_data(b" ".join(parts))
        page[NameObject("/Contents")] = writer._add_object(stream)

    if off_groups or on_groups or base_state:
        d = DictionaryObject()
        if off_groups:
            d[NameObject("/OFF")] = ArrayObject(
                [group_refs[n] for n in off_groups])
        if on_groups:
            d[NameObject("/ON")] = ArrayObject(
                [group_refs[n] for n in on_groups])
        if base_state:
            d[NameObject("/BaseState")] = NameObject(base_state)
        writer._root_object[NameObject("/OCProperties")] = DictionaryObject({
            NameObject("/D"): d,
            NameObject("/OCGs"): ArrayObject(all_groups),
        })

    with open(path, "wb") as f:
        writer.write(f)


def _build_named_layer(path, name, *, key="/Pr0", body="layered off."):
    """LN2-T18: one-page PDF whose OFF optional-content group carries
    its /Name as a TEXT string (the shapes above name the group with
    a PDF name), so the group name can carry arbitrary PDF-authored
    text."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica")})
    font_ref = writer._add_object(font)
    ocg = DictionaryObject({
        NameObject("/Type"): NameObject("/OCG"),
        NameObject("/Name"): TextStringObject(name)})
    ocg_ref = writer._add_object(ocg)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject(
            {NameObject("/F1"): font_ref}),
        NameObject("/Properties"): DictionaryObject(
            {NameObject(key): ocg_ref})})
    writer._root_object[NameObject("/OCProperties")] = DictionaryObject({
        NameObject("/D"): DictionaryObject(
            {NameObject("/OFF"): ArrayObject([ocg_ref])}),
        NameObject("/OCGs"): ArrayObject([ocg_ref])})
    stream = DecodedStreamObject()
    stream.set_data(b"/MC0 " + key.encode("ascii") + b" BDC "
                    + _text_show(body) + b" EMC")
    page[NameObject("/Contents")] = writer._add_object(stream)
    with open(path, "wb") as f:
        writer.write(f)


@unittest.skipUnless(PYPDF_AVAILABLE, "pypdf not installed")
class TestHiddenKindsLN2Full(unittest.TestCase):

    def setUp(self):
        self.engine = SieveLensEngine()
        install(self.engine)
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmpdir.cleanup()

    def _path(self, name):
        return Path(self._tmpdir.name) / (name + ".pdf")

    # --- LN2-T03 --------------------------------------------------------

    def test_ln2t03_origin_outside_the_view_box_is_hidden(self):
        content = (b"BT /F1 12 Tf -50 700 Td (off left.) Tj ET "
                   b"BT /F1 12 Tf 50 700 Td (on page.) Tj ET")
        p = self._path("off_left")
        _build_full(p, [content])
        obs = self.engine.observe(p)
        hidden = [s for s in obs.segments if s.kind == "css_hidden"]
        self.assertEqual([(s.location, s.text) for s in hidden],
                         [("page 1 (off_page)", "off left.")])
        self.assertIn("on page.", visible_text(obs).text)
        self.assertNotIn("off left.", visible_text(obs).text)

    def test_ln2t03_mediabox_applies_when_no_cropbox(self):
        content = b"BT /F1 12 Tf 700 50 Td (off right.) Tj ET"
        p = self._path("off_right")
        _build_full(p, [content])
        obs = self.engine.observe(p)
        hidden = [s for s in obs.segments if s.kind == "css_hidden"]
        self.assertEqual([s.location for s in hidden],
                         ["page 1 (off_page)"])

    def test_ln2t03_cropbox_tightens_the_view_box(self):
        content = (b"BT /F1 12 Tf 50 700 Td (outside crop.) Tj ET "
                   b"BT /F1 12 Tf 150 300 Td (inside crop.) Tj ET")
        p = self._path("crop")
        _build_full(p, [content], cropbox=(100, 100, 512, 692))
        obs = self.engine.observe(p)
        hidden = [s for s in obs.segments if s.kind == "css_hidden"]
        self.assertEqual([(s.location, s.text) for s in hidden],
                         [("page 1 (off_page)", "outside crop.")])
        self.assertIn("inside crop.", visible_text(obs).text)

    def test_ln2t03_partial_overflow_keeps_the_text_visible(self):
        # the origin sits inside the box: the overhang stays visible
        content = b"BT /F1 12 Tf 600 700 Td (sticks out.) Tj ET"
        p = self._path("partial")
        _build_full(p, [content])
        obs = self.engine.observe(p)
        self.assertEqual(obs.mask, "1000-000")
        self.assertIn("sticks out.", visible_text(obs).text)

    def test_ln2t03_page_rotation_does_not_move_the_box(self):
        content = b"BT /F1 12 Tf 50 700 Td (rotated page.) Tj ET"
        p = self._path("rot")
        _build_full(p, [content], rotate=90)
        obs = self.engine.observe(p)
        self.assertEqual(obs.mask, "1000-000")
        self.assertIn("rotated page.", visible_text(obs).text)

    # --- LN2-T04 --------------------------------------------------------

    def test_ln2t04_off_group_is_hidden_on_group_visible(self):
        content = (b"/MC0 /Pr0 BDC BT /F1 12 Tf 50 700 Td "
                   b"(layered off.) Tj ET EMC "
                   b"BT /F1 12 Tf 50 600 Td (plain text.) Tj ET")
        p = self._path("ocg_off")
        _build_full(p, [content], off_groups=("/L1",),
                    properties={"/Pr0": ("ocg", "/L1")})
        obs = self.engine.observe(p)
        hidden = [s for s in obs.segments if s.kind == "css_hidden"]
        self.assertEqual([(s.location, s.text) for s in hidden],
                         [("page 1 (off_layer '/L1')", "layered off.")])
        self.assertIn("plain text.", visible_text(obs).text)

    def test_ln2t04_group_on_by_default_stays_visible(self):
        content = (b"/MC0 /Pr0 BDC BT /F1 12 Tf 50 700 Td "
                   b"(layered on.) Tj ET EMC")
        p = self._path("ocg_on")
        _build_full(p, [content], on_groups=("/L1",),
                    properties={"/Pr0": ("ocg", "/L1")})
        obs = self.engine.observe(p)
        self.assertEqual(obs.mask, "1000-000")
        self.assertIn("layered on.", visible_text(obs).text)

    def test_ln2t04_base_state_off_with_on_list(self):
        content = (b"/MC0 /Pr0 BDC BT /F1 12 Tf 50 700 Td "
                   b"(in on list.) Tj ET EMC "
                   b"/MC1 /Pr1 BDC BT /F1 12 Tf 50 680 Td "
                   b"(not in on list.) Tj ET EMC")
        p = self._path("base_off")
        _build_full(p, [content], base_state="/OFF", on_groups=("/L1",),
                    properties={"/Pr0": ("ocg", "/L1"),
                                "/Pr1": ("ocg", "/L2")})
        obs = self.engine.observe(p)
        hidden = [s for s in obs.segments if s.kind == "css_hidden"]
        self.assertEqual([(s.location, s.text) for s in hidden],
                         [("page 1 (off_layer '/L2')", "not in on list.")])
        self.assertIn("in on list.", visible_text(obs).text)

    def test_ln2t04_ocmd_four_policies(self):
        members = ("/L1", "/L2")   # /L1 is off, /L2 is on
        cases = {
            "/AnyOn": "1000-000",   # ON if any member on -> visible
            "/AllOn": "1001-000",   # all on required -> hidden
            "/AnyOff": "1000-000",  # ON if any off -> visible
            "/AllOff": "1001-000",  # all off required -> hidden
        }
        for policy, expected_mask in cases.items():
            with self.subTest(policy=policy):
                p = self._path("ocmd" + policy[1:].lower())
                content = (b"/MC0 /Pr0 BDC BT /F1 12 Tf 50 700 Td "
                           b"(policy text.) Tj ET EMC")
                _build_full(p, [content], off_groups=("/L1",),
                            properties={"/Pr0": ("ocmd", ("/L1", "/L2"),
                                                 policy)})
                obs = self.engine.observe(p)
                self.assertEqual(obs.mask, expected_mask)
                if expected_mask == "1001-000":
                    hidden = [s for s in obs.segments
                              if s.kind == "css_hidden"]
                    self.assertEqual(hidden[0].location,
                                     "page 1 (off_layer '/Pr0')")

    def test_ln2t04_form_oc_is_honoured(self):
        p = self._path("form_oc")
        content = b"/Fm0 Do BT /F1 12 Tf 50 600 Td (plain after.) Tj ET"
        _build_full(
            p, [content], off_groups=("/L1",),
            forms={"/Fm0": (b"BT /F1 12 Tf 10 100 Td (form oc.) Tj ET",
                            ("ocg", "/L1"))})
        obs = self.engine.observe(p)
        hidden = [s for s in obs.segments if s.kind == "css_hidden"]
        self.assertEqual([(s.location, s.text) for s in hidden],
                         [("page 1 (form '/Fm0', off_layer '/L1')",
                           "form oc.")])
        self.assertIn("plain after.", visible_text(obs).text)

    def test_ln2t04_unresolvable_reference_fails_closed(self):
        p = self._path("oc_bad")
        content = (b"/MC0 /PrMissing BDC BT /F1 12 Tf 50 700 Td "
                   b"(never classified.) Tj ET EMC")
        _build_full(p, [content, b"BT /F1 12 Tf 50 700 Td "
                                        b"(second page.) Tj ET"])
        obs = self.engine.observe(p)
        self.assertEqual(obs.mask, "1000-000")
        vis = visible_text(obs).text
        self.assertNotIn("never classified.", vis)
        page1 = [s for s in obs.segments if s.kind == "body"
                 and s.location.startswith("page 1")]
        self.assertEqual(page1[0].location, "page 1 (Extraction failed)")
        # the other page is unaffected
        self.assertIn("second page.", vis)

    def test_ln2t04_visibility_expression_fails_closed(self):
        p = self._path("oc_ve")
        content = (b"/MC0 /Pr0 BDC BT /F1 12 Tf 50 700 Td "
                   b"(ve text.) Tj ET EMC")
        _build_full(p, [content], properties={"/Pr0": ("ocg_ve", "/L1")})
        obs = self.engine.observe(p)
        page1 = [s for s in obs.segments if s.kind == "body"]
        self.assertEqual(page1[0].location, "page 1 (Extraction failed)")

    # --- LN2-T05 --------------------------------------------------------

    def test_ln2t05_near_white_device_colors_are_hidden(self):
        texts = [
            (b"1 g", "gray one."), (b"0.98 g", "gray boundary."),
            (b"1 1 1 rg", "rgb one."),
            (b"0.98 0.98 0.98 rg", "rgb boundary."),
            (b"0 0 0 0 k", "cmyk white."),
            (b"0.02 0.02 0.02 0.02 k", "cmyk boundary."),
        ]
        content = b" ".join(
            b"BT " + color + b" /F1 12 Tf 50 %d Td " % (700 - i * 20)
            + _s(text) + b" Tj ET"
            for i, (color, text) in enumerate(texts))
        p = self._path("white_set")
        _build_full(p, [content])
        obs = self.engine.observe(p)
        hidden = [s for s in obs.segments if s.kind == "css_hidden"]
        self.assertEqual(len(hidden), 1)
        self.assertEqual(hidden[0].location, "page 1 (white_text)")
        self.assertEqual(hidden[0].text,
                         "".join(t for _, t in texts))
        self.assertEqual(visible_text(obs).text, "")
        self.assertEqual(obs.mask, "1001-000")

    def test_ln2t05_below_the_threshold_stays_visible(self):
        texts = [
            (b"0.97 g", "gray under."),
            (b"0.97 1 1 rg", "rgb under."),
            (b"0.03 0 0 0 k", "cmyk under."),
        ]
        content = b" ".join(
            b"BT " + color + b" /F1 12 Tf 50 %d Td " % (700 - i * 20)
            + _s(text) + b" Tj ET"
            for i, (color, text) in enumerate(texts))
        p = self._path("white_under")
        _build_full(p, [content])
        obs = self.engine.observe(p)
        self.assertEqual(obs.mask, "1000-000")
        self.assertNotIn("white_on_painted", obs.diagnostics)
        vis = visible_text(obs).text
        for _, text in texts:
            self.assertIn(text, vis)

    def test_ln2t05_render_mode_picks_the_color(self):
        cases = [
            (b"1 G", 1, "mode one stroke."),         # stroke color
            (b"1 G", 5, "mode five stroke."),        # stroke color
            (b"1 g", 4, "mode four fill."),         # fill color
            (b"1 1 1 rg 1 G", 2, "mode two both."),  # both white
            (b"1 1 1 rg 1 G", 6, "mode six both."),  # both white
        ]
        parts = []
        for i, (color, mode, text) in enumerate(cases):
            parts.append(b"BT " + color + b" /F1 12 Tf %d Tr 50 %d Td "
                         % (mode, 700 - i * 20) + _s(text) + b" Tj ET")
        p = self._path("white_modes")
        _build_full(p, [b" ".join(parts)])
        obs = self.engine.observe(p)
        hidden = [s for s in obs.segments if s.kind == "css_hidden"]
        self.assertEqual(len(hidden), 1)
        self.assertEqual(hidden[0].location, "page 1 (white_text)")
        self.assertEqual(hidden[0].text,
                         "".join(t for _, _, t in cases))
        # mode 2 with a white fill and a black stroke stays visible
        p2 = self._path("white_mode2_mixed")
        content = (b"BT 1 1 1 rg 0 G 2 Tr /F1 12 Tf 50 700 Td "
                   b"(mixed mode two.) Tj ET")
        _build_full(p2, [content])
        obs2 = self.engine.observe(p2)
        self.assertEqual(obs2.mask, "1000-000")
        self.assertIn("mixed mode two.", visible_text(obs2).text)

    # --- LN2-T07 --------------------------------------------------------

    def test_ln2t07_undecidable_space_stays_visible_and_counted(self):
        p = self._path("icc")
        content = (b"BT /CS0 cs 1 1 1 scn /F1 12 Tf 50 700 Td "
                   b"(icc white-ish.) Tj ET "
                   b"BT 0 0 0 rg /F1 12 Tf 50 600 Td "
                   b"(plain body.) Tj ET")
        _build_full(p, [content], colorspaces={"/CS0": ("icc", 3)})
        obs = self.engine.observe(p)
        self.assertEqual(obs.mask, "1000-000")
        self.assertIn("icc white-ish.", visible_text(obs).text)
        self.assertEqual(obs.diagnostics.get("color_unresolved"), 1)

    def test_ln2t07_operand_count_mismatch_is_unresolved(self):
        p = self._path("mismatch")
        content = (b"BT /DeviceGray cs 1 0 scn /F1 12 Tf 50 700 Td "
                   b"(mismatch text.) Tj ET")
        _build_full(p, [content])
        obs = self.engine.observe(p)
        self.assertEqual(obs.mask, "1000-000")
        self.assertIn("mismatch text.", visible_text(obs).text)
        self.assertEqual(obs.diagnostics.get("color_unresolved"), 1)

    # --- LN2-T08 --------------------------------------------------------

    def test_ln2t08_q_restores_the_color(self):
        content = (b"q 1 1 1 rg BT /F1 12 Tf 50 700 Td "
                   b"(in q white.) Tj ET Q "
                   b"BT /F1 12 Tf 50 680 Td (after q black.) Tj ET")
        p = self._path("qcolor")
        _build_full(p, [content])
        obs = self.engine.observe(p)
        hidden = [s for s in obs.segments if s.kind == "css_hidden"]
        self.assertEqual([(s.location, s.text) for s in hidden],
                         [("page 1 (white_text)", "in q white.")])
        self.assertIn("after q black.", visible_text(obs).text)

    def test_ln2t08_color_persists_across_bt_et(self):
        content = (b"BT 1 1 1 rg /F1 12 Tf 50 700 Td "
                   b"(first white.) Tj ET "
                   b"BT /F1 12 Tf 50 680 Td (second white.) Tj ET")
        p = self._path("across")
        _build_full(p, [content])
        obs = self.engine.observe(p)
        hidden = [s for s in obs.segments if s.kind == "css_hidden"]
        self.assertEqual(len(hidden), 1)
        self.assertEqual(hidden[0].text, "first white.second white.")
        self.assertEqual(visible_text(obs).text, "")

    def test_ln2t08_form_inherits_the_invocation_color(self):
        p = self._path("form_color")
        content = (b"1 1 1 rg /Fm0 Do 0 0 0 rg BT /F1 12 Tf 50 600 Td "
                   b"(plain black after.) Tj ET")
        _build_full(
            p, [content],
            forms={"/Fm0": (b"BT /F1 12 Tf 10 100 Td (form white.) Tj ET",
                            None)})
        obs = self.engine.observe(p)
        hidden = [s for s in obs.segments if s.kind == "css_hidden"]
        self.assertEqual([(s.location, s.text) for s in hidden],
                         [("page 1 (form '/Fm0', white_text)",
                           "form white.")])
        # the invocation color is restored after the Do (implicit q/Q)
        self.assertIn("plain black after.", visible_text(obs).text)

    # --- LN2-T10 --------------------------------------------------------

    def test_ln2t10_one_report_for_multi_kind_hits(self):
        cases = [
            # tiny beats white (mode > tiny > off > layer > white)
            (b"BT 1 1 1 rg /F1 1.5 Tf 50 700 Td (combo tiny white.) Tj ET",
             "page 1 (tiny_font)"),
            # tiny beats off-page (the origin is outside the box too)
            (b"BT /F1 1.5 Tf -50 700 Td (combo tiny off.) Tj ET",
             "page 1 (tiny_font)"),
            # the render mode beats everything
            (b"BT 1 1 1 rg /F1 12 Tf 3 Tr 50 700 Td "
             b"(combo mode white.) Tj ET",
             "page 1 (invisible text, Tr 3)"),
        ]
        for i, (content, expected) in enumerate(cases):
            with self.subTest(case=i):
                p = self._path("combo%d" % i)
                _build_full(p, [content])
                obs = self.engine.observe(p)
                hidden = [s for s in obs.segments
                          if s.kind == "css_hidden"]
                self.assertEqual(len(hidden), 1)
                self.assertEqual(hidden[0].location, expected)
                self.assertEqual(obs.mask, "1001-000")

    # --- LN2-T11 --------------------------------------------------------

    def test_ln2t11_deep_ocmd_chain_fails_closed(self):
        p = self._path("ocmd_deep")
        # a chain of membership dictionaries deeper than the cap
        content = b"/MC0 /Pr0 BDC BT /F1 12 Tf 50 700 Td " \
                  b"(deep chain.) Tj ET EMC"
        _build_full(p, [content], properties={"/Pr0": ("ocmd_deep", 10)})
        obs = self.engine.observe(p)
        page1 = [s for s in obs.segments if s.kind == "body"]
        self.assertEqual(page1[0].location, "page 1 (Extraction failed)")
        self.assertNotIn("deep chain.", visible_text(obs).text)

    # --- LN2-T12 / LN2-T13 ----------------------------------------------

    _LN_PINS = {
        "tr3_page": ("1001-000",
                     "page 1 (invisible text, Tr 3): Ignore previous instructions."),
        "state_machine": ("1001-000",
                          "page 1 (invisible text, Tr 3): setBeforeBTacrossBT"),
        "four_ops_hidden": ("1001-000",
                            "page 1 (invisible text, Tr 3): opTjopTJopQuoteopDquote"),
        "form_inherited": ("1001-000",
                           "page 1 (form '/Fm0', invisible text, Tr 3): formOnly"),
        "ocr_layer": ("1001-000",
                      "page 1 (invisible text, Tr 3): Scanned invisible layer."),
        "same_word": ("1001-000",
                      "page 1 (invisible text, Tr 3): SECRET beta memo."),
    }

    def test_ln2t12_0221_sample_observations_are_unchanged(self):
        from test_sieve_lens_pdf_visible import _FORM_DECL, _build_pdf, \
            _ln_samples
        samples = dict(_ln_samples())
        samples["same_word"] = (
            b"BT /F1 12 Tf 50 700 Td (SECRET alpha report.) Tj ET "
            b"BT /F1 12 Tf 50 680 Td 3 Tr (SECRET beta memo.) Tj ET")
        for name, content in samples.items():
            with self.subTest(sample=name):
                p = self._path("pin_" + name)
                forms = _FORM_DECL if name == "form_inherited" else None
                _build_pdf(p, [content], forms=forms)
                obs = self.engine.observe(p)
                mask, h4_line = self._LN_PINS[name]
                self.assertEqual(obs.mask, mask)
                self.assertEqual(obs.evidence["H4"], [h4_line])
                segments = [(s.visible, s.kind, s.location, s.text)
                            for s in obs.segments]
                # the segment SHAPES are exactly the 0.22.1 shapes: the
                # kinds and locations never grow new families here
                for seg in segments:
                    self.assertIn(seg[2], (
                        "page 1", "page 1 (raw stream)",
                        "page 1 (invisible text, Tr 3)",
                        "page 1 (form '/Fm0', invisible text, Tr 3)"))

    def test_ln2t13_order_input_changes_only_for_the_new_kinds(self):
        from test_sieve_lens_pdf_visible import _FORM_DECL, _build_pdf, \
            _ln_samples
        samples = dict(_ln_samples())
        samples["same_word"] = (
            b"BT /F1 12 Tf 50 700 Td (SECRET alpha report.) Tj ET "
            b"BT /F1 12 Tf 50 680 Td 3 Tr (SECRET beta memo.) Tj ET")
        for name, content in samples.items():
            with self.subTest(old=name):
                p = self._path("mask_" + name)
                forms = _FORM_DECL if name == "form_inherited" else None
                _build_pdf(p, [content], forms=forms)
                obs = self.engine.observe(p)
                self.assertEqual(obs.mask, self._LN_PINS[name][0])
                self.assertEqual(sorted(obs.h_states),
                                 ["H1", "H2", "H3", "H4", "H5", "H6",
                                  "H7"])
        # every new-kind sample raises H4 through the same css_hidden
        # route and nothing else moves (1001-000)
        for name in ("mode7", "tiny", "slide_unpainted",
                     "slide_overflow"):
            with self.subTest(new=name):
                p = self._path("masknew_" + name)
                _build_ln2(p, _SAMPLES[name],
                           image=(name == "slide_image"))
                obs = self.engine.observe(p)
                self.assertEqual(obs.mask, "1001-000")
                self.assertEqual(sorted(obs.h_states),
                                 ["H1", "H2", "H3", "H4", "H5", "H6",
                                  "H7"])

    # --- LN2-T14 --------------------------------------------------------

    def test_ln2t14_two_runs_in_two_directories_agree(self):
        import json
        results = []
        for round_index in range(2):
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / ("round%d.pdf" % round_index)
                _build_ln2(p, _SAMPLES["slide_overflow"])
                obs = self.engine.observe(p)
                results.append({
                    "mask": obs.mask,
                    "h_states": obs.h_states,
                    "evidence": obs.evidence,
                    "diagnostics": obs.diagnostics,
                    "segments": [(s.visible, s.kind, s.location, s.text)
                                 for s in obs.segments],
                })
        self.assertEqual(results[0], results[1])

    # --- LN2-T15 --------------------------------------------------------

    def test_ln2t15_version_pins_and_dependency_floor(self):
        import sieve_lens
        self.assertEqual(sieve_lens.__version__, "0.23.0")
        pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('version = "0.23.0"', pyproject)
        # the pypdf floor and the dependency set are unchanged
        self.assertIn('pdf = ["pypdf>=4.0"]', pyproject)
        self.assertIn("dependencies = []", pyproject)
        for name in ("README.md", "README.ja.md"):
            text = (_ROOT / name).read_text(encoding="utf-8")
            self.assertIn("# Sieve Lens v0.23.0", text)
        changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertTrue(changelog.startswith(
            "# Changelog\n\n## [0.23.0]"),
            "CHANGELOG must start with the [0.23.0] section")

    # --- LN2-T17 --------------------------------------------------------

    def test_ln2t17_vocabulary_is_closed_and_documented(self):
        import sieve_lens
        # the existing closed sets are unchanged
        self.assertEqual(sieve_lens.CONCEALMENT_REASONS,
                         ("vanish", "low_contrast", "tiny_font",
                          "tracked_deletion"))
        self.assertEqual(len(sieve_lens.REFUSAL_CODES), 13)
        self.assertEqual(sieve_lens.STRIP_KINDS,
                         ("zero_width_space", "word_joiner",
                          "bom_mid_text", "bidi_control", "tag_chars"))
        # the three new words are defined in the docs (the release's
        # whole addition; fewer than the cap of five)
        docs = (_ROOT / "docs" / "ARCHITECTURE.md").read_text(
            encoding="utf-8")
        for word in ("off_page", "off_layer", "white_text"):
            self.assertIn(word, docs)
        self.assertNotIn("off_screen", docs)
        self.assertNotIn("tiny_text", docs)

    # --- LN2-T18 --------------------------------------------------------

    def test_ln2t18_off_layer_label_cleans_the_name(self):
        """LN2-T18 (design chat pre-publication check 2026-11-20): the
        label keeps printable characters only - control and format
        characters (newlines, ESC, bidi overrides, ...) are removed -
        and the payload beyond the cap is gone."""
        hostile = "\n\x01\x1b injected\t" + "PAD " * 20 + "SECRETZQX"
        p = self._path("hostile_layer")
        _build_named_layer(p, hostile)
        obs = self.engine.observe(p)
        hidden = [s for s in obs.segments if s.kind == "css_hidden"]
        self.assertEqual(len(hidden), 1)
        loc = hidden[0].location
        self.assertIn("off_layer", loc)
        for ch in loc:
            self.assertTrue(ch.isprintable() or ch == " ", repr(loc))
        self.assertNotIn("SECRETZQX", loc)
        self.assertTrue(loc.endswith("...')"), loc)
        # the layer's text stays hidden exactly as in LN2-T04
        self.assertNotIn("layered off.", visible_text(obs).text)

    def test_ln2t18_off_layer_label_caps_the_name_at_40_characters(self):
        """LN2-T18: 40 characters stay complete, 41 gain the cap
        marker."""
        for limit, marked in ((40, False), (41, True)):
            with self.subTest(limit=limit):
                p = self._path("cap_%d" % limit)
                _build_named_layer(p, "A" * limit)
                obs = self.engine.observe(p)
                loc = [s for s in obs.segments
                       if s.kind == "css_hidden"][0].location
                self.assertEqual(
                    loc, "page 1 (off_layer '%s%s')"
                    % ("A" * 40, "..." if marked else ""))

    def test_ln2t18_off_layer_label_falls_back_to_the_key(self):
        """LN2-T18: a name that cleans to nothing falls back to the
        BDC property key (itself cleaned)."""
        p = self._path("blank_name")
        _build_named_layer(p, "\n\x01\t\x1b")
        obs = self.engine.observe(p)
        loc = [s for s in obs.segments
               if s.kind == "css_hidden"][0].location
        self.assertEqual(loc, "page 1 (off_layer '/Pr0')")

    def test_ln2t18_off_layer_label_collapses_whitespace_runs(self):
        """LN2-T18: whitespace runs inside the name collapse to one
        space."""
        p = self._path("spaced_name")
        _build_named_layer(p, "Layer\t\tOne\n\nName")
        obs = self.engine.observe(p)
        loc = [s for s in obs.segments
               if s.kind == "css_hidden"][0].location
        self.assertEqual(loc, "page 1 (off_layer 'Layer One Name')")


class _FakeWriter:
    """Unused placeholder kept out of the sample paths."""


if __name__ == "__main__":
    unittest.main(verbosity=2)
