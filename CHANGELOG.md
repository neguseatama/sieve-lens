# Changelog

## [0.21.1] - 2026-11-05

### Changed
- **Public README refresh (en/ja): the known-limitations list was
  reorganized.** The 18-item list is now a 4-item "Good to know"
  section (observation-not-judgment, OCR language packs, DOCX
  Transitional-only, kanji shared with Chinese), and the requirement
  for PDF report charts (Chrome/Chromium with kaleido 1.x) moved to
  the installation section. The removed detail stays in `docs/`: the
  geometry measurement scope is consolidated in
  `docs/ARCHITECTURE.md` ("Geometry Observation Scope"), the
  character-table scope (fixed coverage, non-ASCII → ASCII twins) in
  `docs/CHARTABLE.md`, and the DOCX simplified-rule boundary and the
  Form XObject depth cap joined the Known Boundaries table. Facts,
  numbers and version claims are unchanged; code, tests (beyond the
  version pins) and bundled files are untouched.

## [0.21.0] - 2026-11-05

### Added
- **The pinned character table ships with Lens**: `chartable_v1.json`
  is the character table the Sieve tools share (schema
  `sieve-chartable/1`) — the invisible characters, the look-alike
  twins, the fullwidth ASCII range, the folding spaces and the folding
  dashes — and the copies in the other Sieve tools are pinned to these
  exact bytes by sha256
  (`c5ae4757bc9d07a2dcd1507d662460c3412c932d73318e54912569608242e605`,
  2,693 bytes). The file is carried inside the package (wheel and
  sdist, declared as package data). The loader verifies the sha256 pin
  on the exact bytes on every load and is fail-closed: a missing,
  tampered or malformed table is a hard error, never a silent
  fallback; every call returns a fresh dict, and the file is read
  lazily (importing the module opens nothing). The observation
  pipeline is unchanged in this version.

## [0.20.2] - 2026-11-05

### Fixed
- **Strict-OOXML documents are refused instead of silently unobserved**:
  a WordprocessingML part whose root element carries a namespace other
  than the transitional one (Strict OOXML, or any unknown namespace)
  parses fine but yields no observations at all — every run in it,
  hidden or not, would be missed. Such a part is now refused with the
  new refusal code `unsupported_namespace` (the closed set grows from
  12 to 13 codes; the evidence still carries the code only — never
  part names or content). The check covers the document part and the
  headers, footers, footnotes, endnotes, comments, styles and settings
  parts. A malformed part still refuses as `malformed_xml` first, a
  root element with an unexpected local name in the standard namespace
  keeps being observed, and an empty-but-valid document stays observed.
- **The Word highlight palette follows ECMA-376**: the `green`
  highlight now resolves to `00FF00`, as the standard's
  ST_HighlightColor prose specifies (it previously used the
  CSS-derived `008000`, which is `darkgreen`; `darkgreen` itself stays
  `008000`). A light-gray run on a green highlight is therefore
  resolved against the bright green and flagged as low-contrast now;
  all other palette values are unchanged, and the full 16-value
  palette is pinned in the test suite.

## [0.20.1] - 2026-11-04

### Changed
- **Public README refresh (en/ja)**: internal development information
  removed from the public surfaces; the L1/L2 capability sections now
  read as plain-language summaries. The deep technical detail remains
  in `docs/` (`SCHEMA_CONTRACT_v1.md`, `ARCHITECTURE.md`) and `SPEC.md`.
- **CHANGELOG alignment**: the [0.20.0] entry was aligned with the
  README limitations list and internal references were removed.
- **Version surfaces bumped to 0.20.1** (pyproject, `__version__`,
  module/engine docstrings, README titles en/ja); the version pin
  tests (L1 reading, L2 DOCX) follow.

### Security / Non-destruction
- Docs-only release: engine behavior unchanged from 0.20.0 — the only
  source differences are version strings. Frozen files (`schema.py`,
  `control_syntax.py`, `geometry.py`, `redact_bridge.py`) untouched,
  zero dependency changes. Receipts and reports recorded with 0.20.0
  stay reproducible.

## [0.20.0] - 2026-11-04

