"""The pinned character table (chartable v1) for Sieve Lens.

``chartable_v1.json`` is the shared Sieve character table — the
standard copy: the invisible characters (zero width, bidi control,
tags, variation selectors), the look-alike twins, the fullwidth
ASCII range, the folding spaces and the folding dashes. The other
Sieve tools pin byte-exact copies of this file by sha256; changes
to the standard are made here, never by editing a copy.

The loader is fail-closed: the file is read lazily (never at import),
its sha256 is verified against the pin below on every load, and a
missing, tampered or malformed table is a hard ``ChartableError`` —
never a silent fallback. Every call returns a fresh dict, so callers
cannot corrupt each other's view through mutation. The observation
pipeline does not consume the table here yet; this module establishes
the pinned source of the standard inside Lens.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Dict, Tuple

CHARTABLE_V1_SHA256 = (
    "c5ae4757bc9d07a2dcd1507d662460c3412c932d73318e54912569608242e605")
SCHEMA_V1 = "sieve-chartable/1"
_TABLE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "chartable_v1.json")

_HEX = re.compile(r"[0-9A-Fa-f]{4,6}\Z")
_KINDS = ("bidi_control", "tag", "variation_selector", "zero_width")


class ChartableError(Exception):
    """The pinned character table is missing, tampered with, or malformed."""


def _cp(entry: Any) -> int:
    if not isinstance(entry, str) or not _HEX.fullmatch(entry):
        raise ChartableError(
            f"the pinned character table: bad code point {entry!r}")
    return int(entry, 16)


def _range(entry: Any) -> Tuple[int, int]:
    if (not isinstance(entry, (list, tuple)) or len(entry) != 2
            or not all(isinstance(x, str) for x in entry)):
        raise ChartableError(
            "the pinned character table: a range must be [lo, hi]")
    lo, hi = _cp(entry[0]), _cp(entry[1])
    if lo > hi:
        raise ChartableError(
            f"the pinned character table: reversed range {entry!r}")
    return lo, hi


def parse_chartable_v1(data: Any) -> Dict[str, Any]:
    """Validate one parsed table object and return it (pure)."""
    if not isinstance(data, dict):
        raise ChartableError(
            "the pinned character table: the top level must be an object")
    if data.get("schema") != SCHEMA_V1:
        raise ChartableError(
            f"the pinned character table: 'schema' must be {SCHEMA_V1!r}")
    version = data.get("version")
    if version != 1 or isinstance(version, bool):
        raise ChartableError(
            "the pinned character table: 'version' must be 1")
    if not isinstance(data.get("description"), str):
        raise ChartableError(
            "the pinned character table: 'description' must be a string")

    inv = data.get("invisible")
    if not isinstance(inv, dict) or sorted(inv) != list(_KINDS):
        raise ChartableError(
            "the pinned character table: 'invisible' must hold exactly "
            "the kinds " + ", ".join(_KINDS))
    for kind in _KINDS:
        entries = inv[kind]
        if not isinstance(entries, list) or not entries:
            raise ChartableError(
                f"the pinned character table: invisible.{kind} must be "
                "a non-empty list")
        for entry in entries:
            _range(entry) if isinstance(entry, list) else _cp(entry)

    twins = data.get("twins")
    if not isinstance(twins, dict) or not twins:
        raise ChartableError(
            "the pinned character table: 'twins' must be a non-empty object")
    for src, dst in twins.items():
        _cp(src)
        if not isinstance(dst, str) or len(dst) != 1 or not ord(dst) <= 0x7E:
            raise ChartableError(
                f"the pinned character table: twins.{src} must map to "
                "one ASCII character")

    fa = data.get("fullwidth_ascii")
    if not isinstance(fa, dict) or not {"base", "from", "to"} <= set(fa):
        raise ChartableError(
            "the pinned character table: 'fullwidth_ascii' must be an "
            "object with 'base', 'from' and 'to'")
    lo, hi = _range([fa["from"], fa["to"]])
    base = _cp(fa["base"])
    if base + (hi - lo) > 0x7E:
        raise ChartableError(
            "the pinned character table: fullwidth_ascii leaves the "
            "printable ASCII range")

    for key in ("spaces", "dashes"):
        items = data.get(key)
        if not isinstance(items, list):
            raise ChartableError(
                f"the pinned character table: {key!r} must be a list")
        for entry in items:
            _cp(entry)
    if len({int(s, 16) for s in data["dashes"]}) != len(data["dashes"]):
        raise ChartableError(
            "the pinned character table: duplicate dash entry")
    return data


def load_chartable_v1_bytes(raw: bytes) -> Dict[str, Any]:
    """Verify the sha256 pin on the exact bytes, parse, and validate."""
    digest = hashlib.sha256(raw).hexdigest()
    if digest != CHARTABLE_V1_SHA256:
        raise ChartableError(
            "the pinned character table is not the pinned one "
            f"(sha256 {digest}, expected {CHARTABLE_V1_SHA256})")
    try:
        data = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise ChartableError(
            "the pinned character table: not valid UTF-8") from None
    except json.JSONDecodeError as exc:
        raise ChartableError(
            f"the pinned character table: not valid JSON ({exc.msg})") \
            from None
    return parse_chartable_v1(data)


def load_chartable_v1() -> Dict[str, Any]:
    """Read, verify and validate the packaged table (fresh dict)."""
    try:
        with open(_TABLE_FILE, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise ChartableError(
            f"the pinned character table is missing ({exc.strerror})") \
            from None
    return load_chartable_v1_bytes(raw)
