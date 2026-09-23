"""
Sieve Lens internationalization (i18n) for reports.

Provides translation dictionaries for the dashboard and PDF report
templates, and a lightweight language detector based on character
script analysis.

Supported languages:
  - "en" : English
  - "ja" : Japanese

The detector is intentionally simple (character-based). It is not a
general-purpose language identifier.

Usage:
    from sieve_lens_ext.i18n import get_translations, detect_language

    t = get_translations("ja")
    print(t["dashboard_title"])
"""

from __future__ import annotations

from typing import Iterable, List


__version__ = "0.9.0"


TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        # Dashboard
        "dashboard_title": "Sieve Lens Dashboard",
        "dashboard_source": "Source",
        "dashboard_scanned": "file(s) scanned",
        "summary_total": "Total Files",
        "summary_clean": "Clean",
        "summary_flagged": "Flagged",
        "summary_unparsed": "Unparsed",
        "chart_mask_title": "Mask Distribution",
        "chart_hypothesis_title": "Hypothesis Activation",
        "chart_extension_title": "File Types",
        "chart_x_mask": "Mask (H1H2H3H4-H5H6H7)",
        "chart_y_count": "Number of Files",
        "chart_x_hypothesis": "Hypothesis",
        "chart_y_hypothesis": "Files with H = 1",
        "table_file": "File",
        "table_mask": "Mask",
        "table_evidence": "Evidence",
        "footer_statement_dashboard":
            "This is an observation dashboard, not a judgment of intent.",
        "footer_human_review":
            "Human review is required to determine whether the detected "
            "invisible content is legitimate or abusive.",
        "footer_deterministic":
            "Generated deterministically by Sieve Lens. "
            "No timestamps or randomness are included.",

        # PDF report
        "report_title": "Sieve Lens Observation Report",
        "report_source": "Source",
        "report_files_scanned": "Files scanned",
        "report_parsed": "Parsed",
        "report_clean": "Clean",
        "report_flagged": "Flagged",
        "report_unparsed": "Unparsed",
        "section_summary": "Summary",
        "section_charts": "Charts",
        "section_hypothesis": "Hypothesis Activation",
        "section_mask": "Mask Distribution",
        "section_files": "Files",
        "table_bit": "Bit",
        "table_name": "Name",
        "table_h_count": "Files with H = 1",
        "table_mask_long": "Mask (H1H2H3H4-H5H6H7)",
        "table_evidence_first": "Evidence (first)",
        "footer_statement_report":
            "This is an observation report, not a judgment of intent.",
        "footer_deterministic_report":
            "Generated deterministically by Sieve Lens v{version}. "
            "No timestamps, randomness, or external resources are included.",
        "footer_engine_note":
            "This is an observation engine, not a judgment engine.",

        # Hypothesis labels
        "hyp_H1": "Parseability",
        "hyp_H2": "Zero-Width Density",
        "hyp_H3": "Bidi Controls",
        "hyp_H4": "Format Concealment",
        "hyp_H5": "Out-of-Band Channel",
        "hyp_H6": "Script Mixing",
        "hyp_H7": "Contiguous Payload",
    },

    "ja": {
        # Dashboard
        "dashboard_title": "Sieve Lens ダッシュボード",
        "dashboard_source": "ソース",
        "dashboard_scanned": "ファイルを走査",
        "summary_total": "総ファイル数",
        "summary_clean": "クリーン",
        "summary_flagged": "要注意",
        "summary_unparsed": "解析不可",
        "chart_mask_title": "マスク分布",
        "chart_hypothesis_title": "仮説発動",
        "chart_extension_title": "ファイル種別",
        "chart_x_mask": "マスク（H1H2H3H4-H5H6H7）",
        "chart_y_count": "ファイル数",
        "chart_x_hypothesis": "仮説",
        "chart_y_hypothesis": "H = 1 のファイル数",
        "table_file": "ファイル",
        "table_mask": "マスク",
        "table_evidence": "根拠",
        "footer_statement_dashboard":
            "これは観測ダッシュボードであり、意図の判定ではありません。",
        "footer_human_review":
            "検出された不可視コンテンツが正当か悪用かを判断するには、"
            "人間による確認が必要です。",
        "footer_deterministic":
            "Sieve Lens によって決定論的に生成されました。"
            "タイムスタンプや乱数は含まれていません。",

        # PDF report
        "report_title": "Sieve Lens 観測レポート",
        "report_source": "ソース",
        "report_files_scanned": "走査ファイル数",
        "report_parsed": "解析成功",
        "report_clean": "クリーン",
        "report_flagged": "要注意",
        "report_unparsed": "解析不可",
        "section_summary": "サマリー",
        "section_charts": "チャート",
        "section_hypothesis": "仮説発動",
        "section_mask": "マスク分布",
        "section_files": "ファイル一覧",
        "table_bit": "ビット",
        "table_name": "名称",
        "table_h_count": "H = 1 のファイル数",
        "table_mask_long": "マスク（H1H2H3H4-H5H6H7）",
        "table_evidence_first": "根拠（先頭）",
        "footer_statement_report":
            "これは観測レポートであり、意図の判定ではありません。",
        "footer_deterministic_report":
            "Sieve Lens v{version} によって決定論的に生成されました。"
            "タイムスタンプ・乱数・外部リソースは含まれていません。",
        "footer_engine_note":
            "これは観測エンジンであり、判定エンジンではありません。",

        # Hypothesis labels
        "hyp_H1": "解析可能性",
        "hyp_H2": "ゼロ幅密度",
        "hyp_H3": "双方向制御文字",
        "hyp_H4": "フォーマット隠蔽",
        "hyp_H5": "帯域外チャネル",
        "hyp_H6": "文字体系混在",
        "hyp_H7": "連続ペイロード",
    },
}


