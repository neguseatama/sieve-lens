"""
Sieve Lens PDF extension.

Adds PDF support to SieveLensEngine via pypdf.

Extracts:
  - PDF metadata (title, author, subject, keywords, creator, producer) -> H5
  - Page text -> body (H2/H3/H6/H7)
  - Annotations (comments, notes) -> H5
  - Invisible text (Tr 3 rendering mode) -> H4 (format concealment)

v0.22.1 - the visible page text no longer contains invisible text.
  One shared classification of the content stream (the text render mode
  state machine: Tr sets it, q/Q save and restore it, it persists across
  BT/ET, and a Form XObject invoked by Do inherits the state at its
  invocation) produces BOTH outputs: the observation's hidden text
  (render mode 3, as in 0.22.0) and the visible text (every show
  operation the classification marks render mode 3 or 7 is removed
  from the content stream before pypdf's own extraction runs on the
  remainder; modes 0, 1, 2, 4, 5 and 6 are visible, exactly as drawn).
  A page whose render-mode state cannot be determined (unreadable
  content stream, a state-tracking failure, form nesting beyond the
  walk limit, a form re-invoked under a different state) fails closed:
  no visible text is emitted for that page and the suppression is
  recorded with the engine's existing unobserved reason word,
  "Extraction failed", in the page location of an empty body segment.
  Other pages are unaffected.

Note on text extraction:
  pypdf's page.extract_text() maps characters through the font's encoding
  (e.g. WinAnsi for Helvetica), which drops characters not present in that
  encoding — including zero-width and bidi control characters. To preserve
  those for H2/H3/H7 detection, we additionally parse the raw content
  stream and include that text as a supplementary body segment.

Usage:
    from sieve_lens import SieveLensEngine
    from sieve_lens_ext.pdf import install

    engine = SieveLensEngine()
    install(engine)               # attaches .pdf support
    obs = engine.observe("resume.pdf")

Requires: pypdf >= 4.0
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    from pypdf import PdfReader
    from pypdf.generic import (
        ContentStream, DecodedStreamObject, DictionaryObject, NameObject,
    )
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

from sieve_lens import Segment, INVISIBLE


class PdfExtractor:
    """Extract segments from a PDF file."""

    _METADATA_KEYS = (
        "/Title", "/Author", "/Subject",
        "/Keywords", "/Creator", "/Producer",
    )

    _OOB_MIN_LENGTH = 10

    # Cycle defense: the record set (per page walk) is the primary
    # guard; this depth cap is insurance against malformed graphs.
    _MAX_FORM_DEPTH = 8

    # Render modes that draw nothing a human reader can see
    # (PDF 32000-1 Table 51): 3 = invisible, 7 = clip only.
    _INVISIBLE_MODES = (3, 7)

    # The engine's existing unobserved-reason word, reused for the
    # fail-closed page location (no new vocabulary).
    _WITHHELD_REASON = "Extraction failed"

    # Sentinel for "the key did not exist" in the restore log.
    _MISSING = object()

    def extract(self, path: Path) -> List[Segment]:
        if not PYPDF_AVAILABLE:
            raise ImportError(
                "sieve_lens_ext.pdf requires pypdf. "
                "Install with: pip install sieve-lens[pdf]"
            )
        segments: List[Segment] = []
        with open(path, "rb") as f:
            reader = PdfReader(f)
            segments.extend(self._extract_metadata(reader))
            for page_num, page in enumerate(reader.pages, start=1):
                segments.extend(self._extract_page_text(page, page_num, reader))
                segments.extend(self._extract_annotations(page, page_num))
        return segments

    def _extract_metadata(self, reader) -> List[Segment]:
        try:
            meta = reader.metadata
        except Exception:
            return []
        if not meta:
            return []
        segments = []
        for key in self._METADATA_KEYS:
            try:
                val = meta.get(key)
            except Exception:
                continue
            if isinstance(val, str) and len(val.strip()) >= self._OOB_MIN_LENGTH:
                segments.append(Segment(
                    text=val,
                    visible=False,
                    kind="metadata",
                    location=f"PDF metadata / {key}",
                ))
        return segments

    # ------------------------------------------------------------------
    # The one shared classification (observation and visible text are
    # both built from it - never from two separate judgments).
    # ------------------------------------------------------------------

    def _classify_page(self, page, reader) -> "_PageClassification":
        """Classify one page's content stream (render-mode state machine).

        Walks the page stream with the shared state, descending into
        every Form XObject the page invokes (Do) with the state at the
        invocation. The observation's own form scan is separate
        (declaration-based, 0.22.0 semantics) and shares only this
        state machine.
        """
        cls = _PageClassification()
        contents = None
        try:
            contents = page.get("/Contents")
        except Exception:
            cls.failed = True
        if contents is None:
            return cls
        try:
            stream = ContentStream(contents, reader)
        except Exception:
            cls.failed = True
            return cls
        cls.page_stream = stream
        cls.page_contents = contents
        resources = self._inherited_resources(page)
        state = _TrState()
        try:
            self._walk_stream(
                stream, state, resources, cls, reader,
                parent_record=None, depth=0)
        except _StateError:
            cls.failed = True
        except Exception:
            # an unexpected failure inside the walk also leaves the
            # render-mode state undetermined for the rest of the page
            cls.failed = True
        return cls

    def _inherited_resources(self, page):
        """The page's /Resources, walking the /Parent chain (PDF spec:
        a page's own /Resources override the inherited ones entirely)."""
        node = page
        for _ in range(64):
            if node is None:
                return None
            try:
                res = node.get("/Resources")
            except Exception:
                return None
            if res is not None:
                try:
                    res = res.get_object()
                except Exception:
                    return None
                if res:
                    return res
            try:
                parent = node.get("/Parent")
            except Exception:
                return None
            try:
                node = parent.get_object() if parent is not None else None
            except Exception:
                return None
        return None

    def _resolve_form(self, resources, name):
        """(form object, xobject container) for one Do operand, or
        (None, None) when the name does not resolve to a Form."""
        if resources is None:
            return None, None
        try:
            xobjs = resources.get("/XObject")
            xobjs = xobjs.get_object() if xobjs is not None else None
            if not xobjs:
                return None, None
            entry = xobjs.get(name, None)
            if entry is None:
                return None, None
            form = entry.get_object()
            return form, xobjs
        except Exception:
            return None, None

    def _walk_stream(self, stream, state: "_TrState", resources, cls,
                     reader, parent_record: Optional["_FormRecord"],
                     depth: int) -> None:
        """One classification pass over a content stream.

        Appends a _Piece per decoded show operand and records the show
        operation indexes (all of them, and the ones the visible side
        must drop). Descends into invoked Form XObjects with the state
        at the Do (implicit save and restore around the form). Raises
        _StateError when the render-mode state cannot be tracked.
        """
        for op_index, (operands, operator) in enumerate(stream.operations):
            if operator in (b"Tr", b"q", b"Q"):
                state.apply(operator, operands)
                continue
            if operator in (b"Tj", b"'", b'"', b"TJ"):
                cls.page_show_indexes_add(parent_record, op_index)
                if state.mode in self._INVISIBLE_MODES:
                    cls.page_drop_add(parent_record, op_index)
                try:
                    if operator == b"TJ":
                        texts = [self._decode(item)
                                 for item in operands[0]
                                 if isinstance(item, (bytes, str))]
                    elif operator == b'"':
                        texts = [self._decode(operands[-1])]
                    else:
                        texts = [self._decode(operands[0])]
                except Exception:
                    # the text of this operation is unknown; it is
                    # omitted from both outputs and never shown
                    cls.page_drop_add(parent_record, op_index)
                    continue
                hidden = state.mode == 3
                target = (parent_record.pieces if parent_record is not None
                          else cls.page_pieces)
                for text in texts:
                    target.append(_Piece(text, hidden, op_index))
                continue
            if operator == b"Do" and operands:
                name = str(operands[0])
                form, xobjs = self._resolve_form(resources, name)
                if form is None or str(form.get("/Subtype")) != "/Form":
                    continue
                existing = cls.records_by_obj.get(id(form))
                if existing is not None:
                    # already walked (cycle or alias): reuse the record,
                    # but only under the same invocation state
                    if existing.entry_mode != state.mode:
                        raise _StateError(
                            "form re-invoked under a different render mode")
                    record = existing
                else:
                    if depth + 1 > self._MAX_FORM_DEPTH:
                        raise _StateError("form nesting too deep")
                    record = _FormRecord(
                        entry_mode=state.mode, obj=form,
                        source_contents=form)
                    cls.records_by_obj[id(form)] = record
                    if parent_record is None:
                        record.site_name = name
                        record.site_xobjs = xobjs
                    else:
                        parent_record.children.append((name, record))
                    form_resources = None
                    try:
                        fres = form.get("/Resources")
                        form_resources = (fres.get_object()
                                          if fres is not None else None)
                    except Exception:
                        form_resources = None
                    saved_mode, saved_len = state.mode, len(state.stack)
                    try:
                        self._walk_stream(
                            ContentStream(form, reader), state,
                            form_resources, cls, reader,
                            parent_record=record, depth=depth + 1)
                    finally:
                        # implicit save/restore around the form
                        # (PDF 32000-1 8.10.2): the invocation state
                        # continues after the Do
                        state.mode = saved_mode
                        del state.stack[saved_len:]
                if parent_record is None:
                    cls.top_sites.append((record, xobjs, name))
                    cls.forms.setdefault(name, record)
                continue

    # ------------------------------------------------------------------
    # Visible text (filtered extraction on the classified remainder)
    # ------------------------------------------------------------------

    def _iter_records(self, cls: "_PageClassification"):
        for record in cls.records_by_obj.values():
            yield record

    def _page_has_hidden(self, cls: "_PageClassification") -> bool:
        if any(pc.hidden for pc in cls.page_pieces):
            return True
        return any(any(pc.hidden for pc in record.pieces)
                   for record in self._iter_records(cls))

    def _extract_filtered(self, page, reader,
                          cls: "_PageClassification") -> str:
        """extract_text on the page with the hidden show operations
        removed (the remainder runs through pypdf's own machinery
        unchanged). Every mutation is restored before returning."""
        saved: List[Tuple[object, object, object]] = []
        try:
            new_contents = DecodedStreamObject()
            new_contents.set_data(
                self._filtered_data(cls.page_contents, cls.page_drop,
                                    reader))
            saved.append((page, NameObject("/Contents"),
                          page.get("/Contents", self._MISSING)))
            page[NameObject("/Contents")] = new_contents

            memo: Dict[Tuple[int, int], DecodedStreamObject] = {}
            for record, xobjs, name in cls.top_sites:
                if xobjs is None:
                    continue
                filtered = self._filtered_form(record, memo, reader)
                saved.append((xobjs, NameObject(name),
                              xobjs.get(name, self._MISSING)))
                xobjs[NameObject(name)] = filtered
            return self._extract_text_quiet(page)
        finally:
            for container, key, old in saved:
                try:
                    if old is self._MISSING:
                        del container[key]
                    else:
                        container[key] = old
                except Exception:
                    pass

    def _filtered_data(self, source_contents, drop: Set[int],
                       reader) -> bytes:
        """Re-serialize one content stream without the dropped show
        operations (the original source is parsed again, so nothing but
        the removed operations differs)."""
        filtered = ContentStream(source_contents, reader)
        filtered.operations = [op for i, op in enumerate(filtered.operations)
                               if i not in drop]
        return filtered.get_data()

    def _filtered_form(self, record: "_FormRecord",
                       memo: Dict[Tuple[int, int], DecodedStreamObject],
                       reader) -> DecodedStreamObject:
        """A stream-object copy of the form with its hidden show
        operations removed; children referenced from the copy's own
        resources are filtered copies as well (children first)."""
        memo_key = (id(record.obj), record.entry_mode)
        if memo_key in memo:
            return memo[memo_key]
        new = DecodedStreamObject()
        new.set_data(self._filtered_data(record.source_contents,
                                         record.drop, reader))
        for key in ("/Type", "/Subtype", "/BBox", "/Matrix", "/Group"):
            try:
                value = record.obj.get(key)
            except Exception:
                value = None
            if value is not None:
                new[NameObject(key)] = value
        try:
            res = record.obj.get("/Resources")
            res = res.get_object() if res is not None else None
        except Exception:
            res = None
        if res is not None:
            res_copy = DictionaryObject()
            res_copy.update(res)
            try:
                xobjs = res.get("/XObject")
                xobjs = xobjs.get_object() if xobjs is not None else None
            except Exception:
                xobjs = None
            if xobjs is not None:
                xo_copy = DictionaryObject()
                xo_copy.update(xobjs)
                for child_name, child_record in record.children:
                    xo_copy[NameObject(child_name)] = self._filtered_form(
                        child_record, memo, reader)
                res_copy[NameObject("/XObject")] = xo_copy
            new[NameObject("/Resources")] = res_copy
        memo[memo_key] = new
        return new

    @staticmethod
    def _extract_text_quiet(page) -> str:
        try:
            return page.extract_text() or ""
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Page text segments (0.22.0 shapes; the visible sources lose the
    # text the shared classification marks invisible)
    # ------------------------------------------------------------------

    def _extract_page_text(self, page, page_num: int, reader) -> List[Segment]:
        """Extract visible page text.

        Uses pypdf's standard extract_text for natural reading order,
        and additionally includes raw content stream text when it
        contains invisible characters that the standard extraction lost.
        Since 0.22.1 the visible text comes from the same
        classification that reports the hidden (Tr 3) text: show
        operations in render mode 3 or 7 never reach the visible side,
        and a page whose render-mode state cannot be determined emits
        no visible text at all (fail closed, "Extraction failed").
        """
        segments: List[Segment] = []

        cls = self._classify_page(page, reader)

        if cls.failed:
            # fail closed: no visible text from this page; report what
            # the classification did establish before the failure
            return self._withheld_segments(page_num, cls)

        if self._page_has_hidden(cls):
            try:
                text = self._extract_filtered(page, reader, cls)
            except Exception:
                # the filtered extraction itself failed: the page's
                # visible text cannot be delivered - fail closed too
                return self._withheld_segments(page_num, cls)
        else:
            text = self._extract_text_quiet(page)
        if text.strip():
            segments.append(Segment(
                text=text,
                visible=True,
                kind="body",
                location=f"page {page_num}",
            ))

        raw = "".join(pc.text for pc in cls.page_pieces if not pc.hidden)
        if raw and self._contains_invisible(raw) and not self._contains_invisible(text):
            segments.append(Segment(
                text=raw,
                visible=True,
                kind="body",
                location=f"page {page_num} (raw stream)",
            ))
        hidden = "".join(pc.text for pc in cls.page_pieces if pc.hidden)
        if hidden:
            segments.append(Segment(
                text=hidden,
                visible=False,
                kind="css_hidden",
                location=f"page {page_num} (invisible text, Tr 3)",
            ))

        for form_name, form_raw, form_hidden in self._scan_form_streams(
                page, reader, self._drawn_modes(cls)):
            if form_hidden:
                segments.append(Segment(
                    text=form_hidden,
                    visible=False,
                    kind="css_hidden",
                    location=(f"page {page_num} (form '{form_name}', "
                              f"invisible text, Tr 3)"),
                ))
            if (form_raw and self._contains_invisible(form_raw)
                    and not self._contains_invisible(text)):
                segments.append(Segment(
                    text=form_raw,
                    visible=True,
                    kind="body",
                    location=(f"page {page_num} (form '{form_name}', "
                              f"raw stream)"),
                ))

        return segments

    def _withheld_segments(self, page_num: int,
                           cls: "_PageClassification") -> List[Segment]:
        """The fail-closed page output: an empty body segment carrying
        the existing unobserved-reason word in the page location, plus
        the hidden text the classification did establish before the
        failure (observation side)."""
        segments: List[Segment] = [Segment(
            text="",
            visible=True,
            kind="body",
            location=f"page {page_num} ({self._WITHHELD_REASON})",
        )]
        page_hidden = "".join(pc.text for pc in cls.page_pieces
                              if pc.hidden)
        if page_hidden:
            segments.append(Segment(
                text=page_hidden,
                visible=False,
                kind="css_hidden",
                location=f"page {page_num} (invisible text, Tr 3)",
            ))
        return segments

    def _drawn_modes(self, cls: "_PageClassification") -> Dict[int, int]:
        """{form object id: invocation mode}, first invocation wins."""
        modes: Dict[int, int] = {}
        for record in self._iter_records(cls):
            modes.setdefault(id(record.obj), record.entry_mode)
        return modes

    # ------------------------------------------------------------------
    # Observation-side scans (0.22.0 semantics; they share only the
    # _TrState state machine with the visible side)
    # ------------------------------------------------------------------

    def _scan_stream_object(self, contents, reader,
                            seed_mode: int = 0) -> Tuple[str, str]:
        """Scan one content-stream object (page /Contents or Form
        XObject) for the observation: returns (raw_text, tr3_text).

        raw_text keeps the 0.22.0 rescue role (preserve zero-width and
        bidi characters the font encoding drops) but, since 0.22.1, it
        respects the same render-mode classification as the visible
        side (mode 3/7 text is not part of it); tr3_text is the mode 3
        text exactly as 0.22.0 reported it. The state machine is the
        shared one; _StateError propagates so the caller's existing
        failure handling (skip this stream) stays in place.
        """
        try:
            stream = ContentStream(contents, reader)
        except Exception:
            return "", ""

        raw_parts: List[str] = []
        tr3_parts: List[str] = []
        state = _TrState(seed_mode)
        for operands, operator in stream.operations:
            try:
                if operator in (b"Tr", b"q", b"Q"):
                    state.apply(operator, operands)
                elif operator in (b"Tj", b"'"):
                    s = self._decode(operands[0])
                    raw_parts.append(s)
                    if state.mode == 3:
                        tr3_parts.append(s)
                elif operator == b'"':
                    s = self._decode(operands[-1])
                    raw_parts.append(s)
                    if state.mode == 3:
                        tr3_parts.append(s)
                elif operator == b"TJ":
                    items = operands[0]
                    for item in items:
                        if isinstance(item, (bytes, str)):
                            s = self._decode(item)
                            raw_parts.append(s)
                            if state.mode == 3:
                                tr3_parts.append(s)
            except _StateError:
                raise
            except Exception:
                continue
        return "".join(raw_parts), "".join(tr3_parts)

    def _scan_form_streams(self, page, reader,
                           drawn_modes: Optional[Dict[int, int]] = None):
        """Walk Form XObjects declared in the page's /Resources.

        Coverage principle (same as metadata/annotations): every Form
        declared in /Resources is scanned, whether or not it is drawn
        via /Do. Survey basis (pypdf 6.19.0, measured): page.images
        already enumerates form/inline images and extract_text already
        returns form-internal text, but nothing scanned form content
        streams - Tr 3 text inside forms was reported as visible body
        only (H4 false negative) and the raw-stream rescue never
        reached forms.

        Since 0.22.1 a form the page invokes (Do) is scanned with the
        render mode at its invocation (the shared classification);
        0.22.0 scanned every form from mode 0. Unreferenced forms keep
        the mode 0 seed. All existing samples invoke forms at mode 0,
        so their observation is unchanged.

        Cycle defense: the visited set of indirect object numbers is
        the primary guard (pypdf defends its own extract_text walk,
        but this observer must not rely on that); _MAX_FORM_DEPTH is
        insurance against malformed deep graphs, not the primary
        defense.
        """
        results = []
        try:
            resources = page.get("/Resources")
            resources = resources.get_object() if resources is not None else None
            xobjs = resources.get("/XObject") if resources is not None else None
            xobjs = xobjs.get_object() if xobjs is not None else None
        except Exception:
            return results
        if not xobjs:
            return results
        visited = set()
        drawn_modes = drawn_modes or {}

        def _walk(container, depth):
            try:
                keys = list(container.keys())
            except Exception:
                return
            for key in keys:
                try:
                    obj = container[key].get_object()
                except Exception:
                    continue
                if str(obj.get("/Subtype")) != "/Form":
                    continue
                idnum = getattr(getattr(obj, "indirect_reference", None),
                                "idnum", None)
                if idnum is not None:
                    if idnum in visited:
                        continue
                    visited.add(idnum)
                if depth > self._MAX_FORM_DEPTH:
                    continue
                try:
                    seed = drawn_modes.get(id(obj), 0)
                    form_raw, form_hidden = self._scan_stream_object(
                        obj, reader, seed_mode=seed)
                except Exception:
                    continue
                results.append((str(key), form_raw, form_hidden))
                try:
                    fres = obj.get("/Resources")
                    fres = fres.get_object() if fres is not None else None
                    child = fres.get("/XObject") if fres is not None else None
                    child = child.get_object() if child is not None else None
                except Exception:
                    continue
                if child:
                    _walk(child, depth + 1)

        _walk(xobjs, 0)
        return results

    @staticmethod
    def _contains_invisible(text: str) -> bool:
        return any(ord(c) in INVISIBLE for c in text)

    def _extract_annotations(self, page, page_num: int) -> List[Segment]:
        segments = []
        try:
            if "/Annots" not in page:
                return segments
            annots = page["/Annots"]
        except Exception:
            return segments
        try:
            annots = list(annots)
        except TypeError:
            return segments
        for idx, annot in enumerate(annots, start=1):
            try:
                obj = annot.get_object()
            except Exception:
                continue
            try:
                contents = obj.get("/Contents")
            except Exception:
                continue
            if isinstance(contents, str) and len(contents.strip()) >= self._OOB_MIN_LENGTH:
                segments.append(Segment(
                    text=contents,
                    visible=False,
                    kind="comment",
                    location=f"page {page_num} annotation #{idx}",
                ))
        return segments

    @staticmethod
    def _decode(s) -> str:
        """Decode a PDF text string.

        PDF text strings may be encoded as:
          - ASCII/Latin-1 byte strings
          - UTF-16BE with a leading BOM (FE FF)

        pypdf may wrap string operands in ByteStringObject or similar
        classes; we unwrap those first.
        """
        # pypdf's ByteStringObject / TextStringObject expose raw bytes
        if hasattr(s, "original_bytes"):
            try:
                s = s.original_bytes
            except Exception:
                pass
        elif hasattr(s, "original"):
            try:
                s = s.original
            except Exception:
                pass

        if isinstance(s, bytes):
            if s.startswith(b"\xfe\xff"):
                try:
                    return s[2:].decode("utf-16-be")
                except Exception:
                    pass
            try:
                return s.decode("latin-1")
            except Exception:
                return ""
        return str(s)


class _TrState:
    """The text render mode, per PDF 32000-1 (sections 8.4 and 9.3.6).

    One instance classifies a whole page walk; the observation and the
    visible text are both derived from it (one judgment, two outputs).
    ``Tr`` sets the mode, ``q``/``Q`` save and restore it, ``BT``/``ET``
    do not reset it (text state is part of the graphics state), and a
    Form XObject invoked by ``Do`` inherits the mode at its invocation
    (the caller saves and restores around the form).
    """

    __slots__ = ("mode", "stack")

    def __init__(self, mode: int = 0):
        self.mode = mode
        self.stack: List[int] = []

    def apply(self, operator: bytes, operands) -> None:
        if operator == b"Tr":
            try:
                self.mode = int(operands[0])
            except (IndexError, TypeError, ValueError):
                raise _StateError("Tr operand is not a number")
        elif operator == b"q":
            self.stack.append(self.mode)
        elif operator == b"Q":
            if self.stack:
                self.mode = self.stack.pop()
        # BT/ET: nothing to do - the mode persists


class _StateError(Exception):
    """The render-mode state could not be tracked (fail closed)."""


class _Piece:
    """One decoded show operand with its classification."""

    __slots__ = ("text", "hidden", "op_index")

    def __init__(self, text: str, hidden: bool, op_index: int):
        self.text = text
        self.hidden = hidden
        self.op_index = op_index


class _FormRecord:
    """The classification of one drawn Form XObject."""

    __slots__ = ("entry_mode", "obj", "source_contents", "pieces", "drop",
                 "show_indexes", "children", "site_name", "site_xobjs")

    def __init__(self, entry_mode: int, obj, source_contents):
        self.entry_mode = entry_mode
        self.obj = obj
        self.source_contents = source_contents
        self.pieces: List[_Piece] = []
        self.drop: Set[int] = set()
        self.show_indexes: Set[int] = set()
        self.children: List[Tuple[str, "_FormRecord"]] = []
        self.site_name: Optional[str] = None
        self.site_xobjs = None


class _PageClassification:
    """The classification of one page (the shared judgment).

    ``forms`` maps the first resource name each drawn form was invoked
    under to its record (used by the tests to tie the observation's
    per-form report to the classification); ``records_by_obj`` maps
    every reached form object to its record (cycle and alias guard);
    ``top_sites`` lists the page-level Do sites for the filtered
    extraction's resource replacement.
    """

    __slots__ = ("page_pieces", "page_drop", "page_show_indexes",
                 "forms", "records_by_obj", "top_sites", "failed",
                 "page_stream", "page_contents")

    def __init__(self):
        self.page_pieces: List[_Piece] = []
        self.page_drop: Set[int] = set()
        self.page_show_indexes: Set[int] = set()
        self.forms: Dict[str, _FormRecord] = {}
        self.records_by_obj: Dict[int, _FormRecord] = {}
        self.top_sites: List[Tuple[_FormRecord, object, str]] = []
        self.failed: bool = False
        self.page_stream = None
        self.page_contents = None

    def page_show_indexes_add(self, parent_record, op_index: int) -> None:
        if parent_record is not None:
            parent_record.show_indexes.add(op_index)
        else:
            self.page_show_indexes.add(op_index)

    def page_drop_add(self, parent_record, op_index: int) -> None:
        if parent_record is not None:
            parent_record.drop.add(op_index)
        else:
            self.page_drop.add(op_index)


def install(engine) -> None:
    """Attach PDF support to a SieveLensEngine instance."""
    engine.register_extractor([".pdf"], PdfExtractor())