### Added
- **DOCX concealment observation (L2)**: the DOCX extractor resolves
  the effective run formatting (docDefaults → paragraph style chain →
  character style chain → direct formatting, memoized per style id)
  and splits runs a human reader would not see out of the visible text
  into `docx_hidden` segments (`visible=False`), with the closed
  reason vocabulary `CONCEALMENT_REASONS = ("vanish", "low_contrast",
  "tiny_font", "tracked_deletion")`: hidden-text formatting, near-
  invisible colour (Rec.709 luma step D < 20, evidence carries the
  resolved colours and source), `w:sz`/`w:szCs` ≤ 2 half-points, and
  text inside `w:del` / `w:moveFrom` (or `w:delText` outside `w:del`).
  Whitespace-only concealed runs stay in the visible text; adjacent
  same-reason runs merge into one segment.
- **H4 condition extension (the one declared mask-assembly change)**:
  `docx_hidden` segments fire H4 (Format Concealment) alongside the
  HTML `css_hidden` segments, and their text joins `body_text` like
  `css_hidden`, so H2/H3/H6/H7 keep scanning it (detection never
  decreases). `OOB_KINDS` (H5) is unchanged.
- **Formatting sources**: `word/styles.xml`, `word/theme/theme1.xml`
  and `word/settings.xml` are read through the same L1 bounds and the
  same budget (absent is normal; malformed/encrypted/oversized/
  DOCTYPE refuses with the L1 code). Theme colours resolve through
  `w:clrSchemeMapping` and the theme part; backgrounds resolve
  highlight-first (Word's palette), then run / paragraph / cell
  shading, then the page background (only with
  `w:displayBackgroundShape`), then white.
- **Tests**: `tests/test_sieve_lens_l2_docx.py` (61 methods),
  with non-destruction verified against v0.19.1 before the change.
  Suite: 356 -> 417 (+61).

### Changed
- **Thresholds fixed (2026-11-04)**: low-contrast
  D < 20 with the confirmed boundary pairs (ECECEC/white detected at
  D = 19, EBEBEB/white not at D = 20); tiny font `w:sz`/`w:szCs` ≤ 2
  half-points (≤ 1 pt); highlight beats shading (ECMA-376 §17.3.2.15);
  `w:shd` `nil` falls through; `w:themeColor` wins over `w:val` unless
  `themeTint`/`themeShade` is present. The geometry thresholds and
  their digest are untouched.
- **Existing test**: the unread-encrypted-entry fixture moved from
  `word/settings.xml` (now a read part) to `word/numbering.xml`; the
  L1 version pin moved to 0.20.0.
- **Docs**: README en/ja gain the L2 feature section and known
  limitation 18 (declared simplifications); `docs/ARCHITECTURE.md`
  reflects the extended DOCX extractor model.

### Security / Non-destruction
- Non-target observations are byte-identical to v0.19.1 (verified on
  five sample documents). Frozen files (`schema.py`,
  `control_syntax.py`, `geometry.py`, `redact_bridge.py`), the refusal
  code set (12), `ReadLimits`, the vocabulary and geometry digests and
  the Schema Contract corpus are unchanged; zero new dependencies.


## [0.19.1] - 2026-11-04

### Added
- **Version-consistency guard extension**: the README title lines
  (en/ja) and the `sieve_lens.py` module / `SieveLensEngine` docstrings
  are now pinned to `__version__`. At 0.19.0 the READMEs read v0.17.0
  and the docstrings v0.2.0 while the package published as 0.19.0; the
  guard fails before the next release can repeat that.
- **`docs/ARCHITECTURE.md` reality refresh**: the title no longer carries
  a version, the boundary table reflects the extension reality (PDF via
  `pypdf`, images/OCR via the Pillow/pytesseract extras, external CSS
  local-only), and an H8 note documents that the geometry lane runs
  beside the pipeline and stays outside the 7-bit mask.
- **Known limitations 16-18 (en/ja)**: H8 is outside the mask, the
  measured pypdf drift band for the `pdf_images` count pins (6.6.0
  drifts, 6.21.4 green), and CSV/Excel inputs as roadmap candidates.

### Changed
- **CHANGELOG structure repair**: `# Changelog` H1 moved to the top of
  the file (it sat mid-file after the 0.11.0 section), and a new
  `MANIFEST.in` ships `CHANGELOG.md` in the sdist.
- **Tests**: `TestPdfFormText` / `TestPdfFormWalk` are skipped when pypdf
  is absent instead of erroring (previously a bare failure in
  extension-less environments). Suite: 353 -> 356 (+3 version-guard
  methods); the L1 version pin moved to 0.19.1.

### Security / Non-destruction
- No functional engine changes: frozen files (`schema.py`,
  `control_syntax.py`, `geometry.py`, `redact_bridge.py`) are untouched,
  zero new dependencies. Receipts and reports recorded before v0.19.1
  stay reproducible.


## [0.19.0] - 2026-11-03

### Added
- **Bounded document reading (L1: safe reading)**: `ReadLimits`, a
  frozen dataclass pinning five positive-integer budgets —
  `max_file_bytes` 64 MiB, `max_entries` 10000, `max_part_bytes` 32 MiB,
  `max_total_bytes` 128 MiB, `max_elements` 1000000 — with
  `SieveLensEngine(read_limits=...)` as an optional override; existing
  calls construct the defaults unchanged. Every value must be a
  positive integer (`ValueError` otherwise).
- **Closed-set refusals**: `ExtractionRefused` carries a `code` from
  `REFUSAL_CODES` — 12 codes: `not_regular_file`, `file_too_large`,
  `too_many_entries`, `part_too_large`, `total_too_large`,
  `too_many_elements`, `doctype_not_allowed`, `unsupported_encoding`,
  `duplicate_part`, `encrypted`, `malformed_xml`, `main_part_missing`.
  `observe()` turns a refusal into a null observation with evidence
  `Extraction refused: <code>` (H1 = 0, mask `0000-000`). Refusal
  evidence carries the code only — never part names, document content,
  or paths.

### Changed
- **.docx reading is bounded and pre-checked**: regular-file/size
  gate, entry-count and case-insensitive duplicate-part refusals,
  per-part encrypted-flag and declared-size checks, chunked
  decompression capped at `max_part_bytes`, per-call total budget,
  pre-parse refusal of UTF-16/DOCTYPE/ENTITY and of parts beyond
  `max_elements`, and `ET.fromstring` on bounded bytes only. An
  unreadable read-part is now `malformed_xml` and a missing
  `word/document.xml` is `main_part_missing` (H1 = 0) instead of a
  silent empty result behind "parsed successfully"; absent optional
  parts stay normal.
- **.txt/.md/.html/.htm reading is gated**: `os.stat` gate (regular
  file, `max_file_bytes`) before a bounded text-mode read that keeps
  universal-newline translation identical to `read_text`.

### Security / Non-destruction
- Zip bombs (including lying declared sizes) are refused bounded —
  memory stays capped with H1 = 0; billion-laughs and external
  entities are refused unexpanded; UTF-16 documents are refused before
  decoding.
- Receipts and reports recorded before v0.19.0 stay reproducible:
  accepted inputs are byte-identical to v0.18.0 (pinned in tests),
  the embedded vocab/thresholds content digests are unchanged
  (`27734e17…6fbf`, `70f2bdb5…4540`), the conformance corpus is
  unchanged, and the frozen files (`schema.py`, `control_syntax.py`,
  `geometry.py`, `redact_bridge.py`) are untouched.
- Zero new dependencies (`os`/`stat` are stdlib).

### Tests
- 292 → 353 (+61): ReadLimits defaults/frozenness/
  validation, byte-identity pins on accepted inputs, zip-bomb and
  lying-size boundedness (tracemalloc), file/entries/total/element
  limits, DOCTYPE/ENTITY/encoding refusals, duplicate and encrypted
  parts, unreadable-vs-absent parts, .txt/.md/.html gates and CRLF
  identity, refusal-evidence hygiene, digest/corpus/frozen-file pins,
  and the 0.19.0 version assertion. Existing tests are otherwise
  unchanged.

## [0.18.0] - 2026-11-01

### Added
- **Sieve Schema Contract v1** (`docs/SCHEMA_CONTRACT_v1.md`): the
  declared contract shared by the Sieve tools' JSON gates, with the
  canonical zero-dependency engine `sieve_lens_ext/schema.py` —
  strict JSON layer (duplicate keys, `NaN`/`Infinity`, UTF-8 BOM,
  1 MiB cap) plus a 12-key mini-validator vocabulary (type / required /
  enum / min / max / min_len / max_len / item_type / item_schema /
  keys / cross / validator; no coercion, unknown keys refused,
  RFC 6901 JSON Pointer errors, recursion bounded by schema depth).
- **Conformance corpus**: 44 accept/reject cases
  (`tests/corpus/schema_contract_v1.json`) pinning the contract,
  replicated into the Redact and Crowd test suites with a sha256 pin
  (sieve-tray vendor-sync precedent).

### Changed
- **validate/build separation**: the control-vocab and
  geometry-threshold gates now split into a pure `validate_*`
  (structural check, `SchemaError` with a JSON Pointer) and a
  `build_*` step (default filling, regex compilation, content
  digest). `_validate_vocab`/`_validate_thresholds` are replaced by
  `validate_control_vocab`/`build_control_vocab` and
  `validate_thresholds`/`build_thresholds`.
- **Gatekeeper behavior changes** (documented in README known
  limitation 14): unknown keys in vocab/threshold documents are
  refused instead of silently ignored, `version`/`lane` must be
  strings when present, and duplicate keys / `NaN` / `Infinity` in
  vocab/threshold files now fall back to the embedded defaults
  instead of being accepted (last-wins) or raising.
- **Receipt non-destruction**: the embedded vocab and thresholds
  content digests are unchanged by the refactor
  (`27734e17…6fbf`, `70f2bdb5…4540`, pinned in tests), so receipts
  recorded before v0.18.0 stay reproducible.

### Tests
- 254 → 292 (+38): corpus runner (integrity pin, JSON layer, schema
  layer with pointer pins, engine pins for bounded recursion,
  iterative arrays, NaN fail-closed, validator hooks) and gate
  integration tests (digest non-destruction, JSON-layer fallbacks,
  gatekeeper refusals, validate/build separation, schema
  self-conformance).

## [0.17.0] - 2026-10-31

### Added
- **Control-syntax audit lane**: a dedicated observation lane for
  AI prompt-boundary control markup (system / role / tool fences and
  model-facing directives embedded in documents). Matching is
  surface-literal; findings are reported in the lane's own receipt
  (known limitation 11). `control_vocab_sha256` now digests the vocab
  content itself instead of its source label, so identical vocab sets
  hash identically regardless of origin.
- **Geometry concealment lane (HTML subscan)**: observes text hidden by
  geometric CSS — `font-size: 0/0.1px`, `opacity: 0`,
  `transform: scale(0)`, `line-height: 0` — and reports it as H8 with
  per-technique threshold observation and evidence
  (known limitation 12).
- **Geometry concealment PDF subscan**: stream scanning also observes
  render mode 3 (`/Tr 3`), extremely small `Tf` font sizes, and
  out-of-bounds `Tm` text positions as H8 concealment signals
  (known limitation 13).

### Changed
- README maintenance: the Sieve series table lists all eight canonical
  engines (Core / Referee / Scope / Lens / Redact / Order / Crowd /
  Tray) with their canonical one-line descriptions, and a stray
  horizontal rule that split the Key Features list after the v0.10
  entry (rendering later bullets as an orphan list) is removed.

## [0.16.0] - 2026-10-13

### Changed
- README maintenance: the core install line is normalized to the PyPI
  form (`pip install sieve-lens`); the Testing section drops the stale
  per-suite counts and shows the full pytest invocation first; known
  limitations add item 9 (CJK script sharing in i18n) and item 10
  (kaleido 1.x requires Chrome/Chromium).
- CI symmetry: the CI Pipeline OCR step installs tesseract-ocr-jpn, so
  the Japanese OCR integration test runs in the matrix pipeline instead
  of being skipped there.
## [0.15.0] - 2026-10-12

### Added
- **PDF Form XObject text scanning**: text inside Form XObject content
  streams is scanned with the same semantics as page content streams.
  Tr 3 (invisible) text reports as hidden text (H4) with the form name in
  the evidence location, and text-showing operands rescue zero-width/bidi
  characters that standard extraction drops (H7). Every form declared in a
  page's resources is covered (drawn or not); the walk is protected against
  cyclic references and caps nesting depth at 8.
- Regression pins: PDF form-internal and inline images reach the image
  analysis pipeline (pypdf 6.19.0 `page.images` enumerates both), including
  a form-internal SMask image triggering H4 end-to-end.

### Changed
- pdf_images docstring corrected: pypdf 6.19.0 enumerates form-internal and
  inline images, so the earlier "not enumerated" note no longer matched
  reality.
- The new PDF image pins are skipped when Pillow is absent (the CI Pipeline
  installs Pillow in a later step); the full-dependency workflow still runs
  them.
- Tests: 167 passed / 12 skipped / 5 subtests locally (previously 159 / 12).
- README known-limitations corrected: item 1 (stale "PDF and images are not supported") now states the observation role split with Sieve Redact, and the form-nesting item moved back into the numbered list.

## [0.14.0] - 2026-10-12

### Added
- **OCR language selection**: `install(engine, ocr_lang=...)` accepts
  tesseract-style language strings (default `eng`), validated at install
  time; Japanese (`jpn`) integration test with a committed fixture.

### Changed
- **Enforced low-contrast gate**: low-contrast detection now requires at
  least 8 distinct non-background gray levels to fire (shared with the PDF
  image pipeline); single-color blobs and two-level noise no longer trigger.
- README revisions: OCR quickstart, dependency notes, known-limitations
  entries, and repaired code fences.

## [0.13.0] - 2026-10-09

### Changed
- **redact_bridge homoglyph twins** expanded from 40 to 102 entries
  (full-width digits and letters; the core observation space is unchanged).

## [0.12.0] - 2026-10-08

### Added
- **redact_bridge** (`sieve_lens_ext/redact_bridge.py`): deterministic,
  stdlib-only catalog exporter for Sieve Redact's `--from-lens`. Emits the
  v1 catalog format (`lens` / `version` / `observations[]` with `kind`,
  `codepoint`, `count`, `positions`) plus an optional `twin` field for
  look-alike letters (Cyrillic/Greek -> Latin, 40 entries). Redact turns
  twins into replacement rules and invisible characters into deletions.
  Imports the core character tables (ZERO_WIDTH / BIDI_CONTROL / INVISIBLE /
  strip_leading_bom) so the bridge can never diverge from the engine.
  CLI: `python -m sieve_lens_ext.redact_bridge IN.txt OUT.json`.
- `probe_redact_roundtrip.py`: end-to-end probe (synthetic input -> catalog
  -> Redact --from-lens -> engine re-observe: H2/H3/H7 = 0).
- 10 new tests (`tests/test_redact_bridge.py`): 144 passed / 11 skipped
  locally.

### Changed
- Repository hygiene: the local virtualenv and audit artifacts are no longer
  tracked.


## [0.11.0] - 2026-10-06

### Fixed (verified end-to-end)
- **pdf_images**: `extract()` called an undefined `_get_page_images()` and the
  combined extractor silently swallowed the error — v0.10.0 PDF embedded image
  analysis never worked. Implemented via pypdf's `page.images`; the loader now
  prefers pypdf's decoder (which composites /SMask into alpha and preserves
  the RGB of invisible pixels); text-extraction failures now propagate (H1=0)
  instead of being silenced.
