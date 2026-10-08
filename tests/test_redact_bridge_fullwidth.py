"""Full-width homoglyph twins in the redact bridge catalog.

The bridge maps non-ASCII lookalike characters to a single ASCII twin.
This file pins the full-width additions: digits U+FF10-FF19 and letters
U+FF21-FF3A / U+FF41-FF5A, each mapping to the corresponding ASCII
character (constant offset 0xFEE0), on top of the base Cyrillic/Greek
table (40 entries).

Run: python -m pytest tests/test_redact_bridge_fullwidth.py -q
"""

import unittest

import sieve_lens
from sieve_lens_ext import redact_bridge


def u(cp):
    return "U+%04X" % cp


# Expected full-width twins, derived mechanically (offset 0xFEE0).
EXPECTED_FULLWIDTH = {}
for _cp in range(0xFF10, 0xFF1A):          # full-width digits -> 0-9
    EXPECTED_FULLWIDTH[_cp] = chr(_cp - 0xFEE0)
for _cp in range(0xFF21, 0xFF3B):          # full-width uppercase A-Z
    EXPECTED_FULLWIDTH[_cp] = chr(_cp - 0xFEE0)
for _cp in range(0xFF41, 0xFF5B):          # full-width lowercase a-z
    EXPECTED_FULLWIDTH[_cp] = chr(_cp - 0xFEE0)


class FullwidthTwins(unittest.TestCase):
    def test_table_contains_all_fullwidth(self):
        for cp, t in EXPECTED_FULLWIDTH.items():
            self.assertEqual(
                redact_bridge.HOMOGLYPH_TWINS.get(cp), t,
                "twin mismatch at %s" % u(cp))

    def test_table_size_102(self):
        # 40 base (Cyrillic/Greek) + 62 full-width (10 digits + 52 letters)
        self.assertEqual(len(redact_bridge.HOMOGLYPH_TWINS), 102)

    def test_letter_entry_shape(self):
        cat = redact_bridge.build_catalog("\uff21")
        self.assertEqual(len(cat["observations"]), 1)
        e = cat["observations"][0]
        self.assertEqual(e["kind"], "homoglyph")
        self.assertEqual(e["codepoint"], "U+FF21")
        self.assertEqual(e["twin"], "U+0041")
        self.assertEqual(e["positions"], [0])
        self.assertEqual(e["count"], 1)

    def test_digit_entry_shape(self):
        cat = redact_bridge.build_catalog("\uff10")
        self.assertEqual(len(cat["observations"]), 1)
        e = cat["observations"][0]
        self.assertEqual(e["kind"], "homoglyph")
        self.assertEqual(e["codepoint"], "U+FF10")
        self.assertEqual(e["twin"], "U+0030")

    def test_twins_are_ascii_alnum_and_disjoint(self):
        for cp, t in redact_bridge.HOMOGLYPH_TWINS.items():
            self.assertNotIn(cp, sieve_lens.INVISIBLE)
            self.assertTrue(t.isascii() and t.isalnum(),
                            "twin at %s is not ASCII alnum" % u(cp))

    def test_positions_in_mixed_text(self):
        cat = redact_bridge.build_catalog("x\uff10y\uff21z")
        codes = [e["codepoint"] for e in cat["observations"]]
        self.assertEqual(codes, ["U+FF10", "U+FF21"])
        by_cp = {e["codepoint"]: e for e in cat["observations"]}
        self.assertEqual(by_cp["U+FF10"]["positions"], [1])
        self.assertEqual(by_cp["U+FF21"]["positions"], [3])
        self.assertEqual(by_cp["U+FF10"]["twin"], "U+0030")
        self.assertEqual(by_cp["U+FF21"]["twin"], "U+0041")


if __name__ == "__main__":
    unittest.main()
