"""Tests for Sieve Lens image layer analysis extension.

Skipped automatically if Pillow is not installed.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from sieve_lens import SieveLensEngine

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from sieve_lens_ext.image_layers import install


@unittest.skipUnless(PIL_AVAILABLE, "Pillow not installed")
class TestImageLayersExtension(unittest.TestCase):

    def setUp(self):
        self.engine = SieveLensEngine()
        install(self.engine)
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmpdir.cleanup()

    def _path(self, name):
        return Path(self._tmpdir.name) / name

    # -- registration --------------------------------------------------

    def test_png_is_registered(self):
        self.assertIn(".png", self.engine._extractors)

    # -- transparent layer --------------------------------------------

    def test_clean_rgba_png(self):
        # Fully opaque white image
        p = self._path("clean.png")
        img = Image.new("RGBA", (400, 200), (255, 255, 255, 255))
        img.save(p)
        obs = self.engine.observe(p)
        self.assertEqual(obs.h_states["H1"], 1)
        self.assertEqual(obs.h_states["H4"], 0)

    def test_transparent_layer_triggers_h4(self):
        # RGBA image where most pixels are fully transparent but carry
        # a non-zero RGB value (invisible payload).
        p = self._path("hidden.png")
        img = Image.new("RGBA", (200, 100), (255, 0, 0, 0))  # red, alpha=0
        img.save(p)
        obs = self.engine.observe(p)
        self.assertEqual(obs.h_states["H4"], 1)
        self.assertTrue(any("transparent layer" in e for e in obs.evidence["H4"]))

    def test_transparent_zero_rgb_not_triggered(self):
        # Fully transparent pixels with RGB=0,0,0 are just empty space.
        p = self._path("empty.png")
        img = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
        img.save(p)
        obs = self.engine.observe(p)
        self.assertEqual(obs.h_states["H4"], 0)

    def test_small_transparent_region_not_triggered(self):
        # A tiny transparent region (< 0.5% and < 100 px) should not trigger.
        p = self._path("tiny.png")
        img = Image.new("RGBA", (400, 400), (255, 255, 255, 255))
        for x in range(5):
            for y in range(5):
                img.putpixel((x, y), (255, 0, 0, 0))
        img.save(p)
        obs = self.engine.observe(p)
        self.assertEqual(obs.h_states["H4"], 0)

    # -- low contrast --------------------------------------------------

    def test_clean_high_contrast_image(self):
        p = self._path("contrast.png")
        img = Image.new("RGB", (400, 200), "white")
        draw = ImageDraw.Draw(img)
        draw.text((20, 80), "HELLO WORLD", fill="black")
        img.save(p)
        obs = self.engine.observe(p)
        self.assertEqual(obs.h_states["H4"], 0)

    def test_low_contrast_triggers_h4(self):
        # Light grey text on white background: WCAG ratio ~1.2
        p = self._path("low.png")
        img = Image.new("RGB", (600, 200), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([(50, 50), (550, 150)], fill=(230, 230, 230))
        draw.text((100, 90), "HIDDEN", fill=(220, 220, 220))
        img.save(p)
        obs = self.engine.observe(p)
        self.assertEqual(obs.h_states["H4"], 1)
        self.assertTrue(any("low contrast" in e for e in obs.evidence["H4"]))

    def test_nearly_flat_image_not_triggered(self):
        # A uniform image has too few unique grey levels; not a
        # concealment signal.
        p = self._path("flat.png")
        img = Image.new("RGB", (200, 100), (128, 128, 128))
        img.save(p)
        obs = self.engine.observe(p)
        self.assertEqual(obs.h_states["H4"], 0)

    # -- determinism ---------------------------------------------------

    def test_deterministic(self):
        p = self._path("det.png")
        img = Image.new("RGBA", (200, 100), (255, 0, 0, 0))
        img.save(p)
        results = [self.engine.observe(p) for _ in range(3)]
        for r in results[1:]:
            self.assertEqual(r.mask, results[0].mask)
            self.assertEqual(r.h_states, results[0].h_states)


if __name__ == "__main__":
    unittest.main(verbosity=2)