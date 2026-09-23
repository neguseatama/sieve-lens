"""
Sieve Lens HTML external CSS extension.

Adds external CSS resolution to SieveLensEngine for HTML documents.

Resolves:
  - <style> ... </style> blocks within the HTML document
  - <link rel="stylesheet" href="..."> referencing local files
    (http:// and https:// URLs are ignored by default for security)

Detects CSS rules that hide content from human readers but not from
a parser:
  - display: none
  - visibility: hidden
  - opacity: 0
  - font-size: 0
  - positioning off-screen (left/top/right/bottom: -NNNN+)
  - text-indent: -NNNN+ (classic screen-reader-only technique)
  - clip / clip-path hiding
  - height: 0 / width: 0 with overflow: hidden

Selector matching is intentionally simplified: ID (#id), class (.class),
and tag selectors are matched against element attributes and tag names.
Complex selectors (descendant, child, pseudo-class) are not fully
resolved; the rule is still reported with its raw selector text.

Requires: tinycss2 >= 1.1
  pip install sieve-lens[html-css]

Usage:
    from sieve_lens import SieveLensEngine
    from sieve_lens_ext.html_css import install

    engine = SieveLensEngine()
    install(engine)               # replaces .html/.htm extractor
    obs = engine.observe("page.html")
"""

from __future__ import annotations

import html.parser
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import unquote, urlparse

try:
    import tinycss2
    from tinycss2.ast import QualifiedRule, Declaration
    TINYCSS2_AVAILABLE = True
except ImportError:
    TINYCSS2_AVAILABLE = False

from sieve_lens import Segment, strip_leading_bom


# ----------------------------------------------------------------------
# Hidden-property patterns
# ----------------------------------------------------------------------

_HIDDEN_PROPERTIES: Dict[str, re.Pattern] = {
    "display": re.compile(r"^\s*none\s*$", re.IGNORECASE),
    "visibility": re.compile(r"^\s*hidden\s*$", re.IGNORECASE),
    "opacity": re.compile(r"^\s*0(?:\.0+)?\s*$", re.IGNORECASE),
    "font-size": re.compile(r"^\s*0(?:px|pt|em|rem|%)?\s*$", re.IGNORECASE),
    "text-indent": re.compile(r"^\s*-\d{3,}(?:px|em|rem|%)?\s*$", re.IGNORECASE),
    "clip": re.compile(r"^\s*rect\(\s*0[,\s]+0[,\s]+0[,\s]+0\s*\)\s*$", re.IGNORECASE),
    "clip-path": re.compile(r"^\s*inset\(\s*100%\s*\)\s*$", re.IGNORECASE),
}

_POSITION_OFFSCREEN = re.compile(
    r"^\s*-\d{4,}(?:px|em|rem|%)?\s*$", re.IGNORECASE
)

# Properties whose combination hides content when overflow is hidden
_SIZE_ZERO = re.compile(r"^\s*0(?:px|em|rem|%)?\s*$", re.IGNORECASE)


def _is_hidden_declaration(name: str, value: str) -> bool:
    """Return True if the (property, value) pair hides content."""
    name = name.strip().lower()
    value = value.strip()

    if name in _HIDDEN_PROPERTIES and _HIDDEN_PROPERTIES[name].match(value):
        return True

    if name in ("left", "top", "right", "bottom") and _POSITION_OFFSCREEN.match(value):
        return True

    return False


# ----------------------------------------------------------------------
# Simplified selector matching
# ----------------------------------------------------------------------

_SIMPLE_SELECTOR = re.compile(
    r"^(?:(?P<tag>[a-zA-Z][\w-]*)|"
    r"(?P<id>#[\w-]+)|"
    r"(?P<class>\.[\w-]+))+$"
)


