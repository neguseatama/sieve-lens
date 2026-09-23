"""Tests for Sieve Lens i18n extension."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from sieve_lens_ext.i18n import (
    TRANSLATIONS,
    SUPPORTED_LANGUAGES,
    get_translations,
    hypothesis_label,
    supported_languages,
    detect_language,
    resolve_language,
)


class TestI18nCore(unittest.TestCase):

    def test_supported_languages(self):
        langs = supported_languages()
        self.assertIn("en", langs)
        self.assertIn("ja", langs)

    def test_get_translations_en(self):
        t = get_translations("en")
        self.assertEqual(t["dashboard_title"], "Sieve Lens Dashboard")
        self.assertEqual(t["summary_total"], "Total Files")

    def test_get_translations_ja(self):
        t = get_translations("ja")
        self.assertEqual(t["dashboard_title"], "Sieve Lens ダッシュボード")
        self.assertEqual(t["summary_total"], "総ファイル数")

    def test_get_translations_unknown_falls_back_to_en(self):
        t = get_translations("fr")
        self.assertEqual(t["dashboard_title"], "Sieve Lens Dashboard")

    def test_all_languages_have_same_keys(self):
        en_keys = set(TRANSLATIONS["en"].keys())
        for lang in SUPPORTED_LANGUAGES:
            self.assertEqual(
                set(TRANSLATIONS[lang].keys()),
                en_keys,
                f"Key mismatch in {lang}",
            )

    def test_hypothesis_label(self):
        self.assertEqual(hypothesis_label("en", "H4"), "Format Concealment")
        self.assertEqual(hypothesis_label("ja", "H4"), "フォーマット隠蔽")


class TestLanguageDetection(unittest.TestCase):

    def test_english_text(self):
        self.assertEqual(detect_language(["Hello world, this is English."]), "en")

    def test_japanese_text(self):
        samples = ["これは日本語のサンプルテキストです。"]
        self.assertEqual(detect_language(samples), "ja")

    def test_mixed_but_japanese_dominant(self):
        samples = ["日本語のテキストです hello"]
        self.assertEqual(detect_language(samples), "ja")

    def test_too_few_japanese_chars(self):
        # Only 2 Japanese characters: not enough
        self.assertEqual(detect_language(["Hi 日本"]), "en")

    def test_empty_samples(self):
        self.assertEqual(detect_language([]), "en")

    def test_ascii_only(self):
        self.assertEqual(detect_language(["abc", "def"]), "en")


class TestLanguageResolution(unittest.TestCase):

    def test_explicit_ja(self):
        self.assertEqual(resolve_language("ja", []), "ja")

    def test_explicit_en(self):
        self.assertEqual(resolve_language("en", []), "en")

    def test_auto_detects_japanese(self):
        samples = ["これは日本語のテキストです。"]
        self.assertEqual(resolve_language("auto", samples), "ja")

    def test_auto_detects_english(self):
        samples = ["This is English text."]
        self.assertEqual(resolve_language("auto", samples), "en")

    def test_unknown_lang_falls_back(self):
        self.assertEqual(resolve_language("fr", []), "en")


class TestDashboardIntegration(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, name, content):
        p = self.base / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_dashboard_ja(self):
        try:
            import jinja2
            import plotly
        except ImportError:
            self.skipTest("jinja2 or plotly not installed")

        from sieve_lens_ext.dashboard import build_dashboard

        self._write("a.txt", "Hello world")
        out = self.base.parent / "dash_ja.html"
        try:
            build_dashboard(
                input_dir=self.base,
                output_path=out,
                standalone=False,
                lang="ja",
            )
            content = out.read_text(encoding="utf-8")
            self.assertIn("Sieve Lens ダッシュボード", content)
            self.assertIn("総ファイル数", content)
            self.assertIn("クリーン", content)
        finally:
            if out.exists():
                out.unlink()

    def test_dashboard_en(self):
        try:
            import jinja2
            import plotly
        except ImportError:
            self.skipTest("jinja2 or plotly not installed")

        from sieve_lens_ext.dashboard import build_dashboard

        self._write("a.txt", "Hello world")
        out = self.base.parent / "dash_en.html"
        try:
            build_dashboard(
                input_dir=self.base,
                output_path=out,
                standalone=False,
                lang="en",
            )
            content = out.read_text(encoding="utf-8")
            self.assertIn("Sieve Lens Dashboard", content)
            self.assertIn("Total Files", content)
        finally:
            if out.exists():
                out.unlink()

    def test_dashboard_auto_detects_japanese(self):
        try:
            import jinja2
            import plotly
        except ImportError:
            self.skipTest("jinja2 or plotly not installed")

        from sieve_lens_ext.dashboard import build_dashboard

        self._write("a.txt", "これは日本語のサンプル文書です。文章が日本語で書かれています。")
        out = self.base.parent / "dash_auto.html"
        try:
            build_dashboard(
                input_dir=self.base,
                output_path=out,
                standalone=False,
                lang="auto",
            )
            content = out.read_text(encoding="utf-8")
            self.assertIn("Sieve Lens ダッシュボード", content)
        finally:
            if out.exists():
                out.unlink()


if __name__ == "__main__":
    unittest.main(verbosity=2)