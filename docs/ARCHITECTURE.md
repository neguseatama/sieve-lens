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
| H4 | Format Concealment | Inline CSS hiding rules; DOCX concealment (vanish / low-contrast / tiny font / tracked deletions); PDF hidden text (render modes 3/7, tiny font, off-page, off layer, white text) |
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

## PDF Hidden Text (v0.23.0)

The visible page text and the hidden-text report are built from ONE
shared classification of the drawing state: the text render mode
(`Tr`, saved and restored by `q`/`Q`, persisting across `BT`/`ET`,
inherited by a Form XObject invoked by `Do`), the CTM (`cm`), the font
size (`Tf`), the text matrix (`Tm`/`Td`/`TD`/`T*`/`TL`; `BT` resets
it), the fill and stroke colors (`g`/`G`/`rg`/`RG`/`k`/`K`/`cs`/`CS`/
`sc`/`scn`/`SC`/`SCN`) and the marked-content stack (`BDC`/`BMC`/`EMC`).

The hidden kinds ride inside H4 with these labels:

| Label | Kind | Definition |
|-------|------|------------|
| `invisible text, Tr 3` / `Tr 7` | render mode | text drawn in render mode 3 (invisible) or 7 (clip only). 0.22.1 only excluded mode 7 from the visible text; since 0.23.0 it is reported as hidden text too. |
| `tiny_font` | tiny text | the effective font size - the `Tf` size x the scale of the text matrix x the scale of the CTM - is below **2.0 pt**. (The DOCX lane uses the same closed word for its own sense: `w:sz` <= 2 half-points.) |
| `off_page` | off-page | the drawing origin (the text-matrix translation carried through the CTM) lies outside the page's view box (`/CropBox` when present, else `/MediaBox`). An origin inside the box keeps the text visible even when glyphs extend past the edge. `/Rotate` does not affect the judgment. |
| `off_layer '<name>'` | hidden layer | text governed by an optional-content group or membership dictionary that is OFF in the default configuration (`/OCProperties /D`), through `BDC /OC ... EMC` (resolved via `/Properties`) or a Form XObject's `/OC`. OCMD policies (`AnyOn` / `AllOn` / `AnyOff` / `AllOff`) are applied to `/OCGs`. The `<name>` in the label is never the PDF's own name text raw: it is cleaned first (printable characters only - control and format characters removed, whitespace runs collapsed to one space) and capped at 40 characters (`...` marks a capped name; `LAYER_LABEL_MAX_CHARS`). The same cleaning applies to the BDC property key, and a name that cleans to nothing falls back to the key. |
| `white_text` | white text | the color the render mode draws with (0/4 fill, 1/5 stroke, 2/6 both) is near white - DeviceGray >= **0.98**, DeviceRGB all >= **0.98**, DeviceCMYK all <= **0.02** - and no non-white paint sits beneath it. |

What a reader may find unexpected:

- **White text on a painted background stays visible.** When one
  non-near-white paint drawn BEFORE the text - a filled path
  (`f` / `F` / `f*` / `B` / `b`) or an image `Do` - fully contains the
  text's estimated box (width from the font's `/Widths`, else 1.0 x
  the font size per character; height = the font size), the text is
  treated as the slide-style "white banner on a colored rectangle"
  and stays visible; the count lands in the diagnostics as
  `white_on_painted`.
- **Colors Lens cannot decide never become hidden.** Non-device color
  spaces (`ICCBased`, `Indexed`, `Separation`, patterns) and operand
  counts that do not match the current space leave the judgment open:
  the text stays visible and the count lands in the diagnostics as
  `color_unresolved`.

One show operation hit by several kinds reports the first reason in
the fixed order above (render mode, tiny, off-page, layer, white) and
never reaches the visible text. The hidden pieces of one page (and of
one form) join into one `css_hidden` segment per label, in the order
the labels first occur; the visible text keeps its 0.22.1 reading
order. A scan PDF whose OCR layer is drawn invisibly over the page
therefore yields an empty visible text while the observation reports
the hidden text - the intended result, not a reading failure.

Fail-closed conditions (the page emits no visible text and records
`Extraction failed` in its page location; other pages are unaffected):
an unreadable content stream, a state-tracking failure (a malformed
`Tr` / `Tf` / `Tm` / `cm` operand), form nesting beyond the walk limit
(8), a form re-invoked under a different state, an unresolvable `/OC`
reference, an unsupported `/VE`, and OCMD nesting beyond 8 levels.
`Tz` (horizontal scaling) is deliberately not applied to `Td` offsets:
pypdf 4.0.0 and 6.6.0 both measure `Td` offsets unscaled, and the
visible side is pypdf's own machinery, so the origin formula follows
that measured behavior.

---

## Known Boundaries

| Boundary | Reason |
|----------|--------|
| PDF via optional extension | `sieve_lens_ext/pdf.py` reads through `pypdf` (pip extra `pdf`); the core engine stays zero-dependency, and extensions read through their own libraries outside the core's bounded reading (L1 — future L2/L3 scope) |
| Images / OCR via optional extensions | `sieve_lens_ext/image_layers.py` (Pillow) and `sieve_lens_ext/ocr.py` (pytesseract) — pip extras `pdf-images` / `ocr`; OCR quality depends on the locally installed language packs |
| External CSS: local files only | The core H4 lane inspects inline CSS only; the optional `html-css` extensions resolve `<style>` blocks and *local* `<link>` stylesheets — remote resources are never fetched (offline principle) |
| Semantic intent not evaluated | Requires language understanding |
| Character tables fixed | New techniques require code update |
| PDF Form XObject nesting capped at 8 levels | Deeper nests are skipped by the observation walk (cycle protection); a page that DRAWS a form beyond the cap emits no visible text for that page (fail closed) |
| DOCX hidden-text resolution is simplified | Toggles disagreeing across several levels, table-style formatting and some width/position tricks are out of scope |