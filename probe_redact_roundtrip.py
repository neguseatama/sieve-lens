#!/usr/bin/env python3
"""probe_redact_roundtrip.py — Lens 観測と Redact 適用の合流検証.

合成入力 → redact_bridge CLI で目録 JSON → Sieve Redact --from-lens →
Lens 本体 observe_text で再観測 (不可視 0・同形文字 0) を機械検証する。
形式目印: 最後の行に "ROUNDTRIP OK" を含む。

使い方 (sieve_lens リポジトリ直下から):
    python3 probe_redact_roundtrip.py
    python3 probe_redact_roundtrip.py --redact /path/to/sieve_redact.py
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
DEFAULT_REDACT = REPO.parent / "sieve-redact" / "sieve_redact.py"

SYNTHETIC = "連絡先 t\u0430rget.example\u200b の確認\u202eを依頼"
CLEAN = "連絡先 target.example の確認を依頼"
EXPECTED_REDACTIONS = 3  # а→a (replace) + ZWSP (delete) + RLO (delete)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--redact", default=str(DEFAULT_REDACT))
    args = ap.parse_args()

    redact = Path(args.redact)
    if not redact.exists():
        print(f"ABORT: sieve_redact.py が見つかりません: {redact}")
        return 2

    with tempfile.TemporaryDirectory() as td_name:
        td = Path(td_name)
        inp = td / "in.txt"
        catalog = td / "catalog.json"
        outp = td / "out.txt"
        receipt = td / "receipt.json"
        inp.write_bytes(SYNTHETIC.encode("utf-8"))

        # [1] bridge CLI: 目録 JSON (契約 v1 + twin)
        r1 = subprocess.run(
            [sys.executable, "-m", "sieve_lens_ext.redact_bridge",
             str(inp), str(catalog)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(REPO))
        if r1.returncode != 0:
            print(f"ABORT: bridge CLI rc={r1.returncode}: "
                  f"{r1.stderr.decode('utf-8', 'replace')}")
            return 2
        cat = json.loads(catalog.read_bytes().decode("utf-8"))
        cps = [e["codepoint"] for e in cat["observations"]]
        print(f"[1] catalog: observations={cps}")

        # [2] Redact --from-lens (twin あり→replace / なし→delete)
        r2 = subprocess.run(
            [sys.executable, str(redact), str(inp), "-o", str(outp),
             "--from-lens", str(catalog), "--receipt", str(receipt)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if r2.returncode != 0:
            print(f"ABORT: redact rc={r2.returncode}: "
                  f"{r2.stderr.decode('utf-8', 'replace')}")
            return 2
        rec = json.loads(receipt.read_bytes().decode("utf-8"))
        print(f"[2] redact: total_redactions={rec['total_redactions']} "
              f"byte_integrity_verified={rec['byte_integrity_verified']}")
        if (rec["total_redactions"] != EXPECTED_REDACTIONS
                or rec["byte_integrity_verified"] is not True):
            print("ABORT: receipt mismatch")
            return 2

        # [3] 再観測 (Lens 本体・合成入力に対する測定)
        out_text = outp.read_bytes().decode("utf-8")
        from sieve_lens import SieveLensEngine
        obs = SieveLensEngine().observe_text(out_text)
        print(f"[3] re-observe: mask={obs.mask} h_states={obs.h_states}")

        if not (out_text == CLEAN
                and obs.h_states["H2"] == 0
                and obs.h_states["H3"] == 0
                and obs.h_states["H7"] == 0
                and "\u0430" not in out_text):
            print(f"ABORT: mismatch: got={out_text!r} expected={CLEAN!r}")
            return 2
    print("ROUNDTRIP OK: H2=0 H3=0 H7=0 homoglyph=0 (invisible threats removed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