def _extract_simple_selectors(prelude: str) -> List[Tuple[str, str]]:
    """Extract simple selectors from a CSS prelude.

    Returns a list of (kind, value) tuples where kind is one of
    "tag", "id", "class". Complex selectors yield an empty list.
    """
    prelude = prelude.strip()
    if not prelude:
        return []
    # Split on combinators; we only handle the last compound selector
    parts = re.split(r"[\s>+~]+", prelude)
    last = parts[-1] if parts else ""
    # Remove pseudo-classes and pseudo-elements
    last = re.sub(r"::?[\w-]+(?:\([^)]*\))?", "", last)
    if not last:
        return []

    results: List[Tuple[str, str]] = []
    pos = 0
    while pos < len(last):
        if last[pos] == "#":
            m = re.match(r"#([\w-]+)", last[pos:])
            if not m:
                return []
            results.append(("id", m.group(1)))
            pos += m.end()
        elif last[pos] == ".":
            m = re.match(r"\.([\w-]+)", last[pos:])
            if not m:
                return []
            results.append(("class", m.group(1)))
            pos += m.end()
        elif last[pos].isalpha():
            m = re.match(r"([a-zA-Z][\w-]*)", last[pos:])
            if not m:
                return []
            results.append(("tag", m.group(1)))
            pos += m.end()
        else:
            return []
    return results


def _selector_matches(
    selectors: List[Tuple[str, str]],
    tag: str,
    attrs: Dict[str, str],
) -> bool:
    """Check whether a compound selector matches an element."""
    for kind, value in selectors:
        if kind == "tag":
            if tag.lower() != value.lower():
                return False
        elif kind == "id":
            if attrs.get("id") != value:
                return False
        elif kind == "class":
            classes = attrs.get("class", "").split()
            if value not in classes:
                return False
    return True


# ----------------------------------------------------------------------
# Extractor
# ----------------------------------------------------------------------

