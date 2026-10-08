"""Sieve Lens → Sieve Redact bridge (目録 JSON).

Redact の --from-lens が消費する観測目録 (契約 v1 + twin) を生成する。
文字集合はコアの公開定数 (ZERO_WIDTH / BIDI_CONTROL / INVISIBLE /
strip_leading_bom) を import して単一情報源とする (ずれはテストが検出)。

決定性: 同一入力 → 同一バイト列。stdlib のみ・オフライン・テレメトリなし。

出力契約 (observations[*] に省略可能な twin を含む目録 JSON):
    {"lens": "sieve-lens", "version": 1,
     "observations": [
       {"kind": "H2", "codepoint": "U+200B",
        "count": 2, "positions": [1, 5]},                  # 不可視文字
       {"kind": "homoglyph", "codepoint": "U+0430",
        "twin": "U+0061", "count": 1, "positions": [3]}]   # 同形文字
    }
  - observations は出現コードポイントごと (初出順・重複排除)
  - positions は 0 始まりの文字インデックス
  - kind: H2 (ZERO_WIDTH) > H3 (BIDI_CONTROL) > H7 (その他の INVISIBLE)。
    同形文字は "homoglyph" + twin (ASCII 英数字 1 文字)
  - Redact は kind をルール生成に使わない (twin の有無のみ参照)

CLI:
    python -m sieve_lens_ext.redact_bridge IN.txt OUT.json
    終了コード: 0 = 成功 / 1 = 失敗 (用法・読み書き・非 UTF-8)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sieve_lens import (
    BIDI_CONTROL,
    INVISIBLE,
    ZERO_WIDTH,
    strip_leading_bom,
)

LENS_NAME = "sieve-lens"
CATALOG_VERSION = 1

# 同形文字 → ASCII 英数字 twin (単一文字) の決定的静的テーブル。
# キリル大文字 12 + キリル小文字 8 + ギリシャ大文字 14 + ギリシャ小文字 6
# + 全角数字 10 + 全角英字 52 (U+FF10-FF19 / U+FF21-FF3A / U+FF41-FF5A)。
# 全量が tests/test_redact_bridge.py の EXPECTED_TWINS で固定される。
# キーは INVISIBLE と非重複 (テストが assert)。
HOMOGLYPH_TWINS = {
    # キリル大文字
    0x0410: "A", 0x0412: "B", 0x0415: "E", 0x041A: "K", 0x041C: "M",
    0x041D: "H", 0x041E: "O", 0x0420: "P", 0x0421: "C", 0x0422: "T",
    0x0423: "Y", 0x0425: "X",
    # キリル小文字
    0x0430: "a", 0x0435: "e", 0x043E: "o", 0x0440: "p", 0x0441: "c",
    0x0443: "y", 0x0445: "x", 0x0456: "i",
    # ギリシャ大文字
    0x0391: "A", 0x0392: "B", 0x0395: "E", 0x0396: "Z", 0x0397: "H",
    0x0399: "I", 0x039A: "K", 0x039C: "M", 0x039D: "N", 0x039F: "O",
    0x03A1: "P", 0x03A4: "T", 0x03A5: "Y", 0x03A7: "X",
    # ギリシャ小文字
    0x03B9: "i", 0x03BF: "o", 0x03C1: "p", 0x03C5: "u", 0x03C7: "x",
    0x03BD: "v",
    # 全角数字
    0xFF10: "0", 0xFF11: "1", 0xFF12: "2", 0xFF13: "3", 0xFF14: "4", 0xFF15: "5",
    0xFF16: "6", 0xFF17: "7", 0xFF18: "8", 0xFF19: "9",
    # 全角英字 (大文字)
    0xFF21: "A", 0xFF22: "B", 0xFF23: "C", 0xFF24: "D", 0xFF25: "E", 0xFF26: "F",
    0xFF27: "G", 0xFF28: "H", 0xFF29: "I", 0xFF2A: "J", 0xFF2B: "K", 0xFF2C: "L",
    0xFF2D: "M", 0xFF2E: "N", 0xFF2F: "O", 0xFF30: "P", 0xFF31: "Q", 0xFF32: "R",
    0xFF33: "S", 0xFF34: "T", 0xFF35: "U", 0xFF36: "V", 0xFF37: "W", 0xFF38: "X",
    0xFF39: "Y", 0xFF3A: "Z",
    # 全角英字 (小文字)
    0xFF41: "a", 0xFF42: "b", 0xFF43: "c", 0xFF44: "d", 0xFF45: "e", 0xFF46: "f",
    0xFF47: "g", 0xFF48: "h", 0xFF49: "i", 0xFF4A: "j", 0xFF4B: "k", 0xFF4C: "l",
    0xFF4D: "m", 0xFF4E: "n", 0xFF4F: "o", 0xFF50: "p", 0xFF51: "q", 0xFF52: "r",
    0xFF53: "s", 0xFF54: "t", 0xFF55: "u", 0xFF56: "v", 0xFF57: "w", 0xFF58: "x",
    0xFF59: "y", 0xFF5A: "z",
}


def _kind_of(cp: int) -> str:
    """INVISIBLE 内のコードポイントの情報ラベル (H2 > H3 > H7)。

    Redact は kind をルール生成に使わない (表示・観測側の整理用)。
    """
    if cp in ZERO_WIDTH:
        return "H2"
    if cp in BIDI_CONTROL:
        return "H3"
    return "H7"


def build_catalog(text: str) -> dict:
    """本文テキストから目録 (契約 v1 + twin) を構築する。

    先行 BOM はコアと同一の strip_leading_bom で除去する
    (SieveLensEngine.observe_text と同じ挙動)。
    """
    text = strip_leading_bom(text)
    order = []  # 出現コードポイント (int) の初出順
    info = {}   # cp -> {"kind": str, "positions": [int], "twin": str|None}
    for i, ch in enumerate(text):
        cp = ord(ch)
        if cp in INVISIBLE:
            kind, twin = _kind_of(cp), None
        elif cp in HOMOGLYPH_TWINS:
            kind, twin = "homoglyph", HOMOGLYPH_TWINS[cp]
        else:
            continue
        if cp not in info:
            info[cp] = {"kind": kind, "positions": [], "twin": twin}
            order.append(cp)
        info[cp]["positions"].append(i)
    observations = []
    for cp in order:
        d = info[cp]
        entry = {
            "kind": d["kind"],
            "codepoint": "U+%04X" % cp,
            "count": len(d["positions"]),
            "positions": d["positions"],
        }
        if d["twin"] is not None:
            entry["twin"] = "U+%04X" % ord(d["twin"])
        observations.append(entry)
    return {"lens": LENS_NAME, "version": CATALOG_VERSION,
            "observations": observations}


def catalog_json(text: str) -> str:
    """目録の決定的な JSON 文字列 (末尾改行つき)。"""
    return json.dumps(build_catalog(text), ensure_ascii=False, indent=2) + "\n"


def main(argv=None) -> int:
    """CLI: IN.txt OUT.json。0 = 成功 / 1 = 失敗 (詳細は stderr)。"""
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 2:
        print("usage: python -m sieve_lens_ext.redact_bridge IN.txt OUT.json",
              file=sys.stderr)
        return 1
    src, dst = argv
    try:
        raw = Path(src).read_bytes()
    except OSError as exc:
        print(f"redact_bridge: cannot read {src}: {exc}", file=sys.stderr)
        return 1
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        print(f"redact_bridge: input is not valid UTF-8: {exc}",
              file=sys.stderr)
        return 1
    payload = catalog_json(text)
    try:
        Path(dst).write_bytes(payload.encode("utf-8"))
    except OSError as exc:
        print(f"redact_bridge: cannot write {dst}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
