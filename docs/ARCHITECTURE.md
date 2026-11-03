# 🏛️ Sieve Lens Architecture Specification

## Pipeline Overview

[ Document D ]
|
v
[ H1: Parseability ]
| (extraction failure -> 0000-000, halt)
v
[ Format-specific Extraction ]
|
v
[ H2: Zero-Width Density ]
[ H3: Bidi Controls ]
[ H4: Format Concealment ]
[ H5: Out-of-Band Channel]
[ H6: Script Mixing ]
[ H7: Contiguous Payload ]
|
v
[ 7-bit Mask: H1H2H3H4-H5H6H7 ]
|
v
[ Observation Report ]

(H8 note: the geometry lane is an *optional extension lane* that runs
 beside this pipeline and emits its own receipt — it is **not** part
 of the 7-bit mask; installing it leaves H1-H7 semantics unchanged.)


---

## The Seven Hypotheses

| Bit | Hypothesis | Observation Domain |
|-----|-----------|---------------------|
| H1 | Parseability | Format-specific extraction succeeds |
| H2 | Zero-Width Density | Symbolic density over body text |
| H3 | Bidi Controls | Presence of directional control chars |
| H4 | Format Concealment | Inline CSS hiding rules |
| H5 | Out-of-Band Channel | Comments, metadata, hidden attrs |
| H6 | Script Mixing | Homoglyph signature within tokens |
| H7 | Contiguous Payload | Long runs of invisible characters |

All seven are **deterministic** and **independent**.

---

## Extraction Model

Each format is handled by a dedicated `_Extractor` subclass:

- `_PlainTextExtractor` — reads bytes, strips leading BOM, returns single segment
- `_HtmlExtractor` — uses `html.parser.HTMLParser`, tracks hidden-state stack,
  captures comments and hidden attributes
- `_DocxExtractor` — uses `zipfile` + `xml.etree.ElementTree` to read
  `word/document.xml`, `word/comments.xml`, `docProps/core.xml`

The extractor does **not** interpret content. It only separates body text from
out-of-band channels.

---

## Observation vs. Judgment

Sieve Lens **never** declares:

- "This document contains a prompt injection."
- "This candidate is cheating."
- "This file is safe."

It declares:

- "H2 = 1: zero-width density exceeded 0.01."
- "H4 = 1: inline `display:none` element contains text."
- "H7 = 1: 47 contiguous invisible characters at offset 1284."

The distinction is intentional. It preserves:

- **Explainability** — evidence is provided, not a verdict.
- **Auditability** — a human can inspect each claim.
- **Legal safety** — the tool does not accuse.

---

## Determinism Guarantees

- No use of `random`, `time`, `datetime`, `os.environ`, or filesystem state
  beyond the input file.
- No network access.
- Character tables are frozen sets.
- Iteration order is preserved as encountered.
- The same input file yields the same mask and evidence on Python 3.9–3.12.

---

## Known Boundaries

| Boundary | Reason |
|----------|--------|
| PDF via optional extension | `sieve_lens_ext/pdf.py` reads through `pypdf` (pip extra `pdf`); the core engine stays zero-dependency, and extensions read through their own libraries outside the core's bounded reading (L1 — future L2/L3 scope) |
| Images / OCR via optional extensions | `sieve_lens_ext/image_layers.py` (Pillow) and `sieve_lens_ext/ocr.py` (pytesseract) — pip extras `pdf-images` / `ocr`; OCR quality depends on the locally installed language packs |
| External CSS: local files only | The core H4 lane inspects inline CSS only; the optional `html-css` extensions resolve `<style>` blocks and *local* `<link>` stylesheets — remote resources are never fetched (offline principle) |
| Semantic intent not evaluated | Requires language understanding |
| Character tables fixed | New techniques require code update |