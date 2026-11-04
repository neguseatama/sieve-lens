[English](README.md) | **日本語**

# Sieve Lens v0.21.0

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

## 🧩 Sieve シリーズ

Sieve は、決定的・ゼロ依存・完全ローカルという共通の設計原則を共有する
エンジン群です。各エンジンが 1 つのリスクの観測または排除を担い、
相互に接続します:

| パッケージ | 役割 | 接続 |
|---------|------|-------------|
| [sieve-core-engine](https://github.com/neguseatama/sieve-core) | 決定論的な構造集約・確信度評価の基盤エンジン | — |
| [sieve-referee](https://github.com/neguseatama/sieve-referee) | テキストの構造・流用・言い換えを観測するエンジン | — |
| [sieve-scope](https://github.com/neguseatama/sieve-scope) | ソースコードの構造的類似性を観測するエンジン | — |
| [sieve-lens](https://github.com/neguseatama/sieve-lens) | 不可視コンテンツや隠蔽要素を観測するエンジン | → `--from-lens` 経由で redact へ |
| [sieve-redact](https://github.com/neguseatama/sieve-redact) | 指定領域の決定論的マスキングと完全性検証 | ← lens、→ tray |
| [sieve-order](https://github.com/neguseatama/sieve-order) | プロンプトの表層構造を 6-bit 観測空間で観測するエンジン | — |
| [sieve-crowd](https://github.com/neguseatama/sieve-crowd) | テーブルデータ匿名化・プライバシー保護エンジン | — |
| [sieve-tray](https://github.com/neguseatama/sieve-tray) | 各エンジンを統合するローカルフロントエンド | ← 全エンジン |

観測から排除まで 1 パスで: Lens が人間に見えないものを見つけ、
Redact が「他は何も変わっていない」ことを証明するレシートとともに
除去します。

## 📐 7-bit 観測空間

| 仮説 | 名称 | 観測内容 |
|------|------|----------|
| H1 | Parseability | 文書が正常に読み込めるか |
| H2 | Zero-Width Density | ゼロ幅文字の密度が閾値超過 |
| H3 | Bidi Controls | 双方向制御文字の存在 |
| H4 | Format Concealment | CSS による隠蔽（display:none 等）。DOCX 隠蔽（隠し文字書式 / ほぼ見えない色 / 極小フォント / 変更履歴の削除） |
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
| `.docx` | 本文・コメント・core プロパティ・ヘッダー・フッター・脚注・末尾脚注。隠蔽の観測（隠し文字書式・ほぼ見えない色・極小フォント・変更履歴の削除） | なし（Core） |
| `.pdf` | 本文・メタデータ・注釈・不可視テキスト（Tr 3）・Form XObject 内テキスト(Tr 3 / raw ストリーム) | `pypdf`（オプション） |
| `.png` / `.jpg` / `.jpeg` / `.gif` / `.bmp` / `.tif` / `.tiff` / `.webp` | メタデータ（EXIF / PNG tEXt / XMP）＋ OCR テキスト | `Pillow`・`pytesseract` ＋ tesseract バイナリ＋言語パック（オプション） |

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
  OCR 言語は `install(engine, ocr_lang="eng+jpn")` で設定可能（既定は `eng`）
- **インタラクティブ HTML ダッシュボード**（v0.5 以降）  
  ディレクトリ単位で一括観測し、サマリーカード・マスク分布・仮説発動チャート・
  ソート可能なファイル一覧を含む単一の自己完結型 HTML を生成します。
  `Jinja2` + `Plotly` が必要です。
- **印刷可能 PDF レポート**（v0.6 以降）  
  ディレクトリ単位で A4 PDF レポートを生成します。サマリー・仮説テーブル・
  マスク分布・色分けされたファイル一覧を含みます。`weasyprint` が必要です
  （チャートにはオプションで `kaleido`）。
- **画像レイヤー解析**（v0.7 以降）  
  画像内のピクセルレベルの隠蔽を検出します。透過 RGBA レイヤー（非ゼロ RGB）、
  および WCAG コントラスト比 2:1 未満の低コントラストテキストを対象とします。
  `Pillow` が必要です。
- **CSS セレクタ完全解決**（v0.8 以降）  
  `cssselect2` により、子孫・子・兄弟・属性・疑似クラスセレクタを含む
  完全な CSS マッチングを HTML 抽出器に追加します。隠蔽ルールは、
  実際に要素へマッチした場合のみ報告されます。
- **レポート多言語化（i18n）**（v0.9 以降）  
  ダッシュボードと PDF レポートを英語・日本語で出力できます。
  入力文書の内容に基づき、言語を自動検出します。
- **PDF 埋め込み画像解析**（v0.10 以降）  
  PDF ページに埋め込まれた画像を抽出し、各画像に OCR・透過レイヤー検出・
  低コントラスト検出・メタデータ解析を適用します。
  `pypdf` + `Pillow` が必要です。
- **PDF Form XObject テキスト走査**(v0.15 以降)  
  Form XObject のコンテンツストリーム内テキスト(不可視 Tr 3 を含む)を、
  ページ直置きと同じ意味論で走査します。ネスト Form は循環防御つきで
  辿ります(深度 8 上限)。
- **制御構文監査レーン**(v0.17 以降)  
  LLM のプロンプト境界を模倣する表層パターン(チャットテンプレート特殊
  トークン `<|im_start|>` / `[INST]` / `<<SYS>>`、命令無効化フレーズ
  (英語・日本語)、擬似構造タグ)を観測します。文書の宣言済みシステム領域
  (メタデータ)内の出現は計上のみでスルーし、裏付けのない出現はパターン・
  位置・オフセットつきでレシートに起票します。意図は判定せず、表層の
  事実だけを記録します。語彙は外部 JSON で、既定の埋め込み語彙
  (リポジトリに control_vocab_v1.json を同梱)にファイル上書きできます。
- **幾何隠蔽監査レーン**(v0.17 以降・H8 HTML 側 / PDF 副走査は v0.18)  
  パース可能なまま人間にはほぼ見えない幾何学的隠蔽スタイル(極小
  `font-size`、ほぼ 0 の `opacity`、つぶれた `transform: scale(...)`、
  0 の `line-height`)を観測します。インライン style 属性は標準ライブラリ
  のみで走査し、`<style>` ブロックとローカル `<link>` スタイルシートは
  tinycss2 導入時に解析します。PDF 副走査はページ内容ストリームと
  Form XObject を辿り、極小 `Tf` フォントサイズとページ MediaBox 外の
  `Tm` 配置を観測します(Tr 3 は PDF 拡張の H4 担当のまま二重計上し
  ません)。閾値は外部 JSON で、既定の埋め込み閾値
  (リポジトリに geometry_thresholds_v2.json を同梱)にファイル上書き
  できます。レシートは規則・生値・実測値・閾値・位置の事実のみを記録し、
  意図は判定しません。
- **有界な文書読み取り（L1: 安全な読み取り）**（v0.19 以降）
  読む前に検査します。巨大すぎる・暗号化されている・壊れている入力は、解析の前に 13 種類の明確な理由をつけて拒否します。拒否した入力からは理由（符号）以外の何も運びません — 中身も名前も記録しません。

- **DOCX 隠蔽の観測（L2）**（v0.20 以降）
  DOCX の「見えない文字」を見つけます。隠し文字指定・極端に小さいフォント・背景とほぼ同色の文字・削除履歴の残骸を検出し、本文とは別の「隠し区間」として報告します。背景色は Word のハイライトや網かけ、テーマ設定をたどって決めます。エンジンは「原理的に見えない」という事実を報告するだけで、意図は判定しません。スタイル・テーマ・設定の各部品が壊れている文書は、無視せず拒否して知らせます。

## 📦 インストール

```bash
# Core（ゼロ依存）
pip install sieve-lens

# PyPI から（リリース済みバージョン向け）
pip install "sieve-lens[pdf]"
pip install "sieve-lens[ocr]"

# または GitHub から最新を
pip install "sieve-lens[pdf] @ git+https://github.com/neguseatama/sieve-lens.git"
pip install "sieve-lens[ocr] @ git+https://github.com/neguseatama/sieve-lens.git"
```

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
```

### 画像 OCR（`ocr` オプションが必要）

```python
from sieve_lens import SieveLensEngine
from sieve_lens_ext.ocr import install

engine = SieveLensEngine()
install(engine, ocr_lang="eng+jpn")    # tesseract の言語パックを指定（既定は eng）
obs = engine.observe("screenshot.png")
print(obs.mask)
```

---

## 🔬 テスト

```bash
# 全体実行（pytest・未導入のオプション依存は skip）
python -m pytest tests/ -q

# 個別実行（unittest discover）
# v0 テストスイート
python -m unittest discover -s tests -p "test_sieve_lens.py" -v

# v0.1 テストスイート
python -m unittest discover -s tests -p "test_sieve_lens_v0_1.py" -v

# v0.2 PDF 拡張（pypdf 必要）
python -m unittest discover -s tests -p "test_sieve_lens_pdf.py" -v
```

---

## 📋 Sieve Schema Contract v1 (v0.18.0)

語彙・閾値の JSON ファイルは、Sieve シリーズ共通の厳格な契約に従います
（詳細は `docs/SCHEMA_CONTRACT_v1.md`）:

- **厳格** — 重複キー・`NaN`/`Infinity`・1 MiB 超の入力は拒否され、既定の内蔵値に戻ります
- **拒否の原則** — 契約外のキーは無視せず拒否します
- **適合コーパス** — 44 の受理/拒否ケースで契約を検証しています

---

## 🔗 Redact Bridge(v0.12.0)

観測結果を、[Sieve Redact](https://github.com/neguseatama/sieve-redact) が
そのまま読める目録（JSON）として出力します:

    python -m sieve_lens_ext.redact_bridge input.txt catalog.json
    python -m sieve_redact input.txt -o clean.txt --from-lens catalog.json

- 目録には、観測の種類・コードポイント・件数・位置（初出順）が入ります
- 同形文字（キリル/ギリシャ → ラテン、全角数字・英字 → ASCII など 102 語）は
  `twin` フィールド付きで報告され、Redact が置換ルールに変換します。
  不可視文字は削除ルールになります
- Lens と Redact は「何が不可視か」を同じ定義で扱います



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

## ⚠️ 既知の限界

1. **観測のみで、除去はしない。** 隠蔽を見つけて報告するのが本工具の役割で、マスク/除去は Sieve Redact の役割です。
2. **意味的な意図は評価しない。** 可視のまま細工された文は対象外です。
3. **インライン CSS のみ検査。** 外部スタイルシートは読みません。
4. **符号表は固定。** 新しい不可視手法には表の追加が必要です。
5. **観測エンジンであり、検出器ではない。** 最終確認は人間が行います。
6. **同形 twin は非 ASCII → ASCII のみ。** O/0・l/1 のような ASCII 内部の類似や CJK 類似は対象外です。
7. **OCR の言語パックが無いと黙って空結果。** 例外は出ず、OCR テキストが 0 件になります。
8. **PDF Form XObject のネストは 8 段まで。** それより深い所は走査しません。
9. **漢字は日中で共有。** 中国語文書が日本語として判定されることがあります。
10. **PDF レポートのチャート生成には Chrome/Chromium が必要**（kaleido 1.x を使う場合）。
11. **制御構文の一致は表層のみ。** 言い換え・文字間スペース・異体字置換は見つけられません。所見は記録であり、意図の証拠ではありません。
12. **幾何の測定は px と無単位のみ。** em/rem/%/pt は対象外で、`@media` ブロックの内側は辿りません。
13. **PDF 幾何の位置は変換前の値。** 相対移動や変換行列は位置に反映しません。背景と同色の塗りは観測しません。
14. **規格外のキーは拒否。** 語彙・閾値ファイルに契約外の項目があれば、無視せず拒否します。重複キーや不正値は内蔵の初期値に戻ります。
15. **入力検査は主要形式のみ。** PDF・画像は各ライブラリで読むため、拒否の詳細までは分かりません。
16. **幾何の所見は mask に入らない。** 各レーンのレシート（`audit_geometry` など）で確認します。
17. **CSV/Excel は未対応**（候補）。列の役割の仕様を固めてから対応します。
18. **DOCX の隠し文字は簡略した規則で解決。** 複数レベルで食い違う上書きや、表スタイル由来の書式、文字幅・位置の細工は対象外です。Strict OOXML の文書は拒否されます（`unsupported_namespace`）。標準形式で保存し直せば観測できます。

---

## 📄 ライセンス

MIT License。詳細は [LICENSE](LICENSE) を参照してください。

---

## 👤 Author

* **Kai IWASAKI**