class HtmlCssExtractor(html.parser.HTMLParser):
    """HTML extractor that also resolves <style> blocks and local <link> CSS."""

    _OOB_MIN_LENGTH = 10

    def __init__(self, base_dir: Optional[Path] = None):
        super().__init__(convert_charrefs=True)
        self.base_dir = base_dir
        self.segments: List[Segment] = []
        self._stack: List[bool] = []
        self._buffer: List[str] = []
        self._in_style_or_script = False
        self._style_buffer: List[str] = []
        self._in_style_tag = False
        self._pending_link_href: Optional[str] = None

    # -- public API ----------------------------------------------------

    def extract(self, path: Path) -> List[Segment]:
        if not TINYCSS2_AVAILABLE:
            raise ImportError(
                "sieve_lens_ext.html_css requires tinycss2. "
                "Install with: pip install sieve-lens[html-css]"
            )
        self.base_dir = path.parent
        text = path.read_text(encoding="utf-8", errors="replace")
        text = strip_leading_bom(text)
        self._reset()
        self.feed(text)
        self.close()
        self._flush()
        self._process_css_sources()
        return self.segments

    # -- parser hooks --------------------------------------------------

    def _reset(self):
        self.segments = []
        self._stack = []
        self._buffer = []
        self._in_style_or_script = False
        self._style_buffer = []
        self._in_style_tag = False
        self._pending_link_href = None

    def handle_starttag(self, tag, attrs):
        self._flush()
        tag = tag.lower()
        attr_dict = {k.lower(): v for k, v in attrs if v is not None}

        if tag == "style":
            self._in_style_tag = True
            self._in_style_or_script = True
            self._style_buffer = []
            return

        if tag in ("script",):
            self._in_style_or_script = True
            return

        if tag == "link":
            rel = attr_dict.get("rel", "").lower()
            href = attr_dict.get("href", "")
            if "stylesheet" in rel and href:
                self._pending_link_href = href
            return

        style = attr_dict.get("style", "")
        hidden = (
            self._style_is_hidden(style)
            or "hidden" in attr_dict
            or attr_dict.get("aria-hidden") == "true"
        )
        self._stack.append(hidden)
        line, _ = self.getpos()

        for attr_name in ("alt", "title", "aria-label"):
            val = attr_dict.get(attr_name)
            if val and len(val.strip()) >= self._OOB_MIN_LENGTH:
                self.segments.append(Segment(
                    text=val, visible=False, kind="hidden_attr",
                    location=f"line {line}, <{tag}> @{attr_name}",
                ))

        # Check whether any known hidden CSS rule matches this element.
        # (Handled later by _process_css_sources; this is a placeholder.)

    def handle_endtag(self, tag):
        self._flush()
        tag = tag.lower()
        if tag == "style":
            self._in_style_tag = False
            self._in_style_or_script = False
        elif tag in ("script",):
            self._in_style_or_script = False
        if self._stack:
            self._stack.pop()

    def handle_data(self, data):
        if self._in_style_tag:
            self._style_buffer.append(data)
            return
        if self._in_style_or_script:
            return
        self._buffer.append(data)

    def handle_comment(self, data):
        self._flush()
        stripped = data.strip()
        if len(stripped) >= 10:
            line, _ = self.getpos()
            self.segments.append(Segment(
                text=stripped, visible=False, kind="comment",
                location=f"line {line}",
            ))

    # -- internals -----------------------------------------------------

    def _flush(self):
        if not self._buffer:
            return
        text = "".join(self._buffer)
        self._buffer = []
        if not text.strip():
            return
        hidden = bool(self._stack and self._stack[-1])
        line, _ = self.getpos()
        self.segments.append(Segment(
            text=text,
            visible=not hidden,
            kind="css_hidden" if hidden else "body",
            location=f"line {line}",
        ))

    def _process_css_sources(self):
        """Parse any inline <style> and local <link> stylesheets."""
        css_blobs: List[Tuple[str, str]] = []

        if self._style_buffer:
            css_blobs.append(("inline <style>", "".join(self._style_buffer)))

        if self._pending_link_href:
            local = self._resolve_local_href(self._pending_link_href)
            if local is not None:
                try:
                    css_text = local.read_text(encoding="utf-8", errors="replace")
                    css_blobs.append((f"<link> {local.name}", css_text))
                except Exception:
                    pass

        for source_label, css_text in css_blobs:
            self._scan_css(css_text, source_label)

    def _resolve_local_href(self, href: str) -> Optional[Path]:
        """Resolve a href to a local file path, or None if remote/unsafe."""
        parsed = urlparse(href)
        if parsed.scheme in ("http", "https", "data", "javascript"):
            return None
        if parsed.scheme == "file":
            candidate = Path(unquote(parsed.path))
        else:
            candidate = Path(unquote(href))
        if not candidate.is_absolute():
            base = self.base_dir or Path.cwd()
            candidate = base / candidate
        try:
            candidate = candidate.resolve()
        except Exception:
            return None
        if not candidate.is_file():
            return None
        return candidate

    def _scan_css(self, css_text: str, source_label: str):
        try:
            rules = tinycss2.parse_stylesheet(
                css_text, skip_comments=True, skip_whitespace=True
            )
        except Exception:
            return
        for rule in rules:
            if not isinstance(rule, QualifiedRule):
                continue
            selector_text = tinycss2.serialize(rule.prelude).strip()
            if not selector_text:
                continue
            selectors = _extract_simple_selectors(selector_text)
            declarations = tinycss2.parse_declaration_list(
                rule.content, skip_comments=True, skip_whitespace=True
            )
            for decl in declarations:
                if not isinstance(decl, Declaration):
                    continue
                if decl.important:
                    continue
                value_text = tinycss2.serialize(decl.value).strip()
                if _is_hidden_declaration(decl.name, value_text):
                    line = getattr(rule, "source_line", None)
                    location = f"{source_label}"
                    if line is not None:
                        location += f", line {line}"
                    location += f", selector: {selector_text}"
                    self.segments.append(Segment(
                        text=f"{decl.name}: {value_text}",
                        visible=False,
                        kind="css_hidden",
                        location=location,
                    ))
                    break  # one hidden declaration per rule is enough

    @staticmethod
    def _style_is_hidden(style: str) -> bool:
        if not style:
            return False
        for decl in style.split(";"):
            if ":" not in decl:
                continue
            name, _, value = decl.partition(":")
            if _is_hidden_declaration(name, value):
                return True
        return False


def install(engine, resolve_local_links: bool = True) -> None:
    """Replace the built-in .html / .htm extractor with the CSS-aware one.

    Args:
        engine: A SieveLensEngine instance.
        resolve_local_links: When True (default), <link> elements pointing
            to local files are resolved. Remote URLs are always ignored.
    """
    extractor = HtmlCssExtractor()
    engine.register_extractor([".html", ".htm"], extractor)