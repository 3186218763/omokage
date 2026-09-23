import pytest

from dialogue.motion import (
    MAX_MOTIONS_PER_TURN,
    MotionPolicy,
    normalize_motion,
    strip_motion_tags,
)
from dialogue.speech_text import strip_style_for_history


@pytest.mark.parametrize(
    ("raw", "motion", "rest"),
    [
        ("【动作:点头】早好音。", "点头", "早好音。"),
        ("[动作：摇头] 才不是呢。", "摇头", "才不是呢。"),
        ("【动作:歪头】诶？怎么了。", "歪头", "诶？怎么了。"),
        ("  【动作:点头】 好呀。", "点头", "好呀。"),
        ("【动作:跳舞】普通一句。", None, "普通一句。"),
        ("【动作:】空标签。", None, "空标签。"),
        ("没有任何标签的句子。", None, "没有任何标签的句子。"),
    ],
)
def test_take_extracts_leading_tag(raw, motion, rest):
    assert MotionPolicy().take(raw) == (motion, rest)


def test_take_strips_every_leading_tag_even_when_all_invalid():
    motion, rest = MotionPolicy().take("[动作:跳舞]【动作:鼓掌】正片。")
    assert motion is None
    assert rest == "正片。"


def test_policy_allows_at_most_two_motions_per_turn():
    policy = MotionPolicy()
    assert policy.take("【动作:点头】一。")[0] == "点头"
    assert policy.take("【动作:摇头】二。")[0] == "摇头"
    assert policy.take("【动作:歪头】三。")[0] is None
    assert policy.accepted == ["点头", "摇头"]


def test_policy_drops_consecutive_repeat_and_keeps_dropping():
    policy = MotionPolicy()
    assert policy.take("【动作:点头】一。")[0] == "点头"
    assert policy.take("【动作:点头】二。")[0] is None
    # 被丢弃的重复也推进「上次用词」：紧跟着再标点头仍算连续重复
    assert policy.take("【动作:点头】三。")[0] is None
    assert policy.take("【动作:摇头】四。")[0] == "摇头"
    assert policy.accepted == ["点头", "摇头"]


def test_limit_and_repeat_share_one_budget_per_turn():
    policy = MotionPolicy()
    assert policy.take("【动作:点头】一。")[0] == "点头"
    assert policy.take("【动作:点头】二。")[0] is None
    assert policy.take("【动作:摇头】三。")[0] == "摇头"
    assert policy.take("【动作:歪头】四。")[0] is None


def test_max_motions_is_two():
    assert MAX_MOTIONS_PER_TURN == 2


def test_strip_motion_tags_removes_anywhere_occurrences():
    assert strip_motion_tags("早【动作:摇头】晚【动作:点头】") == "早晚"
    assert strip_motion_tags("[动作：歪头]开头") == "开头"
    assert strip_motion_tags("没有标签") == "没有标签"
    assert strip_motion_tags("") == ""


def test_history_cleanup_strips_style_and_motion_tags():
    cleaned = strip_style_for_history("【说话语气:元气】【动作:点头】早好音。【动作:摇头】再见。")
    assert "动作" not in cleaned
    assert "说话语气" not in cleaned
    assert cleaned == "早好音。再见。"


def test_normalize_motion_rejects_words_outside_closed_set():
    assert normalize_motion("点头") == "点头"
    assert normalize_motion(" 摇头 ") == "摇头"
    assert normalize_motion("跳舞") is None
    assert normalize_motion("") is None
    assert normalize_motion(None) is None
