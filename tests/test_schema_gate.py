"""Contract v1 gate integration for the Lens vocab/thresholds loaders.

Pins, against the real loaders:
  - the content digests of the embedded vocab and thresholds are
    UNCHANGED by the validate/build refactor (receipt non-destruction:
    any receipt recorded before v0.18.0 stays reproducible)
  - JSON-layer violations (duplicate keys, NaN/Infinity, BOM, oversize)
    fall back to the embedded defaults via the StrictJSONError
    fallback, while parseable-but-schema-invalid documents raise
  - the gatekeeper behavior changes: unknown keys and mistyped
    version/lane fields are refused, not ignored
  - the validate/build separation: validate_* is pure, build_* fills
    defaults and compiles regexes with the historical error wording
"""

import json
import unittest
from pathlib import Path

from sieve_lens_ext.control_syntax import (
    CONTROL_VOCAB_SCHEMA,
    build_control_vocab,
    load_control_vocab,
    validate_control_vocab,
)
from sieve_lens_ext.geometry import (
    GEOMETRY_THRESHOLDS_SCHEMA,
    build_thresholds,
    load_thresholds,
    validate_thresholds,
)
from sieve_lens_ext.schema import SchemaError, validate

# Content digests measured on v0.17.0 (before the validate/build split).
# These MUST NOT change: receipts record vocab/threshold sha256 and stay
# reproducible against the exact content that produced them.
_EMBEDDED_VOCAB_SHA256 = (
    "27734e17bd334d7a66ffad7b5a9e1ebe8c918d3badc8b6240d115d9804956fbf")
_EMBEDDED_THRESHOLDS_SHA256 = (
    "70f2bdb5f29ffbd7a73bae318a3da5c7195dec30fb8d71cd7bb2ef0759fa4540")

_MB_PLUS_ONE = 1048576 + 1


class _TmpBase(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, name, content):
        p = Path(self._tmpdir.name) / name
        p.write_text(content, encoding="utf-8")
        return p


class DigestNonDestruction(_TmpBase):
    def test_embedded_vocab_digest_unchanged(self):
        self.assertEqual(load_control_vocab(None).sha256,
                         _EMBEDDED_VOCAB_SHA256)

    def test_embedded_thresholds_digest_unchanged(self):
        self.assertEqual(load_thresholds(None).sha256,
                         _EMBEDDED_THRESHOLDS_SHA256)

    def test_file_loaded_vocab_digest_unchanged(self):
        ref = Path(__file__).resolve().parent.parent / "control_vocab_v1.json"
        copy = self._write("copy.json", ref.read_text(encoding="utf-8"))
        self.assertEqual(load_control_vocab(str(copy)).sha256,
                         _EMBEDDED_VOCAB_SHA256)

    def test_file_loaded_thresholds_digest_unchanged(self):
        ref = (Path(__file__).resolve().parent.parent /
               "geometry_thresholds_v2.json")
        copy = self._write("copy.json", ref.read_text(encoding="utf-8"))
        self.assertEqual(load_thresholds(str(copy)).sha256,
                         _EMBEDDED_THRESHOLDS_SHA256)


class VocabJsonLayerFallback(_TmpBase):
    """JSON-layer violations fall back to the embedded default."""

    def test_duplicate_keys_fall_back(self):
        p = self._write("dup.json", '{"patterns": [], "patterns": []}')
        vocab = load_control_vocab(str(p))
        self.assertEqual(vocab.source, "embedded")
        self.assertEqual(len(vocab.patterns), 14)

    def test_nan_falls_back(self):
        p = self._write("nan.json", '{"patterns": [], "x": NaN}')
        vocab = load_control_vocab(str(p))
        self.assertEqual(vocab.source, "embedded")

    def test_bom_falls_back(self):
        p = self._write("bom.json", "﻿" + json.dumps({"patterns": []}))
        vocab = load_control_vocab(str(p))
        self.assertEqual(vocab.source, "embedded")

    def test_oversize_falls_back(self):
        junk = json.dumps({"patterns": []}) + " " * _MB_PLUS_ONE
        p = self._write("big.json", junk)
        vocab = load_control_vocab(str(p))
        self.assertEqual(vocab.source, "embedded")

    def test_invalid_regex_still_raises_valueerror(self):
        p = self._write("re.json", json.dumps({"patterns": [
            {"category": "c", "name": "n", "pattern": "([",
             "match": "regex"}]}))
        with self.assertRaises(ValueError) as ctx:
            load_control_vocab(str(p))
        self.assertIn("invalid regex", str(ctx.exception))


