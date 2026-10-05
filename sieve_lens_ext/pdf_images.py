"""PDF embedded-image analysis extension for Sieve Lens.

Enumerates raster images embedded in PDF pages via pypdf's ``page.images``
API, decodes them into PIL images, and inspects the pixels for hidden-layer
patterns (fully transparent regions whose RGB is preserved, near-flat
low-contrast layers). Findings are emitted as invisible segments so the
engine can raise H4.

v0.11.0 fixes (bugs #38 and #3):

* P14: :meth:`PdfImagesExtractor._get_page_images` is now implemented with
  ``list(page.images)``. v0.10.0 called this undefined method from
  :meth:`PdfImagesExtractor.extract` (AttributeError at line 99) and
  ``_CombinedExtractor`` swallowed it with ``except Exception: pass``, so
  PDF embedded-image analysis never produced a single segment.
* P4: :meth:`PdfImagesExtractor._load_image` now tries pypdf's decode result
  (``image_file.image``) first: pypdf composites ``/SMask`` into the alpha
  channel while preserving the RGB of invisible regions (verified with
  pypdf 6.19.0: flate ``(255,0,0,0)`` / dct ``(254,0,0,0)``). The raw-stream
  magic-number path (bare PNG/JPEG container) is kept as a fallback only,
  because that route carries no SMask.
* P5: ``_CombinedExtractor.extract`` propagates text-extractor failures
  (unanalysable file => H1=0, matching the engine's exception policy) while
  image extraction remains best-effort so it never buries text results.

Known limitations (documented, inherent to ``page.images``):

* inline images (BI/ID/EI operators) are not enumerated;
* images nested inside Form XObjects are not enumerated.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, List, Optional

from sieve_lens import Segment

try:
    from pypdf import PdfReader

    PYPDF_AVAILABLE = True
except ImportError:  # pragma: no cover - environment without pypdf
    PdfReader = None  # type: ignore[assignment]
    PYPDF_AVAILABLE = False

try:
    from PIL import Image, ImageChops

    PIL_AVAILABLE = True
except ImportError:  # pragma: no cover - environment without Pillow
    Image = None  # type: ignore[assignment]
    ImageChops = None  # type: ignore[assignment]
    PIL_AVAILABLE = False

__all__ = ["PdfImagesExtractor", "install", "PYPDF_AVAILABLE", "PIL_AVAILABLE"]


class PdfImagesExtractor:
    """Pixel-level analysis of the images embedded in PDF pages.

    Registered for ``.pdf`` through :func:`install` as the image half of the
    combined extractor (the text half keeps running first and its results are
    never discarded by an image-side failure).
    """

    EXTENSIONS = (".pdf",)

    # -- thresholds (aligned with sieve_lens_ext.image_layers semantics) ----
    _TRANSPARENT_MIN_PIXELS = 16
    _TRANSPARENT_MIN_RATIO = 0.001

    _LOW_CONTRAST_MIN_UNIQUE = 4
    _LOW_CONTRAST_MODE_RATIO = 0.30
    _LOW_CONTRAST_MIN_GAP = 32
    _LOW_CONTRAST_MIN_REGION_RATIO = 0.05

    # -- public API ----------------------------------------------------------
    def extract(self, path: Path) -> List[Segment]:
        """Analyse every enumerated image on every page (best-effort).

        This method itself never raises for image-side problems: per the P5
        policy, only the text extractor's failures may propagate (handled by
        ``_CombinedExtractor``).
        """
        segments: List[Segment] = []
        if not (PYPDF_AVAILABLE and PIL_AVAILABLE):
            return segments
        try:
            reader = PdfReader(str(path))
        except Exception:
            return segments
        try:
            for page_no, page in enumerate(reader.pages, start=1):
                for idx, image_file in enumerate(self._get_page_images(page)):
                    name = str(getattr(image_file, "name", "") or f"image #{idx}")
                    try:
                        img = self._load_image(image_file)
                    except Exception:
                        continue
                    if img is None:
                        continue
                    try:
                        segments.extend(self._analyze_image(img, page_no, name))
                    except Exception:
                        continue
        except Exception:
            # ページ列挙等の予期しない失敗も画像解析内では best-effort。
            # テキスト側の結果は _CombinedExtractor が既に保持しているため
            # ここで返す部分結果によって葬られることはない。
            return segments
        return segments

    # -- P14 -------------------------------------------------------------------
    def _get_page_images(self, page):
        """Enumerate images on a page via pypdf's page.images API.

        Limitations (documented): inline images (BI/ID/EI) and images inside
        Form XObjects are not enumerated by page.images.
        """
        try:
            return list(page.images)
        except Exception:
            return []

    # -- P4 --------------------------------------------------------------------
    def _load_image(self, image_file):
        # 1) pypdf のデコード結果を優先する。
        #    pypdf は /SMask をアルファに合成し、不可視領域の RGB を保持する。
        try:
            img = image_file.image
            if img is not None:
                return img
        except Exception:
            pass
        # 2) フォールバック: ストリームが PNG/JPEG コンテナを直接格納する場合。
        #    この経路は SMask を持たないため、優先しない。
        try:
            data = image_file.data
        except Exception:
            data = None
        if data and (data.startswith(b"\x89PNG") or data.startswith(b"\xff\xd8")):
            try:
                img = Image.open(io.BytesIO(data))
                img.load()
                return img
            except Exception:
                pass
        return None

    # -- pixel analysis ----------------------------------------------------------
    def _analyze_image(self, img, page_no: int, name: str) -> List[Segment]:
        segments: List[Segment] = []
        segments.extend(self._detect_transparent_layer(img, page_no, name))
        segments.extend(self._detect_low_contrast(img, page_no, name))
        return segments

    def _detect_transparent_layer(self, img, page_no: int, name: str) -> List[Segment]:
        """alpha=0 かつ RGB 非ゼロの領域（見えないがデータは存在する層）を検出する。"""
        try:
            has_alpha = img.mode in ("RGBA", "LA", "PA") or (
                "transparency" in (img.info or {})
            )
            if not has_alpha:
                return []
            rgba = img.convert("RGBA")
            width, height = rgba.size
            total = width * height
            if total == 0:
                return []
            a0 = rgba.getchannel("A").point(lambda v: 255 if v == 0 else 0)
            rgb_max = ImageChops.lighter(
                ImageChops.lighter(rgba.getchannel("R"), rgba.getchannel("G")),
                rgba.getchannel("B"),
            )
            nz = rgb_max.point(lambda v: 255 if v > 0 else 0)
            invisible = ImageChops.multiply(a0, nz)
            count = invisible.histogram()[255]
            if count < self._TRANSPARENT_MIN_PIXELS:
                return []
            if (count / total) < self._TRANSPARENT_MIN_RATIO:
                return []
            bbox = invisible.getbbox()
            first = (
                f"first hit at ({bbox[0]}, {bbox[1]})" if bbox else "first hit unknown"
            )
            ratio_pct = round((count / total) * 100, 2)
            return [
                Segment(
                    text=(
                        f"transparent layer: {count} pixels "
                        f"({ratio_pct}% of image) with alpha=0 and non-zero RGB"
                    ),
                    visible=False,
                    kind="css_hidden",
                    location=f"page {page_no}, image '{name}' ({width}x{height}), {first}",
                )
            ]
        except Exception:
            return []

    def _detect_low_contrast(self, img, page_no: int, name: str) -> List[Segment]:
        """ほぼ単色の低コントラスト層（白地に白文字など）を検出する。"""
        try:
            if img.mode in ("RGBA", "LA", "PA") or ("transparency" in (img.info or {})):
                base = Image.new("RGBA", img.convert("RGBA").size, (255, 255, 255, 255))
                base.alpha_composite(img.convert("RGBA"))
                gray = base.convert("L")  # 見た目に整合（白背景へ合成）
            else:
                gray = img.convert("L")
        except Exception:
            return []
        width, height = gray.size
        total = width * height
        if total == 0:
            return []
        histogram = gray.histogram()
        unique_levels = sum(1 for c in histogram if c)
        if unique_levels < self._LOW_CONTRAST_MIN_UNIQUE:
            return []
        mode_value = max(range(256), key=lambda v: histogram[v])
        mode_count = histogram[mode_value]
        if (mode_count / total) < self._LOW_CONTRAST_MODE_RATIO:
            return []
        lo = mode_value - self._LOW_CONTRAST_MIN_GAP
        hi = mode_value + self._LOW_CONTRAST_MIN_GAP
        far = sum(c for v, c in enumerate(histogram) if v < lo or v > hi)
        if far == 0:
            return []
        ratio = far / total
        if ratio < self._LOW_CONTRAST_MIN_REGION_RATIO:
            return []
        return [
            Segment(
                text=(
                    f"low-contrast layer: {far} pixels ({round(ratio * 100, 2)}% of image) "
                    f"differ from dominant gray level {mode_value} "
                    f"by >= {self._LOW_CONTRAST_MIN_GAP}"
                ),
                visible=False,
                kind="css_hidden",
                location=f"page {page_no}, image '{name}' ({width}x{height})",
            )
        ]


class _CombinedExtractor:
    """``.pdf`` extractor = registered text extractor + embedded-image analysis.

    v0.10.0 shipped this class with ``except Exception: pass`` around *both*
    halves, which is how bug #38 stayed invisible for a whole release.
    P5 restores the engine's exception policy: text failures propagate,
    image failures do not.
    """

    def __init__(self, text_extractor, images_extractor) -> None:
        self._text = text_extractor
        self._images = images_extractor

    def extract(self, path: Path) -> List[Segment]:
        if self._text is None:
            # テキスト抽出器を取得できない環境（P6 未適用のコア等）では
            # 画像解析のみで成立させる（P5 本体の前に置いた防御節）。
            return list(self._images.extract(path))
        # テキスト抽出の失敗 = 解析不能ファイル（H1=0）。エンジンの例外ポリシーに
        # 一致させるため伝播する。画像側の失敗は best-effort（テキスト結果を葬らない）。
        segments = list(self._text.extract(path))
        try:
            segments.extend(self._images.extract(path))
        except Exception:
            pass
        return segments


def _registered_text_extractor(engine: Any) -> Optional[object]:
    """Return the extractor currently registered for ``.pdf``, or None.

    P6（SieveLensEngine.get_extractor）適用済みのコアでは公開 API のみを使う。
    未適用のコアでも動かすため、get_extractor が無い場合は同じマッピング
    （engine._extractors）を直接読む。どちらも不可能なら None を返し、
    install() は画像解析のみを登録する（テキスト能力を壊さず、画像解析だけで
    H4 が成立する）。
    """
    getter = getattr(engine, "get_extractor", None)
    if callable(getter):
        try:
            return getter(".pdf")
        except Exception:
            pass
    registry = getattr(engine, "_extractors", None)
    if isinstance(registry, dict):
        try:
            return registry.get(".pdf")
        except Exception:
            return None
    return None


def install(engine: Any) -> None:
    """Replace the plain ``.pdf`` extractor with text + images combined.

    The text extractor already registered for ``.pdf`` (installed by
    ``sieve_lens_ext.pdf.install``) keeps running first; embedded-image
    analysis is chained after it and never discards its results.
    """
    engine.register_extractor(
        PdfImagesExtractor.EXTENSIONS,
        _CombinedExtractor(_registered_text_extractor(engine), PdfImagesExtractor()),
    )