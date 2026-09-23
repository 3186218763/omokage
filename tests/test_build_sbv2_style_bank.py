import json

import numpy as np

from scripts.build_sbv2_style_bank import (
    STYLE_ORDER,
    clip_paths,
    load_style_clips,
    stack_style_matrix,
    write_style_bank,
)


def test_stack_style_matrix_keeps_neutral_at_index_zero():
    neutral = np.ones(4, dtype=np.float32)
    styles = {name: np.full(4, index + 2, dtype=np.float32) for index, name in enumerate(STYLE_ORDER)}
    matrix, style2id = stack_style_matrix(neutral, styles)
    assert matrix.shape == (7, 4)
    assert style2id["Neutral"] == 0
    assert style2id["日常"] == 1
    assert style2id["惊讶"] == 6
    assert matrix[0, 0] == 1
    assert matrix[1, 0] == 2


def test_load_style_clips_requires_existing_audio(tmp_path):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    refs = {
        "styles": {
            name: {
                "primary": {"audio": "clip.wav"},
                "alternates": [],
            }
            for name in STYLE_ORDER
        }
    }
    path = tmp_path / "refs.json"
    path.write_text(json.dumps(refs), encoding="utf-8")
    clips = load_style_clips(path, tmp_path)
    assert clips["元气"] == [(tmp_path / "clip.wav").resolve()]
    assert clip_paths({"primary": {"audio": "missing.wav"}}, tmp_path)


def test_write_style_bank_updates_config(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"data": {"num_styles": 1, "style2id": {"Neutral": 0}}}', encoding="utf-8")
    matrix = np.zeros((2, 3), dtype=np.float32)
    vectors = tmp_path / "style_vectors.npy"
    write_style_bank(matrix, {"Neutral": 0, "日常": 1}, config, vectors_path=vectors)
    saved = np.load(vectors)
    assert saved.shape == (2, 3)
    payload = json.loads(config.read_text(encoding="utf-8"))
    assert payload["data"]["num_styles"] == 2
    assert payload["data"]["style2id"]["日常"] == 1
