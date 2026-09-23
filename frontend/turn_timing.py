"""每轮对话的关键时延观测。

一轮 ``WebChatService.stream()`` 在关键节点打点（perf_counter 相对秒），轮末产出
两种出口：SSE ``timing`` 事件（配置开关，前端忽略）与一条结构化 JSON 日志行
（``omokage.timing`` logger，生产入口落 ``logs/timing.jsonl``）。口径约定见
``docs/improvements/p1-10-turn-latency-observability.md``：

- 首音延迟 = request → first_audio（首条成功合成的音频下发）
- 句间 gap = 相邻两次 audio 下发的间隔（服务端近似，不含播放侧）
- Jev 覆盖 = jev_done 早于轮末的比例（jev_dispatch/jev_done 缺省为 null）
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path


logger = logging.getLogger("omokage.timing")

_KNOWN_MARKS = ("llm_first_token", "first_sentence", "jev_dispatch", "jev_done")


def _ms(seconds: float | None) -> int | None:
    return round(seconds * 1000) if seconds is not None else None


@dataclass
class TurnTiming:
    """一轮 stream 的打点器；mark 只记首次命中（首 token / 首句）。"""

    _started: float = field(default_factory=time.perf_counter, repr=False)
    marks: dict[str, float] = field(default_factory=dict)
    audio_sent: list[float] = field(default_factory=list)
    sentences: int = 0
    interrupted: bool = False

    def mark(self, name: str) -> None:
        self.marks.setdefault(name, time.perf_counter() - self._started)

    def mark_audio(self) -> None:
        self.audio_sent.append(time.perf_counter() - self._started)

    def as_dict(self) -> dict[str, object]:
        gaps = [
            round((self.audio_sent[i] - self.audio_sent[i - 1]) * 1000)
            for i in range(1, len(self.audio_sent))
        ]
        payload: dict[str, object] = {
            "type": "timing",
            "sentences": self.sentences,
            "interrupted": self.interrupted,
            "total_ms": _ms(time.perf_counter() - self._started),
            "audio_sent_ms": [_ms(value) for value in self.audio_sent],
            "audio_gaps_ms": gaps,
        }
        for name in _KNOWN_MARKS:
            payload[f"{name}_ms"] = _ms(self.marks.get(name))
        payload["first_audio_ms"] = _ms(self.audio_sent[0] if self.audio_sent else None)
        return payload

    def log(self) -> None:
        """轮末打一条 JSON 行；无 handler 时是 no-op（测试/自定义部署）。"""
        logger.info(json.dumps(self.as_dict(), ensure_ascii=False))


def install_timing_log_file(logs_dir: Path) -> None:
    """生产入口把 timing 日志落成 JSONL，便于 ``jq`` 查询；目录缺失时静默跳过。"""
    if not logs_dir.is_dir():
        return
    handler = logging.FileHandler(logs_dir / "timing.jsonl", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