SUPPORTED_LANGUAGES: List[str] = sorted(TRANSLATIONS.keys())
DEFAULT_LANGUAGE = "en"


def get_translations(lang: str = DEFAULT_LANGUAGE) -> dict:
    """Return the translation dictionary for the given language.

    Falls back to English for unknown languages.
    """
    return TRANSLATIONS.get(lang, TRANSLATIONS[DEFAULT_LANGUAGE])


def hypothesis_label(lang: str, bit: str) -> str:
    """Return the translated label for a hypothesis bit (e.g. "H4")."""
    key = f"hyp_{bit}"
    return get_translations(lang).get(key, bit)


def supported_languages() -> List[str]:
    """Return the sorted list of supported language codes."""
    return list(SUPPORTED_LANGUAGES)


def _is_japanese_char(ch: str) -> bool:
    cp = ord(ch)
    # Hiragana, Katakana, CJK Unified Ideographs (common ranges)
    return (
        0x3040 <= cp <= 0x309F or    # Hiragana
        0x30A0 <= cp <= 0x30FF or    # Katakana
        0x4E00 <= cp <= 0x9FFF or    # CJK Unified Ideographs
        0x3400 <= cp <= 0x4DBF       # CJK Extension A
    )


def _is_latin_letter(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def detect_language(samples: Iterable[str]) -> str:
    """Detect language from a set of text samples.

    Returns "ja" if Japanese characters dominate over Latin letters,
    otherwise returns "en". The heuristic requires at least 4 Japanese
    characters total to avoid misclassification on short inputs.
    """
    ja_count = 0
    latin_count = 0
    for sample in samples:
        if not isinstance(sample, str):
            continue
        for ch in sample:
            if _is_japanese_char(ch):
                ja_count += 1
            elif _is_latin_letter(ch):
                latin_count += 1

    if ja_count < 4:
        return DEFAULT_LANGUAGE
    if ja_count >= latin_count:
        return "ja"
    # Japanese presence is significant but Latin dominates
    if ja_count * 2 >= latin_count:
        return "ja"
    return DEFAULT_LANGUAGE


def resolve_language(lang: str, samples: Iterable[str]) -> str:
    """Resolve a language setting.

    If lang == "auto", runs detect_language on the samples.
    Otherwise, returns the language if supported, or the default.
    """
    if lang == "auto":
        return detect_language(samples)
    if lang in TRANSLATIONS:
        return lang
    return DEFAULT_LANGUAGE


__all__ = [
    "TRANSLATIONS",
    "SUPPORTED_LANGUAGES",
    "DEFAULT_LANGUAGE",
    "get_translations",
    "hypothesis_label",
    "supported_languages",
    "detect_language",
    "resolve_language",
]