"""表演情绪：驱动 Live2D 的脸和身体，不选参考音。

闭集与说话语气相同，便于 Jev 缺席时一一回落。
"""

from __future__ import annotations

from dataclasses import dataclass

from .speaking_style import normalize_speaking_style


PERFORMANCE_EMOTIONS = ("日常", "元气", "温柔", "俏皮", "倔强", "惊讶")
PERFORMANCE_EMOTION_SET = frozenset(PERFORMANCE_EMOTIONS)
DEFAULT_PERFORMANCE = "日常"
SURPRISE_DECAY_MS = 1200

# valence, arousal, dominance。强度再抬 arousal。
VAD_TABLE: dict[str, tuple[float, float, float]] = {
    "日常": (0.55, 0.35, 0.50),
    "元气": (0.80, 0.75, 0.60),
    "温柔": (0.70, 0.25, 0.40),
    "俏皮": (0.75, 0.60, 0.55),
    "倔强": (0.45, 0.55, 0.75),
    "惊讶": (0.50, 0.80, 0.45),
}

INTENSITY_BY_CHOICE = {"mild": 0.6, "moderate": 0.9, "strong": 1.0}
DEFAULT_INTENSITY = 0.9

# 决策请求用英文选项。Live2D 与说话语气仍用中文闭集。
EMOTION_CHOICE_TO_LABEL = {
    "casual": "日常",
    "energetic": "元气",
    "gentle": "温柔",
    "playful": "俏皮",
    "defiant": "倔强",
    "surprised": "惊讶",
}
EMOTION_INSTRUCTIONS = (
    "Which performance emotion should Baicai show on her face right now? "
    "Baicai is a memorial AI of Mashiro Hanane. Decide only from the dialogue state. "
    "Heavy or sad topics use gentle, never a crying face. "
    "A firm comeback is defiant, not anger or scolding."
)
EMOTION_CRITERIA = {
    "casual": "Ordinary chat or plain narration. Neither especially upbeat nor soft.",
    "energetic": "Light and lifted, like a stream greeting, with a smile.",
    "gentle": "Soft reassurance, thanks, or being cared for. Heavy topics also use gentle, never a crying face.",
    "playful": "Mildly cheeky, a little smug, cute banter.",
    "defiant": "Pushing back when called small, or a firm retort. Spirited, not rage.",
    "surprised": "A short beat of being startled or curious. Not a joke about a graduation set-piece.",
}
INTENSITY_INSTRUCTIONS = "How visible should this performance emotion be on the face and body?"
INTENSITY_CRITERIA = {
    "mild": "Only a light touch on the face. The body barely moves.",
    "moderate": "The expression is clear and the body follows a little.",
    "strong": "Face and body are both clearly affected, still brief, not stage exaggeration.",
}


@dataclass(frozen=True)
class PerformanceDecision:
    emotion: str
    intensity: float
    confidence: float
    source: str
    decay_ms: int = 0

    def as_event(self) -> dict[str, object]:
        return {
            "type": "performance",
            "emotion": self.emotion,
            "intensity": self.intensity,
            "confidence": self.confidence,
            "source": self.source,
            "decay_ms": self.decay_ms,
        }


def normalize_performance(value: str | None) -> str:
    text = (value or "").strip()
    if text in PERFORMANCE_EMOTION_SET:
        return text
    return DEFAULT_PERFORMANCE


def vad_for(emotion: str) -> tuple[float, float, float]:
    return VAD_TABLE[normalize_performance(emotion)]


def intensity_from_choice(choice: str | None) -> float:
    if not choice:
        return DEFAULT_INTENSITY
    return INTENSITY_BY_CHOICE.get(choice.strip(), DEFAULT_INTENSITY)


def from_speaking_style(style: str | None) -> PerformanceDecision:
    """说话语气回落。非法标签先按说话语气规则落到日常，再当作表演情绪。"""
    emotion = normalize_performance(normalize_speaking_style(style))
    return PerformanceDecision(
        emotion=emotion,
        intensity=DEFAULT_INTENSITY,
        confidence=0.0,
        source="speaking_style",
        decay_ms=SURPRISE_DECAY_MS if emotion == "惊讶" else 0,
    )


def emotion_from_choice(choice: str | None) -> str | None:
    """英文决策选项或中文闭集标签都收成表演情绪。对不上则放弃。"""
    if not isinstance(choice, str):
        return None
    text = choice.strip()
    if text in PERFORMANCE_EMOTION_SET:
        return text
    return EMOTION_CHOICE_TO_LABEL.get(text)


def from_jev_choice(
    emotion: str | None,
    intensity_choice: str | None,
    confidence: float | None,
    *,
    min_confidence: float,
) -> PerformanceDecision | None:
    label = emotion_from_choice(emotion)
    if label is None:
        return None
    score = 0.0 if confidence is None else float(confidence)
    if score < min_confidence:
        return None
    return PerformanceDecision(
        emotion=label,
        intensity=intensity_from_choice(intensity_choice),
        confidence=score,
        source="jev",
        decay_ms=SURPRISE_DECAY_MS if label == "惊讶" else 0,
    )


def build_jev_state(messages: list[dict[str, str]], assistant_text: str) -> str:
    """最近 6 条、每条 200 字。最后强调用户最新一句。不含说话语气标签。"""

    def excerpt(text: str) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) > 200:
            return cleaned[:200] + "…"
        return cleaned

    lines: list[str] = []
    for message in messages[-6:]:
        role = "User" if message.get("role") == "user" else "Character"
        lines.append(f"{role}: {excerpt(str(message.get('content') or ''))}")
    if assistant_text:
        spoken = f"Character: {excerpt(assistant_text)}"
        if not lines or lines[-1] != spoken:
            lines.append(spoken)
    last_user = ""
    for message in reversed(messages):
        if message.get("role") == "user":
            last_user = str(message.get("content") or "")
            break
    lines.append(
        "Most recent message from the User "
        f'(weigh this most heavily): "{excerpt(last_user)}"'
    )
    lines.append("Evaluate the character state as of the final line.")
    return "\n".join(lines)
