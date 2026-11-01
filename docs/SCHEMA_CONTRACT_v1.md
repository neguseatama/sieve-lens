# Sieve Schema Contract v1

- **Version**: contract `sieve-schema-contract-v1` (corpus version 1)
- **Status**: Adopted in Sieve Lens v0.18.0
- **Canonical implementation**: [`sieve_lens_ext/schema.py`](../sieve_lens_ext/schema.py) (this repository)
- **Conformance corpus**: [`tests/corpus/schema_contract_v1.json`](../tests/corpus/schema_contract_v1.json) (44 cases)
- **Scope**: the JSON gates of the Sieve tools — Lens control vocab,
  Lens geometry thresholds, Redact `--from-lens` catalog, Crowd JSON
  input

---

## 1. Purpose and structure

The Sieve series shares one stance toward untrusted JSON: *nothing is
guessed or coerced; violations fail closed with a precise location*.
Before this contract each tool hand-rolled that stance, and the
hand-rolled checks had drifted (the S2 probe measured a proposed
schema that was *weaker* than the shipped v0.8 Redact gate). Contract
v1 freezes the shared semantics in one place:

1. **This specification** (this document, plus the engine docstring)
2. **The canonical engine** — `sieve_lens_ext/schema.py`, zero
   dependencies, ~390 lines
3. **The conformance corpus** — accept/reject cases with pinned error
   pointers, replicated into the other tools' test suites with a
   sha256 pin

The engine is **not** a sixth Sieve tool and is not distributed as its
own package. Redact keeps an inline subset in its single file (the
single-file invariant forbids importing from Lens); Crowd keeps its
input adapter. The corpus pins all copies to the same semantics.

**Revisit triggers for a standalone engine** (decided 2026-11): a
Markdown/prompt embedding of the contract exceeds ~100 lines, three or
more tools embed copies and a drift incident slips through the corpus,
or an external consumer actually needs the engine as a library.

## 2. JSON layer

The strict parse (`load_strict_json`):

| Input property | Behavior |
| --- | --- |
| duplicate object key | refused (`StrictJSONError`) |
| `NaN` / `Infinity` / `-Infinity` literal | refused (`StrictJSONError`) |
| leading UTF-8 BOM | refused (`StrictJSONError`) |
| byte length over `max_bytes` | refused (`StrictJSONError`) |
| `1e400` (overflows to inf) | parses; must be bounded by schema `max` |
| invalid UTF-8 | refused by the byte decoder (unchanged per tool) |

`StrictJSONError` subclasses `json.JSONDecodeError`, so tools whose
house rule is "invalid JSON falls back / is refused" via
`except (OSError, json.JSONDecodeError)` keep their exact behavior:

- **Lens** vocab/thresholds loaders: JSON-layer violations fall back to
  the embedded defaults (visible in the receipt's `vocab_source` and
  content sha256); parseable-but-schema-invalid documents raise
  `ValueError`
- **Redact** `--from-lens`: all violations are `UsageError` (rc2)
- **Crowd** JSON input: all violations are `InputError`

## 3. Schema grammar

Every node is a dict with a `type`; a field spec is a node plus
`required` (default **True** — fail closed; optionality is declared,
never assumed). `type` itself is optional in a field spec
(redact-aligned): a type-less spec carries only `enum`/`validator`.

```
object node : {"type": "object", "keys": {field: spec, ...},
               "cross"?: {"mutually_exclusive": [[k1, k2], ...]}}
array node  : {"type": "array", "item_type"?: <type-name>}
              or {"type": "array", "item_schema": <object node>}
scalar node : {"type": "string"|"integer"|"number"|"boolean"|"null",
               "enum"?: [...], "min"?: n, "max"?: n,
               "min_len"?: n, "max_len"?: n}
```

Vocabulary (11 spec keys, all fail-closed — an unknown spec key is an
authoring error):

