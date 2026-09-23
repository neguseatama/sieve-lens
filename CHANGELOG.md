# Changelog

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