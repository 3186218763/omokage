"""共享的句级准备管线：标签先行 → 切句 → 停顿/动作提取 → 归一化。

CLI（Orchestrator）与 Web（LiveConversation）都用这一条链把 LLM token 流
变成可朗读、可合成的句子；两端只保留各自的调度差异（预取、打断、打点）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .motion import MotionPolicy
from .pause import PausePolicy
from .sentence_streamer import SentenceStreamer
from .speaking_style import StylePrefixParser
from .speech_text import normalize_speech_text


@dataclass(frozen=True)
class Utterance:
    """一句可朗读台词：正文进显示与 TTS，动作/停顿是句级元数据。"""

    text: str
    motion: str | None = None
    pause_ms: int = 0


class SentencePipeline:
    """喂入 LLM token，按序吐出 Utterance；说话语气标签先行解析。"""

    def __init__(self, max_chars: int = 50, min_chars: int = 4):
        self._parser = StylePrefixParser()
        self._streamer = SentenceStreamer(max_chars, min_chars=min_chars)
        self._motions = MotionPolicy()
        self._pauses = PausePolicy()
        self._speech = ""
        self._spoken = 0

    @property
    def style(self) -> str:
        """本轮说话语气；标签尚未解析完时是默认值。"""
        return self._parser.style

    @property
    def style_resolved(self) -> bool:
        return self._parser.resolved

    @property
    def speech_text(self) -> str:
        """剥掉语气标签后的完整正文（含动作/停顿标签，供历史保存前再清洗）。"""
        return self._speech

    def feed(self, token: str) -> list[Utterance]:
        speech = self._parser.feed(token)
        if not speech:
            return []
        self._speech += speech
        return self._utterances(self._streamer.add_token(speech))

    def close(self) -> list[Utterance]:
        """流结束：冲掉语气标签缓冲与句缓冲的尾巴。"""
        tail = self._parser.flush()
        if tail:
            self._speech += tail
        utterances = self._utterances(self._streamer.add_token(tail))
        remaining = self._streamer.flush()
        if remaining:
            utterances.extend(self._utterances([remaining]))
        return utterances

    def _utterances(self, raw_sentences: list[str]) -> list[Utterance]:
        # 首句不接停顿（开口即回应）；产出顺序即朗读顺序，内部计数与
        # 调用侧的 spoken 列表等价。
        result: list[Utterance] = []
        for raw in raw_sentences:
            pause_ms, without_pause = self._pauses.take(raw, opening=self._spoken == 0)
            motion, stripped = self._motions.take(without_pause)
            text = normalize_speech_text(stripped)
            if text is None:
                continue
            self._spoken += 1
            result.append(Utterance(text=text, motion=motion, pause_ms=pause_ms))
        return result
