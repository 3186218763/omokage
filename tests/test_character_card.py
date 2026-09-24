from pathlib import Path

import pytest

from dialogue.character_card import load_character_card
from dialogue.persona import get_system_prompt


def test_shipped_card_loads_original_prompt_and_assets():
    path = Path(__file__).resolve().parent.parent / "configs/huayin_card.yaml"
    card = load_character_card(path)
    assert card.name == "真白花音"
    assert card.prompt == get_system_prompt()
    assert "AI 复刻" in card.prompt
    assert card.voice_recipe.is_file()


def test_invalid_card_fails_at_load(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: test\nspeaking_styles: []\nmotion_vocab: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="speaking_styles"):
        load_character_card(path)
