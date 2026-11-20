"""LN2 tests (v0.23.0): the five new hidden kinds of PDF text.

Red-first (design request 2026-11-19): LN2-T01 (render mode 7 must be
REPORTED as hidden text, not merely excluded), LN2-T02 (text whose
effective font size is below 2.0 pt is hidden; the text matrix and the
CTM scale it), LN2-T06 (white text is hidden only when no non-white
paint sits beneath it - the slide-style false-positive regression) and
LN2-T09 (the position invariant of LN-T06 widened to the new kinds)
enter the suite BEFORE the implementation and fail on the 0.22.1 tree.

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
        DecodedStreamObject, DictionaryObject, NameObject,
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
        img[NameObject("/Width")] = NameObject("1")
        img[NameObject("/Height")] = NameObject("1")
        img[NameObject("/ColorSpace")] = NameObject("/DeviceGray")
        img[NameObject("/BitsPerComponent")] = NameObject("8")
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
        p = self._path(name)
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
        p = self._path(name)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