| Key | Applies to | Semantics |
| --- | --- | --- |
| `type` | any | strict type name; bool never passes as integer/number |
| `required` | field spec | default True |
| `enum` | scalars / type-less | type-strict membership (`True` ∉ `[1]`) |
| `min`, `max` | integer/number | inclusive, NaN-safe |
| `min_len`, `max_len` | string/array | `len()` bounds |
| `item_type` | array | scalar item type, checked iteratively |
| `item_schema` | array | object item node, recursed |
| `keys` | object | nested field map |
| `cross` | object | at most one key per group may be present |
| `validator` | any | Python callable; runs after all structural checks |

Not expressible in v1 (deliberately): coercion, defaults inside the
schema, nested arrays, `anyOf`/conditionals. Schema-side completion
(defaults, compiled objects) is the caller's **build** step.

## 4. Error contract

- `SchemaError(ValueError)` with `.pointer`, an RFC 6901 JSON Pointer
  (`/observations/2/count`; `~` and `/` escaped as `~0`/`~1`; the root
  is reported as `(root)`)
- Violations fail fast, in schema-declaration order; the first error
  wins
- Unknown data keys are **rejected, not ignored** (gatekeeper stance:
  a future producer must extend the contract explicitly)
- Message language is per-tool (Lens: English, Redact: Japanese); the
  contract pins pointers and semantics, not wording

## 5. Bounded validation (DoS stance)

Recursion follows only `keys` and `item_schema` — both schema-owned —
so validation depth is bounded by the **schema depth**, never the
input depth. Array items are checked iteratively. Pinned in the
corpus (`schema-reject-depth-bounded`) and, with stress sizes, in each
engine test suite (50,000-deep input refused near the root; a
100,000-item array validated in milliseconds).

## 6. Conformance matrix

The corpus is one file; each tool runs the layers it implements.
Declared divergences are part of the matrix — they are decisions, not
accidents.

| Tool | JSON layer: dup key | NaN/Infinity | BOM | size cap | Schema engine |
| --- | --- | --- | --- | --- | --- |
| **Lens** (this repo) | refuse → fallback | refuse → fallback | refuse → fallback | 1 MiB, refuse → fallback | full Contract v1 (`schema.py`) |
| **Redact** (inline subset) | `UsageError` rc2 | `UsageError` rc2 | `UsageError` rc2 | 1 MiB, `UsageError` rc2 | catalog-v1 subset (type/required/enum/item_type/item_schema) |
| **Crowd** (`jsonio.py`) | `InputError` | `InputError` | **accepted** (`utf-8-sig`, Excel-export tolerance) | none (upstream reader caps) | record-shape checks (its own domain) |

Replication protocol (mirrors the sieve-tray vendor-sync precedent):

1. The canonical corpus lives in this repository under
   `tests/corpus/schema_contract_v1.json`; its sha256 is pinned in
   `tests/test_schema_contract_corpus.py`.
2. A replica copy ships in the other tool's `tests/corpus/` directory;
   a pin test in that tool asserts the byte-identical sha256.
3. A corpus bump is one contract versioning step: bump here, refresh
   the replicas and pins in the same cycle.
4. Tray does not replicate the corpus (it consumes Redact/Crowd code,
   not JSON gates).

## 7. In-code schemas (this repository)

| Schema | Location | Consumed by |
| --- | --- | --- |
| `CONTROL_VOCAB_SCHEMA` | `sieve_lens_ext/control_syntax.py` | control-syntax lane vocab (file or embedded default) |
| `GEOMETRY_THRESHOLDS_SCHEMA` | `sieve_lens_ext/geometry.py` | geometry lane thresholds (file or embedded default) |

Both split into a pure `validate_*` (structure only) and a `build_*`
(default filling + regex compilation + content digest). The content
digests of the embedded defaults are pinned
(`27734e17…6fbf`, `70f2bdb5…4540`) — receipts recorded before v0.18.0
stay reproducible byte-for-byte.

## 8. Versioning

- `contract` (`sieve-schema-contract-v1`) changes only when the
  grammar or the JSON layer changes — that is a breaking step for
  every tool gate and bumps each tool's minor version
- `corpus_version` changes when cases are added or refined without a
  grammar change
- The corpus file itself must stay loadable by the strict JSON layer
  (no `Infinity` literals; deep-nesting cases stay within parser-safe
  depth)
