"""
Local replacements for mineru library imports used in parsing/chunking.

These are inlined from:
  - mineru.utils.enum_class  (BlockType, ContentType, MakeMode)
  - mineru.backend.pipeline.para_split  (ListLineTag)
  - mineru.utils.config_reader  (get_latex_delimiter_config)
  - mineru.utils.language  (detect_lang)

This removes the mineru[core] heavy-ML package as a runtime dependency of the
main backend. The celery worker still installs mineru for the actual PDF
extraction subprocess; only the output-parsing layer lives here.
"""

import unicodedata


# ---------------------------------------------------------------------------
# Enums (originally mineru.utils.enum_class)
# ---------------------------------------------------------------------------

class BlockType:
    IMAGE = 'image'
    TABLE = 'table'
    CHART = 'chart'
    IMAGE_BODY = 'image_body'
    TABLE_BODY = 'table_body'
    CHART_BODY = 'chart_body'
    CAPTION = 'caption'
    IMAGE_CAPTION = 'image_caption'
    TABLE_CAPTION = 'table_caption'
    CHART_CAPTION = 'chart_caption'
    ALGORITHM_CAPTION = 'algorithm_caption'
    FOOTNOTE = 'footnote'
    IMAGE_FOOTNOTE = 'image_footnote'
    TABLE_FOOTNOTE = 'table_footnote'
    CHART_FOOTNOTE = 'chart_footnote'
    TEXT = 'text'
    TITLE = 'title'
    INTERLINE_EQUATION = 'interline_equation'
    EQUATION = 'equation'
    LIST = 'list'
    INDEX = 'index'
    DISCARDED = 'discarded'
    CODE = 'code'
    CODE_BODY = 'code_body'
    CODE_CAPTION = 'code_caption'
    CODE_FOOTNOTE = 'code_footnote'
    ALGORITHM = 'algorithm'
    REF_TEXT = 'ref_text'
    PHONETIC = 'phonetic'
    HEADER = 'header'
    FOOTER = 'footer'
    PAGE_NUMBER = 'page_number'
    ASIDE_TEXT = 'aside_text'
    PAGE_FOOTNOTE = 'page_footnote'
    ABSTRACT = 'abstract'
    DOC_TITLE = 'doc_title'
    PARAGRAPH_TITLE = 'paragraph_title'
    VERTICAL_TEXT = 'vertical_text'
    HEADER_IMAGE = 'header_image'
    FOOTER_IMAGE = 'footer_image'
    FORMULA_NUMBER = 'formula_number'


class ContentType:
    IMAGE = 'image'
    TABLE = 'table'
    CHART = 'chart'
    TEXT = 'text'
    INTERLINE_EQUATION = 'interline_equation'
    INLINE_EQUATION = 'inline_equation'
    EQUATION = 'equation'
    HYPERLINK = 'hyperlink'


class MakeMode:
    MM_MD = 'mm_markdown'
    NLP_MD = 'nlp_markdown'
    CONTENT_LIST = 'content_list'
    CONTENT_LIST_V2 = 'content_list_v2'


# ---------------------------------------------------------------------------
# ListLineTag (originally mineru.backend.pipeline.para_split)
# ---------------------------------------------------------------------------

class ListLineTag:
    IS_LIST_START_LINE = 'is_list_start_line'
    IS_LIST_END_LINE = 'is_list_end_line'


# ---------------------------------------------------------------------------
# get_latex_delimiter_config (originally mineru.utils.config_reader)
#
# In the main backend we don't ship ~/mineru.json, so this always returns
# None — callers already fall back to the standard $$/$$ delimiters.
# ---------------------------------------------------------------------------

def get_latex_delimiter_config():
    """Return None so callers use their built-in default delimiters."""
    return None


# ---------------------------------------------------------------------------
# detect_lang (originally mineru.utils.language via fast_langdetect)
#
# The only thing callers care about is whether the language is CJK
# (zh / ja / ko) so they can skip inter-word spaces.  A Unicode-range check
# is sufficient and avoids pulling in the full ML fasttext model.
# ---------------------------------------------------------------------------

_CJK_RANGES = (
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs (Chinese)
    (0x3040, 0x309F),    # Hiragana (Japanese)
    (0x30A0, 0x30FF),    # Katakana (Japanese)
    (0xAC00, 0xD7AF),    # Hangul Syllables (Korean)
    (0x3400, 0x4DBF),    # CJK Extension A
    (0x20000, 0x2A6DF),  # CJK Extension B
)


def _is_cjk_char(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def detect_lang(text: str) -> str:
    """
    Lightweight CJK language detector.

    Returns 'zh', 'ja', or 'ko' when the dominant script is CJK,
    otherwise returns 'en' (callers only branch on CJK vs. non-CJK).
    """
    if not text:
        return ""

    text = text.replace("\n", "")
    # strip invalid surrogates
    text = ''.join(c for c in text if not (0xD800 <= ord(c) <= 0xDFFF))
    # strip control characters (same as the original fallback)
    text = ''.join(c for c in text if unicodedata.category(c)[0] != 'C')

    if not text:
        return ""

    cjk_count = sum(1 for c in text if _is_cjk_char(ord(c)))
    ratio = cjk_count / len(text)

    if ratio < 0.1:
        return "en"

    # Distinguish zh / ja / ko by dominant script
    hiragana = sum(1 for c in text if 0x3040 <= ord(c) <= 0x309F)
    katakana = sum(1 for c in text if 0x30A0 <= ord(c) <= 0x30FF)
    hangul   = sum(1 for c in text if 0xAC00 <= ord(c) <= 0xD7AF)

    if hangul > hiragana and hangul > katakana:
        return "ko"
    if hiragana + katakana > 0:
        return "ja"
    return "zh"
