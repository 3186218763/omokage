"""Optional sentence-leading pause tags with a strict per-turn budget."""

from __future__ import annotations

import re

PAUSE_MS = {"短": 300, "中": 700, "长": 1200}
MAX_PAUSES_PER_TURN = 2
_TAG_RE = re.compile(r"[【\[]\s*停顿\s*[:：]\s*([^\]】\n]{0,12})\s*[】\]]")
_LEADING_RE = re.compile(r"^\s*[【\[]\s*(动作|停顿)\s*[:：]\s*([^\]】\n]{0,12})\s*[】\]]")


def strip_pause_tags(text: str) -> str:
    return _TAG_RE.sub("", text)


class PausePolicy:
    def __init__(self) -> None:
        self._used = 0

    def take(self, raw_sentence: str, *, opening: bool = False) -> tuple[int, str]:
        """Return (milliseconds, text); preserve leading motion tags for MotionPolicy.

        A pause is a beat before a later sentence. The first spoken sentence of a
        turn answers immediately, so an opening tag is dropped and does not spend
        the budget.
        """
        remaining = raw_sentence or ""
        motion_tags: list[str] = []
        pause_ms = 0
        while match := _LEADING_RE.match(remaining):
            if match.group(1) == "动作":
                motion_tags.append(match.group(0).strip())
            elif not opening and pause_ms == 0 and self._used < MAX_PAUSES_PER_TURN:
                pause_ms = PAUSE_MS.get(match.group(2).strip(), 0)
                if pause_ms:
                    self._used += 1
            remaining = remaining[match.end():]
        return pause_ms, "".join(motion_tags) + strip_pause_tags(remaining)
