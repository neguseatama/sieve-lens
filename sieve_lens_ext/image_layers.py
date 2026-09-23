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
    from PIL import Image
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
    _LOW_CONTRAST_MIN_UNIQUE = 8          # ignore nearly-flat images
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
        if img.mode not in ("RGBA", "LA", "PA"):
            return []

        rgba = img.convert("RGBA")
        width, height = rgba.size
        total = width * height
        if total == 0:
            return []

        pixels = rgba.load()

        # Count pixels with alpha=0 and non-zero RGB (invisible text).
        invisible_count = 0
        first_hit: Optional[Tuple[int, int]] = None
        for y in range(height):
            for x in range(width):
                r, g, b, a = pixels[x, y]
                if a == 0 and (r != 0 or g != 0 or b != 0):
                    invisible_count += 1
                    if first_hit is None:
                        first_hit = (x, y)

        if invisible_count < self._TRANSPARENT_MIN_COUNT:
            return []
        if (invisible_count / total) < self._TRANSPARENT_MIN_RATIO:
            return []

        ratio_pct = round((invisible_count / total) * 100, 2)
        return [Segment(
            text=(
                f"transparent layer: {invisible_count} pixels "
                f"({ratio_pct}% of image) with alpha=0 and non-zero RGB"
            ),
            visible=False,
            kind="css_hidden",
            location=f"first hit at ({first_hit[0]}, {first_hit[1]})",
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

        pixels = gray.load()

        # Histogram
        histogram = [0] * 256
        for y in range(height):
            for x in range(width):
                histogram[pixels[x, y]] += 1

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
        for v in range(256):
            if abs(v - mode_value) < MIN_GAP:
                continue
            c = histogram[v]
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

        if contrast >= self._LOW_CONTRAST_RATIO_THRESHOLD:
            return []

        return [Segment(
            text=(
                f"low contrast: WCAG ratio {round(contrast, 2)}:1 "
                f"(background={mode_value}, "
                f"foreground_mean={round(mean_non_bg, 1)}, "
                f"region_ratio={round(non_bg_ratio, 3)})"
            ),
            visible=False,
            kind="css_hidden",
            location=f"grayscale analysis ({width}x{height})",
        )]


def install(engine) -> None:
    """Replace the image extractor with the layer-aware one.

    This installs on the same extensions as sieve_lens_ext.ocr, so
    install this one *after* the OCR extension to combine both.
    """
    extractor = ImageLayersExtractor()
    engine.register_extractor(ImageLayersExtractor.EXTENSIONS, extractor)


__all__ = ["ImageLayersExtractor", "install"]