# Sieve Lens v0.1.0

**Invisible Prompt Observation Engine**

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

| Format | Coverage |
|--------|----------|
| `.txt`, `.md` | Plain text, full character-level scanning |
| `.html`, `.htm` | HTML with inline-style concealment detection |
| `.docx` | Body, comments, core properties, **headers, footers, footnotes, endnotes** (v0.1) |

**Not supported in v0.1**: PDF, images, audio, video.

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
- **Self-contained HTML report** (v0.1)  
  Deterministic, no external resources, greppable `data-mask` attribute.

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

Or write the HTML report to a file:

from sieve_lens import write_report_html
write_report_html(obs, "report.html")

---

##🔬 Testing

# v0 test suite (26 tests)
python -m unittest discover -s tests -p "test_sieve_lens.py" -v

# v0.1 test suite (14 tests)
python -m unittest discover -s tests -p "test_sieve_lens_v0_1.py" -v

## Known Limitations (v0.1)
PDF and images are not supported. This is a deliberate scope decision.

Semantic intent is not evaluated. A visible but manipulative prompt is
outside the scope of this tool.

Only inline CSS is inspected. External stylesheets and CSS classes are
not resolved.

Character-table coverage is fixed. New invisible techniques require
updating the tables.

This is an observation engine, not a detector. Findings should always
be confirmed by human review.

---

##📄 License
MIT License. See LICENSE for details.

---

##👤 Author
Kai IWASAKI