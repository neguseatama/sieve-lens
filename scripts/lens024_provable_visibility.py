"""The provable-visibility measurement of the real collection.

Read-only measurement script (not part of the wheel): it re-uses the
engine's own drawing-state parts to evaluate the conservative rule R
against every show operation, and reports, per file, how many text
fragments the rule certifies as certainly visible - without changing
the observation, the visible text or the diagnostics in any way.

Rule R (measurement only): a fragment is certainly visible when

- the render mode is 0, 1, 2, 4, 5 or 6,
- the effective font size (Tf x the text-matrix scale x the CTM scale)
  is 2.0 pt or more,
- the drawing origin is inside the page's view box,
- no governing optional-content group is off,
- the opacity of the drawing side (fill for 0/4, stroke for 1/5, both
  for 2/6) resolves and stays above 0.02, with no soft mask or
  non-normal blend mode in effect,
- the clip region (when present) is a rectangle that the fragment's
  bounding box intersects,
- the drawing color resolves, and the background - the last fill whose
  box contains the fragment's bounding box, else the white page - has
  a resolvable color whose per-component difference from the drawing
  color reaches 0.5, and no image, shading or undecidable fill sits
  over that background under the fragment (an unknown background is
  never certainly visible).

Usage: python scripts/lens024_provable_visibility.py FILE [FILE ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from sieve_lens_ext.pdf import (  # noqa: E402
    ALPHA_MAX_HIDDEN, PdfExtractor, _color_delta, _color_near_white,
    _mat_apply, _scale2,
)

RULE_R_MIN_SIZE = 2.0
RULE_R_MIN_DELTA = 0.5


class _ProvableVisibilityExtractor(PdfExtractor):
    """The engine's extractor with one read-only hook: every show
    operation is additionally scored against rule R before the normal
    classification runs."""

    def __init__(self):
        super().__init__()
        self.rows = []

    def _classify_show(self, state, texts, resources, cls, box, paints):
        provable = self._rule_r(state, texts, resources, box, paints)
        reason, _label = super()._classify_show(
            state, texts, resources, cls, box, paints)
        self.rows.append((provable, reason is not None))
        return reason, _label

    def _rule_r(self, state, texts, resources, box, paints):
        if state.mode not in (0, 1, 2, 4, 5, 6):
            return False
        if state.size is None:
            return False
        effective = (state.size * _scale2(state.tm[:4])
                     * _scale2(state.ctm[:4]))
        if effective < RULE_R_MIN_SIZE:
            return False
        if box is None:
            return False
        origin = _mat_apply(state.ctm, state.tm[4], state.tm[5])
        if not (box[0] <= origin[0] <= box[2]
                and box[1] <= origin[1] <= box[3]):
            return False
        for item_pair in state.oc:
            item, _key = item_pair
            if item is not None and self._oc_item_off(item, cls.oc_cfg):
                return False
        if state.mode in (0, 4):
            alphas = (state.alpha_fill,)
        elif state.mode in (1, 5):
            alphas = (state.alpha_stroke,)
        else:
            alphas = (state.alpha_fill, state.alpha_stroke)
        if any(a <= ALPHA_MAX_HIDDEN for a in alphas):
            return False
        if state.smask or state.bm:
            return False
        if state.clip in ("empty", "unresolved"):
            return False
        joined = "".join(texts)
        bbox = self._text_bbox(state, joined, resources)
        if state.clip is not None:
            cx0, cy0, cx1, cy1 = state.clip[1]
            if not (bbox[0] < cx1 and cx0 < bbox[2]
                    and bbox[1] < cy1 and cy0 < bbox[3]):
                return False
        if state.mode in (1, 5):
            color = state.stroke
        else:
            color = state.fill
        if color[0] == "other" or color[1] is None:
            return False
        background = None
        covered = False
        for entry in paints:
            if entry[3] == "fill":
                box_p = entry[0]
                if (box_p[0] <= bbox[0] and box_p[1] <= bbox[1]
                        and bbox[2] <= box_p[2] and bbox[3] <= box_p[3]):
                    background = entry
            elif entry[0] is not None:
                box_p = entry[0]
                if (box_p[0] < bbox[2] and bbox[0] < box_p[2]
                        and box_p[1] < bbox[3] and bbox[1] < box_p[3]):
                    covered = True
            else:
                covered = True
        if background is not None \
                and _color_near_white(background[1]) is None:
            return False
        if covered and background is not None:
            # something unknown was painted over the background under
            # this fragment - the background is no longer known
            return False
        if background is not None:
            delta = _color_delta(color[0], color[1],
                                 background[1][0], background[1][1])
        else:
            delta = _color_delta(color[0], color[1], "gray", 1.0)
        if delta is None:
            return False
        return delta >= RULE_R_MIN_DELTA


def measure(path):
    from pypdf import PdfReader

    extractor = _ProvableVisibilityExtractor()
    rows_per_page = []
    with open(path, "rb") as f:
        reader = PdfReader(f)
        for page in reader.pages:
            extractor.rows = []
            cls = extractor._classify_page(page, reader)
            rows = list(extractor.rows)
            if cls.failed:
                # the page's visible text is withheld: nothing the
                # current way delivers is visible
                rows = [(provable, True) for provable, _ in rows]
            rows_per_page.append(rows)
    fragments = sum(len(rows) for rows in rows_per_page)
    provable = sum(1 for rows in rows_per_page
                   for p, _ in rows if p)
    not_provable = fragments - provable
    not_provable_visible = sum(1 for rows in rows_per_page
                               for p, hidden in rows
                               if not p and not hidden)
    return {"file": str(path), "fragments": fragments,
            "provable": provable, "not_provable": not_provable,
            "not_provable_current_visible": not_provable_visible}


def main(argv):
    if not argv:
        print(__doc__.strip())
        return 2
    header = ("file", "fragments", "provable", "not_provable",
              "not_provable_current_visible")
    print("\t".join(header))
    for arg in argv:
        row = measure(Path(arg))
        print("\t".join(str(row[key]) for key in header))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
