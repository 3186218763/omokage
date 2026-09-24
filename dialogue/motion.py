"""动作闭集与句级标签解析。

标签先行通道：句前 【动作:点头】。解析后不朗读、不进 UI、不进历史。
每个合法标签都按句保留，允许同一轮重复动作；非法词仍丢弃，但标签仍剥净不外漏。
"""

from __future__ import annotations

import re

MOTION_WORDS = ("点头", "摇头", "歪头")
MOTION_WORD_SET = frozenset(MOTION_WORDS)

# 句前标签：【动作:点头】 / [动作：点头]（括号与冒号全半角皆收）
_MOTION_TAG_RE = re.compile(
    r"^[【\[]\s*动作\s*[:：]\s*([^\]】\n]{1,12})\s*[】\]]\s*"
)
# 兜底清洗：任何位置的动作标签都剥掉（防泄漏进 TTS / 历史）
_MOTION_TAG_ANYWHERE_RE = re.compile(
    r"[【\[]\s*动作\s*[:：]\s*[^\]】\n]{0,24}[】\]]"
)


def normalize_motion(value: str | None) -> str | None:
    """闭集外一词不算动作。"""
    if not value:
        return None
    text = str(value).strip()
    return text if text in MOTION_WORD_SET else None


def strip_motion_tags(text: str) -> str:
    if not text:
        return text
    return _MOTION_TAG_ANYWHERE_RE.sub("", text)


class MotionPolicy:
    """按句提取动作标签，不对同一轮的合法动作做次数或相邻去重。"""

    def __init__(self) -> None:
        self._accepted: list[str] = []

    @property
    def accepted(self) -> list[str]:
        return list(self._accepted)

    def take(self, raw_sentence: str) -> tuple[str | None, str]:
        """取句前动作标签。返回 (动作或 None, 剥净后的句子)。"""
        text = raw_sentence or ""
        intended: str | None = None
        while True:
            stripped = text.lstrip()
            match = _MOTION_TAG_RE.match(stripped)
            if not match:
                break
            word = normalize_motion(match.group(1))
            text = stripped[match.end():]
            if intended is None and word is not None:
                intended = word
        clean = strip_motion_tags(text).strip()
        motion: str | None = None
        if intended is not None:
            self._accepted.append(intended)
            motion = intended
        return motion, clean