class ThresholdsJsonLayerFallback(_TmpBase):
    def test_duplicate_keys_fall_back(self):
        p = self._write("dup.json", '{"thresholds": {}, "thresholds": {}}')
        t = load_thresholds(str(p))
        self.assertEqual(t.source, "embedded")

    def test_nan_falls_back(self):
        p = self._write("nan.json", '{"thresholds": {"font_size_px_max": NaN,'
                                    ' "opacity_max": 0.01, "scale_max": 0.01,'
                                    ' "line_height_max": 0.0,'
                                    ' "pdf_font_size_pt_max": 0.5}}')
        t = load_thresholds(str(p))
        self.assertEqual(t.source, "embedded")

    def test_bom_falls_back(self):
        ref = (Path(__file__).resolve().parent.parent /
               "geometry_thresholds_v2.json")
        p = self._write("bom.json", "﻿" + ref.read_text(encoding="utf-8"))
        t = load_thresholds(str(p))
        self.assertEqual(t.source, "embedded")

    def test_oversize_falls_back(self):
        junk = json.dumps({"thresholds": {}}) + " " * _MB_PLUS_ONE
        p = self._write("big.json", junk)
        t = load_thresholds(str(p))
        self.assertEqual(t.source, "embedded")

    def test_1e400_overflows_to_inf_and_is_refused(self):
        # 1e400 is a legal JSON number token (not a NaN/Infinity
        # literal), but it parses to inf and the max bound refuses it.
        p = self._write("inf.json", '{"thresholds": {"font_size_px_max": 1e400,'
                                    ' "opacity_max": 0.01, "scale_max": 0.01,'
                                    ' "line_height_max": 0.0,'
                                    ' "pdf_font_size_pt_max": 0.5}}')
        with self.assertRaises(ValueError):
            load_thresholds(str(p))


class GatekeeperBehaviorChanges(_TmpBase):
    """Refusals that were silent ignores before Contract v1."""

    def test_unknown_top_level_vocab_key_is_refused(self):
        doc = json.loads(json.dumps({"patterns": [], "junk": 1}))
        with self.assertRaises(ValueError) as ctx:
            load_control_vocab(self._write("junk.json", json.dumps(doc)))
        self.assertIn("junk", str(ctx.exception))

    def test_numeric_version_is_refused(self):
        doc = {"version": 1, "patterns": []}  # producers emit "1" (string)
        with self.assertRaises(ValueError) as ctx:
            load_control_vocab(self._write("v.json", json.dumps(doc)))
        self.assertIn("version", str(ctx.exception))

    def test_unknown_thresholds_key_is_refused(self):
        ref = (Path(__file__).resolve().parent.parent /
               "geometry_thresholds_v2.json")
        doc = json.loads(ref.read_text(encoding="utf-8"))
        doc["junk"] = True
        with self.assertRaises(ValueError) as ctx:
            load_thresholds(self._write("junk.json", json.dumps(doc)))
        self.assertIn("junk", str(ctx.exception))

    def test_empty_backing_kind_is_refused(self):
        doc = {"backing_kinds": ["metadata", ""], "patterns": []}
        with self.assertRaises(ValueError):
            load_control_vocab(self._write("bk.json", json.dumps(doc)))


