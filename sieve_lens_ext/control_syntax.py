"""Sieve Lens control-syntax audit lane (AI prompt-boundary observation).

Observes the surface of documents for control-syntax patterns that imitate
LLM system prompts or chat-template special tokens (e.g. <|im_start|>,
[INST], "Ignore all previous instructions"). These patterns are frequent
surface signatures of indirect prompt injection in documents consumed by
LLM / RAG pipelines.

Sieve stance (enforced structurally):
  - The lane NEVER declares an attack or intent. It records facts only:
    which pattern was observed, where, and whether the document has a
    backing zone (declared system area) for it.
  - Backing (GREEN): the occurrence sits in a declared system area
    (default: kind "metadata", i.e. PDF Info dict / DOCX docProps).
    Backed occurrences are counted, not raised.
  - Unbacked (RED): the occurrence sits in a content stream (body, hidden
    text, comments, headers/footers, attributes, footnotes). These become
    receipt findings. Comments and headers/footers are deliberately NOT
    backing zones: they are attacker-writable channels.
  - Unknown segment kinds fail closed: they are scanned as content (no
    backing), so a future kind can never silently suppress findings.

Design principles (inherited from the Sieve series):
  - Deterministic : same input + same vocab -> same receipt, always.
  - Zero deps     : Python standard library only.
  - Explainable   : every finding reports pattern, category, location,
                    offset, and an excerpt.
  - Observation   : reports facts, not judgments.

Zone rule (deterministic, one line):
  an occurrence in a backing-kind segment is GREEN (counted, passed);
  an occurrence anywhere else is RED (receipt finding).

Vocabulary (house rules, mirrors the modifier-vocab convention):
  - Embedded default vocab (14 patterns, v1) is the runtime default.
  - An optional vocab file overrides it; a missing, unreadable, or
    invalid-JSON file falls back to the embedded default.
  - The receipt records control_vocab_sha256 and pattern_count, so any
    receipt stays reproducible against the exact vocab that produced it.
  - A repo-root reference copy ships as control_vocab_v1.json.

Vocab JSON shape:
    {"version": "1", "lane": "control_syntax",
     "backing_kinds": ["metadata"],          # optional, default as shown
     "patterns": [
       {"category": "special_tokens", "name": "openai_im_start",
        "pattern": "<|im_start|>",
        "match": "literal",                   # optional, default "literal"
        "case_sensitive": false,              # optional, default false
        "description": "..."}]}

Matching semantics:
  - "literal": plain substring scan (no regex metacharacter meaning).
    Case-insensitive unless case_sensitive is true (str.lower()).
  - "regex": re-scanned per pattern (re.IGNORECASE unless case_sensitive).
  - Matches are non-overlapping. Offsets are 0-based character offsets
    within the segment text; the segment location string (page, line,
    paragraph, ...) identifies the position in the document.

Usage:
    from sieve_lens import SieveLensEngine
    from sieve_lens_ext.pdf import install as install_pdf
    from sieve_lens_ext.control_syntax import audit_control_syntax

    engine = SieveLensEngine()
    install_pdf(engine)
    obs = engine.observe("resume.pdf")
    report = audit_control_syntax(obs)
    print(report_json(report))

CLI:
    python -m sieve_lens_ext.control_syntax IN OUT.json [VOCAB.json]
    Exit codes: 0 = receipt written / 1 = failure (usage, read, or
    unsupported input format).

Requires: nothing beyond the Python standard library (PDF inputs need
the optional sieve_lens_ext.pdf dependency, pypdf >= 4.0).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

LANE_NAME = "control_syntax"

# Segment kinds that constitute the content streams of a document
# (attacker-writable channels). Everything scanned outside backing zones
# is treated as content (fail-closed), including unknown kinds.
CONTENT_KINDS = frozenset({
    "body", "css_hidden", "hidden_attr", "header_footer", "footnote",
})

_DEFAULT_BACKING_KINDS = ["metadata"]

_DEFAULT_VOCAB_JSON = """{
  "version": "1",
  "lane": "control_syntax",
  "description": "Sieve Lens control-syntax audit vocabulary (default, v1)",
  "backing_kinds": ["metadata"],
  "patterns": [
    {
      "category": "special_tokens",
      "name": "openai_im_start",
      "pattern": "<|im_start|>",
      "description": "OpenAI chat template role start marker"
    },
    {
      "category": "special_tokens",
      "name": "openai_im_end",
      "pattern": "<|im_end|>",
      "description": "OpenAI chat template role end marker"
    },
    {
      "category": "special_tokens",
      "name": "llama_inst_start",
      "pattern": "[INST]",
      "description": "Llama chat template instruction start marker"
    },
    {
      "category": "special_tokens",
      "name": "llama_inst_end",
      "pattern": "[/INST]",
      "description": "Llama chat template instruction end marker"
    },
    {
      "category": "special_tokens",
      "name": "llama_sys",
      "pattern": "<<SYS>>",
      "description": "Llama 2 system prompt marker"
    },
    {
      "category": "override_phrases_en",
      "name": "ignore_previous",
      "pattern": "Ignore all previous instructions",
      "description": "Classic instruction reset phrase"
    },
    {
      "category": "override_phrases_en",
      "name": "disregard_above",
      "pattern": "Disregard the text above",
      "description": "Context override phrase"
    },
    {
      "category": "override_phrases_en",
      "name": "developer_mode",
      "pattern": "You are now in developer mode",
      "description": "Persona and mode hijacking phrase"
    },
    {
      "category": "override_phrases_jp",
      "name": "ignore_previous_jp",
      "pattern": "これまでの指示をすべて無視",
      "description": "Japanese instruction reset phrase"
    },
    {
      "category": "override_phrases_jp",
      "name": "priority_override_jp",
      "pattern": "ここからの指示が最優先",
      "description": "Japanese priority override phrase"
    },
    {
      "category": "structural_tags",
      "name": "system_instruction_tag",
      "pattern": "[SYSTEM INSTRUCTION]",
      "description": "Pseudo system command tag"
    },
    {
      "category": "structural_tags",
      "name": "override_tag",
      "pattern": "[OVERRIDE]",
      "description": "Pseudo override tag"
    },
    {
      "category": "structural_tags",
      "name": "markdown_instruction_header",
      "pattern": "### Instruction:",
      "description": "Markdown instruction block header"
    },
    {
      "category": "structural_tags",
      "name": "begin_system_override",
      "pattern": "--- BEGIN SYSTEM OVERRIDE ---",
      "description": "Pseudo system override fence"
    }
  ]
}
"""

_VALID_MATCH = ("literal", "regex")
_EXCERPT_WINDOW = 30


# ----------------------------------------------------------------------
# Vocabulary
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class PatternSpec:
    """One validated control-syntax pattern."""
    category: str
    name: str
    pattern: str
    match: str            # "literal" | "regex"
    case_sensitive: bool
    description: str
    compiled: Optional[object] = None   # compiled re for match == "regex"


@dataclass(frozen=True)
class ControlVocab:
    """A validated vocabulary plus its provenance."""
    patterns: Tuple[PatternSpec, ...]
    backing_kinds: Tuple[str, ...]
    sha256: str
    source: str           # "embedded" or the vocab file path


def _validate_vocab(data, source: str) -> ControlVocab:
    """Validate a parsed vocab dict and build the frozen ControlVocab."""
    if not isinstance(data, dict):
        raise ValueError(f"{source}: vocab must be a JSON object")
    raw_patterns = data.get("patterns")
    if not isinstance(raw_patterns, list):
        raise ValueError(f"{source}: 'patterns' must be a list")

    raw_backing = data.get("backing_kinds", _DEFAULT_BACKING_KINDS)
    if not isinstance(raw_backing, list) or not all(
            isinstance(k, str) and k for k in raw_backing):
        raise ValueError(f"{source}: 'backing_kinds' must be a list of strings")

    specs: List[PatternSpec] = []
    for idx, raw in enumerate(raw_patterns):
        where = f"{source}: patterns[{idx}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where} must be an object")
        for key in ("category", "name", "pattern"):
            val = raw.get(key)
            if not isinstance(val, str) or not val:
                raise ValueError(f"{where}: '{key}' must be a non-empty string")
        match = raw.get("match", "literal")
        if match not in _VALID_MATCH:
            raise ValueError(
                f"{where}: 'match' must be one of {_VALID_MATCH}")
        case_sensitive = raw.get("case_sensitive", False)
        if not isinstance(case_sensitive, bool):
            raise ValueError(f"{where}: 'case_sensitive' must be a boolean")
        description = raw.get("description", "")
        if not isinstance(description, str):
            raise ValueError(f"{where}: 'description' must be a string")
        compiled = None
        if match == "regex":
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                compiled = re.compile(raw["pattern"], flags)
            except re.error as exc:
                raise ValueError(f"{where}: invalid regex: {exc}") from exc
        specs.append(PatternSpec(
            category=raw["category"],
            name=raw["name"],
            pattern=raw["pattern"],
            match=match,
            case_sensitive=case_sensitive,
            description=description,
            compiled=compiled,
        ))
    digest_payload = json.dumps(
        {
            "backing_kinds": list(raw_backing),
            "patterns": [
                {
                    "category": s.category,
                    "name": s.name,
                    "pattern": s.pattern,
                    "match": s.match,
                    "case_sensitive": s.case_sensitive,
                    "description": s.description,
                }
                for s in specs
            ],
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    # Content digest: identical vocab content yields the same sha256
    # regardless of its path, so a receipt stays reproducible against
    # the exact vocab that produced it.
    digest = hashlib.sha256(digest_payload.encode("utf-8")).hexdigest()
    return ControlVocab(
        patterns=tuple(specs),
        backing_kinds=tuple(raw_backing),
        sha256=digest,
        source=source,
    )


def load_control_vocab(vocab_path: Optional[str] = None) -> ControlVocab:
    """Load a control-syntax vocabulary.

    House rules (modifier-vocab convention): without a path, the embedded
    default vocab is used. A missing, unreadable, or invalid-JSON file
    falls back to the embedded default. A valid JSON file with an explicit
    empty "patterns" list is honored (0 patterns). Malformed but parseable
    vocabularies raise ValueError.
    """
    if vocab_path:
        path = Path(vocab_path)
        try:
            source = path.read_text(encoding="utf-8")
            data = json.loads(source)
            return _validate_vocab(data, str(path))
        except (OSError, json.JSONDecodeError):
            pass  # fall back to the embedded default
    return _validate_vocab(json.loads(_DEFAULT_VOCAB_JSON), "embedded")


# ----------------------------------------------------------------------
# Scanning
# ----------------------------------------------------------------------

def _iter_literal_offsets(text: str, needle: str, case_sensitive: bool):
    """Non-overlapping literal occurrences; yields start offsets."""
    hay, pat = (text, needle) if case_sensitive else (text.lower(), needle.lower())
    if not pat:
        return
    start = hay.find(pat)
    while start != -1:
        yield start
        start = hay.find(pat, start + len(pat))


def _excerpt(text: str, start: int, end: int) -> str:
    lo = max(0, start - _EXCERPT_WINDOW)
    hi = min(len(text), end + _EXCERPT_WINDOW)
    snippet = text[lo:hi]
    return snippet.replace("\r", " ").replace("\n", " ").replace("\t", " ")


def _scan_text(text: str, vocab: ControlVocab):
    """Scan one text; yields (pattern_index, offset, matched_length)."""
    for p_idx, spec in enumerate(vocab.patterns):
        if spec.match == "regex":
            for m in spec.compiled.finditer(text):
                yield p_idx, m.start(), m.end() - m.start()
        else:
            for off in _iter_literal_offsets(text, spec.pattern,
                                             spec.case_sensitive):
                yield p_idx, off, len(spec.pattern)


@dataclass
class ControlSyntaxReport:
    """Deterministic receipt of the control-syntax audit lane."""
    source: str
    findings: List[dict] = field(default_factory=list)
    backed_count: int = 0
    backing_kinds: Tuple[str, ...] = ()
    vocab_sha256: str = ""
    pattern_count: int = 0
    vocab_source: str = "embedded"


def audit_control_syntax(observation, vocab: Optional[ControlVocab] = None,
                         vocab_path: Optional[str] = None,
                         source: Optional[str] = None) -> ControlSyntaxReport:
    """Audit an Observation for control-syntax surface patterns.

    Works on any object exposing ``segments`` (each with ``text``, ``kind``,
    ``location``) — in practice, sieve_lens.Observation. The H1-H7
    observation space and masks are not read or modified.
    """
    if vocab is None:
        vocab = load_control_vocab(vocab_path)
    backing = frozenset(vocab.backing_kinds)
    report = ControlSyntaxReport(
        source=source if source is not None else getattr(observation,
                                                         "source", ""),
        backing_kinds=vocab.backing_kinds,
        vocab_sha256=vocab.sha256,
        pattern_count=len(vocab.patterns),
        vocab_source=vocab.source,
    )
    rows = []  # (seg_idx, offset, pattern_idx, seg, spec, length)
    for seg_idx, seg in enumerate(observation.segments):
        kind = seg.kind
        is_backing = kind in backing
        is_content = kind in CONTENT_KINDS or kind not in backing
        if not (is_backing or is_content):
            continue  # unreachable; kept as an explicit guard
        for p_idx, off, length in _scan_text(seg.text, vocab):
            rows.append((seg_idx, off, p_idx, seg, vocab.patterns[p_idx],
                         length, is_backing))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    for seg_idx, off, p_idx, seg, spec, length, is_backing in rows:
        if is_backing:
            report.backed_count += 1
            continue
        report.findings.append({
            "lane": LANE_NAME,
            "observation": "pattern_found",
            "category": spec.category,
            "name": spec.name,
            "pattern": spec.pattern,
            "segment_kind": seg.kind,
            "location": seg.location or "",
            "offset": off,
            "backing": "absent",
            "excerpt": _excerpt(seg.text, off, off + length),
        })
    return report


# ----------------------------------------------------------------------
# Receipt rendering
# ----------------------------------------------------------------------

def report_json(report: ControlSyntaxReport) -> str:
    """Deterministic JSON receipt (trailing newline included)."""
    payload = {
        "lane": LANE_NAME,
        "source": report.source,
        "backing_kinds": list(report.backing_kinds),
        "vocab_source": report.vocab_source,
        "vocab_sha256": report.vocab_sha256,
        "pattern_count": report.pattern_count,
        "backed_count": report.backed_count,
        "finding_count": len(report.findings),
        "findings": report.findings,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def format_control_syntax_report(report: ControlSyntaxReport) -> str:
    """Human-readable text receipt (facts only, no judgment)."""
    lines = []
    lines.append("=" * 66)
    lines.append("  SIEVE-LENS CONTROL SYNTAX LANE — OBSERVATION RECEIPT")
    lines.append(f"  Source  : {report.source}")
    lines.append(f"  Vocab   : {report.pattern_count} patterns "
                 f"(sha256 {report.vocab_sha256})")
    lines.append(f"  Vocab src: {report.vocab_source}")
    lines.append(f"  Backing zones: "
                 f"{', '.join(report.backing_kinds) or '(none)'}")
    lines.append(f"  Backed observations (passed through): "
                 f"{report.backed_count}")
    lines.append(f"  Unbacked findings (receipt): {len(report.findings)}")
    lines.append("=" * 66)
    for idx, f in enumerate(report.findings, start=1):
        lines.append(f"[{idx}] pattern {f['pattern']!r} "
                     f"({f['category']} / {f['name']})")
        lines.append(f"    where   : kind={f['segment_kind']}, "
                     f"location={f['location'] or '(none)'}, "
                     f"offset={f['offset']}")
        lines.append(f"    backing : {f['backing']}")
        lines.append(f"    excerpt : {f['excerpt']}")
    if report.findings:
        lines.append("-" * 66)
    lines.append("  NOTE")
    lines.append("  This lane records surface patterns and their backing")
    lines.append("  status. It does not judge intent or declare an attack.")
    lines.append("=" * 66)
    return "\n".join(lines)


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def main(argv=None) -> int:
    """CLI: IN OUT.json [VOCAB.json]. 0 = success / 1 = failure."""
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) not in (2, 3):
        print("usage: python -m sieve_lens_ext.control_syntax IN OUT.json "
              "[VOCAB.json]", file=sys.stderr)
        return 1
    src, dst = argv[0], argv[1]
    vocab_path = argv[2] if len(argv) == 3 else None
    src_path = Path(src)
    if not src_path.is_file():
        print(f"control_syntax: cannot read {src}", file=sys.stderr)
        return 1
    try:
        from sieve_lens import SieveLensEngine
    except ImportError as exc:
        print(f"control_syntax: core engine unavailable: {exc}",
              file=sys.stderr)
        return 1
    engine = SieveLensEngine()
    try:
        from sieve_lens_ext.pdf import install as install_pdf
        install_pdf(engine)
    except ImportError:
        pass  # PDF inputs stay unsupported without the optional extra
    obs = engine.observe(src_path)
    if obs.h_states.get("H1") == 0 and "Unsupported format" in " ".join(
            obs.evidence.get("H1", [])):
        print(f"control_syntax: unsupported input format: "
              f"{src_path.suffix}", file=sys.stderr)
        return 1
    try:
        report = audit_control_syntax(obs, vocab_path=vocab_path,
                                      source=str(src_path))
    except ValueError as exc:
        print(f"control_syntax: {exc}", file=sys.stderr)
        return 1
    try:
        Path(dst).write_bytes(report_json(report).encode("utf-8"))
    except OSError as exc:
        print(f"control_syntax: cannot write {dst}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
