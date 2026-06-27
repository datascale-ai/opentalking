from __future__ import annotations

import re

# Only targets emoji code blocks and emoji glue marks, not CJK characters or
# fullwidth punctuation.
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FAFF"  # extended-A
    "\U00002600-\U000027BF"  # misc symbols and dingbats
    "\U0000FE0F"  # variation selector-16
    "\U0000200D"  # zero width joiner
    "\U000020E3"  # combining enclosing keycap
    "]+",
    flags=re.UNICODE,
)

# Markdown bold/italic markers: **text**, *text*, __text__, _text_
_MD_BOLD_ITALIC_RE = re.compile(r"\*{1,3}|_{1,3}")
# Markdown headers: # ## ### etc at start of line
_MD_HEADER_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
# Markdown list bullets: - or * at start of line (with optional leading spaces)
_MD_LIST_RE = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
# Markdown numbered list: 1. 2. etc
_MD_NUMLIST_RE = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
# Markdown inline code: `text`
_MD_CODE_RE = re.compile(r"`([^`]*)`")
# Markdown links: [text](url)
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_EDGE_BOUNDARY_CLOSERS = "”’」』）》】〕〉）)]}\"'"
_EDGE_BOUNDARY_OPENERS = "“‘「『《【〔〈（([{\"'"
_SPEECH_CONTENT_RE = re.compile(r"[\w\u3400-\u9fff]", flags=re.UNICODE)


def strip_emoji(text: str) -> str:
    """Remove emoji from text shown to users or sent to TTS."""
    return _EMOJI_RE.sub("", text)


def strip_markdown(text: str) -> str:
    """Remove markdown formatting so TTS reads clean prose."""
    text = _MD_LINK_RE.sub(r"\1", text)     # [text](url) → text
    text = _MD_CODE_RE.sub(r"\1", text)      # `code` → code
    text = _MD_BOLD_ITALIC_RE.sub("", text)  # **bold** → bold
    text = _MD_HEADER_RE.sub("", text)       # ## Header → Header
    text = _MD_NUMLIST_RE.sub("", text)      # 1. item → item
    text = _MD_LIST_RE.sub("", text)         # - item → item
    return text


def sanitize_tts_text(text: str) -> str:
    """Normalize streamed LLM text into something Edge TTS handles reliably."""
    text = strip_markdown(strip_emoji(text)).strip()
    if not text:
        return ""

    # Streaming sentence splits can leave orphan closing quotes/brackets at the
    # next sentence boundary, e.g. `”理发师...` or a trailing bare `”`.
    while len(text) > 1 and text[:1] in _EDGE_BOUNDARY_CLOSERS:
        text = text[1:].lstrip()
    while len(text) > 1 and text[-1:] in _EDGE_BOUNDARY_OPENERS:
        text = text[:-1].rstrip()

    if not text or _SPEECH_CONTENT_RE.search(text) is None:
        return ""
    return text
