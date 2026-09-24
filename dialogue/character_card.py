"""Validated local character card references for the dialogue runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .motion import MOTION_WORD_SET
from .speaking_style import SPEAKING_STYLES


@dataclass(frozen=True)
class CharacterCard:
    name: str
    prompt: str
    voice_recipe: Path
    facts_file: Path
    fewshot_file: Path
    speaking_styles: tuple[str, ...]
    motion_vocab: tuple[str, ...]
    language: str


def load_character_card(path: str | Path) -> CharacterCard:
    source = Path(path).resolve()
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("character card must be a mapping")

    def asset(key: str) -> Path:
        raw = data.get(key)
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"character card requires {key}")
        resolved = (source.parent / raw).resolve()
        if not resolved.is_file():
            raise ValueError(f"character card asset missing: {key}")
        return resolved

    name = data.get("name")
    styles = data.get("speaking_styles")
    motions = data.get("motion_vocab")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("character card requires name")
    if not isinstance(styles, list) or set(styles) != set(SPEAKING_STYLES):
        raise ValueError("character card speaking_styles mismatch")
    if not isinstance(motions, list) or not set(motions).issubset(MOTION_WORD_SET):
        raise ValueError("character card motion_vocab mismatch")
    prompt = asset("prompt_file").read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError("character card prompt is empty")
    return CharacterCard(
        name=name.strip(), prompt=prompt, voice_recipe=asset("voice_recipe"),
        facts_file=asset("facts_file"), fewshot_file=asset("fewshot_file"),
        speaking_styles=tuple(styles), motion_vocab=tuple(motions),
        language=str(data.get("language") or "zh"),
    )
