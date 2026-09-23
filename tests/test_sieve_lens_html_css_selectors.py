"""Tests for Sieve Lens HTML full CSS selector resolution extension."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from sieve_lens import SieveLensEngine

try:
    import tinycss2
    import cssselect2
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

from sieve_lens_ext.html_css_selectors import install


@unittest.skipUnless(AVAILABLE, "tinycss2 or cssselect2 not installed")
class TestHtmlCssSelectorsExtension(unittest.TestCase):

    def setUp(self):
        self.engine = SieveLensEngine()
        install(self.engine)
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, name, content):
        p = Path(self._tmpdir.name) / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_html_is_registered(self):
        self.assertIn(".html", self.engine._extractors)
        self.assertIn(".htm", self.engine._extractors)

    def test_clean_html(self):
        html = "<html><body><p>Hello world</p></body></html>"
        p = self._write("clean.html", html)
        obs = self.engine.observe(p)
        self.assertEqual(obs.h_states["H4"], 0)

    def test_simple_class_selector(self):
        html = (
            "<html><head><style>"
            ".secret { display: none; }"
            "</style></head><body>"
            '<div class="secret">Hidden</div>'
            "</body></html>"
        )
        p = self._write("class.html", html)
        self.assertEqual(self.engine.observe(p).h_states["H4"], 1)

    def test_simple_id_selector(self):
        html = (
            "<html><head><style>"
            "#hidden { visibility: hidden; }"
            "</style></head><body>"
            '<div id="hidden">Secret</div>'
            "</body></html>"
        )
        p = self._write("id.html", html)
        self.assertEqual(self.engine.observe(p).h_states["H4"], 1)

    def test_descendant_selector(self):
        html = (
            "<html><head><style>"
            "div.wrapper p { display: none; }"
            "</style></head><body>"
            '<div class="wrapper"><p>Hidden</p></div>'
            "</body></html>"
        )
        p = self._write("desc.html", html)
        obs = self.engine.observe(p)
        self.assertEqual(obs.h_states["H4"], 1)
        self.assertTrue(any("matched" in e for e in obs.evidence["H4"]))

    def test_child_selector(self):
        html = (
            "<html><head><style>"
            "div > span { display: none; }"
            "</style></head><body>"
            "<div><span>Hidden</span></div>"
            "</body></html>"
        )
        p = self._write("child.html", html)
        self.assertEqual(self.engine.observe(p).h_states["H4"], 1)

    def test_attribute_selector(self):
        html = (
            "<html><head><style>"
            "[data-hidden='true'] { display: none; }"
            "</style></head><body>"
            '<div data-hidden="true">Hidden</div>'
            "</body></html>"
        )
        p = self._write("attr.html", html)
        self.assertEqual(self.engine.observe(p).h_states["H4"], 1)

    def test_pseudo_class_selector(self):
        html = (
            "<html><head><style>"
            "li:first-child { display: none; }"
            "</style></head><body>"
            "<ul><li>Hidden</li><li>Visible</li></ul>"
            "</body></html>"
        )
        p = self._write("pseudo.html", html)
        self.assertEqual(self.engine.observe(p).h_states["H4"], 1)

    def test_not_pseudo_class(self):
        html = (
            "<html><head><style>"
            "p:not(.keep) { display: none; }"
            "</style></head><body>"
            '<p class="other">Hidden</p>'
            '<p class="keep">Visible</p>'
            "</body></html>"
        )
        p = self._write("not.html", html)
        self.assertEqual(self.engine.observe(p).h_states["H4"], 1)

    def test_sibling_selector(self):
        html = (
            "<html><head><style>"
            "h1 + p { display: none; }"
            "</style></head><body>"
            "<h1>Title</h1><p>Hidden</p>"
            "</body></html>"
        )
        p = self._write("sibling.html", html)
        self.assertEqual(self.engine.observe(p).h_states["H4"], 1)

    def test_selector_with_no_match_not_reported(self):
        html = (
            "<html><head><style>"
            ".nonexistent { display: none; }"
            "</style></head><body>"
            "<p>Hello</p>"
            "</body></html>"
        )
        p = self._write("nomatch.html", html)
        self.assertEqual(self.engine.observe(p).h_states["H4"], 0)

    def test_benign_rule_not_triggered(self):
        html = (
            "<html><head><style>"
            "p { color: red; }"
            "</style></head><body>"
            "<p>Normal</p>"
            "</body></html>"
        )
        p = self._write("benign.html", html)
        self.assertEqual(self.engine.observe(p).h_states["H4"], 0)

    def test_local_linked_stylesheet(self):
        self._write("styles.css", "div.hidden > span { display: none; }")
        html = (
            '<html><head>'
            '<link rel="stylesheet" href="styles.css">'
            "</head><body>"
            '<div class="hidden"><span>Secret</span></div>'
            "</body></html>"
        )
        p = self._write("linked.html", html)
        obs = self.engine.observe(p)
        self.assertEqual(obs.h_states["H4"], 1)
        self.assertTrue(any("styles.css" in e for e in obs.evidence["H4"]))

    def test_remote_stylesheet_ignored(self):
        html = (
            '<html><head>'
            '<link rel="stylesheet" href="https://example.com/evil.css">'
            "</head><body><p>Hello</p></body></html>"
        )
        p = self._write("remote.html", html)
        self.assertEqual(self.engine.observe(p).h_states["H4"], 0)

    def test_deterministic(self):
        html = (
            "<html><head><style>"
            "div.wrapper p { display: none; }"
            "</style></head><body>"
            '<div class="wrapper"><p>Hidden</p></div>'
            "</body></html>"
        )
        p = self._write("det.html", html)
        results = [self.engine.observe(p) for _ in range(3)]
        for r in results[1:]:
            self.assertEqual(r.mask, results[0].mask)
            self.assertEqual(r.h_states, results[0].h_states)


if __name__ == "__main__":
    unittest.main(verbosity=2)