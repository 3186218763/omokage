"""Conservative extraction and ranking of user-stated facts."""

from __future__ import annotations

import re
from datetime import datetime, timezone

_CLAIMS = (
    ("name", re.compile(r"(?:我叫|我的名字是)([\u4e00-\u9fffA-Za-z]{1,12})")),
    ("preference", re.compile(r"我(?:很|最|特别)?喜欢([^，。！？!？\n]{1,24})")),
    ("dislike", re.compile(r"我(?:不|很不)喜欢([^，。！？!？\n]{1,24})")),
)


def extract_user_facts(text: str) -> list[tuple[str, str]]:
    """Extract at most two literal first-person claims; never infer context."""
    facts: list[tuple[str, str]] = []
    for kind, pattern in _CLAIMS:
        match = pattern.search(text)
        if match is None:
            continue
        value = match.group(1).strip(" ，。！？!？ ")
        if value:
            facts.append((kind, value))
        if len(facts) == 2:
            break
    return facts


def memory_score(
    *, kind: str, updated_at: str, retrieval_count: int, query: str, value: str
) -> float:
    """Rank literal matches with a half-life; identity lasts longer than events."""
    try:
        age_days = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(updated_at)).total_seconds() / 86400)
    except ValueError:
        age_days = 0.0
    half_life = 365.0 if kind == "name" else 45.0
    relevance = 2.0 if value in query else 1.0
    return relevance * (0.5 ** (age_days / half_life)) * (1 + min(retrieval_count, 20) * 0.05)
