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
| H4 | Format Concealment | Inline CSS hiding rules; DOCX concealment (vanish / low-contrast / tiny font / tracked deletions) |
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
  `word/document.xml`, `word/styles.xml`, `word/theme/theme1.xml`,
  `word/settings.xml`, `word/comments.xml`, `docProps/core.xml`,
  headers, footers, footnotes and endnotes. Since v0.20 it resolves
  the effective run formatting (docDefaults → style chains → direct,
  memoized) and emits concealed runs as `docx_hidden` segments
  (`visible=False`), which feed H4 alongside the HTML `css_hidden`
  segments; the visible text keeps the v0.19 segment shape for
  non-concealed documents.

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

## The Pinned Character Table

`sieve_lens_ext/chartable.py` loads the packaged character table
`sieve_lens_ext/chartable_v1.json` (schema `sieve-chartable/1`): the
invisible characters, the look-alike twins, the fullwidth ASCII range,
the folding spaces and the folding dashes, in one sha256-pinned file.
The loader is fail-closed and lazy: it verifies the digest pin on the
exact bytes on every load, raises `ChartableError` on a missing,
tampered or malformed table (no fallback), and returns a fresh dict per
call. The observation pipeline does not consume the table yet; the
module establishes the pinned source of the standard inside Lens. See
`docs/CHARTABLE.md` for the table contents.

---

## Determinism Guarantees

- No use of `random`, `time`, `datetime`, `os.environ`, or filesystem state
  beyond the input file.
- No network access.
- Character tables are frozen sets.
- Iteration order is preserved as encountered.
- The same input file yields the same mask and evidence on Python 3.9–3.12.

---

## Geometry Observation Scope

The geometry lanes (v0.17 HTML, v0.18 PDF subscan) measure how a
document positions text, not what it says. Their scope:

- CSS lengths are measured in px and unitless numbers only; em/rem/%/pt
  are skipped, and `@media` blocks are not descended into.
- Inline style attributes are scanned with the standard library;
  `<style>` blocks and local `<link>` stylesheets are parsed when the
  optional CSS extras are installed (remote resources are never
  fetched).
- The PDF subscan reads un-transformed positions: relative moves and
  the transform matrix are not composed into the observed values, and
  fills matching the page background are not observed.
- Geometry findings never enter the 7-bit mask. They are confirmed
  through each lane's own receipt (`audit_geometry` /
  `audit_pdf_geometry`).

---

## Known Boundaries

| Boundary | Reason |
|----------|--------|
| PDF via optional extension | `sieve_lens_ext/pdf.py` reads through `pypdf` (pip extra `pdf`); the core engine stays zero-dependency, and extensions read through their own libraries outside the core's bounded reading (L1 — future L2/L3 scope) |
| Images / OCR via optional extensions | `sieve_lens_ext/image_layers.py` (Pillow) and `sieve_lens_ext/ocr.py` (pytesseract) — pip extras `pdf-images` / `ocr`; OCR quality depends on the locally installed language packs |
| External CSS: local files only | The core H4 lane inspects inline CSS only; the optional `html-css` extensions resolve `<style>` blocks and *local* `<link>` stylesheets — remote resources are never fetched (offline principle) |
| Semantic intent not evaluated | Requires language understanding |
| Character tables fixed | New techniques require code update |
| PDF Form XObject nesting capped at 8 levels | Deeper nests are skipped (cycle protection in the content-stream walk) |
| DOCX hidden-text resolution is simplified | Toggles disagreeing across several levels, table-style formatting and some width/position tricks are out of scope |