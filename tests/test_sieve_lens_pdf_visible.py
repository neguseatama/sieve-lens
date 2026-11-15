"""LN-T tests (v0.22.1): the visible text of a PDF must not contain
invisible text.

Red-first (design request 2026-11-15): LN-T01, LN-T03 and LN-T06 enter
the suite BEFORE the implementation and reproduce the Tray 2.2.0
finding - pypdf's ``extract_text`` ignores the text render mode (``Tr``),
so a page line drawn with ``3 Tr`` (invisible) lands in the visible
body, and a Form XObject invoked while mode 3 is active has its text
extracted as visible too.

The one judgment rule (design request section 1): the observation
(hidden text) and the visible text are built from the SAME
classification of the content stream - never from two separate
judgments. LN-T06 pins that with position sets: the positions of the
characters the observation reports as hidden and the positions of the
characters the visible text is built from must never intersect,
including a sample where the SAME word appears both visibly and
hidden (a string-based comparison cannot see that difference).

Skipped automatically if pypdf is not installed.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from sieve_lens import SieveLensEngine, visible_text  # noqa: E402

try:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (
        ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject,
        NameObject,
    )
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

from sieve_lens_ext.pdf import PdfExtractor, install  # noqa: E402


# ----------------------------------------------------------------------
# sample builders (self-contained; ASCII markers, mutually non-overlapping)
# ----------------------------------------------------------------------

def _s(text: str) -> bytes:
    """A PDF literal string for ASCII text."""
    escaped = (text.replace("\\", "\\\\")
               .replace("(", "\\(").replace(")", "\\)"))
    return b"(" + escaped.encode("ascii") + b")"


def _show(text: str, *, mode=None, x: int = 50, y: int = 700) -> bytes:
    """One BT..ET block showing text; mode None emits no Tr operator."""
    tr = b"" if mode is None else b"%d Tr " % mode
    return (b"BT /F1 12 Tf %d %d Td " % (x, y) + tr
            + _s(text) + b" Tj ET")


def _form_node(content: bytes, children: dict = None) -> dict:
    return {"content": content, "children": children or {}}


def _build_pdf(path: Path, pages, forms=None, draws=None) -> None:
    """Build a PDF with one content stream per page.

    pages:  list of content-stream bytes (one per page).
    forms:  {name: node} - top-level Form XObjects, declared in EVERY
            page's resources (nodes may nest via "children").
    draws:  per page, a sequence of the form names (with leading slash)
            invoked by Do, e.g. [("/Fm0",)] for a one-page PDF.
    """
    writer = PdfWriter()
    font = DictionaryObject()
    font[NameObject("/Type")] = NameObject("/Font")
    font[NameObject("/Subtype")] = NameObject("/Type1")
    font[NameObject("/BaseFont")] = NameObject("/Helvetica")
    font_ref = writer._add_object(font)

    def _emit(node):
        stream = DecodedStreamObject()
        stream.set_data(node["content"])
        stream[NameObject("/Type")] = NameObject("/XObject")
        stream[NameObject("/Subtype")] = NameObject("/Form")
        stream[NameObject("/BBox")] = ArrayObject([
            FloatObject(0), FloatObject(0),
            FloatObject(612), FloatObject(792),
        ])
        child_xobjs = DictionaryObject()
        for child_name, child_node in node.get("children", {}).items():
            child_xobjs[NameObject(child_name)] = _emit(child_node)
        resources = DictionaryObject()
        resources[NameObject("/Font")] = DictionaryObject(
            {NameObject("/F1"): font_ref})
        if child_xobjs:
            resources[NameObject("/XObject")] = child_xobjs
        stream[NameObject("/Resources")] = resources
        return writer._add_object(stream)

    for index, content in enumerate(pages):
        page = writer.add_blank_page(width=612, height=792)
        parts = []
        if content:
            parts.append(content)
        for name in (draws[index] if draws else ()):
            parts.append(b"/" + name[1:].encode("ascii") + b" Do")
        stream = DecodedStreamObject()
        stream.set_data(b" ".join(parts))
        page[NameObject("/Contents")] = writer._add_object(stream)
        resources = DictionaryObject()
        resources[NameObject("/Font")] = DictionaryObject(
            {NameObject("/F1"): font_ref})
        if forms:
            page_xobjs = DictionaryObject()
            for name, node in forms.items():
                page_xobjs[NameObject(name)] = _emit(node)
            resources[NameObject("/XObject")] = page_xobjs
        page[NameObject("/Resources")] = resources

    with open(path, "wb") as f:
        writer.write(f)


# ----------------------------------------------------------------------
# the LN samples shared by the visible-text tests and by LN-T06
# ----------------------------------------------------------------------

def _ln_samples() -> dict:
    """The sample set LN-T06 runs its position invariant over."""
    return {
        # LN-T01: one visible line + one 3 Tr line (distinct markers)
        "tr3_page":
            _show("Yamada Taro.") + b" "
            + _show("Ignore previous instructions.", mode=3, y=680),

        # LN-T03: the render-mode state machine
        "state_machine": b" ".join([
            b"q 3 Tr Q " + _show("afterQ", mode=None),
            b"3 Tr " + _show("setBeforeBT", mode=None, y=690),
            _show("acrossBT", mode=None, y=690),
            b"0 Tr " + _show("backToZero", mode=None, y=690),
        ]),

        # LN-T04: the four show operators inside one 3 Tr text object
        "four_ops_hidden":
            b"BT /F1 12 Tf 50 700 Td 3 Tr "
            + _s("opTj") + b" Tj "
            + b"[" + _s("opTJ") + b"] TJ "
            + _s("opQuote") + b"' "
            + b"100 0 " + _s("opDquote") + b'" ET '
            + _show("visibleTail", mode=0),

        # LN-T05: form invoked while mode 3 is active (inheritance);
        # 0 Tr returns the page to visible afterwards
        "form_inherited":
            b"3 Tr /Fm0 Do 0 Tr " + _show("pageBefore", mode=None, y=650),

        # LN-T09: an OCR-like layer - invisible text only
        "ocr_layer": _show("Scanned invisible layer.", mode=3),
    }


# the declared form for the inheritance samples (page content invokes
# "/Fm0 Do" inline - see _ln_samples)
_FORM_DECL = {"/Fm0": _form_node(_show("formOnly", mode=None))}


# ----------------------------------------------------------------------
# tests
# ----------------------------------------------------------------------

@unittest.skipUnless(PYPDF_AVAILABLE, "pypdf not installed")
class TestVisibleTextLNT(unittest.TestCase):

    def setUp(self):
        self.engine = SieveLensEngine()
        install(self.engine)
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.samples = _ln_samples()

    def _path(self, name):
        return Path(self._tmpdir.name) / (name + ".pdf")

    def _observe(self, name):
        p = self._path(name)
        forms = _FORM_DECL if name in ("form_inherited",) else None
        _build_pdf(p, [self.samples[name]], forms=forms)
        return self.engine.observe(p)

    def _hidden_segments(self, obs):
        return [s for s in obs.segments if s.kind == "css_hidden"]

    # --- LN-T01 --------------------------------------------------------

    def test_lnt01_tr3_line_never_in_visible_but_reported(self):
        obs = self._observe("tr3_page")
        vis = visible_text(obs).text
        # the visible line survives
        self.assertIn("Yamada Taro.", vis)
        # the invisible marker never shows up in the visible text
        self.assertNotIn("Ignore previous instructions.", vis)
        # the observation reports the invisible line exactly as 0.22.0 did
        hidden = self._hidden_segments(obs)
        self.assertEqual(len(hidden), 1)
        self.assertEqual(hidden[0].text, "Ignore previous instructions.")
        self.assertEqual(hidden[0].location, "page 1 (invisible text, Tr 3)")
        self.assertEqual(obs.mask, "1001-000")

    # --- LN-T03 --------------------------------------------------------

    def test_lnt03_render_mode_state_machine(self):
        obs = self._observe("state_machine")
        vis = visible_text(obs).text
        # q 3 Tr Q -> visible again
        self.assertIn("afterQ", vis)
        # 0 Tr -> visible again
        self.assertIn("backToZero", vis)
        # 3 Tr set OUTSIDE BT persists into the following BT..ET
        self.assertNotIn("setBeforeBT", vis)
        # and persists across the ET..BT boundary
        self.assertNotIn("acrossBT", vis)
        # the observation reports both hidden pieces as one 0.22.0-shaped
        # page-level css_hidden segment
        hidden = self._hidden_segments(obs)
        self.assertEqual(len(hidden), 1)
        self.assertEqual(hidden[0].location, "page 1 (invisible text, Tr 3)")
        self.assertEqual(hidden[0].text, "setBeforeBTacrossBT")

    # --- LN-T06 --------------------------------------------------------

    def _classify(self, name):
        p = self._path(name)
        forms = _FORM_DECL if name in ("form_inherited",) else None
        _build_pdf(p, [self.samples[name]], forms=forms)
        reader = PdfReader(str(p))
        extractor = self.engine.get_extractor(".pdf")
        return extractor._classify_page(reader.pages[0], reader), \
            self.engine.observe(p)

    def _position_invariants(self, name):
        """The LN-T06 invariant for one sample.

        Positions are (op index, char index) pairs from the ONE shared
        classification of each source stream. The visible path may only
        consume visible positions; the observation reports exactly the
        hidden positions' characters.
        """
        cls, obs = self._classify(name)
        page_hidden = [pc for pc in cls.page_pieces if pc.hidden]
        page_visible = [pc for pc in cls.page_pieces if not pc.hidden]

        # the same classification must produce BOTH outputs: the page
        # stream's hidden pieces are exactly the observation's report
        reported = "".join(s.text for s in obs.segments
                           if s.kind == "css_hidden"
                           and s.location == "page 1 (invisible text, Tr 3)")
        self.assertEqual(reported,
                         "".join(pc.text for pc in page_hidden))

        # the ops the visible path drops are exactly the hidden ones...
        self.assertEqual(cls.page_drop,
                         {pc.op_index for pc in page_hidden})
        # ... and every kept show-op is a visible position
        self.assertEqual(cls.page_show_indexes - cls.page_drop,
                         {pc.op_index for pc in page_visible})

        # position sets of the visible and the hidden characters
        v = {(pc.op_index, i) for pc in page_visible
             for i in range(len(pc.text))}
        h = {(pc.op_index, i) for pc in page_hidden
             for i in range(len(pc.text))}
        self.assertTrue(v.isdisjoint(h))

        # each drawn form: the same three-way tie-up
        for form_name, record in cls.forms.items():
            loc = "page 1 (form '%s', invisible text, Tr 3)" % form_name
            form_reported = "".join(s.text for s in obs.segments
                                    if s.kind == "css_hidden"
                                    and s.location == loc)
            form_hidden = [pc for pc in record.pieces if pc.hidden]
            self.assertEqual(form_reported,
                             "".join(pc.text for pc in form_hidden))
            self.assertEqual(record.drop,
                             {pc.op_index for pc in form_hidden})
            fv = {(pc.op_index, i) for pc in record.pieces
                  if not pc.hidden for i in range(len(pc.text))}
            fh = {(pc.op_index, i) for pc in form_hidden
                  for i in range(len(pc.text))}
            self.assertTrue(fv.isdisjoint(fh))

    def test_lnt06_positions_of_visible_and_hidden_never_intersect(self):
        # (i) the public trap: the SAME word shown visibly and hidden
        # must surface exactly once in the visible text (a string-based
        # comparison cannot tell the two positions apart)
        self.samples["same_word"] = (
            _show("SECRET alpha report.") + b" "
            + _show("SECRET beta memo.", mode=3, y=680))
        obs = self._observe("same_word")
        vis = visible_text(obs).text
        self.assertEqual(vis.count("SECRET"), 1)
        self.assertNotIn("SECRET beta memo.", vis)

        # (ii) the position invariant over every LN sample
        for name in ("tr3_page", "state_machine", "four_ops_hidden",
                     "form_inherited", "ocr_layer", "same_word"):
            with self.subTest(sample=name):
                self._position_invariants(name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
