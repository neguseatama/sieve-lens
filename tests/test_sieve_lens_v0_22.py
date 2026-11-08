"""v0.22.0: the visible_text API and the character-code policy (LN-T01..T09).

M1 implementation request (Tray 2.0 "Gate"), sections §3.7 (design) and
§5.1 (test ids). red-first: this commit precedes the feature commit, so
public names are read through getattr and pinned by T01/T09 (a None
keeps the module red, not uncollectable).

- LN-T01 visible_text: visible segments only, in order, joined by "\n";
  empty segments dropped; no re-extraction (result == the join of the
  observation's visible segments).
- LN-T02 hidden text (w:vanish, display:none) never reaches
  visible_text; revision deletions, comments, metadata, alt text stay
  out; header/footer body text stays in (it observes visible=True by
  the pre-existing design, measured on v0.21.2).
- LN-T03 strip kinds: the 5 closed names, counts per kind; ZWJ, ZWNJ
  and variation selectors are preserved; tag chars right after
  U+1F3F4 are preserved as part of the flag sequence; unknown kinds
  are refused.
- LN-T04 golden: accepted UTF-8 inputs observe exactly as v0.21.2
  (mask, v0_mask, h_states, evidence, diagnostics minus version,
  segments) — canonical-JSON sha256 pins measured on v0.21.2.
- LN-T05 encoding corpus equals the Crowd 0.9.0 reference
  (sieve_crowd/tabular.py decode_csv auto; expected values measured on
  the Crowd 0.9.0 implementation 2026-11-08): BOM UTF-8 -> strict
  UTF-8 -> strict CP932 -> unsupported_encoding; UTF-16/32 BOMs
  refused; errors="replace" never used. A CP932 detection adds
  encoding_name to diagnostics.
- LN-T06 UTF-8 inputs add nothing to diagnostics (same 5 keys, same
  order); the refusal set stays the closed 13; UTF-16/32 BOMs are
  refused as unsupported_encoding.
- LN-T07 the 102 twins in chartable_v1.json are identical to
  redact_bridge.HOMOGLYPH_TWINS with the key type excluded (already
  true on 0.21.2; the test pins it).
- LN-T08 frozen files keep their bytes (schema, control_syntax,
  geometry, redact_bridge), the vocabulary/threshold pins hold, the
  chartable pin holds and the Schema Contract v1 corpus keeps its 44
  cases and digest.
- LN-T09 version 0.22.0 consistency across pyproject, CHANGELOG and
  both READMEs.
"""

import hashlib
import io
import json
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import sieve_lens  # noqa: E402
from sieve_lens import (  # noqa: E402
    REFUSAL_CODES,
    SieveLensEngine,
    __version__,
)

# Tolerant at the red boundary: the public names are read through
# getattr and pinned by T01 (None != callable keeps the module red,
# not uncollectable).
visible_text = getattr(sieve_lens, "visible_text", None)
VisibleText = getattr(sieve_lens, "VisibleText", None)

REPO_ROOT = Path(__file__).resolve().parent.parent

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# ---------------------------------------------------------------
# LN-T08 pins. The frozen-file and the corpus digests are the sha256
# of the file bytes (measured 2026-11-08); the loader-level pins with
# the same intent live in tests/test_sieve_lens_l2_docx.py.
# ---------------------------------------------------------------
_VOCAB_FILE_SHA256 = (
    "23f7de65990ebdaba4b3085f6821a2fa862a57213d03a3eb3684291a8ffcadd2")
_THRESHOLDS_FILE_SHA256 = (
    "a2881f88b02f64ea7f924e1bc9d39e25a2fd562ac0640b07fd8fdd5b69f16564")
_CORPUS_SHA256 = (
    "514d45eb2580a9ea5a4336094be347d9c9bd8fb2990044551aec96cd094ae6aa")
_SCHEMA_PY_SHA256 = (
    "03e242234d252e2790cfdd1fe8b07dcea2ec5f710b142da7e5743c8daef94c90")
_CONTROL_SYNTAX_PY_SHA256 = (
    "e9bfa1e805624c568da3ecd2c87adf2f2563344cde8c187302dd47fa60394981")
_GEOMETRY_PY_SHA256 = (
    "7599396c9f266c3a8f4f821f6cdd4fa9be73f0ccf9c647712776adf7aa84ae2c")
