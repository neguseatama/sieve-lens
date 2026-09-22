# Sieve Lens v0

**Invisible Prompt Observation Engine**

> Zero-dependency, deterministic, explainable observation of invisible content
> in documents (resumes, submissions, reports) that may be intended to
> influence AI-based evaluation systems.

Extends the [Sieve](https://github.com/neguseatama/sieve-core) series to the
domain of **machine-readable vs. human-visible divergence**.

---

## 💡 Concept

Modern AI evaluation systems parse documents as text.
Humans read documents as rendered output.
These two views are not the same, and the gap between them can be exploited:

- Zero-width characters (`U+200B`...) that a model reads but a human cannot see.
- CSS rules (`display:none`) that hide text from a human but not from a parser.
- Out-of-band channels (comments, metadata) that a parser reads but a human never sees.

**Sieve Lens observes this divergence.**  
It does not judge intent. It surfaces what is invisible, with location and
decoded content, so that a human can decide what to do.

---

## 📐 7-bit Observation Space

| Bit | Name | What it observes |
|-----|------|------------------|
| H1 | Parseability | The file can be read and parsed |
| H2 | Zero-Width Density | Density of zero-width chars exceeds threshold |
| H3 | Bidi Controls | Bidi control characters present |
| H4 | Format Concealment | CSS hiding rules (`display:none`, etc.) present |
| H5 | Out-of-Band Channel | Meaningful content in comments / metadata / hidden attrs |
| H6 | Script Mixing | Latin+Cyrillic or Latin+Greek mixed within a token |
| H7 | Contiguous Payload | A run of ≥ N contiguous invisible chars exists |

Mask format: `H1H2H3H4-H5H6H7` (e.g., `1101-101`).

---

## 📦 Supported Formats

- `.txt`, `.md` — plain text
- `.html`, `.htm` — HTML with inline-style concealment detection
- `.docx` — DOCX with body text, comments, and core properties

**Not supported in v0**: PDF, images, audio, video.

---

## 💻 Quick Start

```python
from sieve_lens import SieveLensEngine, format_report

engine = SieveLensEngine()
obs = engine.observe("resume.docx")

print(obs.mask)            # e.g. "1001-100"
print(obs.h_states)        # {'H1': 1, 'H2': 0, ..., 'H7': 0}
print(format_report(obs))  # human-readable observation report

---

##🔬 Testing
bash
python -m unittest discover -s tests -p "test_sieve_lens.py" -v
⚠️ Known Limitations (v0)
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
MIT License.

---

##👤 Author
Kai IWASAKI