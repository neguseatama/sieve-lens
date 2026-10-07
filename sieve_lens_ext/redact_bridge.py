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
  - kind: H2 (ZERO_WIDTH) > H3 (BIDI_CONTROL) > H7 (其余の INVISIBLE)。
    同形文字は "homoglyph" + twin (ASCII ラテン 1 文字)
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

# 同形文字 → ASCII ラテン twin (単一文字) の決定的静的テーブル。
# キリル大文字 12 + キリル小文字 8 + ギリシャ大文字 14 + ギリシャ小文字 6。
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