- **html_css_selectors (v0.8)**: document body text was never emitted,
  disabling H2/H3/H6/H7 detection for HTML entirely. Body text is now emitted
  with ancestor hidden-state inheritance; selector evidence reports the real
  match count.
- **ocr**: the EXIF SubIFD (IFD 0x8769) is now scanned — UserComment
  (tag 37510), the primary metadata injection point, was previously never read.
- **core (HTML)**: hidden state now inherits from ancestors; the bare
  `hidden` attribute is detected; void elements no longer leak hidden state
  to following text nodes.
- **core**: Variation Selectors Supplement (U+E0100–E01EF) added to the
  INVISIBLE set (H2/H7).
- **security**: dashboard and PDF report enable Jinja2 autoescape — content
  from untrusted documents (e.g. comments carrying event handlers) can no
  longer inject HTML/JS into reports; `input_dir` double-escaping removed.
- **pdf_report**: fixed `dcterms.created`/`dcterms.modified` meta tags and a fixed PDF /ID (via a write_pdf finisher) make the PDF
  byte-deterministic (weasyprint previously embedded the current time,
  contradicting the "no timestamps" statement).
- **pdf_report/tests**: weasyprint's import guard now catches `OSError`
  (missing pango raises OSError, not ImportError — tests crashed at
  collection on such systems).