_REDACT_BRIDGE_PY_SHA256 = (
    "481035051208747d61db736c8509beb48ad1dbc34c81e8a4810909b68f71e29a")

# LN-T04 golden canonical-JSON sha256 pins, measured on v0.21.2
# (2026-11-08). "version" is excluded from diagnostics so the pin
# survives the version bump of this release; UTF-8 inputs must not add
# any other diagnostic key (LN-T06 covers the key list).
_GOLDEN_0212_SHA256 = {
    "txt": "ed20e0abac1d21f57a220fb5981a5e56732943aad94a3909badaccd0d88d71a2",
    "html": "a0387026df86cdc32d4801b92a75d0b29b70ff59b22cc1c0dbd77835a8bd84dd",
    "docx": "80c2258705ec85081914bafb46cfbfd2bd13f96e384ed1f45292f5d41d8ab15a",
}

_DIAGNOSTIC_KEYS_V0212 = ["zero_width_density", "zero_width_threshold",
                          "payload_min_length", "oob_min_length", "version"]

_STRIP_KINDS_ALL = frozenset({"zero_width_space", "word_joiner",
                              "bom_mid_text", "bidi_control", "tag_chars"})

# ---------------------------------------------------------------
# LN-T05 encoding corpus — expected values measured on the Crowd 0.9.0
# reference (sieve_crowd/tabular.py decode_csv auto), 2026-11-08.
# ---------------------------------------------------------------
_C_UTF8_PLAIN = "Hello plain text\nsecond line"
_C_UTF8_BOM = b"\xef\xbb\xbfHello plain text\nsecond"
_C_UTF8_JA = "こんにちは本文です"
_C_CP932_JA = "メールの本文です"
_C_CP932_MIXED_BYTES = b"abc \xff\x80 def"   # cp932-valid on the Crowd reference
_C_CP932_MIXED_TEXT = "abc \uf8f3\x80 def"
_C_INVALID_BOTH = b"\x81\x7f"                # invalid as UTF-8 and as CP932
_C_UTF16LE_BOM = b"\xff\xfe" + "plain".encode("utf-16-le")
_C_UTF16BE_BOM = b"\xfe\xff" + "plain".encode("utf-16-be")
_C_UTF32LE_BOM = b"\xff\xfe\x00\x00" + b"plain"
_C_UTF32BE_BOM = b"\x00\x00\xfe\xff" + b"plain"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _para(text: str, rpr: str = "") -> str:
    rpr_xml = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
    return f"<w:p><w:r>{rpr_xml}<w:t>{_esc(text)}</w:t></w:r></w:p>"


def _decl(inner: str, root: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<{root} xmlns:w="{_W_NS}">{inner}</{root}>')


def _body_doc(body: str) -> str:
    return _decl(f"<w:body>{body}</w:body>", "w:document")


_STYLES_BENIGN = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    f'<w:styles xmlns:w="{_W_NS}">'
    '<w:docDefaults><w:rPrDefault><w:rPr><w:sz w:val="22"/></w:rPr>'
    '</w:rPrDefault></w:docDefaults>'
    '<w:style w:type="paragraph" w:styleId="Normal">'
    '<w:name w:val="Normal"/></w:style></w:styles>')


