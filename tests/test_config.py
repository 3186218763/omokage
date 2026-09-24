from config import load_config

import pytest


def _base_yaml() -> str:
    return """
llm:
  api_key: key
  base_url: https://example.test
  model: model
tts:
  base_url: http://localhost:5000
"""


def test_load_config_uses_asr_defaults(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(_base_yaml(), encoding="utf-8")

    config = load_config(str(path))

    assert config.asr.model == "small"
    assert config.asr.device == "auto"
    assert config.asr.language == "auto"
    assert config.asr.max_upload_mb == 15
    assert config.llm.temperature == 0.8
    assert config.recent_turns == 8
    assert config.summary_trigger_turns == 12
    assert config.min_sentence_chars == 4
    assert config.max_sentence_chars == 50
    assert config.tts_prefetch_depth == 2
    assert config.timing_event is True
    assert config.tts.base_url == "http://localhost:5000"
    assert config.tts.model_name == "huayin"
    assert config.tts.speaker_name == "花音"
    assert config.tts.style == "Neutral"
    assert config.tts.timeout == 60.0
    assert config.jev.enabled is False
    assert config.jev.model == "jev-latest"
    assert config.live2d.model_dir == ""
    assert config.live2d.background == ""


def test_load_config_reads_prefetch_depth_and_timing_event(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        _base_yaml()
        + """
conversation:
  timing_event: false
streaming:
  tts_prefetch_depth: 3
""",
        encoding="utf-8",
    )

    config = load_config(str(path))

    assert config.tts_prefetch_depth == 3
    assert config.timing_event is False


def test_load_config_rejects_out_of_range_prefetch_depth(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        _base_yaml() + "\nstreaming:\n  tts_prefetch_depth: 4\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="tts_prefetch_depth"):
        load_config(str(path))


def test_load_config_rejects_invalid_audio_encoding(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(_base_yaml() + "\nstreaming:\n  audio_encoding: ogg\n", encoding="utf-8")
    with pytest.raises(ValueError, match="audio_encoding"):
        load_config(str(path))


def test_load_config_reads_asr_settings(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        _base_yaml()
        + """
asr:
  model: medium
  device: cuda
  compute_type: float16
  language: zh
  beam_size: 3
  max_upload_mb: 8
""",
        encoding="utf-8",
    )

    config = load_config(str(path))

    assert config.asr.model == "medium"
    assert config.asr.device == "cuda"
    assert config.asr.compute_type == "float16"
    assert config.asr.language == "zh"
    assert config.asr.beam_size == 3
    assert config.asr.max_upload_mb == 8


def test_load_config_reads_long_conversation_and_llm_settings(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        _base_yaml()
        + """
conversation:
  recent_turns: 6
  summary_trigger_turns: 10
  summary_trigger_chars: 9000
  summary_max_chars: 1200
streaming:
  min_sentence_chars: 3
  max_sentence_chars: 60
""",
        encoding="utf-8",
    )

    config = load_config(str(path))

    assert config.recent_turns == 6
    assert config.summary_trigger_turns == 10
    assert config.summary_trigger_chars == 9000
    assert config.summary_max_chars == 1200
    assert config.min_sentence_chars == 3
    assert config.max_sentence_chars == 60


def test_load_config_supports_legacy_max_turns(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        _base_yaml() + "\nconversation:\n  max_turns: 7\n",
        encoding="utf-8",
    )

    assert load_config(str(path)).recent_turns == 7


def test_load_config_ignores_legacy_protocol_and_frequency_penalty(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        """
llm:
  api_key: key
  base_url: https://example.test
  model: model
  protocol: anthropic
  frequency_penalty: 0.15
tts:
  base_url: http://localhost:5000
  ref_audio_path: /ref.wav
  ref_text: ref
  ref_language: zh
""",
        encoding="utf-8",
    )

    config = load_config(str(path))
    assert not hasattr(config.llm, "protocol")
    assert not hasattr(config.llm, "frequency_penalty")
    assert config.llm.model == "model"
    assert config.llm.temperature == 0.8
    assert not hasattr(config.tts, "ref_audio_path")
    assert config.tts.base_url == "http://localhost:5000"


def test_load_config_reads_sbv2_tts_settings(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        _base_yaml()
        + """
tts:
  base_url: http://127.0.0.1:5000
  model_name: huayin
  speaker_name: 花音
  style: Neutral
  length: 1.05
  timeout: 30
""",
        encoding="utf-8",
    )

    config = load_config(str(path))
    assert config.tts.model_name == "huayin"
    assert config.tts.speaker_name == "花音"
    assert config.tts.length == 1.05
    assert config.tts.timeout == 30
