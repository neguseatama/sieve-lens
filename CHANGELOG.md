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

# Changelog

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