import re
# from loguru import logger
from typing import Dict, List, Tuple

from components.stand_alone_functions.page_find_logic.mineru_types import (
    get_latex_delimiter_config,
    ListLineTag,
    BlockType,
    ContentType,
    MakeMode,
    detect_lang,
)
import tiktoken


_TOKEN_ENCODER = None


def _get_token_encoder():
    global _TOKEN_ENCODER
    if _TOKEN_ENCODER is not None:
        return _TOKEN_ENCODER

    try:
        _TOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")
    except Exception:
        _TOKEN_ENCODER = None

    return _TOKEN_ENCODER


def __is_hyphen_at_line_end(line):
    """Check if a line ends with one or more letters followed by a hyphen.

    Args:
    line (str): The line of text to check.

    Returns:
    bool: True if the line ends with one or more letters followed by a hyphen, False otherwise.
    """
    # Use regex to check if the line ends with one or more letters followed by a hyphen
    return bool(re.search(r'[A-Za-z]+-\s*$', line))


def make_blocks_to_markdown(paras_of_layout,
                                      mode,
                                      img_buket_path='',
                                      ):
    page_markdown = []
    for para_block in paras_of_layout:
        para_text = ''
        para_type = para_block['type']
        if para_type in [BlockType.TEXT, BlockType.LIST, BlockType.INDEX]:
            para_text = merge_para_with_text(para_block)
        elif para_type == BlockType.TITLE:
            title_level = get_title_level(para_block)
            para_text = f'{"#" * title_level} {merge_para_with_text(para_block)}'
        elif para_type == BlockType.INTERLINE_EQUATION:
            if len(para_block['lines']) == 0 or len(para_block['lines'][0]['spans']) == 0:
                continue
            if para_block['lines'][0]['spans'][0].get('content', ''):
                para_text = merge_para_with_text(para_block)
            else:
                para_text += f"![]({img_buket_path}/{para_block['lines'][0]['spans'][0]['image_path']})"
        elif para_type == BlockType.IMAGE:
            if mode == MakeMode.NLP_MD:
                continue
            elif mode == MakeMode.MM_MD:
                # 检测是否存在图片脚注
                has_image_footnote = any(block['type'] == BlockType.IMAGE_FOOTNOTE for block in para_block['blocks'])
                # 如果存在图片脚注，则将图片脚注拼接到图片正文后面
                if has_image_footnote:
                    for block in para_block['blocks']:  # 1st.拼image_caption
                        if block['type'] == BlockType.IMAGE_CAPTION:
                            para_text += merge_para_with_text(block) + '  \n'
                    for block in para_block['blocks']:  # 2nd.拼image_body
                        if block['type'] == BlockType.IMAGE_BODY:
                            for line in block['lines']:
                                for span in line['spans']:
                                    if span['type'] == ContentType.IMAGE:
                                        if span.get('image_path', ''):
                                            para_text += f"![]({img_buket_path}/{span['image_path']})"
                    for block in para_block['blocks']:  # 3rd.拼image_footnote
                        if block['type'] == BlockType.IMAGE_FOOTNOTE:
                            para_text += '  \n' + merge_para_with_text(block)
                else:
                    for block in para_block['blocks']:  # 1st.拼image_body
                        if block['type'] == BlockType.IMAGE_BODY:
                            for line in block['lines']:
                                for span in line['spans']:
                                    if span['type'] == ContentType.IMAGE:
                                        if span.get('image_path', ''):
                                            para_text += f"![]({img_buket_path}/{span['image_path']})"
                    for block in para_block['blocks']:  # 2nd.拼image_caption
                        if block['type'] == BlockType.IMAGE_CAPTION:
                            para_text += '  \n' + merge_para_with_text(block)
        elif para_type == BlockType.TABLE:
            if mode == MakeMode.NLP_MD:
                continue
            elif mode == MakeMode.MM_MD:
                for block in para_block['blocks']:  # 1st.拼table_caption
                    if block['type'] == BlockType.TABLE_CAPTION:
                        para_text += merge_para_with_text(block) + '  \n'
                for block in para_block['blocks']:  # 2nd.拼table_body
                    if block['type'] == BlockType.TABLE_BODY:
                        for line in block['lines']:
                            for span in line['spans']:
                                if span['type'] == ContentType.TABLE:
                                    # if processed by table model
                                    if span.get('html', ''):
                                        para_text += f"\n{span['html']}\n"
                                    elif span.get('image_path', ''):
                                        para_text += f"![]({img_buket_path}/{span['image_path']})"
                for block in para_block['blocks']:  # 3rd.拼table_footnote
                    if block['type'] == BlockType.TABLE_FOOTNOTE:
                        para_text += '\n' + merge_para_with_text(block) + '  '

        if para_text.strip() == '':
            continue
        else:
            # page_markdown.append(para_text.strip() + '  ')
            page_markdown.append(para_text.strip())

    return page_markdown


