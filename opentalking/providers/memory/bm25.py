from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence

from opentalking.providers.memory.schemas import MemoryItem

_CATEGORY_PROMPT_GROUPS = (
    ("user_preference", "Preferences"),
    ("entity_relation", "Important people/entities"),
    ("goal_progress", "Goals and progress"),
    ("decision_plan", "Decisions and plans"),
    ("feedback_correction", "Interaction feedback"),
    ("episode_summary", "Conversation summaries"),
)
_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_SERVER_ALIAS_RE = re.compile(r"(?<![A-Za-z0-9_])(\d{2,4})\s*(服务器)")
_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/][^\s]+|/[A-Za-z0-9._~+/@:-]+)")
_NAME_QUERY_RE = re.compile(r"(我\s*(叫|是)\s*(什么|啥|谁)|我的\s*(名字|称呼))")
_NAME_MEMORY_RE = re.compile(r"(我\s*叫\s*(?!什么|啥|谁)|我的\s*(名字|称呼)\s*是|以后\s*叫我|请\s*叫我)")


def extract_exact_entities(text: str) -> set[str]:
    lowered = (text or "").lower()
    entities: set[str] = set(_IP_RE.findall(lowered))
    entities.update(path.rstrip(".,;:!?，。；：！？") for path in _PATH_RE.findall(lowered))
    for number, label in _SERVER_ALIAS_RE.findall(lowered):
        entities.add(number)
        entities.add(f"{number}{label}")
    return {entity for entity in entities if entity}


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    lowered = (text or "").lower()
    for ip in _IP_RE.findall(lowered):
        tokens.append(ip)
        tokens.extend(part for part in ip.split(".") if part)
    for number, label in _SERVER_ALIAS_RE.findall(lowered):
        tokens.extend([number, label, f"{number}{label}"])
    for path in _PATH_RE.findall(lowered):
        tokens.append(path.rstrip(".,;:!?，。；：！？"))
    for match in _TOKEN_RE.finditer((text or "").lower()):
        value = match.group(0)
        if not value:
            continue
        server_match = _SERVER_ALIAS_RE.fullmatch(value)
        if server_match:
            number, label = server_match.groups()
            tokens.extend([number, label, value])
        if re.fullmatch(r"[\u4e00-\u9fff]+", value):
            tokens.extend(value[i : i + 2] for i in range(max(1, len(value) - 1)))
        elif re.fullmatch(r"\d+[\u4e00-\u9fff]+", value):
            match_num = re.match(r"(\d+)([\u4e00-\u9fff]+)", value)
            if match_num:
                number, chinese = match_num.groups()
                tokens.append(number)
                tokens.extend(chinese[i : i + 2] for i in range(max(1, len(chinese) - 1)))
            tokens.append(value)
        else:
            tokens.append(value)
    return [t for t in tokens if t.strip()]


def rank_items_bm25(
    query: str,
    items: Sequence[MemoryItem],
    *,
    limit: int = 5,
    min_score: float = 0.0,
) -> list[MemoryItem]:
    query_terms = tokenize(query)
    if not query_terms or not items or limit <= 0:
        return []
    query_entities = extract_exact_entities(query)
    name_query = bool(_NAME_QUERY_RE.search(query or ""))

    doc_tokens = [tokenize(item.text) for item in items]
    doc_freq: Counter[str] = Counter()
    for tokens in doc_tokens:
        doc_freq.update(set(tokens))

    avgdl = sum(len(tokens) for tokens in doc_tokens) / max(1, len(doc_tokens))
    q_counts = Counter(query_terms)
    scored: list[tuple[float, int, MemoryItem]] = []
    for idx, (item, tokens) in enumerate(zip(items, doc_tokens)):
        if not tokens:
            continue
        item_entities = extract_exact_entities(item.text)
        if query_entities and query_entities.isdisjoint(item_entities):
            continue
        term_freq = Counter(tokens)
        score = 0.0
        for term, qf in q_counts.items():
            tf = term_freq.get(term, 0)
            if tf <= 0:
                continue
            df = doc_freq.get(term, 0)
            idf = math.log(1 + (len(items) - df + 0.5) / (df + 0.5))
            denom = tf + 1.5 * (1 - 0.75 + 0.75 * len(tokens) / max(avgdl, 1e-6))
            score += idf * ((tf * 2.5) / denom) * max(1, qf)
        if query_entities:
            score += 10.0 * len(query_entities & item_entities)
        if name_query and _NAME_MEMORY_RE.search(item.text):
            score += 5.0
        if score > min_score:
            scored.append((score, idx, item))

    scored.sort(key=lambda row: (-row[0], row[1]))
    return [item for _, _, item in scored[:limit]]


def memories_to_prompt(items: Iterable[MemoryItem]) -> str:
    materialized = [item for item in items if item.text.strip()]
    if any((item.metadata or {}).get("category") for item in materialized):
        grouped: dict[str, list[str]] = {category: [] for category, _label in _CATEGORY_PROMPT_GROUPS}
        other: list[str] = []
        for item in materialized:
            line = item.text.strip()
            category = str((item.metadata or {}).get("category") or "").strip()
            if not category and item.type == "preference":
                category = "user_preference"
            if category in grouped:
                grouped[category].append(line)
            else:
                other.append(line)
        sections: list[str] = []
        for category, label in _CATEGORY_PROMPT_GROUPS:
            lines = grouped[category]
            if lines:
                sections.append(f"{label}:\n" + "\n".join(f"- {line}" for line in lines))
        if other:
            sections.append("Other memories:\n" + "\n".join(f"- {line}" for line in other))
        if not sections:
            return ""
        return "Relevant user memories:\n\n" + "\n\n".join(sections)

    lines = [item.text.strip() for item in materialized]
    if not lines:
        return ""
    body = "\n".join(f"- {line}" for line in lines)
    return f"Relevant long-term memories:\n{body}"
