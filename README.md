**English** | [日本語](README.ja.md)

# Sieve Lens v0.20.0

## 💡 Concept

Modern AI evaluation systems parse documents as text.
Humans read documents as rendered output.
These two views are not the same, and the gap between them can be exploited:

- Zero-width characters (`U+200B`...) that a model reads but a human cannot see.
- CSS rules (`display:none`) that hide text from a human but not from a parser.
- Out-of-band channels (comments, metadata, headers, footnotes) that a parser
  reads but a human never notices.

**Sieve Lens observes this divergence.**  
It does not judge intent. It surfaces what is invisible, with location and
decoded content, so that a human can decide what to do.

> The name "Sieve Lens" comes from the design philosophy of seeing through a
> document the way a lens reveals what the naked eye cannot.

---

## 🧩 The Sieve Series

Sieve is a family of deterministic, zero-dependency engines that share
the same design principles (deterministic output, no telemetry, fully
local) — each engine observes or masks one specific risk, and they
compose:

| Package | Role | Connects to |
|---------|------|-------------|
| [sieve-core-engine](https://github.com/neguseatama/sieve-core) | Foundational engine for deterministic structure aggregation and confidence scoring | — |
| [sieve-referee](https://github.com/neguseatama/sieve-referee) | Observes text structure, reuse, and paraphrase | — |
| [sieve-scope](https://github.com/neguseatama/sieve-scope) | Observes structural similarity of source code | — |
| [sieve-lens](https://github.com/neguseatama/sieve-lens) | Observes invisible content and concealment elements | → redact via `--from-lens` |
| [sieve-redact](https://github.com/neguseatama/sieve-redact) | Deterministic masking of designated regions with completeness verification | ← lens, → tray |
| [sieve-order](https://github.com/neguseatama/sieve-order) | Observes the surface structure of prompts in a 6-bit observation space | — |
| [sieve-crowd](https://github.com/neguseatama/sieve-crowd) | Table-data anonymization and privacy-protection engine | — |
| [sieve-tray](https://github.com/neguseatama/sieve-tray) | Local front-end that integrates the engines | ← all engines |

Observation → masking in one pass: Lens finds what a human can't see,
Redact removes it with a receipt that proves nothing else changed.

## 📐 7-bit Observation Space

| Bit | Name | What it observes |
|-----|------|------------------|
| H1 | Parseability | The file can be read and parsed |
| H2 | Zero-Width Density | Density of zero-width chars exceeds threshold |
| H3 | Bidi Controls | Bidi control characters present |
| H4 | Format Concealment | CSS hiding rules (`display:none`, etc.); DOCX concealment (hidden-text formatting / near-invisible colour / tiny font / tracked deletions) |
| H5 | Out-of-Band Channel | Meaningful content in comments / metadata / headers / footers / footnotes |
| H6 | Script Mixing | Latin+Cyrillic or Latin+Greek mixed within a token |
| H7 | Contiguous Payload | A run of ≥ N contiguous invisible chars exists |

Mask format: `H1H2H3H4-H5H6H7` (e.g., `1000-100`).

---

## 📦 Supported Formats

| Format | Coverage | Dependencies |
|--------|----------|--------------|
| `.txt`, `.md` | Plain text, full character-level scanning | none (core) |
| `.html`, `.htm` | HTML with inline-style and `<style>` block concealment detection; optional external CSS resolution | none (core); `tinycss2` (optional) |
| `.docx` | Body, comments, core properties, headers, footers, footnotes, endnotes; concealment observation (hidden-text formatting, near-invisible colour, tiny font, tracked deletions) | none (core) |
| `.pdf` | Body text, metadata, annotations, invisible text (Tr 3), Form XObject text (Tr 3 / raw stream) | `pypdf` (optional) |
| `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.tif`, `.tiff`, `.webp` | Metadata (EXIF / PNG text / XMP) + OCR text | `Pillow`, `pytesseract` + tesseract binary + language packs (optional) |

**Not supported**: audio, video.

---

## 🔥 Key Features

- **7-bit observation space (H1–H7)**  
  Independent, deterministic detection of each class of invisible content.
- **Zero dependencies**  
  Python standard library only. Runs offline, no telemetry, no network.
- **Deterministic**  
  Same input always yields the same observation, on any platform.
- **Explainable**  
  Every observation carries location and decoded content, so a human can verify.
- **Observation, not judgment**  
  The engine reports evidence. It never declares "this is an attack".
- **Self-contained HTML report** (since v0.1)  
- **PDF support** via `pypdf` (since v0.2)  
- **Image OCR support** via `Pillow` + `pytesseract` (since v0.3)  
  OCR language is configurable: `install(engine, ocr_lang="eng+jpn")`
- **Interactive HTML dashboard** (since v0.5)  
  Batch-analyze a directory and produce a single self-contained dashboard
  with summary cards, mask distribution, hypothesis activation charts,
  and a sortable file table. Requires `Jinja2` + `Plotly`.
- **Printable PDF report** (since v0.6)  
  Generate an A4 PDF report from a directory of documents. Includes
  summary, hypothesis table, mask distribution, and a color-coded file
  list. Requires `weasyprint` (and optionally `kaleido` for charts).
- **Image layer analysis** (since v0.7)  
  Detects pixel-level concealment in images: transparent RGBA layers
  carrying non-zero RGB values, and low-contrast text with a WCAG ratio
  below 2:1. Requires `Pillow`.
- **Full CSS selector resolution** (since v0.8)  
  Extends the HTML extractor with full CSS selector matching via
  `cssselect2`: descendant, child, sibling, attribute, and pseudo-class
  selectors. Hidden rules are only reported when they match an element.
- **Report internationalization (i18n)** (since v0.9)  
  Dashboard and PDF reports are available in English and Japanese.
  Auto-detection selects the language based on input document content.
- **PDF embedded image analysis** (since v0.10)  
  Extracts images embedded in PDF pages and applies OCR, transparent
  layer detection, low-contrast detection, and metadata analysis to
  each image. Requires `pypdf` + `Pillow`.
- **PDF Form XObject text scanning** (since v0.15)  
  Text inside Form XObject content streams, including invisible (Tr 3)
  text, is scanned with the same semantics as page content streams;
  nested forms are walked with cycle protection (depth cap of 8).
- **Control-syntax audit lane** (since v0.17)  
  Observes documents for LLM prompt-boundary patterns: chat-template
  special tokens (`<|im_start|>`, `[INST]`, `<<SYS>>`), override phrases
  in English and Japanese, and pseudo structural tags. Occurrences in
  declared system zones (document metadata) are counted and passed
  through; unbacked occurrences become receipt findings with pattern,
  location, and offset. The lane records surface facts only and never
  declares intent. The vocabulary is an external JSON
  (`control_vocab_v1.json` ships as a reference copy; the embedded
  default applies unless a file override is given).
- **Geometry concealment lane** (since v0.17, H8 html; PDF subscan v0.18)  
  Observes geometric concealment styles that keep text parseable while
  rendering it invisible to human readers: sub-pixel `font-size`,
  near-zero `opacity`, collapsed `transform: scale(...)`, and zero
  `line-height`. Inline style attributes are scanned with the standard
  library; `<style>` blocks and local `<link>` stylesheets are parsed
  when tinycss2 is installed. The PDF subscan walks page content
  streams and Form XObjects and observes tiny `Tf` font sizes and
  `Tm` placements outside the page MediaBox (Tr 3 stays with the PDF
  extension's H4 coverage). The threshold set is an external JSON
  (`geometry_thresholds_v2.json` ships as a reference copy; embedded
  defaults apply unless a file override is given). The receipt records
  rule, raw value, measured number, threshold, and position - facts
  only, no intent judgment.
- **Bounded document reading (L1: safe reading)** (since v0.19)  
  The core reading paths (`.txt` / `.md` / `.html` / `.htm` / `.docx`)
  are guarded by `ReadLimits`, a frozen dataclass pinning five
  positive-integer budgets: file size (64 MiB), zip entries (10,000),
  decompressed part size (32 MiB), per-call total (128 MiB), and XML
  elements (1M). Hostile inputs are refused before parsing through a
  closed set of 12 codes: non-regular files, oversized files, too many
  entries, oversized or duplicate (case-insensitive) parts, encrypted
  flags, DOCTYPE/ENTITY, unsupported encodings (UTF-16 is refused),
  malformed XML, and a missing main part. A refusal is non-destructive:
  the receipt becomes a null observation (H1 = 0, mask `0000-000`)
  whose evidence carries the refusal code only — never part names,
  document content, or paths. Accepted inputs are byte-identical to
  v0.18.0.
- **DOCX concealment observation (L2)** (since v0.20)  
  The DOCX extractor resolves the effective run formatting
  (docDefaults → paragraph style chain → character style chain →
  direct formatting, memoized) and splits runs that a human reader
  would not see out of the visible text into `docx_hidden` segments:
  `vanish` (hidden-text formatting), `low_contrast` (Rec.709 luma step
  D < 20 between the resolved foreground and background, with the
  resolved colours and source in the evidence), `tiny_font`
  (`w:sz`/`w:szCs` ≤ 2 half-points), and `tracked_deletion` (text
  inside `w:del` / `w:moveFrom`, or `w:delText` outside `w:del`).
  Backgrounds resolve highlight-first (Word's palette), then run /
  paragraph / cell shading, then the page background (only when
  `w:displayBackgroundShape` is set), then white. Theme colours
  resolve through `w:clrSchemeMapping` and `theme1.xml`. The three
  formatting parts (`word/styles.xml`, `word/theme/theme1.xml`,
  `word/settings.xml`) are read through the same L1 bounds and shared
  budget; a malformed one refuses (see limitation 20). The engine
  reports the fact that text is invisible-in-principle; it never
  judges whether it is abusive.

## 📦 Installation

```bash
# Core (zero-dependency)
pip install sieve-lens

# From PyPI (for released versions)
pip install "sieve-lens[pdf]"
pip install "sieve-lens[ocr]"

# Or the latest from GitHub (may include changes not yet on PyPI)
pip install "sieve-lens[pdf] @ git+https://github.com/neguseatama/sieve-lens.git"
pip install "sieve-lens[ocr] @ git+https://github.com/neguseatama/sieve-lens.git"
```

---

## 💻 Quick Start

```python
from sieve_lens import SieveLensEngine, format_report, format_report_html

engine = SieveLensEngine()
obs = engine.observe("resume.docx")

print(obs.mask)                    # e.g. "1000-100"
print(obs.h_states)                # {'H1': 1, 'H2': 0, ..., 'H7': 0}
print(format_report(obs))          # human-readable text report

html = format_report_html(obs)     # self-contained HTML report
```

To write the HTML report to a file:

```python
from sieve_lens import write_report_html
write_report_html(obs, "report.html")
```

### PDF (requires the `pdf` extra)

```python
from sieve_lens import SieveLensEngine
from sieve_lens_ext.pdf import install

engine = SieveLensEngine()
install(engine)                    # attach .pdf support
obs = engine.observe("resume.pdf")
print(obs.mask)
```

### Image OCR (requires the `ocr` extra)

```python
from sieve_lens import SieveLensEngine
from sieve_lens_ext.ocr import install

engine = SieveLensEngine()
install(engine, ocr_lang="eng+jpn")    # tesseract language packs
obs = engine.observe("screenshot.png")
print(obs.mask)
```

---

## 🔬 Testing

```bash
# Full suite (pytest; missing optional deps are skipped)
python -m pytest tests/ -q

# Per-suite (unittest discover)
# v0 test suite
python -m unittest discover -s tests -p "test_sieve_lens.py" -v

# v0.1 test suite
python -m unittest discover -s tests -p "test_sieve_lens_v0_1.py" -v

# v0.2 PDF extension (requires pypdf)
python -m unittest discover -s tests -p "test_sieve_lens_pdf.py" -v
```

---

## 📋 Sieve Schema Contract v1 (v0.18.0)

All JSON gates in the Sieve tools share one declared contract
(`docs/SCHEMA_CONTRACT_v1.md`, canonical engine
`sieve_lens_ext/schema.py`):

- **Strict JSON layer** — duplicate object keys, `NaN`/`Infinity`, a
  UTF-8 BOM and files over the 1 MiB cap are refused; for the Lens
  vocab/thresholds loaders "refused" means the documented fallback to
  the embedded defaults (the receipt's `vocab_source`/sha256 shows it)
- **Declared schemas** — the control-vocab and geometry-threshold
  documents are validated against explicit schema declarations
  (`CONTROL_VOCAB_SCHEMA`, `GEOMETRY_THRESHOLDS_SCHEMA`), separated
  into a pure `validate_*` (structure, RFC 6901 JSON Pointer errors)
  and a `build_*` step (default filling, regex compilation)
- **Gatekeeper stance** — unknown keys are refused, not ignored
  (behavior change: mistyped `version`/`lane` values and unknown
  fields now raise `ValueError` instead of being silently skipped)
- **Receipt non-destruction** — the content digests of the embedded
  vocab and thresholds are unchanged by the refactor (pinned in
  tests), so every receipt recorded before v0.18.0 stays reproducible
- **Conformance corpus** — 44 accept/reject cases
  (`tests/corpus/schema_contract_v1.json`) pin the contract; replicas
  in the Redact and Crowd test suites are pinned by sha256
- **Bounded validation** — recursion follows the schema depth only,
  never the input depth; a 50,000-deep document is refused near the
  root, a 100,000-item array is checked iteratively

---

## 🔗 Redact Bridge (v0.12.0)

`sieve_lens_ext.redact_bridge` exports an observation catalog that
[Sieve Redact](https://github.com/neguseatama/sieve-redact) consumes directly:

    python -m sieve_lens_ext.redact_bridge input.txt catalog.json
    python -m sieve_redact input.txt -o clean.txt --from-lens catalog.json

- Catalog format (version 1): `observations[]` with `kind`, `codepoint`,
  `count`, `positions` (first-seen order).
- Look-alike characters (Cyrillic/Greek -> Latin, full-width digits
  and letters -> ASCII, 102 entries) carry an optional
  `twin` field, which Redact converts into a replacement rule; invisible
  characters become deletions.
- Deterministic, stdlib-only. The bridge imports the core character tables,
  so the two engines can never disagree on what counts as invisible.
- End-to-end check: `python3 probe_redact_roundtrip.py`
  (synthetic input -> catalog -> redact -> re-observe clean).

## v0.11.0 Highlights

- **Fixed critical regressions**: PDF embedded-image analysis and HTML body
  text extraction (which had silently disabled H2/H3/H6/H7 detection), and
  EXIF UserComment/SubIFD reading.
- **Security**: report output is now HTML-escaped (untrusted specimens can no
  longer inject markup into dashboards/PDF reports), and local stylesheet
  resolution is confined to the specimen's directory tree.
- **Deterministic PDF reports**: byte-identical output across builds,
  verified in CI (fixed dcterms dates + pinned XMP DocumentID).
- **Chained extensions**: `sieve_lens_ext.image_layers` now composes with
  `sieve_lens_ext.ocr` automatically; new `SieveLensEngine.get_extractor()`.

**Invisible Prompt Observation Engine**

*Sieve Lens is not a tool that distrusts AI.*  
*It is a tool that helps AI receive trustworthy input.*

> Zero-dependency, deterministic, explainable observation of invisible content
> in documents (resumes, submissions, reports) that may be intended to
> influence AI-based evaluation systems.

Extends the [Sieve](https://github.com/neguseatama/sieve-core) series to the
domain of **machine-readable vs. human-visible divergence**.

[![CI](https://github.com/neguseatama/sieve-lens/actions/workflows/test.yml/badge.svg)](https://github.com/neguseatama/sieve-lens/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)

---

## ⚠️ Known Limitations

1. **Observation, not removal.** Concealment found in PDFs and images is reported; masking is Sieve Redact's domain (deliberate role split).
2. **Semantic intent is not evaluated.** A visible but manipulative prompt is
   outside the scope of this tool.
3. **Only inline CSS is inspected.** External stylesheets and CSS classes are
   not resolved.
4. **Character-table coverage is fixed.** New invisible techniques require
   updating the tables.
5. **This is an observation engine, not a detector.** Findings should always
   be confirmed by human review.
6. **Homoglyph twins are non-ASCII -> ASCII only** — lookalike pairs
   inside ASCII (O/0, l/1) and CJK lookalikes are out of scope

7. **Missing OCR language packs fail silently.** If the configured language
   pack is not installed, OCR yields no text without an error; metadata
   extraction is unaffected

8. **PDF Form XObject nesting is capped.** Text inside Form XObjects is scanned with a cycle-safe walk; nesting deeper than 8 levels is skipped.

9. **CJK script sharing:** kanji are shared between Japanese and Chinese, so a Chinese-language document may be detected as Japanese.
10. **kaleido 1.x requires Chrome/Chromium:** PDF report charts need a local Chrome/Chromium runtime when generated with kaleido 1.x.

11. **Control-syntax matching is surface-literal.** The audit lane matches a
   fixed vocabulary (literal substring by default, regex opt-in);
   paraphrased, spaced-out, or glyph-substituted instructions and
   non-listed phrases are out of scope. A finding records the surface
   pattern and its backing status — it is not evidence of intent

12. **Geometry thresholds are unit-scoped.** The geometry lane measures
   px and unitless lengths only (em/rem/%/pt are skipped), does not
   convert `scale()` percentage arguments, and does not descend into
   `@media` blocks; exponent notation and negative values are outside
   the observation scope.

13. **PDF geometry positions are un-composed.** The PDF subscan checks
   `Tm` operands of the un-transformed text space; relative moves
   (`Td`/`TD`/`T*`/`TL` accumulation) and the graphics CTM (`cm`) are
   not composed into the position, and same-color-as-background fills
   are not observed (future vocabulary).

14. **Schema gates refuse unknown keys.** The control-vocab and
   geometry-threshold documents reject fields outside Contract v1
   instead of ignoring them; a future producer must extend the
   contract explicitly. Duplicate keys / `NaN` / `Infinity` in vocab
   or thresholds files now fall back to the embedded defaults instead
   of being accepted with last-wins semantics.

15. **L1 guards the core extractor only.** `ReadLimits` and the
   closed-set refusals protect the core reading paths
   (`.txt`/`.md`/`.html`/`.htm`/`.docx`); the PDF, OCR, image-layer,
   and report extensions read through their own libraries
   (`pypdf`, `pytesseract`, `Pillow`, ...) and are outside L1
   (future L2/L3 scope). Refusal evidence is deliberately coarse —
   the code only — so identifying which part triggered a refusal
   requires re-examining the file with other tooling.

16. **H8 (geometry) is outside the 7-bit mask.** The mask stays
   `H1H2H3H4-H5H6H7` and never carries the geometry lane's findings;
   they are confirmed through the lane's own receipt
   (`audit_geometry` / `audit_pdf_geometry`), not through
   mask/h_states/evidence.

17. **pypdf versions drift in the pdf_images pins.** Measured band:
   with pypdf 6.6.0 the `TestPdfImagesFormInlinePins` count pin drifts
   (4 != 3 — fixture-side counting, not a library defect); with pypdf
   6.21.4 the whole suite is green. The CI pypdf pin stays open in the
   ledger.

18. **CSV/Excel inputs are not supported** (roadmap candidate). The
   engine reads `.txt`/`.md`/`.html`/`.htm`/`.docx` plus the optional
   PDF/image extensions; column-oriented formats need a column-role
   specification to be settled before they can be observed.

19. **DOCX concealment simplifications (declared, L2).** Toggle
   properties (`w:vanish`) resolve by plain override — the last
   explicit level wins — while ECMA-376 resolves toggles by XOR
   *between* style levels (first explicit value wins *within* a
   `basedOn` chain; docDefaults=true forces on). The two disagree only
   when the same toggle is explicit at more than one level. Table
   styles (conditional formatting) are not resolved; `w:w`,
   `w:spacing`, `w:position`, `w:fitText` concealment is not observed;
   `w:moveFromRangeStart/End` range-only deletions are not covered;
   whitespace-only concealed runs stay in the visible text; properties
   that cannot be resolved (pattern shading with fill ≠ colour,
   invalid values) are not claimed. Strict-OOXML-namespace documents
   still parse to an empty observation with `parsed successfully`
   (recorded — a follow-up patch release is expected to refuse them as
   unobserved).

20. **Some v0.19.1-accepted documents now refuse (intended, L2).** The
   three formatting parts (`word/styles.xml`, `word/theme/theme1.xml`,
   `word/settings.xml`) are now read through the same L1 bounds and
   the same 128 MiB budget: a malformed, DOCTYPE-carrying, encrypted
   or oversized auxiliary part now refuses with the corresponding L1
   code instead of being ignored. Documents without these parts (or
   with well-formed ones) are unaffected — non-target observations are
   byte-identical to v0.19.1 (pinned).

21. **Low-contrast threshold is its own integer rule (L2).** Detection
   uses D = |Y_fg − Y_bg| // 10000 < 20 on Rec.709 luma without gamma
   correction; the boundary pairs are ECECEC/white (D = 19, detected)
   and EBEBEB/white (D = 20, not detected). Light-gray watermarks
   (EBEBEB or lighter on white) are not detected by design. Highlight
   colours follow Word's rendering palette; ECMA-376's prose values
   for the dark*/gray names differ (CSS-derived) and are not used.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.

---

## 👤 Author

* **Kai IWASAKI**