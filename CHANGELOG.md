# Changelog

## [0.0.1] - 2026-09-XX

### Added
- Initial release of Sieve Lens v0
- 7-bit observation space (H1–H7)
- Support for `.txt`, `.md`, `.html`, `.htm`, `.docx`
- Deterministic zero-width density detection (H2)
- Bidi control character detection (H3)
- Inline CSS concealment detection (H4)
- Out-of-band channel detection for comments and metadata (H5)
- Homoglyph (Latin/Cyrillic, Latin/Greek) detection (H6)
- Contiguous invisible payload detection with best-effort decoding (H7)
- Human-readable observation report via `format_report()`
- 26-test suite covering all hypotheses and integration scenarios

### Design Notes
- The engine is an observation tool, not a judgment engine.
- Zero runtime dependencies; standard library only.
- Deterministic across Python 3.9–3.12.