- **ocr tests**: skip when the tesseract *binary* is absent (previously
  failed on systems with the pytesseract package but no binary).
- **html_css (v0.4)**: symmetric push/pop for style/script tags; multiple
  `<style>` blocks and multiple `<link rel=stylesheet>` hrefs are all
  processed; `display:none !important` is no longer skipped; P2 semantics
  (inheritance, void elements, bare `hidden`) applied; the
  `resolve_local_links` argument of `install()` is now honored.

### Added
- `SieveLensEngine.get_extractor()` — public accessor enabling chained
  extension installs; `sieve_lens_ext.image_layers.install()` now chains
  onto the existing image extractor (honoring the "install both to
  combine" contract) instead of replacing it.
- dashboard `_build_engine` now installs all extensions (v0.7 image layers,
  v0.8 full selectors, v0.10 pdf images become active in batch tools).

### Changed
- i18n: hypothesis chart labels follow the report language; the PDF report
  footer prints the real package version instead of a hardcoded 0.9.0;
  the duplicate i18n `__version__` was removed.
- image_layers: transparent-layer and histogram analysis are C-accelerated
  via Pillow channel ops (large images no longer require pure-Python
  O(W×H) loops); palette transparency (GIF / indexed PNG tRNS) is now
  recognized.

### Docs
- `_LOW_CONTRAST_MIN_UNIQUE` documented as informational (not enforced).

## [0.10.0] - 2026-09-24

### Added
- **PDF embedded image analysis** (optional extension)
  `sieve_lens_ext.pdf_images.install(engine)` extracts images embedded
  in PDF pages and applies:
  - **Transparent layer detection** → H4
  - **Low-contrast detection** → H4
  - **OCR text extraction** → body (H2/H3/H6/H7)
  - **Image metadata** (EXIF / PNG text / XMP) → H5
- Images smaller than 50x50 pixels are skipped (logos, icons).
- Duplicate images (same pixel content) are processed once.
- Processing is capped at 200 images per PDF (defensive).
- New optional-dependency group: `pip install sieve-lens[pdf-images]`.

### Design Notes
- The core library (`sieve_lens.py`) remains zero-dependency.
- The `.pdf` extractor is replaced with a combined extractor that runs
  both the text-based extractor (v0.2) and the new image extractor.
- Each segment carries `page N, image #M (WxH)` for traceability.
- The 7-bit observation space is unchanged.

## [0.9.0] - 2026-09-24

### Added
- **Report internationalization (i18n)**: English and Japanese
  `sieve_lens_ext.i18n` provides translation dictionaries for the
  dashboard and PDF report templates.
- `build_dashboard(..., lang="auto")` and `build_pdf_report(..., lang="auto")`
  auto-detect the language from the input documents (character-script
  based detection).
- `lang="en"` or `lang="ja"` forces a specific language.

### Design Notes
- The core library (`sieve_lens.py`) remains zero-dependency.
- i18n uses embedded dictionaries; no external i18n libraries.
- The language detector is script-based (Hiragana/Katakana/Kanji vs
  Latin letters), not a general-purpose classifier.
- The 7-bit observation space is unchanged.

## [0.8.0] - 2026-09-24

### Added
- **Full CSS selector resolution via `cssselect2`** (optional extension)
  `sieve_lens_ext.html_css_selectors.install(engine)` replaces the
  simplified ID/class/tag matcher from v0.4 with full selector matching.
- Supported selectors:
  - Descendant (`div p`), child (`div > p`)
  - Adjacent sibling (`h1 + p`), general sibling (`h1 ~ p`)
  - Attribute selectors (`[data-x]`, `[href^='http']`)
  - Pseudo-classes (`:first-child`, `:nth-child()`, `:not()`)
- **Hidden rules are only reported when the selector matches at least
  one element**, reducing false positives.
- New optional-dependency group: `pip install sieve-lens[html-css-full]`.

### Design Notes
- The core library (`sieve_lens.py`) remains zero-dependency.
- v0.8 is a strict superset of v0.4; both extractors can coexist, and
  the one installed last takes effect for `.html`/`.htm`.
- The 7-bit observation space is unchanged.

## [0.7.0] - 2026-09-23

### Added
- **Image layer analysis** (optional extension, same dependency as OCR)
  `sieve_lens_ext.image_layers.install(engine)` detects pixel-level
  concealment in image files.
- **Transparent layer detection (H4):** RGBA images with alpha=0 pixels
  that carry non-zero RGB values (invisible payload).
- **Low-contrast detection (H4):** foreground/background luminance gap
  below WCAG 2:1 ratio, with at least 1% of pixels in the dark cluster.
- Both detections surface as `kind="css_hidden"`, reusing the existing
  H4 observation channel.

### Design Notes
- The core library (`sieve_lens.py`) remains zero-dependency.
- The extension reuses the same `.png`, `.jpg`, etc. extensions as the
  OCR extension; install both to combine pixel-level and metadata
  analysis.
- Detection thresholds are fixed constants, preserving determinism.
- The 7-bit observation space is unchanged.

## [0.6.0] - 2026-09-23

### Added
- **Printable PDF report generation via `weasyprint`** (optional extension)
  `sieve_lens_ext.pdf_report.build_pdf_report()` scans a directory, runs
  observations, and writes an A4 PDF report.
- Report contents:
  - Executive summary (total / clean / flagged / unparsed)
  - Hypothesis activation table
  - Mask distribution table
  - Detailed file list with H1–H7 badges and evidence summaries
  - Optional PNG charts (requires `kaleido`)
- Deterministic output: fixed PDF metadata, sorted files, no timestamps.
- New optional-dependency group: `pip install sieve-lens[pdf-report]`.

### Design Notes
- The core library (`sieve_lens.py`) remains zero-dependency.
- weasyprint requires system libraries (Pango, Cairo) at install time.
- Charts are rendered to PNG via `kaleido` and embedded as images.
- The 7-bit observation space is unchanged.

## [0.5.0] - 2026-09-23

### Added
- **Interactive HTML dashboard via `Jinja2` + `Plotly`** (optional extension)
  `sieve_lens_ext.dashboard.build_dashboard()` scans a directory, runs
  observations in parallel, and writes a single self-contained HTML file.
- Dashboard features:
  - Summary cards (total / clean / flagged / unparsed files)
  - Mask distribution bar chart (color-coded)
  - Hypothesis activation bar chart
  - File extension breakdown pie chart
  - Sortable, color-coded file table with evidence summaries
- `standalone` option: embed Plotly.js inline (~3MB) for offline use,
  or load from CDN for a compact file.
- New optional-dependency group: `pip install sieve-lens[dashboard]`.

### Design Notes
- The core library (`sieve_lens.py`) remains zero-dependency.
- The dashboard is deterministic: files are sorted by path, mask counts
  are sorted, and Plotly div IDs are fixed.
- No timestamps are included in the HTML output.
- The 7-bit observation space is unchanged.

## [0.4.0] - 2026-09-23

### Added
- **HTML external CSS resolution via `tinycss2`** (optional extension)
  `sieve_lens_ext.html_css.install(engine)` replaces the built-in HTML
  extractor with a CSS-aware one.
- Resolves `<style>` blocks within the HTML document.
- Resolves `<link rel="stylesheet" href="...">` when the href points to
  a **local file**. Remote URLs (`http://`, `https://`, `data:`,
  `javascript:`) are ignored for security.
- Detects CSS hiding patterns:
  - `display: none`, `visibility: hidden`, `opacity: 0`
  - `font-size: 0`, `text-indent: -NNNN+`
  - off-screen positioning (`left/top/right/bottom: -NNNN+`)
  - `clip: rect(0,0,0,0)`, `clip-path: inset(100%)`
- New optional-dependency group: `pip install sieve-lens[html-css]`.

### Design Notes
- The core library (`sieve_lens.py`) remains zero-dependency.
- CSS hiding is surfaced as H4 (Format Concealment).
- Selector matching is simplified: ID, class, and tag selectors are
  matched against element attributes. Complex selectors are reported
  with their raw text but not fully resolved.
- Remote stylesheets are never fetched, preserving determinism and
  avoiding SSRF risks.
- The 7-bit observation space is unchanged.

## [0.3.0] - 2026-09-23

### Added
- **Image OCR support via `Pillow` + `pytesseract`** (optional extension)
  `sieve_lens_ext.ocr.install(engine)` attaches image handling for
  `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.tif`, `.tiff`, `.webp`.
- Extracts image metadata:
  - EXIF text tags (ImageDescription, UserComment, XP* tags, etc.)
  - PNG `tEXt` / `iTXt` / `zTXt` chunks
  - XMP packets
- Extracts OCR text via Tesseract.
- New optional-dependency group: `pip install sieve-lens[ocr]`.

### Design Notes
- The core library (`sieve_lens.py`) remains zero-dependency.
- Image metadata is surfaced as H5 (Out-of-Band Channel).
- OCR text is surfaced as body text; zero-width and bidi control
  characters cannot be recovered by OCR and are therefore documented
  as metadata-only vectors for images.
- The 7-bit observation space is unchanged.

## [0.2.0] - 2026-09-23

### Added
- **PDF support via `pypdf`** (optional extension)
  `sieve_lens_ext.pdf.install(engine)` attaches `.pdf` handling.
- Extracts PDF metadata, page text, annotations, and invisible text
  (rendering mode `Tr 3`).
- New public `Extractor` protocol and `SieveLensEngine.register_extractor()`
  method for user-defined extractors.
- New optional-dependency groups in `pyproject.toml`:
  `pip install sieve-lens[pdf]` and `[all]`.

### Design Notes
- The core library (`sieve_lens.py`) remains zero-dependency.
- Extensions are opt-in and isolated in the `sieve_lens_ext` package.
- The 7-bit observation space is unchanged.
- PDF invisible text is mapped to H4 (Format Concealment), reusing the
  existing `css_hidden` kind.
- `pypdf`'s standard `extract_text()` drops zero-width and bidi control
  characters due to font encoding (WinAnsi). The extension additionally
  parses the raw content stream to preserve those characters for H2/H3/H7.

## [0.1.0] - 2026-09-23

### Added
- DOCX extraction now covers `word/headerN.xml`, `word/footerN.xml`,
  `word/footnotes.xml`, and `word/endnotes.xml`.
- New self-contained HTML report generator: `format_report_html()`,
  `write_report_html()`.
- New invisible-character rendering helpers: `render_markers_html()`,
  `render_markers_text()`.

### Changed
- `H5` (Out-of-Band Channel) now includes header, footer, footnote, and
  endnote segments. This reflects the observation that these are visible
  but easy to overlook for humans, while being read unconditionally by
  AI parsers.
- Footnote/endnote separators (`w:type="separator"`) are explicitly ignored.

### Design Notes
- The 7-bit observation space is unchanged. v0.1 is a strict superset of
  v0.0.1.
- The HTML report is deterministic and self-contained: no timestamps,
  no external resources, no randomness.
- All 26 v0 tests continue to pass without modification.

## [0.0.1] - 2026-09-23

### Added
- Initial release of Sieve Lens
- 7-bit observation space (H1–H7)
- Support for `.txt`, `.md`, `.html`, `.htm`, `.docx`
- 26-test suite covering all hypotheses and integration scenarios