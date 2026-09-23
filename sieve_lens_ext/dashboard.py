"""
Sieve Lens dashboard extension.

Batch-analyzes a directory of documents and produces a single self-contained
HTML dashboard with interactive visualizations.

Features:
  - Recursive directory scanning
  - Parallel observation via ProcessPoolExecutor
  - Mask distribution chart (Plotly)
  - Hypothesis activation chart (Plotly)
  - File extension breakdown (Plotly)
  - Sortable, filterable file table
  - Deterministic output (sorted by path, explicit div IDs)

Requires:
  - Jinja2 >= 3.0
  - Plotly >= 5.0

Install with:
    pip install sieve-lens[dashboard]

Usage:
    from sieve_lens_ext.dashboard import build_dashboard

    build_dashboard(
        input_dir="submissions/",
        output_path="dashboard.html",
        standalone=False,
    )
"""

from __future__ import annotations

import html
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    from jinja2 import Template
    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False

try:
    import plotly.graph_objects as go
    import plotly.io as pio
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

from sieve_lens import SieveLensEngine, Observation


_DEFAULT_EXTENSIONS = (
    ".txt", ".md", ".html", ".htm", ".docx",
    ".pdf",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp",
    ".tif", ".tiff", ".webp",
)

_HYPOTHESES = ("H1", "H2", "H3", "H4", "H5", "H6", "H7")

_HYPOTHESIS_LABELS = {
    "H1": "Parseability",
    "H2": "Zero-Width Density",
    "H3": "Bidi Controls",
    "H4": "Format Concealment",
    "H5": "Out-of-Band Channel",
    "H6": "Script Mixing",
    "H7": "Contiguous Payload",
}


# ----------------------------------------------------------------------
# Engine construction
# ----------------------------------------------------------------------

def _build_engine() -> SieveLensEngine:
    """Build a SieveLensEngine with all available extensions installed."""
    engine = SieveLensEngine()

    try:
        from sieve_lens_ext.pdf import install as pdf_install
        pdf_install(engine)
    except ImportError:
        pass

    try:
        from sieve_lens_ext.ocr import install as ocr_install
        ocr_install(engine)
    except ImportError:
        pass

    try:
        from sieve_lens_ext.html_css import install as html_css_install
        html_css_install(engine)
    except ImportError:
        pass

    return engine


def _worker_observe(args):
    """Top-level worker for ProcessPoolExecutor."""
    path_str, = args
    engine = _build_engine()
    return engine.observe(path_str)


# ----------------------------------------------------------------------
# Scanning and batch analysis
# ----------------------------------------------------------------------

def scan_directory(
    input_dir: Path,
    extensions: Sequence[str] = _DEFAULT_EXTENSIONS,
    recursive: bool = True,
) -> List[Path]:
    """Return a sorted list of supported files in the directory."""
    input_dir = Path(input_dir)
    ext_set = {e.lower() for e in extensions}
    files: List[Path] = []
    iterator = input_dir.rglob("*") if recursive else input_dir.glob("*")
    for p in iterator:
        if p.is_file() and p.suffix.lower() in ext_set:
            files.append(p)
    files.sort(key=lambda p: str(p))
    return files


def analyze_batch(
    files: List[Path],
    max_workers: Optional[int] = None,
) -> List[Observation]:
    """Run observations over a list of files, in parallel if beneficial."""
    if not files:
        return []

    results: List[Observation] = []

    if len(files) >= 4 and (max_workers is None or max_workers > 1):
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_worker_observe, (str(f),)) for f in files]
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception:
                    continue
    else:
        engine = _build_engine()
        for f in files:
            try:
                results.append(engine.observe(f))
            except Exception:
                continue

    results.sort(key=lambda o: o.source)
    return results


# ----------------------------------------------------------------------
# Summary aggregation
# ----------------------------------------------------------------------

@dataclass
class DashboardSummary:
    total_files: int
    parsed_files: int
    unparsed_files: int
    clean_files: int
    flagged_files: int
    mask_counts: Dict[str, int] = field(default_factory=dict)
    hypothesis_counts: Dict[str, int] = field(default_factory=dict)
    extension_counts: Dict[str, int] = field(default_factory=dict)


