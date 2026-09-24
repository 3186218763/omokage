"""真白花音人设 system prompt，从角色卡加载。"""

from pathlib import Path

from .character_card import load_character_card

_CARD_PATH = Path(__file__).resolve().parent.parent / "configs/huayin_card.yaml"


def get_system_prompt() -> str:
    """返回花音的 LLM 系统提示词。"""
    return load_character_card(_CARD_PATH).prompt
