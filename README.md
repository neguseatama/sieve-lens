**English** | [日本語](README.ja.md)

# Sieve Lens v0.8.0

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

## 📐 7-bit Observation Space

| Bit | Name | What it observes |
|-----|------|------------------|
| H1 | Parseability | The file can be read and parsed |
| H2 | Zero-Width Density | Density of zero-width chars exceeds threshold |
| H3 | Bidi Controls | Bidi control characters present |
| H4 | Format Concealment | CSS hiding rules (`display:none`, etc.) present |
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
| `.docx` | Body, comments, core properties, headers, footers, footnotes, endnotes | none (core) |
| `.pdf` | Body text, metadata, annotations, invisible text (Tr 3) | `pypdf` (optional) |
| `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.tif`, `.tiff`, `.webp` | Metadata (EXIF / PNG text / XMP) + OCR text | `Pillow`, `pytesseract` + tesseract binary (optional) |

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

---

## 📦 Installation

```bash
# Core (zero-dependency)
pip install git+https://github.com/neguseatama/sieve-lens.git

# With PDF support
pip install "git+https://github.com/neguseatama/sieve-lens.git#egg=sieve-lens[pdf]"

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

---

## 🔬 Testing

# v0 test suite (26 tests)
python -m unittest discover -s tests -p "test_sieve_lens.py" -v

# v0.1 test suite (14 tests)
python -m unittest discover -s tests -p "test_sieve_lens_v0_1.py" -v

# v0.2 PDF extension (7 tests, requires pypdf)
python -m unittest discover -s tests -p "test_sieve_lens_pdf.py" -v

---

## ⚠️ Known Limitations (v0.1)

1. **PDF and images are not supported.** This is a deliberate scope decision.
2. **Semantic intent is not evaluated.** A visible but manipulative prompt is
   outside the scope of this tool.
3. **Only inline CSS is inspected.** External stylesheets and CSS classes are
   not resolved.
4. **Character-table coverage is fixed.** New invisible techniques require
   updating the tables.
5. **This is an observation engine, not a detector.** Findings should always
   be confirmed by human review.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.

---

## 👤 Author

* **Kai IWASAKI**