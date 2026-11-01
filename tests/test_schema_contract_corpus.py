"""Sieve Schema Contract v1 conformance corpus — canonical runner (Lens).

Runs every case in tests/corpus/schema_contract_v1.json against the
canonical engine in sieve_lens_ext.schema.  The corpus file is the
canonical copy: replicas ship in the other Sieve tools' test suites
(Redact: JSON layer; Crowd: JSON core) and are pinned to the sha256
below, so silent drift between the copies fails the drifting build and
a human reviews the diff (intentional contract bump vs missed sync).

Refresh the pin ONLY when the contract corpus is intentionally
versioned forward (contract or corpus_version change), and update the
replicas in the same cycle.
"""

import hashlib
import json
import time
import unittest
from pathlib import Path

from sieve_lens_ext.schema import (
    CONTRACT_VERSION,
    SchemaError,
    StrictJSONError,
    load_strict_json,
    validate,
)

CORPUS = Path(__file__).resolve().parent / "corpus" / "schema_contract_v1.json"
CORPUS_SHA256 = "514d45eb2580a9ea5a4336094be347d9c9bd8fb2990044551aec96cd094ae6aa"


def _load_corpus():
    return json.loads(CORPUS.read_text(encoding="utf-8"))


class CorpusIntegrity(unittest.TestCase):
    def test_corpus_file_matches_pin(self):
        actual = hashlib.sha256(
            CORPUS.read_bytes()).hexdigest()
        self.assertEqual(actual, CORPUS_SHA256,
                         "the conformance corpus drifted from its pin; "
                         "refresh the pin and the replicas together")

    def test_corpus_declares_the_current_contract(self):
        corpus = _load_corpus()
        self.assertEqual(corpus["contract"], CONTRACT_VERSION)
        self.assertEqual(corpus["corpus_version"], "1")
        ids = [case["id"] for case in corpus["cases"]]
        self.assertEqual(len(ids), len(set(ids)), "duplicate case ids")


class JsonLayerCorpus(unittest.TestCase):
    """JSON-layer cases run against load_strict_json."""

    def test_json_layer_cases(self):
        corpus = _load_corpus()
        for case in corpus["cases"]:
            if case["layer"] != "json":
                continue
            with self.subTest(case=case["id"]):
                if case["expect"] == "accept":
                    value = load_strict_json(case["input_text"])
                    self.assertIsNotNone(value)
                else:
                    self.assertTrue(case.get("violations"),
                                    "reject cases must declare violations")
                    with self.assertRaises(StrictJSONError):
                        load_strict_json(case["input_text"])

    def test_strict_json_error_is_a_json_decode_error(self):
        # The fallback contract of the vocab/thresholds loaders relies
        # on StrictJSONError being catchable as json.JSONDecodeError.
        self.assertTrue(issubclass(StrictJSONError, json.JSONDecodeError))


class SchemaLayerCorpus(unittest.TestCase):
    """Schema-layer cases run against validate() with pointer pins."""

    def test_schema_layer_cases(self):
        corpus = _load_corpus()
        for case in corpus["cases"]:
            if case["layer"] != "schema":
                continue
            with self.subTest(case=case["id"]):
                data = (json.loads(case["input_text"])
                        if "input_text" in case else case["input"])
                if case["expect"] == "accept":
                    validate(data, case["schema"])
                else:
                    with self.assertRaises(SchemaError) as ctx:
                        validate(data, case["schema"])
                    if "error_pointer" in case:
                        self.assertEqual(ctx.exception.pointer,
                                         case["error_pointer"])


class EnginePins(unittest.TestCase):
    """Engine properties that are measured, not corpus-transportable."""

    def test_recursion_depth_is_bounded_by_schema_depth(self):
        # 50,000-deep input against a schema 3 nodes deep: the unknown
        # key is refused near the root and no RecursionError can happen,
        # because recursion follows the schema, never the input.
        data = 1
        for _ in range(50_000):
            data = {"a": data}
        schema = {"type": "object", "keys": {
            "a": {"type": "object", "keys": {
                "a": {"type": "object", "keys": {
                    "a": {"type": "string"}}}}}}}
        with self.assertRaises(SchemaError) as ctx:
            validate(data, schema)
        self.assertEqual(ctx.exception.pointer, "/a/a/a")

    def test_wide_arrays_are_checked_iteratively(self):
        # 100,000 items against a depth-1 schema: per-item checking is a
        # loop, not recursion, so a huge flat array cannot exhaust the
        # stack.
        schema = {"type": "array", "item_type": "integer"}
        t0 = time.perf_counter()
        validate([0] * 100_000, schema)
        self.assertLess(time.perf_counter() - t0, 5.0)

    def test_nan_fails_closed_on_range_checks(self):
        # NaN cannot arrive through the strict JSON layer, but a caller
        # may hand-build a dict; the range comparison must refuse it.
        schema = {"type": "object", "keys": {
            "v": {"type": "number", "min": 0.0, "max": 1.0}}}
        with self.assertRaises(SchemaError):
            validate({"v": float("nan")}, schema)
        with self.assertRaises(SchemaError):
            validate({"v": float("inf")}, schema)

    def test_validator_hook_runs_after_structural_checks(self):
        schema = {"type": "object", "keys": {
            "kinds": {"type": "array", "item_type": "string",
                      "validator": lambda v: (_ for _ in ()).throw(
                          ValueError("empty kind"))
                      if any(not k for k in v) else None}}}
        validate({"kinds": ["a", "b"]}, schema)
        with self.assertRaises(SchemaError) as ctx:
            validate({"kinds": ["a", ""]}, schema)
        self.assertEqual(ctx.exception.pointer, "/kinds")

    def test_non_callable_validator_is_authoring_error(self):
        with self.assertRaises(SchemaError):
            validate({}, {"type": "object", "keys": {},
                          "validator": "nope"})

    def test_type_less_spec_carries_only_enum_and_validator(self):
        schema = {"type": "object", "keys": {"v": {"enum": [1, "x"]}}}
        validate({"v": 1}, schema)
        validate({"v": "x"}, schema)
        with self.assertRaises(SchemaError):
            validate({"v": True}, schema)
        with self.assertRaises(SchemaError):
            validate({}, {"type": "object",
                          "keys": {"v": {"min": 0}}})


if __name__ == "__main__":
    unittest.main()
