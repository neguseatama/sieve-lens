# Changelog

<<<<<<< HEAD
## [0.0.1] - 2026-09-23
=======
## [0.1.0] - 2026-09-23
>>>>>>> 3cdf31d (release: v0.1.0 - DOCX header/footer/footnote support and HTML report)

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
<<<<<<< HEAD
- The engine is an observation tool, not a judgment engine.
- Zero runtime dependencies; standard library only.
- Deterministic across Python 3.9–3.12.
=======
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
>>>>>>> 3cdf31d (release: v0.1.0 - DOCX header/footer/footnote support and HTML report)
