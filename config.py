from dataclasses import dataclass, field
from pathlib import Path
import yaml


# TTS 预取深度上限：保护单卡 SBV2 的并发合成（frontend.web 与本模块共用）
MAX_TTS_PREFETCH_DEPTH = 3

_LLM_FIELDS = {"api_key", "base_url", "model", "temperature", "max_tokens"}
_ASR_FIELDS = {"model", "device", "compute_type", "language", "beam_size", "max_upload_mb"}
_TTS_FIELDS = {
    "base_url",
    "model_name",
    "speaker_name",
    "style",
    "style_weight",
    "length",
    "sdp_ratio",
    "noise",
    "noisew",
    "timeout",
}


@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    temperature: float = 0.8
    max_tokens: int = 400


@dataclass
class TTSConfig:
    base_url: str
    model_name: str = "huayin"
    speaker_name: str = "花音"
    style: str = "Neutral"
    style_weight: float = 1.0
    length: float = 1.0
    sdp_ratio: float = 0.2
    noise: float = 0.6
    noisew: float = 0.8
    timeout: float = 60.0


@dataclass
class ASRConfig:
    model: str = "small"
    device: str = "auto"
    compute_type: str = "auto"
    language: str = "auto"
    beam_size: int = 5
    max_upload_mb: int = 15


@dataclass
class JevConfig:
    enabled: bool = False
    base_url: str = "https://api.typesafe.ai"
    api_key: str = ""
    model: str = "jev-latest"
    timeout_seconds: float = 2.0
    min_confidence: float = 0.4
    fail_cooldown_seconds: float = 60.0


@dataclass
class Live2DConfig:
    model_dir: str = ""
    background: str = ""


_JEV_FIELDS = {
    "enabled",
    "base_url",
    "api_key",
    "model",
    "timeout_seconds",
    "min_confidence",
    "fail_cooldown_seconds",
}


@dataclass
class AppConfig:
    llm: LLMConfig
    tts: TTSConfig
    recent_turns: int = 8
    summary_trigger_turns: int = 12
    summary_trigger_chars: int = 12_000
    summary_max_chars: int = 1_800
    min_sentence_chars: int = 4
    max_sentence_chars: int = 50
    tts_prefetch_depth: int = 2
    timing_event: bool = True
    database_path: str = "data/sessions.db"
    audio_encoding: str = "wav"
    audio_bitrate_kbps: int = 96
    asr: ASRConfig = field(default_factory=ASRConfig)
    jev: JevConfig = field(default_factory=JevConfig)
    live2d: Live2DConfig = field(default_factory=Live2DConfig)


def load_config(path: str = "configs/config.yaml") -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"配置文件不存在：{path}\n"
            f"请复制 configs/config.example.yaml 为 configs/config.yaml 并填写配置"
        )
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    conversation = data.get("conversation") or {}
    streaming = data.get("streaming") or {}
    jev_raw = data.get("jev") or {}
    live2d_raw = data.get("live2d") or {}
    tts_prefetch_depth = streaming.get("tts_prefetch_depth", 2)
    if not 1 <= tts_prefetch_depth <= MAX_TTS_PREFETCH_DEPTH:
        raise ValueError(
            f"streaming.tts_prefetch_depth must be between 1 and {MAX_TTS_PREFETCH_DEPTH}"
        )
    audio_encoding = str(streaming.get("audio_encoding", "wav") or "wav").lower()
    audio_bitrate_kbps = int(streaming.get("audio_bitrate_kbps", 96))
    if audio_encoding not in {"wav", "mp3"}:
        raise ValueError("streaming.audio_encoding must be wav or mp3")
    if not 32 <= audio_bitrate_kbps <= 192:
        raise ValueError("streaming.audio_bitrate_kbps must be between 32 and 192")
    return AppConfig(
        llm=LLMConfig(
            **{key: value for key, value in data["llm"].items() if key in _LLM_FIELDS}
        ),
        tts=TTSConfig(
            **{key: value for key, value in data["tts"].items() if key in _TTS_FIELDS}
        ),
        asr=ASRConfig(**{key: value for key, value in (data.get("asr") or {}).items() if key in _ASR_FIELDS}),
        recent_turns=conversation.get(
            "recent_turns", conversation.get("max_turns", 8)
        ),
        summary_trigger_turns=conversation.get("summary_trigger_turns", 12),
        summary_trigger_chars=conversation.get("summary_trigger_chars", 12_000),
        summary_max_chars=conversation.get("summary_max_chars", 1_800),
        min_sentence_chars=streaming.get("min_sentence_chars", 4),
        max_sentence_chars=streaming.get("max_sentence_chars", 50),
        tts_prefetch_depth=tts_prefetch_depth,
        timing_event=conversation.get("timing_event", True),
        database_path=str(conversation.get("database_path", "data/sessions.db") or ""),
        audio_encoding=audio_encoding,
        audio_bitrate_kbps=audio_bitrate_kbps,
        jev=JevConfig(**{key: value for key, value in jev_raw.items() if key in _JEV_FIELDS}),
        live2d=Live2DConfig(
            model_dir=str(live2d_raw.get("model_dir") or ""),
            background=str(live2d_raw.get("background") or ""),
        ),
    )
