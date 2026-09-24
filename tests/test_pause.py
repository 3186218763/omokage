from dialogue.pause import PausePolicy
from dialogue.speech_text import normalize_speech_text


def test_pause_tags_are_budgeted_and_do_not_enter_speech():
    policy = PausePolicy()
    opening_ms, opening = policy.take("【停顿:长】【动作:点头】先接住你。", opening=True)
    first_ms, first = policy.take("【动作:点头】【停顿:短】你好。")
    second_ms, second = policy.take("【停顿:长】【动作:歪头】真的？")
    third_ms, third = policy.take("【停顿:中】还有。")
    assert opening_ms == 0
    assert (first_ms, second_ms, third_ms) == (300, 1200, 0)
    assert normalize_speech_text(opening) == "先接住你。"
    assert normalize_speech_text(first) == "你好。"
    assert normalize_speech_text(second) == "真的？"
    assert normalize_speech_text(third) == "还有。"
    assert normalize_speech_text("【停顿:短】你来了。") == "你来了。"
