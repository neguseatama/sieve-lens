"""
Sieve Lens PDF report extension.

Generates a printable PDF report from a directory of documents.
Reuses the observation results from the dashboard extension.

Features:
  - Executive summary (total / clean / flagged / unparsed)
  - Hypothesis activation table
  - Mask distribution (chart if kaleido is available)
  - Detailed file list with H1–H7 badges
  - Deterministic output (fixed PDF metadata, sorted files)

Requires:
  - weasyprint >= 60.0
  - (optional) kaleido >= 0.2 and Plotly >= 5.0 for chart embedding

System dependencies (weasyprint):
  - macOS: brew install pango (Homebrew required)
  - Ubuntu/Debian: apt-get install libpango-1.0-0 libpangoft2-1.0-0
  - Fedora: dnf install pango

Install with:
    pip install sieve-lens[pdf-report]

Usage:
    from sieve_lens_ext.pdf_report import build_pdf_report

    build_pdf_report(
        input_dir="submissions/",
        output_path="report.pdf",
        include_charts=True,
    )
"""

from __future__ import annotations

import html
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence

try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False

try:
    import plotly.graph_objects as go
    import plotly.io as pio
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

try:
    import kaleido  # noqa: F401
    KALEIDO_AVAILABLE = True
except ImportError:
    KALEIDO_AVAILABLE = False

from sieve_lens import Observation
from sieve_lens_ext.dashboard import (
    _HYPOTHESES,
    _HYPOTHESIS_LABELS,
    _DEFAULT_EXTENSIONS,
    scan_directory,
    analyze_batch,
    build_summary,
    DashboardSummary,
)


# ----------------------------------------------------------------------
# Chart rendering (optional, requires kaleido)
# ----------------------------------------------------------------------

def _render_mask_chart_png(summary: DashboardSummary, path: Path) -> bool:
    """Render the mask distribution chart as PNG. Return True on success."""
    if not (PLOTLY_AVAILABLE and KALEIDO_AVAILABLE):
        return False
    masks = list(summary.mask_counts.keys())
    counts = [summary.mask_counts[m] for m in masks]
    colors = []
    for m in masks:
        if m.startswith("0"):
            colors.append("#b0b0b0")
        elif m == "1000-000":
            colors.append("#22863a")
        else:
            colors.append("#d73a49")

    fig = go.Figure(
        data=[go.Bar(
            x=masks, y=counts,
            marker_color=colors,
            text=counts, textposition="auto",
        )]
    )
    fig.update_layout(
        title="Mask Distribution",
        xaxis_title="Mask",
        yaxis_title="Files",
        margin=dict(l=50, r=20, t=50, b=80),
        width=700, height=380,
        font=dict(size=11),
    )
    try:
        fig.write_image(str(path), format="png", scale=2)
        return True
    except Exception:
        return False


def _render_hypothesis_chart_png(summary: DashboardSummary, path: Path) -> bool:
    if not (PLOTLY_AVAILABLE and KALEIDO_AVAILABLE):
        return False
    labels = [_HYPOTHESIS_LABELS[h] for h in _HYPOTHESES]
    values = [summary.hypothesis_counts.get(h, 0) for h in _HYPOTHESES]
    colors = ["#0366d6" if h == "H1" else "#d73a49" for h in _HYPOTHESES]

    fig = go.Figure(
        data=[go.Bar(
            x=labels, y=values,
            marker_color=colors,
            text=values, textposition="auto",
        )]
    )
    fig.update_layout(
        title="Hypothesis Activation",
        xaxis_title="Hypothesis",
        yaxis_title="Files with H = 1",
        margin=dict(l=50, r=20, t=50, b=100),
        width=700, height=380,
        font=dict(size=11),
    )
    try:
        fig.write_image(str(path), format="png", scale=2)
        return True
    except Exception:
        return False


