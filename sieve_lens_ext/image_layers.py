"""
Sieve Lens image layer analysis extension.

Adds pixel-level analysis to image handling:
  - Transparent layer detection (RGBA images with alpha=0 pixels
    that carry non-zero RGB values, i.e. invisible text)
  - Low-contrast concealment detection (foreground/background
    luminance gap below a threshold)

These are surfaced as H4 (Format Concealment), complementing the
metadata-based H5 detection in sieve_lens_ext.ocr.

Requires:
  - Pillow >= 10.0

Install with:
    pip install sieve-lens[ocr]

Usage:
    from sieve_lens import SieveLensEngine
    from sieve_lens_ext.image_layers import install

    engine = SieveLensEngine()
    install(engine)
    obs = engine.observe("image.png")
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

try:
    from PIL import Image, ImageChops
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from sieve_lens import Segment


class ImageLayersExtractor:
    """Extract pixel-level and metadata segments from an image."""

    EXTENSIONS = [
        ".png", ".gif", ".tif", ".tiff", ".webp",
        ".jpg", ".jpeg", ".bmp",
    ]

    # Transparent-layer detection thresholds
    _TRANSPARENT_MIN_RATIO = 0.005   # ≥0.5% of pixels are invisible
    _TRANSPARENT_MIN_COUNT = 100     # and at least 100 pixels

    # Low-contrast detection thresholds
    _LOW_CONTRAST_RATIO_THRESHOLD = 2.0   # WCAG-based, <2.0 is "failing"
    _LOW_CONTRAST_MIN_UNIQUE = 8          # min distinct non-background gray levels required to fire H4
    _LOW_CONTRAST_MIN_REGION = 0.01       # ≥1% of pixels in the dark cluster

    def extract(self, path: Path) -> List[Segment]:
        if not PIL_AVAILABLE:
            raise ImportError(
                "sieve_lens_ext.image_layers requires Pillow. "
                "Install with: pip install sieve-lens[ocr]"
            )
        segments: List[Segment] = []
        with Image.open(path) as img:
            segments.extend(self._detect_transparent_layer(img))
            segments.extend(self._detect_low_contrast(img))
        return segments

    # ------------------------------------------------------------------
    # Transparent-layer detection (H4)
    # ------------------------------------------------------------------

    def _detect_transparent_layer(self, img) -> List[Segment]:
        # v0.11.0: C-accelerated via channel ops + histogram.
        # Also recognizes palette transparency ("transparency" in info),
        # covering GIF / indexed PNG in addition to RGBA/LA/PA modes.
        has_alpha = (
            img.mode in ("RGBA", "LA", "PA")
            or "transparency" in (img.info or {})
        )
        if not has_alpha:
            return []

        rgba = img.convert("RGBA")
        width, height = rgba.size
        total = width * height
        if total == 0:
            return []

        # Mask: alpha == 0
        a0 = rgba.getchannel("A").point(lambda v: 255 if v == 0 else 0)
        # Mask: any non-zero RGB
        rgb_max = ImageChops.lighter(
            ImageChops.lighter(rgba.getchannel("R"), rgba.getchannel("G")),
            rgba.getchannel("B"),
        )
        nz = rgb_max.point(lambda v: 255 if v > 0 else 0)
        invisible = ImageChops.multiply(a0, nz)

        histogram = invisible.histogram()
        invisible_count = histogram[255] if len(histogram) > 255 else 0

        if invisible_count < self._TRANSPARENT_MIN_COUNT:
            return []
        if (invisible_count / total) < self._TRANSPARENT_MIN_RATIO:
            return []

        bbox = invisible.getbbox()
        first = f"first hit at ({bbox[0]}, {bbox[1]})" if bbox else "first hit unknown"

        ratio_pct = round((invisible_count / total) * 100, 2)
        return [Segment(
            text=(
                f"transparent layer: {invisible_count} pixels "
                f"({ratio_pct}% of image) with alpha=0 and non-zero RGB"
            ),
            visible=False,
            kind="css_hidden",
            location=first,
        )]

    # ------------------------------------------------------------------
    # Low-contrast detection (H4)
    # ------------------------------------------------------------------

    def _detect_low_contrast(self, img) -> List[Segment]:
        try:
            gray = img.convert("L")
        except Exception:
            return []

        width, height = gray.size
        total = width * height
        if total == 0:
            return []

        # Histogram (C-accelerated via Pillow)
        histogram = gray.histogram()

        # Find the mode (background)
        mode_value = max(range(256), key=lambda v: histogram[v])
        mode_count = histogram[mode_value]

        # Require a dominant background
        if (mode_count / total) < 0.30:
            return []

        # Non-background pixels: differ from mode by >= MIN_GAP grey levels
        MIN_GAP = 5
        non_bg_count = 0
        non_bg_weighted_sum = 0
        unique_non_bg = 0
        for v in range(256):
            if abs(v - mode_value) < MIN_GAP:
                continue
            c = histogram[v]
            if c > 0:
                unique_non_bg += 1
            non_bg_count += c
            non_bg_weighted_sum += v * c

        if non_bg_count == 0:
            return []

        non_bg_ratio = non_bg_count / total
        if non_bg_ratio < self._LOW_CONTRAST_MIN_REGION:
            return []

        mean_non_bg = non_bg_weighted_sum / non_bg_count

        # WCAG relative luminance
        def luminance(v: int) -> float:
            c = v / 255.0
            if c <= 0.03928:
                return c / 12.92
            return ((c + 0.055) / 1.055) ** 2.4

        lum_bg = luminance(mode_value)
        lum_fg = luminance(int(round(mean_non_bg)))
        contrast = (max(lum_bg, lum_fg) + 0.05) / (min(lum_bg, lum_fg) + 0.05)

        if unique_non_bg < self._LOW_CONTRAST_MIN_UNIQUE:
            return []

        if contrast >= self._LOW_CONTRAST_RATIO_THRESHOLD:
            return []

        return [Segment(
            text=(
                f"low contrast: WCAG ratio {round(contrast, 2)}:1 "
                f"(background={mode_value}, "
                f"foreground_mean={round(mean_non_bg, 1)}, "
                f"region_ratio={round(non_bg_ratio, 3)}, "
                f"region_unique={unique_non_bg})"
            ),
            visible=False,
            kind="css_hidden",
            location=f"grayscale analysis ({width}x{height})",
        )]


def install(engine) -> None:
    """Chain the layer-aware extractor onto the existing image extractor
    (e.g. sieve_lens_ext.ocr) instead of replacing it, so metadata (H5)
    and pixel-level analysis (H4) both survive. v0.11.0 fix (#1).

    If no image extractor is registered yet, register the layer
    extractor standalone.
    """
    layer = ImageLayersExtractor()
    exts = list(ImageLayersExtractor.EXTENSIONS)
    base = engine.get_extractor(exts[0])
    if base is None:
        engine.register_extractor(exts, layer)
        return

    class _Chained:
        def extract(self, path):
            return base.extract(path) + layer.extract(path)

    engine.register_extractor(exts, _Chained())


__all__ = ["ImageLayersExtractor", "install"]