from pathlib import Path

from dialogue.performance import (
    PERFORMANCE_EMOTIONS,
    SURPRISE_DECAY_MS,
    VAD_TABLE,
    build_jev_state,
    from_jev_choice,
    from_speaking_style,
    normalize_performance,
)


def test_speaking_style_fallback_covers_closed_set_and_illegal_values():
    for emotion in PERFORMANCE_EMOTIONS:
        decision = from_speaking_style(emotion)
        assert decision.emotion == emotion
        assert decision.source == "speaking_style"
        assert decision.confidence == 0.0
        assert decision.decay_ms == (SURPRISE_DECAY_MS if emotion == "惊讶" else 0)
        assert emotion in VAD_TABLE

    fallen = from_speaking_style("低落")
    assert fallen.emotion == "日常"
    assert normalize_performance("哭脸") == "日常"


def test_jev_choice_respects_confidence_and_intensity():
    weak = from_jev_choice("温柔", "strong", 0.2, min_confidence=0.4)
    assert weak is None

    picked = from_jev_choice("惊讶", "mild", 0.8, min_confidence=0.4)
    assert picked is not None
    assert picked.emotion == "惊讶"
    assert picked.intensity == 0.6
    assert picked.source == "jev"
    assert picked.decay_ms == SURPRISE_DECAY_MS
    english = from_jev_choice("surprised", "mild", 0.8, min_confidence=0.4)
    assert english is not None
    assert english.emotion == "惊讶"
    assert english.decay_ms == SURPRISE_DECAY_MS
    gentle = from_jev_choice("gentle", "moderate", 0.7, min_confidence=0.4)
    assert gentle is not None
    assert gentle.emotion == "温柔"
    assert gentle.decay_ms == 0
    assert from_jev_choice("生气", "moderate", 0.9, min_confidence=0.4) is None
    assert from_jev_choice("angry", "moderate", 0.9, min_confidence=0.4) is None


def test_jev_state_excerpt_keeps_latest_user_line_and_drops_long_text():
    messages = [
        {"role": "user", "content": "早"},
        {"role": "assistant", "content": "早好音"},
        {"role": "user", "content": "谁说你小"},
    ]
    state = build_jev_state(messages, "谁说我小！" + "啊" * 400)

    assert "User: 谁说你小" in state
    assert 'weigh this most heavily): "谁说你小"' in state
    assert "说话语气" not in state
    assert len(state) < 2000


def test_frontend_blender_uses_the_same_vad_table():
    blend = Path("frontend/src/live2d/blend.ts").read_text(encoding="utf-8")
    for emotion, (valence, arousal, dominance) in VAD_TABLE.items():
        assert emotion in blend
        assert str(valence) in blend
        assert str(arousal) in blend
        assert str(dominance) in blend