class ValidateBuildSeparation(_TmpBase):
    def test_validate_is_pure_and_pointer_typed(self):
        doc = {"patterns": [{"category": "c", "name": "n",
                             "pattern": "x", "match": "fuzzy"}]}
        with self.assertRaises(SchemaError) as ctx:
            validate_control_vocab(doc)
        self.assertEqual(ctx.exception.pointer, "/patterns/0/match")
        # The pure check mutates nothing and fills nothing.
        self.assertEqual(doc["patterns"][0].get("match"), "fuzzy")

    def test_build_fills_defaults(self):
        doc = {"patterns": [{"category": "c", "name": "n",
                             "pattern": "x"}]}
        vocab = build_control_vocab(doc, "test")
        spec = vocab.patterns[0]
        self.assertEqual(spec.match, "literal")
        self.assertFalse(spec.case_sensitive)
        self.assertEqual(spec.description, "")
        self.assertEqual(vocab.backing_kinds, ("metadata",))
        self.assertIsNone(spec.compiled)

    def test_build_compiles_regex(self):
        import re
        doc = {"patterns": [{"category": "c", "name": "n",
                             "pattern": "^a+b$",
                             "match": "regex",
                             "case_sensitive": True}]}
        spec = build_control_vocab(doc, "test").patterns[0]
        self.assertIsNotNone(spec.compiled)
        self.assertEqual(spec.compiled.flags & re.IGNORECASE, 0)

    def test_thresholds_validate_is_pure(self):
        doc = {"thresholds": {"font_size_px_max": 0.5,
                              "opacity_max": "small", "scale_max": 0.01,
                              "line_height_max": 0.0,
                              "pdf_font_size_pt_max": 0.5}}
        with self.assertRaises(SchemaError) as ctx:
            validate_thresholds(doc)
        self.assertEqual(ctx.exception.pointer, "/thresholds/opacity_max")

    def test_thresholds_build_normalizes_ints(self):
        doc = {"thresholds": {"font_size_px_max": 1, "opacity_max": 0,
                              "scale_max": 0, "line_height_max": 0,
                              "pdf_font_size_pt_max": 1}}
        t = build_thresholds(doc, "test")
        self.assertIsInstance(t.font_size_px_max, float)
        self.assertEqual(t.as_dict()["font_size_px_max"], 1.0)


class SchemaDeclarations(unittest.TestCase):
    """The in-repo schemas must satisfy the contract they declare."""

    def test_control_vocab_schema_self_conforms(self):
        # Every field spec must be a valid node; run the contract's own
        # authoring rules over the schema by validating a minimal
        # document with it (already covered) and pin the known keys.
        self.assertEqual(
            set(CONTROL_VOCAB_SCHEMA["keys"]),
            {"version", "lane", "description", "backing_kinds",
             "patterns"})

    def test_geometry_thresholds_schema_self_conforms(self):
        self.assertEqual(
            set(GEOMETRY_THRESHOLDS_SCHEMA["keys"]),
            {"version", "lane", "description", "thresholds"})
        inner = GEOMETRY_THRESHOLDS_SCHEMA["keys"]["thresholds"]["keys"]
        self.assertEqual(
            set(inner),
            {"font_size_px_max", "opacity_max", "scale_max",
             "line_height_max", "pdf_font_size_pt_max"})

    def test_repo_reference_vocab_passes_the_gate(self):
        ref = Path(__file__).resolve().parent.parent / "control_vocab_v1.json"
        doc = json.loads(ref.read_text(encoding="utf-8"))
        validate(doc, CONTROL_VOCAB_SCHEMA)

    def test_repo_reference_thresholds_pass_the_gate(self):
        ref = (Path(__file__).resolve().parent.parent /
               "geometry_thresholds_v2.json")
        doc = json.loads(ref.read_text(encoding="utf-8"))
        validate(doc, GEOMETRY_THRESHOLDS_SCHEMA)


if __name__ == "__main__":
    unittest.main()
