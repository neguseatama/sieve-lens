"""Sieve Lens → Sieve Redact bridge (目録 JSON) — 受け入れ試験.

契約: 目録 JSON (observations[*] に省略可能な twin を含む)。
本モジュールはコアの公開文字表 (ZERO_WIDTH / BIDI_CONTROL / INVISIBLE /
strip_leading_bom) を import して単一情報源とする。

実行: python -m pytest tests/test_redact_bridge.py -q
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import sieve_lens
from sieve_lens_ext import redact_bridge

REPO = Path(__file__).resolve().parent.parent

# 同形文字 → ASCII twin の完全な期待表 (102 エントリ)。
EXPECTED_TWINS = {
    "U+0410": "U+0041", "U+0412": "U+0042", "U+0415": "U+0045",
    "U+041A": "U+004B", "U+041C": "U+004D", "U+041D": "U+0048",
    "U+041E": "U+004F", "U+0420": "U+0050", "U+0421": "U+0043",
    "U+0422": "U+0054", "U+0423": "U+0059", "U+0425": "U+0058",
    "U+0430": "U+0061", "U+0435": "U+0065", "U+043E": "U+006F",
    "U+0440": "U+0070", "U+0441": "U+0063", "U+0443": "U+0079",
    "U+0445": "U+0078", "U+0456": "U+0069",
    "U+0391": "U+0041", "U+0392": "U+0042", "U+0395": "U+0045",
    "U+0396": "U+005A", "U+0397": "U+0048", "U+0399": "U+0049",
    "U+039A": "U+004B", "U+039C": "U+004D", "U+039D": "U+004E",
    "U+039F": "U+004F", "U+03A1": "U+0050", "U+03A4": "U+0054",
    "U+03A5": "U+0059", "U+03A7": "U+0058",
    "U+03B9": "U+0069", "U+03BF": "U+006F", "U+03C1": "U+0070",
    "U+03C5": "U+0075", "U+03C7": "U+0078", "U+03BD": "U+0076",
    "U+FF10": "U+0030", "U+FF11": "U+0031", "U+FF12": "U+0032",
    "U+FF13": "U+0033", "U+FF14": "U+0034", "U+FF15": "U+0035",
    "U+FF16": "U+0036", "U+FF17": "U+0037", "U+FF18": "U+0038",
    "U+FF19": "U+0039", "U+FF21": "U+0041", "U+FF22": "U+0042",
    "U+FF23": "U+0043", "U+FF24": "U+0044", "U+FF25": "U+0045",
    "U+FF26": "U+0046", "U+FF27": "U+0047", "U+FF28": "U+0048",
    "U+FF29": "U+0049", "U+FF2A": "U+004A", "U+FF2B": "U+004B",
    "U+FF2C": "U+004C", "U+FF2D": "U+004D", "U+FF2E": "U+004E",
    "U+FF2F": "U+004F", "U+FF30": "U+0050", "U+FF31": "U+0051",
    "U+FF32": "U+0052", "U+FF33": "U+0053", "U+FF34": "U+0054",
    "U+FF35": "U+0055", "U+FF36": "U+0056", "U+FF37": "U+0057",
    "U+FF38": "U+0058", "U+FF39": "U+0059", "U+FF3A": "U+005A",
    "U+FF41": "U+0061", "U+FF42": "U+0062", "U+FF43": "U+0063",
    "U+FF44": "U+0064", "U+FF45": "U+0065", "U+FF46": "U+0066",
    "U+FF47": "U+0067", "U+FF48": "U+0068", "U+FF49": "U+0069",
    "U+FF4A": "U+006A", "U+FF4B": "U+006B", "U+FF4C": "U+006C",
    "U+FF4D": "U+006D", "U+FF4E": "U+006E", "U+FF4F": "U+006F",
    "U+FF50": "U+0070", "U+FF51": "U+0071", "U+FF52": "U+0072",
    "U+FF53": "U+0073", "U+FF54": "U+0074", "U+FF55": "U+0075",
    "U+FF56": "U+0076", "U+FF57": "U+0077", "U+FF58": "U+0078",
    "U+FF59": "U+0079", "U+FF5A": "U+007A",
}


class BridgeBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "sieve_lens_ext.redact_bridge"] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(REPO))


class TablesAndContract(BridgeBase):
    def test_tables_are_core_single_source(self):
        self.assertIs(redact_bridge.ZERO_WIDTH, sieve_lens.ZERO_WIDTH)
        self.assertIs(redact_bridge.BIDI_CONTROL, sieve_lens.BIDI_CONTROL)
        self.assertIs(redact_bridge.INVISIBLE, sieve_lens.INVISIBLE)

    def test_catalog_contract_shape(self):
        cat = redact_bridge.build_catalog("a\u200bb\u202ec")
        self.assertEqual(set(cat), {"lens", "version", "observations"})
        self.assertEqual(cat["lens"], "sieve-lens")
        self.assertEqual(cat["version"], 1)
        for e in cat["observations"]:
            self.assertEqual(set(e), {"kind", "codepoint", "count", "positions"})
        kinds = {e["codepoint"]: e["kind"] for e in cat["observations"]}
        self.assertEqual(kinds["U+200B"], "H2")
        self.assertEqual(kinds["U+202E"], "H3")

    def test_kinds_h2_h3_h7(self):
        # Tag 文字 (U+E0001) と異体字セレクタ (U+FE0F) は H7 相当ラベル
        cat = redact_bridge.build_catalog("\u200b\u202e\U000E0001\uFE0F")
        kinds = {e["codepoint"]: e["kind"] for e in cat["observations"]}
        self.assertEqual(kinds["U+200B"], "H2")
        self.assertEqual(kinds["U+202E"], "H3")
        self.assertEqual(kinds["U+E0001"], "H7")
        self.assertEqual(kinds["U+FE0F"], "H7")

    def test_first_seen_order_and_positions(self):
        cat = redact_bridge.build_catalog("a\u200bb\u202ec\u200b")
        obs = cat["observations"]
        self.assertEqual([e["codepoint"] for e in obs], ["U+200B", "U+202E"])
        by_cp = {e["codepoint"]: e for e in obs}
        # 位置検算: 対象文字列は a(0) ZWSP(1) b(2)
        # RLO(3) c(4) ZWSP(5) の 6 文字 (0 始まり) なので位置は [1, 5]。
        self.assertEqual(by_cp["U+200B"]["positions"], [1, 5])
        self.assertEqual(by_cp["U+200B"]["count"], 2)
        self.assertEqual(by_cp["U+202E"]["positions"], [3])


class Homoglyphs(BridgeBase):
    def test_homoglyph_entries_have_twin(self):
        cat = redact_bridge.build_catalog("t\u0430rget")
        self.assertEqual(len(cat["observations"]), 1)
        e = cat["observations"][0]
        self.assertEqual(e["kind"], "homoglyph")
        self.assertEqual(e["codepoint"], "U+0430")
        self.assertEqual(e["twin"], "U+0061")
        self.assertEqual(e["positions"], [1])
        self.assertEqual(e["count"], 1)

    def test_homoglyph_table_fixed(self):
        self.assertEqual(len(redact_bridge.HOMOGLYPH_TWINS), 102)
        got = {"U+%04X" % cp: "U+%04X" % ord(t)
               for cp, t in redact_bridge.HOMOGLYPH_TWINS.items()}
        self.assertEqual(got, EXPECTED_TWINS)
        for cp, t in redact_bridge.HOMOGLYPH_TWINS.items():
            self.assertNotIn(cp, sieve_lens.INVISIBLE)  # 集合非重複
            self.assertTrue("A" <= t <= "Z" or "a" <= t <= "z"
                            or "0" <= t <= "9")

    def test_invisible_full_coverage_partition(self):
        # INVISIBLE の全コードポイントが H2/H3/H7 のいずれかにちょうど 1 回
        text = "".join(chr(cp) for cp in sorted(sieve_lens.INVISIBLE))
        cat = redact_bridge.build_catalog(text)
        self.assertEqual(len(cat["observations"]), len(sieve_lens.INVISIBLE))
        by_kind = {}
        for e in cat["observations"]:
            self.assertNotIn("twin", e)
            by_kind.setdefault(e["kind"], set()).add(int(e["codepoint"][2:], 16))
        self.assertEqual(by_kind.get("H2", set()), set(sieve_lens.ZERO_WIDTH))
        self.assertEqual(by_kind.get("H3", set()), set(sieve_lens.BIDI_CONTROL))
        self.assertEqual(by_kind.get("H7", set()),
                         sieve_lens.INVISIBLE - sieve_lens.ZERO_WIDTH
                         - sieve_lens.BIDI_CONTROL)

    def test_leading_bom_stripped(self):
        # コアと同一の先行 BOM 取扱い (strip_leading_bom)
        cat = redact_bridge.build_catalog("\ufeffa\u200b")
        self.assertEqual([e["codepoint"] for e in cat["observations"]],
                         ["U+200B"])


class DeterminismAndCli(BridgeBase):
    def test_catalog_json_deterministic_bytes(self):
        text = "x\u200by\u0430z\u202e"
        j1 = redact_bridge.catalog_json(text)
        j2 = redact_bridge.catalog_json(text)
        self.assertIsInstance(j1, str)
        self.assertEqual(j1, j2)
        json.loads(j1)  # 妥当な JSON

    def test_cli_writes_catalog_file(self):
        text = "t\u0430rget\u200b.example"
        inp = self.dir / "in.txt"
        out1 = self.dir / "o1.json"
        out2 = self.dir / "o2.json"
        inp.write_bytes(text.encode("utf-8"))
        r = self.run_cli(str(inp), str(out1))
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        r2 = self.run_cli(str(inp), str(out2))
        self.assertEqual(r2.returncode, 0)
        self.assertEqual(out1.read_bytes(), out2.read_bytes())  # 決定的
        data = json.loads(out1.read_bytes().decode("utf-8"))
        self.assertEqual(data, redact_bridge.build_catalog(text))


if __name__ == "__main__":
    unittest.main()