# ----------------------------------------------------------------------
# HTML template for PDF
# ----------------------------------------------------------------------

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Sieve Lens Observation Report</title>
<style>
@page {
  size: A4 portrait;
  margin: 18mm 14mm 16mm 14mm;
  @bottom-center {
    content: "Sieve Lens Observation Report — page " counter(page) " / " counter(pages);
    font-size: 8pt;
    color: #888;
  }
}
body {
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size: 10pt;
  color: #1a1a1a;
  line-height: 1.4;
}
h1 { font-size: 18pt; margin: 0 0 4mm 0; }
h2 { font-size: 12pt; margin: 6mm 0 2mm 0; border-bottom: 1px solid #ccc; padding-bottom: 1mm; }
h3 { font-size: 10pt; margin: 4mm 0 2mm 0; }

.header-meta {
  font-size: 9pt;
  color: #555;
  margin-bottom: 4mm;
}
.header-meta code { background: #f5f5f5; padding: 0 2px; }

.statement {
  font-style: italic;
  color: #444;
  border-left: 3px solid #0366d6;
  padding-left: 4mm;
  margin: 4mm 0;
}

table {
  width: 100%;
  border-collapse: collapse;
  margin: 2mm 0;
  font-size: 9pt;
}
th, td {
  text-align: left;
  padding: 1.5mm 2mm;
  border-bottom: 0.5pt solid #ddd;
}
th {
  background: #f0f0f0;
  font-weight: 600;
}
tr.flagged { background: #fff5f5; }
tr.unparsed { background: #f5f5f5; color: #888; }

.summary-grid {
  display: table;
  width: 100%;
  margin: 3mm 0;
  border-collapse: separate;
  border-spacing: 3mm 0;
}
.summary-card {
  display: table-cell;
  width: 25%;
  border: 0.5pt solid #ddd;
  border-radius: 2mm;
  padding: 3mm;
  background: #fafafa;
}
.summary-label { font-size: 8pt; color: #777; }
.summary-value { font-size: 16pt; font-weight: 600; margin-top: 1mm; }
.summary-card.warn .summary-value { color: #d73a49; }
.summary-card.ok   .summary-value { color: #22863a; }

.mask {
  font-family: "SF Mono", Menlo, Consolas, monospace;
  font-weight: 600;
}
.mask-flag { color: #d73a49; }
.mask-clean { color: #22863a; }
.mask-unparsed { color: #888; }

.badge {
  display: inline-block;
  padding: 0.5mm 1.2mm;
  margin: 0 0.5mm;
  border-radius: 1mm;
  font-size: 7pt;
  font-family: "SF Mono", Menlo, Consolas, monospace;
}
.badge.on { background: #d73a49; color: white; }
.badge.off { background: #eee; color: #999; }

.file-list td.file { font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 8pt; }
.file-list td.evidence { font-size: 8pt; color: #555; }

.chart-img { max-width: 100%; margin: 2mm 0; }

footer-note {
  display: block;
  margin-top: 8mm;
  padding-top: 3mm;
  border-top: 1px solid #ccc;
  font-size: 8pt;
  color: #666;
}
</style>
</head>
<body>

<h1>Sieve Lens Observation Report</h1>

<div class="header-meta">
  Source: <code>{{ input_dir }}</code><br>
  Files scanned: {{ summary.total_files }} &mdash;
  Parsed: {{ summary.parsed_files }} &mdash;
  Clean: {{ summary.clean_files }} &mdash;
  Flagged: {{ summary.flagged_files }} &mdash;
  Unparsed: {{ summary.unparsed_files }}
</div>

<p class="statement">
  This is an observation report, not a judgment of intent.
  Human review is required to determine whether the detected invisible
  content is legitimate or abusive.
</p>

<h2>Summary</h2>

<div class="summary-grid">
  <div class="summary-card">
    <div class="summary-label">Total Files</div>
    <div class="summary-value">{{ summary.total_files }}</div>
  </div>
  <div class="summary-card ok">
    <div class="summary-label">Clean</div>
    <div class="summary-value">{{ summary.clean_files }}</div>
  </div>
  <div class="summary-card warn">
    <div class="summary-label">Flagged</div>
    <div class="summary-value">{{ summary.flagged_files }}</div>
  </div>
  <div class="summary-card">
    <div class="summary-label">Unparsed</div>
    <div class="summary-value">{{ summary.unparsed_files }}</div>
  </div>
</div>

{% if chart_mask_path or chart_hypothesis_path %}
<h2>Charts</h2>
{% if chart_mask_path %}
<img class="chart-img" src="{{ chart_mask_path }}" alt="Mask Distribution">
{% endif %}
{% if chart_hypothesis_path %}
<img class="chart-img" src="{{ chart_hypothesis_path }}" alt="Hypothesis Activation">
{% endif %}
{% endif %}

<h2>Hypothesis Activation</h2>
<table>
<thead>
<tr><th>Bit</th><th>Name</th><th>Files with H = 1</th></tr>
</thead>
<tbody>
{% for h in hypothesis_keys %}
<tr>
  <td><code>{{ h }}</code></td>
  <td>{{ hypothesis_labels[h] }}</td>
  <td>{{ summary.hypothesis_counts[h] }}</td>
</tr>
{% endfor %}
</tbody>
</table>

<h2>Mask Distribution</h2>
<table>
<thead>
<tr><th>Mask (H1H2H3H4-H5H6H7)</th><th>Files</th></tr>
</thead>
<tbody>
{% for mask, count in summary.mask_counts.items() %}
<tr>
  <td class="mask">{{ mask }}</td>
  <td>{{ count }}</td>
</tr>
{% endfor %}
</tbody>
</table>

<h2>Files</h2>
<table class="file-list">
<thead>
<tr>
  <th>File</th>
  <th>Mask</th>
  <th>H1 &ndash; H7</th>
  <th>Evidence (first)</th>
</tr>
</thead>
<tbody>
{% for obs in observations %}
<tr class="{% if obs.row_class %}{{ obs.row_class }}{% endif %}">
  <td class="file">{{ obs.display_path }}</td>
  <td class="mask {{ obs.mask_class }}">{{ obs.mask }}</td>
  <td>
    {% for h in hypothesis_keys %}
      <span class="badge {{ 'on' if obs.h_states[h] else 'off' }}">{{ h }}</span>
    {% endfor %}
  </td>
  <td class="evidence">{{ obs.evidence_summary }}</td>
</tr>
{% endfor %}
</tbody>
</table>

<footer-note>
  Generated deterministically by Sieve Lens v{{ version }}.
  No timestamps, randomness, or external resources are included.<br>
  This is an observation engine, not a judgment engine.
</footer-note>

</body>
</html>
"""


# ----------------------------------------------------------------------
# Row data (mirrors dashboard's _row_data but returns plain dict)
# ----------------------------------------------------------------------

def _row_data(obs: Observation, base_dir: Optional[Path]) -> dict:
    h1 = obs.h_states.get("H1", 0)
    if h1 == 0:
        row_class = "unparsed"
        mask_class = "mask-unparsed"
    elif any(obs.h_states.get(h, 0) == 1 for h in _HYPOTHESES[1:]):
        row_class = "flagged"
        mask_class = "mask-flag"
    else:
        row_class = ""
        mask_class = "mask-clean"

    display_path = obs.source
    if base_dir:
        try:
            display_path = str(Path(obs.source).relative_to(base_dir))
        except ValueError:
            display_path = Path(obs.source).name

    evidence_parts = []
    for h in _HYPOTHESES:
        if h == "H1":
            continue
        items = obs.evidence.get(h, [])
        for item in items:
            if item and item != "none":
                evidence_parts.append(f"[{h}] {item}")
                break
    evidence_summary = " / ".join(evidence_parts[:1]) if evidence_parts else ""
    if len(evidence_summary) > 100:
        evidence_summary = evidence_summary[:97] + "..."

    return {
        "source": obs.source,
        "display_path": display_path,
        "mask": obs.mask,
        "h_states": obs.h_states,
        "row_class": row_class,
        "mask_class": mask_class,
        "evidence_summary": evidence_summary,
    }


# ----------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------

def render_pdf_report_html(
    summary: DashboardSummary,
    observations: List[Observation],
    input_dir: str,
    base_dir: Optional[Path] = None,
    chart_mask_path: Optional[Path] = None,
    chart_hypothesis_path: Optional[Path] = None,
    version: str = "0.6.0",
) -> str:
    from jinja2 import Template

    rows = [_row_data(obs, base_dir) for obs in observations]
    template = Template(_TEMPLATE)
    return template.render(
        input_dir=html.escape(input_dir),
        summary=summary,
        observations=rows,
        hypothesis_keys=_HYPOTHESES,
        hypothesis_labels=_HYPOTHESIS_LABELS,
        chart_mask_path=str(chart_mask_path) if chart_mask_path else "",
        chart_hypothesis_path=str(chart_hypothesis_path) if chart_hypothesis_path else "",
        version=version,
    )


# ----------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------

def build_pdf_report(
    input_dir: Path,
    output_path: Path,
    recursive: bool = True,
    extensions: Optional[Sequence[str]] = None,
    include_charts: bool = True,
    max_workers: Optional[int] = None,
) -> Path:
    """Generate a PDF report from a directory of documents.

    Args:
        input_dir: Directory containing documents.
        output_path: Path for the generated PDF file.
        recursive: If True, scan subdirectories.
        extensions: Override the default file extension filter.
        include_charts: If True and kaleido is available, embed PNG charts.
        max_workers: Number of parallel workers.

    Returns:
        The output path.
    """
    if not WEASYPRINT_AVAILABLE:
        raise ImportError(
            "sieve_lens_ext.pdf_report requires weasyprint. "
            "Install with: pip install sieve-lens[pdf-report]"
        )

    input_dir = Path(input_dir).resolve()
    output_path = Path(output_path)

    exts = tuple(extensions) if extensions else _DEFAULT_EXTENSIONS
    files = scan_directory(input_dir, extensions=exts, recursive=recursive)
    observations = analyze_batch(files, max_workers=max_workers)
    summary = build_summary(observations)

    # Render charts to PNG in a temporary directory
    chart_mask_path: Optional[Path] = None
    chart_hypothesis_path: Optional[Path] = None

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        if include_charts:
            p1 = tmp / "mask.png"
            if _render_mask_chart_png(summary, p1):
                chart_mask_path = p1
            p2 = tmp / "hypothesis.png"
            if _render_hypothesis_chart_png(summary, p2):
                chart_hypothesis_path = p2

        html_text = render_pdf_report_html(
            summary=summary,
            observations=observations,
            input_dir=str(input_dir),
            base_dir=input_dir,
            chart_mask_path=chart_mask_path,
            chart_hypothesis_path=chart_hypothesis_path,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # WeasyPrint: build PDF. Fixed metadata for determinism.
        doc = HTML(string=html_text, base_url=str(input_dir))
        doc.write_pdf(
            target=str(output_path),
            presentational_hints=False,
            optimize_images=True,
        )

    return output_path


__all__ = [
    "build_pdf_report",
    "render_pdf_report_html",
]