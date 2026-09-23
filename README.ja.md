[English](README.md) | **日本語**

# Sieve Lens v0.4.0

**不可視プロンプト観測エンジン**

*Sieve Lens は、AI を疑うための道具ではない。*  
*AI が信頼できる入力を受け取るための道具である。*

> 履歴書・提出物・報告書などに含まれる「AI判定を意図的に誘導する不可視コンテンツ」を、
> 決定論的・ゼロ依存・説明可能な形で観測するエンジンです。

[Sieve](https://github.com/neguseatama/sieve-core) シリーズを、
**「機械可読性と人間可視性の乖離」** という新しいドメインへ拡張しました。

[![CI](https://github.com/neguseatama/sieve-lens/actions/workflows/test.yml/badge.svg)](https://github.com/neguseatama/sieve-lens/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)

---

## 💡 コンセプト

現代の AI 審査システムは、文書をテキストとして解析します。  
人間は、文書をレンダリング結果として読みます。  
この2つの視点は同じではなく、その差は悪用され得ます。

- **ゼロ幅文字** (`U+200B` など)：モデルは読めるが、人間には見えない。
- **CSS 隠蔽** (`display:none`)：人間には見えないが、パーサは読める。
- **帯域外チャネル**（コメント・メタデータ・ヘッダー・脚注）：パーサは読めるが、人間は見落とす。

**Sieve Lens は、この乖離を観測します。**  
悪意の有無は判定しません。位置情報とデコード結果を提示し、
最終判断を人間に委ねます。

> 「Sieve Lens」という名称は、レンズのように、肉眼では見えないものを
> 可視化するという設計思想に由来します。

---

## 📐 7-bit 観測空間

| 仮説 | 名称 | 観測内容 |
|------|------|----------|
| H1 | Parseability | 文書が正常に読み込めるか |
| H2 | Zero-Width Density | ゼロ幅文字の密度が閾値超過 |
| H3 | Bidi Controls | 双方向制御文字の存在 |
| H4 | Format Concealment | CSS による隠蔽（display:none 等） |
| H5 | Out-of-Band Channel | コメント・メタデータ・ヘッダー・フッター・脚注に実質的内容 |
| H6 | Script Mixing | 同一トークン内の異文字体系混在 |
| H7 | Contiguous Payload | 閾値長以上の連続した不可視文字 |

マスク表記：`H1H2H3H4-H5H6H7`（例：`1000-100`）

---

## 📦 対応形式

| 形式 | 対応範囲 | 依存 |
|------|---------|------|
| `.txt` / `.md` | プレーンテキスト、全文字スキャン | なし（Core） |
| `.html` / `.htm` | インライン style 属性および `<style>` ブロックの隠蔽検出、オプションで外部 CSS 解決 | なし（Core）；`tinycss2`（オプション） |
| `.docx` | 本文・コメント・core プロパティ・ヘッダー・フッター・脚注・末尾脚注 | なし（Core） |
| `.pdf` | 本文・メタデータ・注釈・不可視テキスト（Tr 3） | `pypdf`（オプション） |
| `.png` / `.jpg` / `.jpeg` / `.gif` / `.bmp` / `.tif` / `.tiff` / `.webp` | メタデータ（EXIF / PNG tEXt / XMP）＋ OCR テキスト | `Pillow`・`pytesseract` ＋ tesseract バイナリ（オプション） |

**非対応**：音声、動画

---

## 🔥 主な特徴

- **7-bit 観測空間（H1〜H7）**  
  不可視コンテンツの種類ごとに独立・決定論的に観測。
- **ゼロ依存**  
  Python 標準ライブラリのみ。オフライン動作、テレメトリなし。
- **決定論**  
  同一入力は、どの環境でも常に同一の観測結果を返す。
- **説明可能性**  
  すべての観測に位置情報とデコード結果を付与。
- **観測であって判定ではない**  
  エンジンは証拠を提示するのみ。「攻撃である」とは宣言しない。
- **自己完結型 HTML レポート**（v0.1 以降）
- **PDF 対応**（`pypdf` 経由、v0.2 以降）
- **画像 OCR 対応**（`Pillow` + `pytesseract` 経由、v0.3 以降）
- **インタラクティブ HTML ダッシュボード**（v0.5 以降）  
  ディレクトリ単位で一括観測し、サマリーカード・マスク分布・仮説発動チャート・
  ソート可能なファイル一覧を含む単一の自己完結型 HTML を生成します。
  `Jinja2` + `Plotly` が必要です。

---

## 📦 インストール

```bash
# Core（ゼロ依存）
pip install git+https://github.com/neguseatama/sieve-lens.git

# PDF 対応込み
pip install "git+https://github.com/neguseatama/sieve-lens.git#egg=sieve-lens[pdf]"

---

## 💻 クイックスタート

```python
from sieve_lens import SieveLensEngine, format_report, format_report_html

engine = SieveLensEngine()
obs = engine.observe("resume.docx")

print(obs.mask)                    # 例: "1000-100"
print(obs.h_states)                # {'H1': 1, 'H2': 0, ..., 'H7': 0}
print(format_report(obs))          # 人間可読なテキストレポート

html = format_report_html(obs)     # 自己完結型 HTML レポート
```

HTML レポートをファイルに保存する場合：

```python
from sieve_lens import write_report_html
write_report_html(obs, "report.html")
```

### PDF（`pdf` オプションが必要）

```python
from sieve_lens import SieveLensEngine
from sieve_lens_ext.pdf import install

engine = SieveLensEngine()
install(engine)                    # .pdf 対応を有効化
obs = engine.observe("resume.pdf")
print(obs.mask)

---

## 🔬 テスト

# v0 テストスイート（26件）
python -m unittest discover -s tests -p "test_sieve_lens.py" -v

# v0.1 テストスイート（14件）
python -m unittest discover -s tests -p "test_sieve_lens_v0_1.py" -v

# v0.2 PDF 拡張（7件、pypdf 必要）
python -m unittest discover -s tests -p "test_sieve_lens_pdf.py" -v

---

## ⚠️ 既知の限界（v0.1）

1. **PDF・画像は非対応**（意図的なスコープ判断）
2. **意味的意図は評価しない**（可視だが細工された文は対象外）
3. **インライン CSS のみ検査**（外部スタイルシート未解決）
4. **符号表は固定**（新しい不可視手法には表の拡張が必要）
5. **これは観測エンジンであり、検出器ではない**（人間による確認が前提）

---

## 📄 ライセンス

MIT License。詳細は [LICENSE](LICENSE) を参照してください。

---

## 👤 Author

* **Kai IWASAKI**