"""Sieve Schema Contract v1 — the canonical zero-dependency mini-validator.

This module is the canonical implementation of the Sieve Schema Contract
v1: the small validation vocabulary shared by the Sieve tools for their
JSON gates (Lens control vocab, Lens geometry thresholds, Redact
``--from-lens`` catalog gate, Crowd JSON input adapter).  Redact keeps an
inline subset inside its single file; Crowd keeps its input adapter;
both are pinned to this contract through the conformance corpus
(replicated into each tool's tests with a sha256 pin).

Node grammar (JSON-representable; every node is a dict with ``type``):

    object node : {"type": "object", "keys": {field: spec, ...},
                   "cross"?: {"mutually_exclusive": [[k1, k2], ...]}}
    array node  : {"type": "array", "item_type"?: <type-name>}
                  or {"type": "array", "item_schema": <object node>}
    scalar node : {"type": "string"|"integer"|"number"|"boolean"|"null",
                   "enum"?: [...], "min"?: n, "max"?: n,
                   "min_len"?: n, "max_len"?: n}

A field spec is a node plus ``{"required"?: bool}``.  ``required``
defaults to True (fail closed): optionality is always declared
explicitly.  ``type`` is optional in a field spec (redact-aligned): a
type-less spec carries only ``enum``/``validator`` constraints —
everything else is authoring-rejected without a type.  ``validator``
accepts a Python callable on any node (named validators keep corpus
schemas JSON-representable).

Strictness rules (normative):

  - booleans are never integers/numbers (``isinstance(True, int)`` is a
    Python accident, not a contract)
  - ``integer`` accepts int only (1.0 fails); ``number`` accepts
    int/float; ``1e400`` parses to inf and fails any finite ``max``
  - no coercion anywhere: values are checked, never converted
  - enum membership is type-strict (True does not match enum [1])
  - min/max are inclusive and NaN-safe (comparisons against NaN fail
    closed)
  - min_len/max_len apply to strings and arrays (``len()``)
  - unknown keys in the validated data are rejected, not ignored
    (gatekeeper stance: a future producer must extend the contract
    explicitly)
  - unknown keys in a schema spec are rejected (fail-closed authoring)
  - violations fail fast, in schema-declaration order
  - error locations are RFC 6901 JSON Pointers (``/a/0/b``, ``~0`` and
    ``~1`` escaped); the root is reported as ``(root)``
  - recursion only follows ``keys`` and ``item_schema``, so validation
    depth is bounded by the schema depth, never by the input depth;
    array items are checked iteratively

JSON layer (:func:`load_strict_json`):

  - duplicate object keys, ``NaN``/``Infinity``/``-Infinity`` and a
    leading UTF-8 BOM are rejected; an optional ``max_bytes`` caps the
    input by byte length
  - violations raise :class:`StrictJSONError`, a
    ``json.JSONDecodeError`` subclass, so existing
    ``except (OSError, json.JSONDecodeError)`` fallback contracts keep
    working unchanged

Conformance corpus:

  ``tests/corpus/schema_contract_v1.json`` (in this repository) pins
  the contract with accept/reject cases.  Copies of that corpus live in
  the other Sieve tools' test suites, each pinned by sha256, and every
  tool runs the layers it implements.  Tool-level divergences are
  declared in the conformance matrix in docs/SCHEMA_CONTRACT_v1.md,
  never silent.

Message language is English (Lens house style).  Other tools keep
their own message language; the contract pins pointers and semantics,
not wording.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

__all__ = [
    "CONTRACT_VERSION",
    "SPEC_KEYS",
    "TYPE_NAMES",
    "SchemaError",
    "StrictJSONError",
    "load_strict_json",
    "validate",
]

CONTRACT_VERSION = "sieve-schema-contract-v1"

TYPE_NAMES = ("object", "array", "string", "integer", "number",
              "boolean", "null")

SPEC_KEYS = frozenset({
    "required", "type", "enum", "min", "max", "min_len", "max_len",
    "item_type", "item_schema", "keys", "cross", "validator",
})
_RANGE_TYPES = ("integer", "number")          # min/max apply here
_LENS_TYPES = ("string", "array")             # min_len/max_len apply here
_SCALAR_TYPES = ("string", "integer", "number", "boolean", "null")


class SchemaError(ValueError):
    """A Contract v1 violation.  ``.pointer`` is an RFC 6901 JSON Pointer."""

    def __init__(self, pointer: str, message: str):
        self.pointer = pointer
        where = pointer or "(root)"
        super().__init__(f"{where}: {message}")


class StrictJSONError(json.JSONDecodeError):
    """A JSON-layer violation (dup key / NaN / BOM / oversize).

    Subclasses :class:`json.JSONDecodeError` so callers whose house
    rule is "invalid JSON falls back / is refused" via
    ``except (OSError, json.JSONDecodeError)`` keep their behavior.
    """

    def __init__(self, message: str):
        super().__init__(message, "<strict-json>", 0)


# ----------------------------------------------------------------------
# JSON layer
# ----------------------------------------------------------------------

def _reject_constant(name: str) -> Any:
    raise StrictJSONError(
        f"non-standard JSON constant is not allowed: {name}")


def _pairs_without_duplicates(pairs):
    obj: Dict[str, Any] = {}
    for key, val in pairs:
        if key in obj:
            raise StrictJSONError(
                f"duplicate key in a JSON object: {key!r}")
        obj[key] = val
    return obj


def load_strict_json(text: str, max_bytes: Optional[int] = None) -> Any:
    """Parse JSON strictly (Contract v1 JSON layer).

    Rejects, all as :class:`StrictJSONError`: a leading UTF-8 BOM,
    input over ``max_bytes`` (byte length), duplicate object keys, and
    the ``NaN``/``Infinity``/``-Infinity`` constants.  Note that
    ``1e400`` (overflow to inf without an Infinity literal) is a value
    problem, not a JSON-layer problem — bound it with schema ``max``.
    """
    if text.startswith("\ufeff"):
        raise StrictJSONError("UTF-8 BOM is not allowed")
    if max_bytes is not None and len(text.encode("utf-8")) > max_bytes:
        raise StrictJSONError(f"input exceeds the {max_bytes}-byte cap")
    return json.loads(text, parse_constant=_reject_constant,
                      object_pairs_hook=_pairs_without_duplicates)


# ----------------------------------------------------------------------
# Schema layer
# ----------------------------------------------------------------------

def _type_ok(val: Any, type_name: str) -> bool:
    """Strict type check; booleans never pass as integer/number."""
    if type_name == "integer":
        return isinstance(val, int) and not isinstance(val, bool)
    if type_name == "number":
        return isinstance(val, (int, float)) and not isinstance(val, bool)
    if type_name == "string":
        return isinstance(val, str)
    if type_name == "boolean":
        return isinstance(val, bool)
    if type_name == "array":
        return isinstance(val, list)
    if type_name == "object":
        return isinstance(val, dict)
    return val is None  # "null"


def _child(pointer: str, token: Any) -> str:
    """Append one RFC 6901 reference token to a pointer."""
    return pointer + "/" + str(token).replace("~", "~0").replace("/", "~1")


def _check_spec(spec: Any, pointer: str) -> None:
    """Fail-closed schema authoring: unknown or contradictory spec keys."""
    if not isinstance(spec, dict):
        raise SchemaError(pointer, "invalid schema: spec must be an object")
    unknown = sorted(set(spec) - SPEC_KEYS)
    if unknown:
        raise SchemaError(
            pointer,
            f"invalid schema: unknown spec key(s): {', '.join(unknown)}")
    type_name = spec.get("type")
    if "type" in spec and type_name not in TYPE_NAMES:
        raise SchemaError(
            pointer,
            f"invalid schema: 'type' must be one of {list(TYPE_NAMES)}")
    for key in ("item_type", "item_schema"):
        if key in spec and type_name != "array":
            raise SchemaError(
                pointer, f"invalid schema: '{key}' requires type 'array'")
    if ("item_type" in spec) and ("item_schema" in spec):
        raise SchemaError(
            pointer,
            "invalid schema: 'item_type' and 'item_schema' are exclusive")
    for key in ("keys", "cross"):
        if key in spec and type_name != "object":
            raise SchemaError(
                pointer, f"invalid schema: '{key}' requires type 'object'")
    for key in ("min", "max"):
        if key in spec and type_name not in _RANGE_TYPES:
            raise SchemaError(
                pointer,
                f"invalid schema: '{key}' requires a numeric type")
        if key in spec:
            bound = spec[key]
            if isinstance(bound, bool) or not isinstance(bound, (int, float)):
                raise SchemaError(
                    pointer, f"invalid schema: '{key}' must be a number")
    for key in ("min_len", "max_len"):
        if key in spec and type_name not in _LENS_TYPES:
            raise SchemaError(
                pointer,
                f"invalid schema: '{key}' requires type 'string' or 'array'")
        if key in spec:
            bound = spec[key]
            if isinstance(bound, bool) or not isinstance(bound, int) or bound < 0:
                raise SchemaError(
                    pointer,
                    f"invalid schema: '{key}' must be a non-negative integer")
    if ("enum" in spec and type_name is not None
            and type_name not in _SCALAR_TYPES):
        raise SchemaError(
            pointer, "invalid schema: 'enum' requires a scalar type")
    validator = spec.get("validator")
    if validator is not None and not callable(validator):
        raise SchemaError(
            pointer, "invalid schema: 'validator' must be callable")
    if "cross" in spec:
        cross = spec["cross"]
        if (not isinstance(cross, dict)
                or set(cross) != {"mutually_exclusive"}):
            raise SchemaError(
                pointer,
                "invalid schema: 'cross' must be "
                "{'mutually_exclusive': [[...], ...]}")
        groups = cross["mutually_exclusive"]
        keys = spec.get("keys", {})
        if not isinstance(groups, list) or not groups:
            raise SchemaError(
                pointer,
                "invalid schema: 'mutually_exclusive' must be a non-empty "
                "list of groups")
        for group in groups:
            if (not isinstance(group, list) or len(group) < 2
                    or not all(isinstance(k, str) for k in group)):
                raise SchemaError(
                    pointer,
                    "invalid schema: each cross group must be a list of "
                    "two or more field names")
            for name in group:
                if name not in keys:
                    raise SchemaError(
                        pointer,
                        "invalid schema: cross group references undeclared "
                        f"field {name!r}")


def _check_length(schema: Dict[str, Any], data: Any,
                  pointer: str) -> None:
    """min_len/max_len checks, shared by the string and array branches."""
    min_len = schema.get("min_len")
    if min_len is not None and len(data) < min_len:
        raise SchemaError(
            pointer,
            f"shorter than min_len ({min_len}): length {len(data)}")
    max_len = schema.get("max_len")
    if max_len is not None and len(data) > max_len:
        raise SchemaError(
            pointer,
            f"longer than max_len ({max_len}): length {len(data)}")


def _run_validator(schema: Dict[str, Any], data: Any,
                   pointer: str) -> None:
    """Run a validator hook; any non-SchemaError failure is wrapped."""
    validator = schema.get("validator")
    if validator is None:
        return
    try:
        validator(data)
    except SchemaError:
        raise
    except Exception as exc:
        raise SchemaError(
            pointer, f"validator rejected the value: {exc}") from exc


def validate(data: Any, schema: Dict[str, Any], pointer: str = "") -> None:
    """Validate ``data`` against ``schema`` (Contract v1 schema layer).

    Raises :class:`SchemaError` at the first violation, in
    schema-declaration order.  Recursion follows only ``keys`` and
    ``item_schema`` (both schema-owned), so the recursion depth is
    bounded by the schema depth regardless of the input depth; array
    items are checked iteratively.
    """
    _check_spec(schema, pointer)
    type_name = schema.get("type")
    if type_name is None:
        # Type-less node (redact-aligned): only enum/validator apply —
        # min/max/min_len/max_len and keys/item_schema/cross are
        # authoring-rejected without a type.
        if "enum" in schema and not any(
                type(data) is type(e) and data == e
                for e in schema["enum"]):
            raise SchemaError(
                pointer,
                f"value not in the allowed enum: {data!r}")
        _run_validator(schema, data, pointer)
        return
    if type_name == "object":
        if not isinstance(data, dict):
            raise SchemaError(
                pointer, f"expected an object, got {type(data).__name__}")
        keys = schema.get("keys", {})
        extra = sorted(set(data) - set(keys))
        if extra:
            allowed = ", ".join(sorted(keys)) or "(none)"
            raise SchemaError(
                _child(pointer, extra[0]),
                f"unknown key is not allowed: {extra[0]!r} "
                f"(allowed: {allowed})")
        for name, spec in keys.items():
            if name not in data:
                if spec.get("required", True):
                    raise SchemaError(
                        _child(pointer, name), "required field is missing")
                continue
            validate(data[name], spec, _child(pointer, name))
        cross = schema.get("cross")
        if cross:
            for group in cross["mutually_exclusive"]:
                present = sorted(k for k in group if k in data)
                if len(present) > 1:
                    raise SchemaError(
                        pointer,
                        "mutually exclusive keys are both present: "
                        + ", ".join(present))
        _run_validator(schema, data, pointer)
        return
    if type_name == "array":
        if not isinstance(data, list):
            raise SchemaError(
                pointer, f"expected an array, got {type(data).__name__}")
        item_type = schema.get("item_type")
        item_schema = schema.get("item_schema")
        for idx, item in enumerate(data):
            if item_type is not None and not _type_ok(item, item_type):
                raise SchemaError(
                    _child(pointer, idx),
                    f"item type mismatch (expected {item_type}, "
                    f"got {type(item).__name__})")
            if item_schema is not None:
                validate(item, item_schema, _child(pointer, idx))
        _check_length(schema, data, pointer)
        _run_validator(schema, data, pointer)
        return
    # Scalar node.
    if not _type_ok(data, type_name):
        raise SchemaError(
            pointer,
            f"type mismatch (expected {type_name}, "
            f"got {type(data).__name__})")
    if "enum" in schema and not any(
            type(data) is type(e) and data == e for e in schema["enum"]):
        raise SchemaError(
            pointer,
            f"value not in the allowed enum: {data!r}")
    low = schema.get("min")
    if low is not None and not (low <= data):
        raise SchemaError(
            pointer, f"value below the minimum ({low}): {data!r}")
    high = schema.get("max")
    if high is not None and not (data <= high):
        raise SchemaError(
            pointer, f"value above the maximum ({high}): {data!r}")
    _check_length(schema, data, pointer)
    _run_validator(schema, data, pointer)