def _normalize_text(text: str) -> str:
    """
    Keep text embedding-friendly:
    - normalize CRLF/CR to LF
    - collapse 2+ newlines to a single newline
    - collapse spaces/tabs
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _remove_image_markdown(text: str) -> str:
    return re.sub(r"!\[[^\]]*\]\(([^)]+)\)", "", text)


def _rewrite_image_urls(text: str, base_url: str, doc_id: int) -> str:
    base = (base_url or "").rstrip("/")

    def _replace(match: re.Match) -> str:
        alt_text = match.group("alt") or ""
        raw_url = (match.group("url") or "").strip()
        if not raw_url:
            return match.group(0)
        if raw_url.startswith("http://") or raw_url.startswith("https://") or raw_url.startswith("data:"):
            return match.group(0)
        file_name = raw_url.split("/")[-1]
        return f"![{alt_text}]({base}/{doc_id}/images/{file_name})"

    pattern = re.compile(
        r'!\[(?P<alt>[^\]]*)\]\((?P<url>[^)\s]+)(?:\s+"[^"]*")?\)',
        flags=re.I,
    )
    return pattern.sub(_replace, text)


def token_len(text: str) -> int:
    if not text:
        return 0

    encoder = _get_token_encoder()
    if encoder is None:
        return max(1, len(text) // 4)

    return len(encoder.encode(text))


def _is_low_signal_embedding_text(text: str, min_tokens: int) -> bool:
    cleaned = _normalize_text(text)
    if not cleaned:
        return True
    if token_len(cleaned) < min_tokens:
        return True
    else:
        return False
    # # Reject mostly-markup/noise fragments like "<tr/>"
    # alnum_count = sum(1 for c in cleaned if c.isalnum())
    # return alnum_count < 8


def build_dual_mode_chunks_from_pdf_info(
    pdf_info_dict: list,
    doc_id: int,
    base_url: str,
    img_buket_path: str = "images",
    max_tokens: int = 800,
    overlap_tokens: int = 150,
    min_chunk_tokens: int = 150,
) -> Tuple[List[Dict], int]:
    """
    Build chunk payloads directly from MinerU middle json (`pdf_info`).

    Returns:
      (
        [
          {
            "chunk_text": str,              # MM_MD text (for storage/display)
            "chunk_embedding_text": str,    # NLP_MD text (for embedding)
            "start_page": int,
            "end_page": int,
            "token_count": int
          },
          ...
        ],
        n_pages
      )
    """
    units: List[Dict] = []

    for page_info in pdf_info_dict:
        paras_of_layout = page_info.get("para_blocks") or []
        page_idx = page_info.get("page_idx", 0)
        if not paras_of_layout:
            continue

        for para_block in paras_of_layout:
            mm_parts = make_blocks_to_markdown([para_block], MakeMode.MM_MD, img_buket_path)
            nlp_parts = make_blocks_to_markdown([para_block], MakeMode.NLP_MD, img_buket_path)
            mm_text = mm_parts[0] if mm_parts else ""
            nlp_text = nlp_parts[0] if nlp_parts else ""

            mm_text = _normalize_text(mm_text)
            nlp_text = _normalize_text(_remove_image_markdown(nlp_text))
            if not mm_text and not nlp_text:
                continue

            units.append(
                {
                    "page_idx": page_idx,
                    "chunk_text": mm_text,
                    "chunk_embedding_text": nlp_text,
                    "tokens": token_len(nlp_text),
                }
            )

    chunks: List[Dict] = []
    i = 0
    n_units = len(units)

    while i < n_units:
        j = i
        token_sum = 0
        seen_textful = False

        while j < n_units:
            u_tokens = units[j]["tokens"]
            candidate_sum = token_sum + u_tokens

            if seen_textful and candidate_sum > max_tokens:
                break

            token_sum = candidate_sum
            if u_tokens > 0:
                seen_textful = True
            j += 1

            if token_sum >= max_tokens:
                break

        # Guard for pathological all-zero token unit.
        if j == i:
            j += 1

        selected = units[i:j]
        mm_chunk = _normalize_text("\n".join(u["chunk_text"] for u in selected if u["chunk_text"]))
        nlp_chunk = _normalize_text("\n".join(u["chunk_embedding_text"] for u in selected if u["chunk_embedding_text"]))

        if not _is_low_signal_embedding_text(nlp_chunk, min_chunk_tokens):
            mm_chunk = _rewrite_image_urls(mm_chunk, base_url=base_url, doc_id=doc_id)
            chunk = {
                "chunk_text": mm_chunk,
                "chunk_embedding_text": nlp_chunk,
                "start_page": selected[0]["page_idx"],
                "end_page": selected[-1]["page_idx"],
                "token_count": token_len(nlp_chunk),
            }
            chunks.append(chunk)

        # Build overlap anchor by walking backward.
        back_tokens = 0
        k = j
        while k > i:
            k -= 1
            back_tokens += units[k]["tokens"]
            if back_tokens >= overlap_tokens:
                break

        if k == i:
            i = j
        else:
            i = k

    max_page = max((u["page_idx"] for u in units), default=-1)
    n_pages = max_page + 1 if max_page >= 0 else 0
    return chunks, n_pages


def full_to_half(text: str) -> str:
    """Convert full-width characters to half-width characters using code point manipulation.

    Args:
        text: String containing full-width characters

    Returns:
        String with full-width characters converted to half-width
    """
    result = []
    for char in text:
        code = ord(char)
        # Full-width letters and numbers (FF21-FF3A for A-Z, FF41-FF5A for a-z, FF10-FF19 for 0-9)
        if (0xFF21 <= code <= 0xFF3A) or (0xFF41 <= code <= 0xFF5A) or (0xFF10 <= code <= 0xFF19):
            result.append(chr(code - 0xFEE0))  # Shift to ASCII range
        else:
            result.append(char)
    return ''.join(result)

latex_delimiters_config = get_latex_delimiter_config()

default_delimiters = {
    'display': {'left': '$$', 'right': '$$'},
    'inline': {'left': '$', 'right': '$'}
}

delimiters = latex_delimiters_config if latex_delimiters_config else default_delimiters

display_left_delimiter = delimiters['display']['left']
display_right_delimiter = delimiters['display']['right']
inline_left_delimiter = delimiters['inline']['left']
inline_right_delimiter = delimiters['inline']['right']

def merge_para_with_text(para_block):
    block_text = ''
    for line in para_block['lines']:
        for span in line['spans']:
            if span['type'] in [ContentType.TEXT]:
                span['content'] = full_to_half(span['content'])
                block_text += span['content']
    block_lang = detect_lang(block_text)

    para_text = ''
    for i, line in enumerate(para_block['lines']):

        if i >= 1 and line.get(ListLineTag.IS_LIST_START_LINE, False):
            para_text += '  \n'

        for j, span in enumerate(line['spans']):

            span_type = span['type']
            content = ''
            if span_type == ContentType.TEXT:
                content = escape_special_markdown_char(span['content'])
            elif span_type == ContentType.INLINE_EQUATION:
                if span.get('content', ''):
                    content = f"{inline_left_delimiter}{span['content']}{inline_right_delimiter}"
            elif span_type == ContentType.INTERLINE_EQUATION:
                if span.get('content', ''):
                    content = f"\n{display_left_delimiter}\n{span['content']}\n{display_right_delimiter}\n"

            content = content.strip()

            if content:
                langs = ['zh', 'ja', 'ko']
                # logger.info(f'block_lang: {block_lang}, content: {content}')
                if block_lang in langs: # 中文/日语/韩文语境下，换行不需要空格分隔,但是如果是行内公式结尾，还是要加空格
                    if j == len(line['spans']) - 1 and span_type not in [ContentType.INLINE_EQUATION]:
                        para_text += content
                    else:
                        para_text += f'{content} '
                else:
                    if span_type in [ContentType.TEXT, ContentType.INLINE_EQUATION]:
                        # 如果span是line的最后一个且末尾带有-连字符，那么末尾不应该加空格,同时应该把-删除
                        if j == len(line['spans'])-1 and span_type == ContentType.TEXT and __is_hyphen_at_line_end(content):
                            para_text += content[:-1]
                        else:  # 西方文本语境下 content间需要空格分隔
                            para_text += f'{content} '
                    elif span_type == ContentType.INTERLINE_EQUATION:
                        para_text += content
            else:
                continue

    return para_text


def union_make(pdf_info_dict: list,
               make_mode: str,
               img_buket_path: str = '',
               ):
    output_content = []
    pages_list = []
    joined = ""
    for page_info in pdf_info_dict:
        paras_of_layout = page_info.get('para_blocks')
        paras_of_discarded = page_info.get('discarded_blocks')
        page_idx = page_info.get('page_idx')
        page_size = page_info.get('page_size')
        if make_mode in [MakeMode.MM_MD, MakeMode.NLP_MD]:
            if not paras_of_layout:
                continue
            page_markdown = make_blocks_to_markdown(paras_of_layout, make_mode, img_buket_path)
            page_markdown = [_normalize_text(p) for p in page_markdown if _normalize_text(p)]

                        # page start is current length of joined
            start = len(joined)
            # print(f"page {page_idx} start {start}")

            # add this page
            output_content.extend(page_markdown)
            joined = '\n'.join(output_content)

            end = len(joined)
            pages_list.append({
                "page_idx": page_idx,
                "start": start,
                "end": end,
            })
            # print(f"page {page_idx} end {end}")

    return joined , pages_list



def get_title_level(block):
    title_level = block.get('level', 1)
    if title_level > 4:
        title_level = 4
    elif title_level < 1:
        title_level = 0
    return title_level


def escape_special_markdown_char(content):
    """
    转义正文里对markdown语法有特殊意义的字符
    """
    special_chars = ["*", "`", "~", "$"]
    for char in special_chars:
        content = content.replace(char, "\\" + char)

    return content