def _canonical(obs) -> str:
    """Canonical JSON of an observation with diagnostics.version removed."""
    diag = dict(obs.diagnostics)
    diag.pop("version", None)
    payload = {
        "mask": obs.mask,
        "v0_mask": obs.v0_mask,
        "h_states": obs.h_states,
        "evidence": obs.evidence,
        "diagnostics": diag,
        "segments": [(s.text, s.visible, s.kind, s.location)
                     for s in obs.segments],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


class Lens022Base(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.engine = SieveLensEngine()

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, name, content):
        p = self.tmp / name
        p.write_text(content, encoding="utf-8")
        return p

    def _write_bytes(self, name, data):
        p = self.tmp / name
        p.write_bytes(data)
        return p

    def _make_docx(self, name, body="", header=None, footer=None,
                   footnote=None, comment=None, subject=None):
        p = self.tmp / name
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("word/document.xml", _body_doc(body))
            zf.writestr("word/styles.xml", _STYLES_BENIGN)
            if header is not None:
                zf.writestr("word/header1.xml",
                            _decl(_para(header), "w:hdr"))
            if footer is not None:
                zf.writestr("word/footer1.xml",
                            _decl(_para(footer), "w:ftr"))
            if footnote is not None:
                inner = ('<w:footnote w:type="separator" w:id="-1">'
                         + _para("sep") + "</w:footnote>"
                         + f'<w:footnote w:id="1">{_para(footnote)}'
                           "</w:footnote>")
                zf.writestr("word/footnotes.xml",
                            _decl(inner, "w:footnotes"))
            if comment is not None:
                inner = f'<w:comment w:id="1">{_para(comment)}</w:comment>'
                zf.writestr("word/comments.xml",
                            _decl(inner, "w:comments"))
            if subject is not None:
                zf.writestr(
                    "docProps/core.xml",
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<cp:coreProperties xmlns:cp="http://schemas.'
                    'openxmlformats.org/package/2006/metadata/'
                    'core-properties" xmlns:dc="http://purl.org/dc/'
                    f'elements/1.1/"><dc:subject>{_esc(subject)}'
                    "</dc:subject></cp:coreProperties>")
        return p


# ----------------------------------------------------------------------
# LN-T01 — visible_text basics
# ----------------------------------------------------------------------

class TestLNT01VisibleTextBasics(Lens022Base):
    def test_public_names_exist(self):
        self.assertIsNotNone(visible_text)
        self.assertIsNotNone(VisibleText)

    def test_txt_observation_returns_full_text(self):
        p = self._write("a.txt", "First visible line\nSecond visible line")
        obs = self.engine.observe(p)
        vt = visible_text(obs)
        self.assertEqual(vt.text, "First visible line\nSecond visible line")
        self.assertEqual(vt.removed, {})

    def test_segments_input_joined_in_order(self):
        from sieve_lens import Segment
        segs = [Segment("A", True, "body"),
                Segment("hidden text here", False, "css_hidden"),
                Segment("B", True, "body")]
        vt = visible_text(segs)
        self.assertEqual(vt.text, "A\nB")

    def test_empty_segments_dropped(self):
        from sieve_lens import Segment
        vt = visible_text([Segment("", True, "body"),
                           Segment("A", True, "body"),
                           Segment("   ", True, "body")])
        self.assertEqual(vt.text, "A")
        self.assertEqual(visible_text([Segment("", True, "body")]).text, "")

    def test_observation_and_segments_agree(self):
        p = self._write("a.txt", "line one\nline two\nline three")
        obs = self.engine.observe(p)
        self.assertEqual(visible_text(obs).text,
                         visible_text(obs.segments).text)

    def test_no_reextraction_docx(self):
        body = (_para("normal visible run")
                + _para("hidden secret phrase", "<w:vanish/>"))
        p = self._make_docx("d.docx", body=body)
        obs = self.engine.observe(p)
        vt = visible_text(obs)
        joined = "\n".join(s.text for s in obs.segments
                           if s.visible and s.text.strip())
        self.assertEqual(vt.text, joined)
        self.assertNotIn("hidden secret phrase", vt.text)


# ----------------------------------------------------------------------
# LN-T02 — hidden channels never reach visible_text
# ----------------------------------------------------------------------

class TestLNT02HiddenNotInVisibleText(Lens022Base):
    def test_docx_hidden_channels_absent(self):
        body = (_para("normal visible run")
                + _para("vanished secret phrase", "<w:vanish/>")
                + '<w:p><w:del w:id="1" w:author="a" '
                  'w:date="2026-01-01T00:00:00Z"><w:r>'
                  '<w:delText>deleted tracked text</w:delText></w:r>'
                  "</w:del></w:p>")
        p = self._make_docx("d.docx", body=body,
                            footnote="footnote text long enough here",
                            comment="comment text long enough",
                            subject="subject prop value ten")
        obs = self.engine.observe(p)
        vt = visible_text(obs)
        for hidden in ("vanished secret phrase", "deleted tracked text",
                       "footnote text long enough here",
                       "comment text long enough",
                       "subject prop value ten"):
            self.assertNotIn(hidden, vt.text, hidden)
        self.assertIn("normal visible run", vt.text)

    def test_html_hidden_channels_absent(self):
        p = self._write("b.html",
                        "<html><body>"
                        "<p>visible paragraph</p>"
                        '<div style="display:none">secret div text</div>'
                        "<!--a long comment ten chars-->"
                        '<img src="x.png" alt="this is a long alt text here">'
                        "</body></html>")
        obs = self.engine.observe(p)
        vt = visible_text(obs)
        for hidden in ("secret div text", "a long comment ten chars",
                       "this is a long alt text"):
            self.assertNotIn(hidden, vt.text, hidden)
        self.assertIn("visible paragraph", vt.text)

    def test_header_footer_body_stays_in(self):
        p = self._make_docx("d.docx", body=_para("normal visible run"),
                            header="header text long enough",
                            footer="footer text long enough")
        obs = self.engine.observe(p)
        vt = visible_text(obs)
        self.assertIn("header text long enough", vt.text)
        self.assertIn("footer text long enough", vt.text)


# ----------------------------------------------------------------------
# LN-T03 — strip kinds
# ----------------------------------------------------------------------

class TestLNT03StripKinds(Lens022Base):
    def _segs(self, text):
        from sieve_lens import Segment
        return [Segment(text, True, "body")]

    def test_each_kind_counted_once(self):
        text = ("A\u200bB\u2060C\ufeffD\u202aE\u2066F\U000e0001G")
        vt = visible_text(self._segs(text), strip=_STRIP_KINDS_ALL)
        self.assertEqual(vt.text, "ABCDEFG")
        self.assertEqual(vt.removed, {
            "zero_width_space": 1, "word_joiner": 1, "bom_mid_text": 1,
            "bidi_control": 2, "tag_chars": 1})

    def test_same_kind_totals(self):
        vt = visible_text(self._segs("a\u200bb\u200bc"),
                          strip=frozenset({"zero_width_space"}))
        self.assertEqual(vt.text, "abc")
        self.assertEqual(vt.removed, {"zero_width_space": 2})

    def test_default_strip_is_faithful(self):
        text = "A\u200bB\u2060C\ufeffD\u202aE\U000e0001F"
        vt = visible_text(self._segs(text))
        self.assertEqual(vt.text, text)
        self.assertEqual(vt.removed, {})

    def test_preserved_kinds_survive(self):
        text = "A\u200dB\u200cC\ufe0fD\U000e0100E"
        vt = visible_text(self._segs(text), strip=_STRIP_KINDS_ALL)
        self.assertEqual(vt.text, text)
        self.assertEqual(vt.removed, {})

    def test_tag_chars_after_1f3f4_preserved(self):
        flag = ("\U0001F3F4"
                "\U000E0067\U000E0062\U000E0065\U000E006E"
                "\U000E0067\U000E007F")
        text = "X" + flag + "Y\U000e0001Z"
        vt = visible_text(self._segs(text),
                          strip=frozenset({"tag_chars"}))
        self.assertEqual(vt.text, "X" + flag + "YZ")
        self.assertEqual(vt.removed, {"tag_chars": 1})

    def test_unknown_kinds_refused(self):
        for bad in (frozenset({"zwj"}), frozenset({"variation_selector"}),
                    frozenset({"bogus"}), frozenset({""})):
            with self.assertRaises(ValueError):
                visible_text(self._segs("x"), strip=bad)


# ----------------------------------------------------------------------
# LN-T04 — golden: accepted UTF-8 inputs observe as v0.21.2
# ----------------------------------------------------------------------

class TestLNT04Golden0212(Lens022Base):
    def _golden(self, name, path):
        obs = self.engine.observe(path)
        got = hashlib.sha256(_canonical(obs).encode("utf-8")).hexdigest()
        self.assertEqual(
            got, _GOLDEN_0212_SHA256[name],
            f"{name} observation drift from v0.21.2 (mask {obs.mask})")

    def test_txt_golden(self):
        p = self._write("a.txt", "Hello plain text\nsecond line")
        self._golden("txt", p)

    def test_html_golden(self):
        p = self._write(
            "b.html",
            '<html><head><title>Doc title here</title></head><body>'
            '<p>visible paragraph</p>'
            '<div style="display:none">secret div text</div>'
            '<!--a long comment ten chars-->'
            '<img src="x.png" alt="this is a long alt text here">'
            '<span aria-hidden="true">aria hidden long text</span>'
            "</body></html>")
        self._golden("html", p)

    def test_docx_golden(self):
        body = (_para("normal visible run")
                + _para("vanished run here", "<w:vanish/>")
                + _para("tiny run here", '<w:sz w:val="2"/>')
                + _para("low contrast run", '<w:color w:val="FEFEFE"/>')
                + '<w:p><w:del w:id="1" w:author="a" '
                  'w:date="2026-01-01T00:00:00Z"><w:r>'
                  '<w:delText>deleted tracked text</w:delText></w:r>'
                  "</w:del></w:p>")
        p = self._make_docx("d.docx", body=body)
        self._golden("docx", p)


# ----------------------------------------------------------------------
# LN-T05 — the character-code corpus equals the Crowd 0.9.0 reference
# ----------------------------------------------------------------------

class TestLNT05EncodingCorpus(Lens022Base):
    def test_utf8_plain(self):
        p = self._write_bytes("a.txt", _C_UTF8_PLAIN.encode("utf-8"))
        obs = self.engine.observe(p)
        self.assertEqual(obs.mask, "1000-000")
        self.assertEqual(obs.segments[0].text, _C_UTF8_PLAIN)
        self.assertNotIn("encoding_name", obs.diagnostics)

    def test_utf8_bom(self):
        p = self._write_bytes("b.txt", _C_UTF8_BOM)
        obs = self.engine.observe(p)
        self.assertEqual(obs.mask, "1000-000")
        self.assertEqual(obs.segments[0].text,
                         _C_UTF8_BOM.decode("utf-8-sig"))
        self.assertNotIn("encoding_name", obs.diagnostics)

    def test_utf8_japanese(self):
        p = self._write_bytes("c.txt", _C_UTF8_JA.encode("utf-8"))
        obs = self.engine.observe(p)
        self.assertEqual(obs.segments[0].text, _C_UTF8_JA)
        self.assertNotIn("encoding_name", obs.diagnostics)

    def test_cp932_japanese(self):
        p = self._write_bytes("d.txt", _C_CP932_JA.encode("cp932"))
        obs = self.engine.observe(p)
        self.assertEqual(obs.mask, "1000-000")
        self.assertEqual(obs.segments[0].text, _C_CP932_JA)
        self.assertEqual(obs.diagnostics.get("encoding_name"), "cp932")

    def test_cp932_mixed_bytes_like_crowd(self):
        p = self._write_bytes("e.txt", _C_CP932_MIXED_BYTES)
        obs = self.engine.observe(p)
        self.assertEqual(obs.mask, "1000-000")
        self.assertEqual(obs.segments[0].text, _C_CP932_MIXED_TEXT)
        self.assertEqual(obs.diagnostics.get("encoding_name"), "cp932")

    def test_html_cp932(self):
        body = "<html><body><p>メールの本文です</p></body></html>"
        p = self._write_bytes("f.html", body.encode("cp932"))
        obs = self.engine.observe(p)
        self.assertEqual(obs.segments[0].text, "メールの本文です")
        self.assertEqual(obs.diagnostics.get("encoding_name"), "cp932")

    def test_invalid_both_refused(self):
        p = self._write_bytes("g.txt", _C_INVALID_BOTH)
        obs = self.engine.observe(p)
        self.assertEqual(obs.mask, "0000-000")
        self.assertEqual(obs.evidence["H1"],
                         ["Extraction refused: unsupported_encoding"])

    def test_utf16_boms_refused(self):
        for name, data in (("u16le.txt", _C_UTF16LE_BOM),
                           ("u16be.txt", _C_UTF16BE_BOM)):
            p = self._write_bytes(name, data)
            obs = self.engine.observe(p)
            with self.subTest(name=name):
                self.assertEqual(obs.mask, "0000-000")
                self.assertEqual(obs.evidence["H1"],
                                 ["Extraction refused: unsupported_encoding"])

    def test_utf32_boms_refused(self):
        for name, data in (("u32le.txt", _C_UTF32LE_BOM),
                           ("u32be.txt", _C_UTF32BE_BOM)):
            p = self._write_bytes(name, data)
            obs = self.engine.observe(p)
            with self.subTest(name=name):
                self.assertEqual(obs.mask, "0000-000")
                self.assertEqual(obs.evidence["H1"],
                                 ["Extraction refused: unsupported_encoding"])


# ----------------------------------------------------------------------
# LN-T06 — UTF-8 adds nothing; the refusal set stays closed
# ----------------------------------------------------------------------

class TestLNT06NoExtraDiagnostics(Lens022Base):
    def test_utf8_diagnostics_keys_unchanged(self):
        for name, data in (("a.txt", _C_UTF8_PLAIN.encode("utf-8")),
                           ("b.txt", _C_UTF8_BOM),
                           ("c.txt", _C_UTF8_JA.encode("utf-8"))):
            p = self._write_bytes(name, data)
            obs = self.engine.observe(p)
            with self.subTest(name=name):
                self.assertEqual(list(obs.diagnostics.keys()),
                                 _DIAGNOSTIC_KEYS_V0212)

    def test_refusal_codes_still_13(self):
        self.assertEqual(REFUSAL_CODES, frozenset({
            "not_regular_file", "file_too_large", "too_many_entries",
            "part_too_large", "total_too_large", "too_many_elements",
            "doctype_not_allowed", "unsupported_encoding",
            "duplicate_part", "encrypted", "malformed_xml",
            "main_part_missing", "unsupported_namespace"}))

    def test_utf16_32_boms_report_unsupported_encoding(self):
        for name, data in (("u16le.txt", _C_UTF16LE_BOM),
                           ("u16be.txt", _C_UTF16BE_BOM),
                           ("u32le.txt", _C_UTF32LE_BOM),
                           ("u32be.txt", _C_UTF32BE_BOM)):
            p = self._write_bytes(name, data)
            obs = self.engine.observe(p)
            with self.subTest(name=name):
                self.assertEqual(obs.h_states["H1"], 0)
                self.assertEqual(
                    obs.evidence["H1"],
                    ["Extraction refused: unsupported_encoding"])


# ----------------------------------------------------------------------
# LN-T07 — twins aligned (already true; pinned here)
# ----------------------------------------------------------------------

class TestLNT07TwinsAligned(unittest.TestCase):
    def test_102_twins_identical_key_type_excluded(self):
        from sieve_lens_ext.chartable import load_chartable_v1
        from sieve_lens_ext.redact_bridge import HOMOGLYPH_TWINS
        table = load_chartable_v1()
        json_twins = {int(k, 16): v for k, v in table["twins"].items()}
        self.assertEqual(len(json_twins), 102)
        self.assertEqual(len(HOMOGLYPH_TWINS), 102)
        self.assertEqual(json_twins, HOMOGLYPH_TWINS)


# ----------------------------------------------------------------------
# LN-T08 — frozen files and pins unchanged
# ----------------------------------------------------------------------

class TestLNT08FrozenUnchanged(unittest.TestCase):
    REPO = REPO_ROOT

    def test_frozen_files_keep_their_bytes(self):
        for name, digest in (
                ("sieve_lens_ext/schema.py", _SCHEMA_PY_SHA256),
                ("sieve_lens_ext/control_syntax.py",
                 _CONTROL_SYNTAX_PY_SHA256),
                ("sieve_lens_ext/geometry.py", _GEOMETRY_PY_SHA256),
                ("sieve_lens_ext/redact_bridge.py",
                 _REDACT_BRIDGE_PY_SHA256),
                ("control_vocab_v1.json", _VOCAB_FILE_SHA256),
                ("geometry_thresholds_v2.json", _THRESHOLDS_FILE_SHA256),
                ("tests/corpus/schema_contract_v1.json", _CORPUS_SHA256)):
            data = (self.REPO / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest, name)

    def test_chartable_pin_holds(self):
        from sieve_lens_ext.chartable import CHARTABLE_V1_SHA256
        data = (self.REPO / "sieve_lens_ext/chartable_v1.json").read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         CHARTABLE_V1_SHA256)

    def test_schema_corpus_keeps_44_cases(self):
        corpus = json.loads(
            (self.REPO / "tests/corpus/schema_contract_v1.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(corpus["contract"], "sieve-schema-contract-v1")
        self.assertEqual(corpus["corpus_version"], "1")
        self.assertEqual(len(corpus["cases"]), 44)


# ----------------------------------------------------------------------
# LN-T09 — version 0.22.0 consistency
# ----------------------------------------------------------------------

class TestLNT09Version0220(unittest.TestCase):
    REPO = REPO_ROOT

    def test_version_is_0220_everywhere(self):
        self.assertEqual(__version__, "0.22.0")
        pyproject = (self.REPO / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('version = "0.22.0"', pyproject)
        changelog = (self.REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [0.22.0]", changelog)
        for name in ("README.md", "README.ja.md"):
            with self.subTest(readme=name):
                text = (self.REPO / name).read_text(encoding="utf-8")
                self.assertIn("# Sieve Lens v0.22.0", text)


if __name__ == "__main__":
    unittest.main()
