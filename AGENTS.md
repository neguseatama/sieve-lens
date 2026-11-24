# AGENTS.md

公開面の文章: README・docs・CHANGELOG・Release 本文・パッケージの説明・コミットメッセージ・コードのコメント・テストの説明文は、利用者と開発者に向けた事実の短い文で書く。作業の経緯・内部の呼び名・日付つきの決定・開発環境の情報・絶対パス・テストの番号（README・docs・CHANGELOG）を書かない。CHANGELOG の版の節は、3〜5 項目の短文にする。`tools/check_public_text.py` が通ること。

## Build and test

- Python >= 3.9; the PDF lane needs pypdf >= 4.0
  (`pip install "sieve-lens[pdf]"`).
- Development install with the test extras:
  `pip install -e ".[all,test]"`.
- Test suite: `python -m pytest tests/ -v`.
- Package build: `python -m build`.
- Public-text watch: `python tools/check_public_text.py`
  (runs in CI; one file: `--text FILE`).
