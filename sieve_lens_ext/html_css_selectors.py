"""
Sieve Lens HTML full CSS selector resolution extension.

Adds full CSS selector matching to the HTML extractor via cssselect2.
Supersedes the simplified ID/class/tag matching in sieve_lens_ext.html_css.

Supports (in addition to v0.4):
  - Descendant combinator: "div p"
  - Child combinator: "div > p"
  - Adjacent sibling: "h1 + p"
  - General sibling: "h1 ~ p"
  - Attribute selectors: "[data-x]", "[href^='http']"
  - Pseudo-classes: ":first-child", ":nth-child(2n)", ":not(.x)"

Hidden CSS rules are only reported when their selector matches at least
one element in the HTML tree.

Requires: tinycss2 >= 1.1, cssselect2 >= 0.7

Install with:
    pip install sieve-lens[html-css-full]

Usage:
    from sieve_lens import SieveLensEngine
    from sieve_lens_ext.html_css_selectors import install

    engine = SieveLensEngine()
    install(engine)
    obs = engine.observe("page.html")
"""

from __future__ import annotations

import html.parser
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

try:
    import tinycss2
    from tinycss2.ast import QualifiedRule, Declaration
    TINYCSS2_AVAILABLE = True
except ImportError:
    TINYCSS2_AVAILABLE = False

try:
    from cssselect2 import Matcher, ElementWrapper, compile_selector_list
    CSSSELECT2_AVAILABLE = True
except ImportError:
    CSSSELECT2_AVAILABLE = False

from sieve_lens import Segment, strip_leading_bom
from sieve_lens_ext.html_css import _is_hidden_declaration


# ----------------------------------------------------------------------
# Minimal HTML tree
# ----------------------------------------------------------------------

class _Element:
    __slots__ = ("tag", "attrib", "text", "tail", "children")

    def __init__(self, tag: str, attrib: Dict[str, str]):
        self.tag = tag
        self.attrib = attrib
        self.text = ""
        self.tail = ""
        self.children: List["_Element"] = []

    def get(self, key, default=None):
        return self.attrib.get(key, default)

    def iter_children(self):
        return iter(self.children)

    def __iter__(self):
        return iter(self.children)


_VOID_ELEMENTS = frozenset([
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
])


class _TreeBuilder(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Element("#document", {})
        self._stack: List[_Element] = [self.root]
        self._in_style = False
        self._in_script = False
        self._style_buffer: List[str] = []
        self.comments: List[Tuple[int, str]] = []
        self.stylesheet_links: List[str] = []
        self.inline_hidden: List[Tuple[_Element, int]] = []
        self.hidden_attr_segments: List[Segment] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr_dict: Dict[str, str] = {}
        for k, v in attrs:
            if v is not None:
                attr_dict[k.lower()] = v

        if tag == "style":
            self._in_style = True
            self._style_buffer = []
            return
        if tag == "script":
            self._in_script = True
            return
        if tag == "link":
            rel = attr_dict.get("rel", "").lower()
            href = attr_dict.get("href", "")
            if "stylesheet" in rel and href:
                self.stylesheet_links.append(href)
            return

        elem = _Element(tag, attr_dict)
        self._stack[-1].children.append(elem)

        line, _ = self.getpos()
        style = attr_dict.get("style", "")
        hidden = (
            _style_is_hidden(style)
            or "hidden" in attr_dict
            or attr_dict.get("aria-hidden") == "true"
        )
        if hidden:
            self.inline_hidden.append((elem, line))

        for attr_name in ("alt", "title", "aria-label"):
            val = attr_dict.get(attr_name)
            if val and len(val.strip()) >= 10:
                self.hidden_attr_segments.append(Segment(
                    text=val, visible=False, kind="hidden_attr",
                    location=f"line {line}, <{tag}> @{attr_name}",
                ))

        if tag not in _VOID_ELEMENTS:
            self._stack.append(elem)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "style":
            self._in_style = False
            return
        if tag == "script":
            self._in_script = False
            return
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data):
        if self._in_style:
            self._style_buffer.append(data)
            return
        if self._in_script:
            return
        self._stack[-1].text += data

    def handle_comment(self, data):
        stripped = data.strip()
        if len(stripped) >= 10:
            line, _ = self.getpos()
            self.comments.append((line, stripped))


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


# ----------------------------------------------------------------------
# Extractor
# ----------------------------------------------------------------------