def build_summary(observations: List[Observation]) -> DashboardSummary:
    mask_counts: Dict[str, int] = {}
    hypothesis_counts: Dict[str, int] = {h: 0 for h in _HYPOTHESES}
    extension_counts: Dict[str, int] = {}

    parsed = 0
    unparsed = 0
    clean = 0
    flagged = 0

    for obs in observations:
        ext = Path(obs.source).suffix.lower() or "<none>"
        extension_counts[ext] = extension_counts.get(ext, 0) + 1

        if obs.h_states.get("H1", 0) == 0:
            unparsed += 1
            mask_counts[obs.mask] = mask_counts.get(obs.mask, 0) + 1
            continue

        parsed += 1
        mask_counts[obs.mask] = mask_counts.get(obs.mask, 0) + 1

        # Any of H2..H7 activated?
        any_flag = any(obs.h_states.get(h, 0) == 1 for h in _HYPOTHESES[1:])
        if any_flag:
            flagged += 1
        else:
            clean += 1

        for h in _HYPOTHESES:
            if obs.h_states.get(h, 0) == 1:
                hypothesis_counts[h] += 1

    return DashboardSummary(
        total_files=len(observations),
        parsed_files=parsed,
        unparsed_files=unparsed,
        clean_files=clean,
        flagged_files=flagged,
        mask_counts=dict(sorted(mask_counts.items())),
        hypothesis_counts=hypothesis_counts,
        extension_counts=dict(sorted(extension_counts.items())),
    )


# ----------------------------------------------------------------------
# Plotly charts
# ----------------------------------------------------------------------

def _mask_color(mask: str) -> str:
    """Return a bar color based on whether any hypothesis is flagged."""
    if mask.startswith("0"):
        return "#b0b0b0"       # unparsed
    if mask in ("1000-000",):
        return "#22863a"       # clean
    return "#d73a49"           # flagged


def _build_mask_chart(mask_counts: Dict[str, int], include_js: bool | str):
    masks = list(mask_counts.keys())
    counts = [mask_counts[m] for m in masks]
    colors = [_mask_color(m) for m in masks]

    fig = go.Figure(
        data=[go.Bar(
            x=masks, y=counts,
            marker_color=colors,
            text=counts, textposition="auto",
        )]
    )
    fig.update_layout(
        title="Mask Distribution",
        xaxis_title="Mask (H1H2H3H4-H5H6H7)",
        yaxis_title="Number of Files",
        margin=dict(l=40, r=20, t=50, b=60),
        height=340,
    )
    return pio.to_html(
        fig, full_html=False,
        include_plotlyjs=include_js,
        div_id="mask-distribution-chart",
    )


def _build_hypothesis_chart(hypothesis_counts: Dict[str, int], include_js: bool | str):
    labels = [_HYPOTHESIS_LABELS[h] for h in _HYPOTHESES]
    values = [hypothesis_counts.get(h, 0) for h in _HYPOTHESES]
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
        margin=dict(l=40, r=20, t=50, b=80),
        height=340,
    )
    return pio.to_html(
        fig, full_html=False,
        include_plotlyjs=include_js,
        div_id="hypothesis-activation-chart",
    )


def _build_extension_chart(extension_counts: Dict[str, int], include_js: bool | str):
    exts = list(extension_counts.keys())
    counts = [extension_counts[e] for e in exts]

    fig = go.Figure(
        data=[go.Pie(
            labels=exts, values=counts,
            hole=0.4,
            textinfo="label+value",
        )]
    )
    fig.update_layout(
        title="File Types",
        margin=dict(l=20, r=20, t=50, b=20),
        height=340,
    )
    return pio.to_html(
        fig, full_html=False,
        include_plotlyjs=include_js,
        div_id="extension-breakdown-chart",
    )


# ----------------------------------------------------------------------
# HTML template
# ----------------------------------------------------------------------

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sieve Lens Dashboard</title>
<style>
:root {
  --fg: #1a1a1a;
  --bg: #fafafa;
  --card: #ffffff;
  --border: #dddddd;
  --muted: #6a737d;
  --warn: #d73a49;
  --warn-bg: #fff5f5;
  --ok: #22863a;
  --ok-bg: #f0fff4;
  --accent: #0366d6;
}
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  max-width: 1200px;
  margin: 2rem auto;
  padding: 0 1rem;
  color: var(--fg);
  background: var(--bg);
  line-height: 1.5;
}
h1 { font-size: 1.6rem; margin: 0 0 1rem; }
h2 { font-size: 1.15rem; margin: 2rem 0 .5rem; }

.summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1rem;
  margin: 1.5rem 0;
}
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem 1.2rem;
}
.card-label { font-size: .85rem; color: var(--muted); }
.card-value { font-size: 1.8rem; font-weight: 600; margin-top: .25rem; }
.card.warn .card-value { color: var(--warn); }
.card.ok .card-value { color: var(--ok); }

.charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
  margin: 1.5rem 0;
}
@media (max-width: 900px) {
  .charts { grid-template-columns: 1fr; }
}
.charts .chart-container {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: .5rem;
}

table {
  width: 100%;
  border-collapse: collapse;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
th, td {
  text-align: left;
  padding: .6rem .8rem;
  border-bottom: 1px solid var(--border);
  font-size: .88rem;
}
th {
  background: #f0f0f0;
  font-weight: 600;
  cursor: pointer;
  user-select: none;
}
th:hover { background: #e8e8e8; }
tr.flagged { background: var(--warn-bg); }
tr.unparsed { background: #f0f0f0; color: var(--muted); }
tr:last-child td { border-bottom: none; }

.mask-cell {
  font-family: "SF Mono", Menlo, Consolas, monospace;
  font-weight: 600;
}
.mask-flag { color: var(--warn); }
.mask-clean { color: var(--ok); }
.mask-unparsed { color: var(--muted); }

.h-badges {
  display: flex;
  gap: 3px;
  flex-wrap: wrap;
}
.badge {
  display: inline-block;
  width: 22px;
  height: 22px;
  line-height: 22px;
  text-align: center;
  border-radius: 4px;
  font-size: .7rem;
  font-family: "SF Mono", Menlo, Consolas, monospace;
  font-weight: 600;
}
.badge.on { background: var(--warn); color: white; }
.badge.off { background: #eee; color: #999; }

.evidence-cell {
  font-family: "SF Mono", Menlo, Consolas, monospace;
  font-size: .78rem;
  color: var(--muted);
  max-width: 400px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-cell {
  font-family: "SF Mono", Menlo, Consolas, monospace;
  font-size: .82rem;
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.evidence-cell { cursor: pointer; }

details { margin-top: .25rem; }
summary { cursor: pointer; }

footer {
  margin-top: 3rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: .85rem;
}
footer p { margin: .4rem 0; }
</style>
</head>
<body>

<h1>Sieve Lens Dashboard</h1>
<p style="color: var(--muted); font-size: .9rem;">
  Source: <code>{{ input_dir }}</code> &mdash; {{ summary.total_files }} file(s) scanned
</p>

<div class="summary">
  <div class="card">
    <div class="card-label">Total Files</div>
    <div class="card-value">{{ summary.total_files }}</div>
  </div>
  <div class="card ok">
    <div class="card-label">Clean</div>
    <div class="card-value">{{ summary.clean_files }}</div>
  </div>
  <div class="card warn">
    <div class="card-label">Flagged</div>
    <div class="card-value">{{ summary.flagged_files }}</div>
  </div>
  <div class="card">
    <div class="card-label">Unparsed</div>
    <div class="card-value">{{ summary.unparsed_files }}</div>
  </div>
</div>

<div class="charts">
  <div class="chart-container">{{ chart_mask | safe }}</div>
  <div class="chart-container">{{ chart_hypothesis | safe }}</div>
</div>

<div class="charts">
  <div class="chart-container">{{ chart_extension | safe }}</div>
</div>

<h2>Files</h2>
<table id="file-table">
<thead>
<tr>
  <th data-sort="file">File</th>
  <th data-sort="mask">Mask</th>
  <th>H1 &ndash; H7</th>
  <th>Evidence</th>
</tr>
</thead>
<tbody>
{% for obs in observations %}
<tr class="{% if obs.row_class %}{{ obs.row_class }}{% endif %}">
  <td class="file-cell" title="{{ obs.source }}">{{ obs.display_path }}</td>
  <td class="mask-cell {{ obs.mask_class }}">{{ obs.mask }}</td>
  <td>
    <div class="h-badges">
    {% for h in hypothesis_keys %}
      <span class="badge {{ 'on' if obs.h_states[h] else 'off' }}">{{ h }}</span>
    {% endfor %}
    </div>
  </td>
  <td class="evidence-cell" title="{{ obs.evidence_summary }}">{{ obs.evidence_summary }}</td>
</tr>
{% endfor %}
</tbody>
</table>

<footer>
<p><strong>This is an observation dashboard, not a judgment of intent.</strong></p>
<p>Human review is required to determine whether the detected invisible
content is legitimate or abusive.</p>
<p>Generated deterministically by Sieve Lens. No timestamps or randomness
are included.</p>
</footer>

<script>
(function() {
  const table = document.getElementById('file-table');
  const headers = table.querySelectorAll('th[data-sort]');
  headers.forEach(function(th) {
    th.addEventListener('click', function() {
      const key = th.getAttribute('data-sort');
      const tbody = table.querySelector('tbody');
      const rows = Array.from(tbody.querySelectorAll('tr'));
      const idx = key === 'file' ? 0 : 1;
      const asc = th.dataset.asc !== 'true';
      rows.sort(function(a, b) {
        const av = a.cells[idx].textContent.trim();
        const bv = b.cells[idx].textContent.trim();
        return asc ? av.localeCompare(bv) : bv.localeCompare(av);
      });
      rows.forEach(function(r) { tbody.appendChild(r); });
      th.dataset.asc = asc ? 'true' : 'false';
    });
  });
})();
</script>

</body>
</html>
"""


# ----------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------

def _row_data(obs: Observation, base_dir: Optional[Path]):
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

    evidence_summary = " / ".join(evidence_parts[:2]) if evidence_parts else ""
    if len(evidence_summary) > 120:
        evidence_summary = evidence_summary[:117] + "..."

    return {
        "source": obs.source,
        "display_path": display_path,
        "mask": obs.mask,
        "h_states": obs.h_states,
        "row_class": row_class,
        "mask_class": mask_class,
        "evidence_summary": evidence_summary,
    }


def render_dashboard(
    summary: DashboardSummary,
    observations: List[Observation],
    input_dir: str,
    base_dir: Optional[Path] = None,
    standalone: bool = False,
) -> str:
    if not JINJA2_AVAILABLE or not PLOTLY_AVAILABLE:
        raise ImportError(
            "sieve_lens_ext.dashboard requires Jinja2 and Plotly. "
            "Install with: pip install sieve-lens[dashboard]"
        )

    # First chart embeds Plotly.js; subsequent charts reuse it.
    include_js_first: bool | str = True if standalone else "cdn"

    chart_mask = _build_mask_chart(summary.mask_counts, include_js_first)
    chart_hypothesis = _build_hypothesis_chart(summary.hypothesis_counts, False)
    chart_extension = _build_extension_chart(summary.extension_counts, False)

    rows = [_row_data(obs, base_dir) for obs in observations]

    template = Template(_TEMPLATE)
    return template.render(
        input_dir=html.escape(input_dir),
        summary=summary,
        chart_mask=chart_mask,
        chart_hypothesis=chart_hypothesis,
        chart_extension=chart_extension,
        observations=rows,
        hypothesis_keys=_HYPOTHESES,
    )


# ----------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------

def build_dashboard(
    input_dir: Path,
    output_path: Path,
    standalone: bool = False,
    recursive: bool = True,
    extensions: Optional[Sequence[str]] = None,
    max_workers: Optional[int] = None,
) -> Path:
    """Scan a directory, run observations, and write an HTML dashboard.

    Args:
        input_dir: Directory containing documents to analyze.
        output_path: Path for the generated HTML file.
        standalone: If True, Plotly.js is embedded inline (~3MB).
                    If False, Plotly.js is loaded from CDN.
        recursive: If True (default), scan subdirectories.
        extensions: Override the default file extension filter.
        max_workers: Number of parallel workers (None = auto).

    Returns:
        The output path.
    """
    if not JINJA2_AVAILABLE or not PLOTLY_AVAILABLE:
        raise ImportError(
            "sieve_lens_ext.dashboard requires Jinja2 and Plotly. "
            "Install with: pip install sieve-lens[dashboard]"
        )

    input_dir = Path(input_dir).resolve()
    output_path = Path(output_path)

    exts = tuple(extensions) if extensions else _DEFAULT_EXTENSIONS
    files = scan_directory(input_dir, extensions=exts, recursive=recursive)
    observations = analyze_batch(files, max_workers=max_workers)
    summary = build_summary(observations)

    html_text = render_dashboard(
        summary=summary,
        observations=observations,
        input_dir=str(input_dir),
        base_dir=input_dir,
        standalone=standalone,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")
    return output_path


__all__ = [
    "build_dashboard",
    "scan_directory",
    "analyze_batch",
    "build_summary",
    "render_dashboard",
    "DashboardSummary",
]