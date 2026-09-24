"""Validate the shipped character card and its referenced assets."""

from pathlib import Path

from dialogue.character_card import load_character_card


if __name__ == "__main__":
    path = Path(__file__).resolve().parent.parent / "configs/huayin_card.yaml"
    card = load_character_card(path)
    print(f"{card.name}: {len(card.prompt)} prompt chars, {len(card.speaking_styles)} styles")
