# Changelog

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