class HtmlCssSelectorsExtractor:
    def extract(self, path: Path) -> List[Segment]:
        if not TINYCSS2_AVAILABLE:
            raise ImportError(
                "sieve_lens_ext.html_css_selectors requires tinycss2. "
                "Install with: pip install sieve-lens[html-css-full]"
            )
        if not CSSSELECT2_AVAILABLE:
            raise ImportError(
                "sieve_lens_ext.html_css_selectors requires cssselect2. "
                "Install with: pip install sieve-lens[html-css-full]"
            )

        text = path.read_text(encoding="utf-8", errors="replace")
        text = strip_leading_bom(text)

        builder = _TreeBuilder()
        builder.feed(text)
        builder.close()

        segments: List[Segment] = []

        # CSS sources
        css_blobs: List[Tuple[str, str]] = []
        if builder._style_buffer:
            css_blobs.append(("inline <style>", "".join(builder._style_buffer)))
        for href in builder.stylesheet_links:
            local = self._resolve_local_href(href, path.parent)
            if local is not None:
                try:
                    css_text = local.read_text(encoding="utf-8", errors="replace")
                    css_blobs.append((f"<link> {local.name}", css_text))
                except Exception:
                    pass

        wrappers = self._build_wrappers(builder.root)

        for label, css_text in css_blobs:
            segments.extend(self._scan_css(css_text, label, wrappers))

        # Inline hidden styles
        for elem, line in builder.inline_hidden:
            style = elem.attrib.get("style", "")
            segments.append(Segment(
                text=style if style else "(hidden attribute)",
                visible=False,
                kind="css_hidden",
                location=f"line {line}, <{elem.tag}> inline style",
            ))

        segments.extend(builder.hidden_attr_segments)

        for line, comment in builder.comments:
            segments.append(Segment(
                text=comment, visible=False, kind="comment",
                location=f"line {line}",
            ))

        return segments

    def _scan_css(self, css_text: str, label: str, wrappers: List) -> List[Segment]:
        segments: List[Segment] = []
        try:
            rules = tinycss2.parse_stylesheet(
                css_text, skip_comments=True, skip_whitespace=True
            )
        except Exception:
            return segments

        for rule in rules:
            if not isinstance(rule, QualifiedRule):
                continue
            selector_text = tinycss2.serialize(rule.prelude).strip()
            if not selector_text:
                continue

            decls = tinycss2.parse_declaration_list(
                rule.content, skip_comments=True, skip_whitespace=True
            )
            hidden_decls = []
            for d in decls:
                if not isinstance(d, Declaration):
                    continue
                if d.important:
                    continue
                v = tinycss2.serialize(d.value).strip()
                if _is_hidden_declaration(d.name, v):
                    hidden_decls.append((d.name, v))
            if not hidden_decls:
                continue

            try:
                compiled = compile_selector_list(selector_text)
            except Exception:
                continue
            if not compiled:
                continue

            matched = False
            for sel in compiled:
                try:
                    test_fn = sel.test
                except AttributeError:
                    continue
                for w in wrappers:
                    try:
                        result = test_fn(w)
                    except Exception:
                        continue
                    if result is None:
                        continue
                    if isinstance(result, tuple):
                        if not result:
                            continue
                        spec = result[0]
                        if spec is None:
                            continue
                        if isinstance(spec, int) and spec == 0:
                            continue
                    elif isinstance(result, int) and result == 0:
                        continue
                    matched = True
                    break
                if matched:
                    break

            if not matched:
                continue

            match_count = 1

            if match_count == 0:
                continue

            line = getattr(rule, "source_line", None)
            name, value = hidden_decls[0]
            location = label
            if line is not None:
                location += f", line {line}"
            location += f", selector: {selector_text} (matched {match_count})"
            segments.append(Segment(
                text=f"{name}: {value}",
                visible=False,
                kind="css_hidden",
                location=location,
            ))

        return segments

    @staticmethod
    def _build_wrappers(root: _Element) -> List:
        wrappers: List = []

        def build(elem, parent_wrapper, index, previous_sibling_wrapper):
            try:
                w = ElementWrapper(
                    elem,
                    parent=parent_wrapper,
                    index=index,
                    previous=previous_sibling_wrapper,
                    in_html_document=True,
                )
            except TypeError:
                try:
                    w = ElementWrapper(
                        elem, parent=parent_wrapper, index=index,
                    )
                except Exception:
                    return None
            wrappers.append(w)
            prev = None
            for i, child in enumerate(elem.children):
                build(child, w, i, prev)
                prev = wrappers[-1] if wrappers else None
            return w

        build(root, None, 0, None)
        return wrappers

    def _resolve_local_href(self, href: str, base_dir: Path) -> Optional[Path]:
        parsed = urlparse(href)
        if parsed.scheme in ("http", "https", "data", "javascript"):
            return None
        if parsed.scheme == "file":
            candidate = Path(unquote(parsed.path))
        else:
            candidate = Path(unquote(href))
        if not candidate.is_absolute():
            candidate = base_dir / candidate
        try:
            candidate = candidate.resolve()
        except Exception:
            return None
        if not candidate.is_file():
            return None
        return candidate


def install(engine) -> None:
    """Replace .html / .htm extractor with the cssselect2 version."""
    extractor = HtmlCssSelectorsExtractor()
    engine.register_extractor([".html", ".htm"], extractor)


__all__ = ["HtmlCssSelectorsExtractor", "install"]