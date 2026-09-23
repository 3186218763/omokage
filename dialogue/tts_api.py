"""Dedicated Huayin TTS HTTP API: POST /tts {\"text\": \"你好\"} -> WAV.

The server locks speaker / model / style so callers cannot switch voices.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from .speech_text import normalize_speech_text

SynthesizeFn = Callable[[str], bytes | Awaitable[bytes]]

MAX_TEXT_CHARS = 500
DEFAULT_MODEL_NAME = "huayin"
DEFAULT_SPEAKER_NAME = "花音"


def parse_tts_request(payload: Mapping[str, Any], *, max_chars: int = MAX_TEXT_CHARS) -> str:
    """Accept only ``text``; extra keys are ignored so the voice stays locked."""
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    text = text.strip()
    if len(text) > max_chars:
        raise ValueError(f"text must be at most {max_chars} characters")
    normalized = normalize_speech_text(text)
    if normalized is None:
        raise ValueError("text contains no speakable content")
    return normalized


async def call_synthesize(synthesize: SynthesizeFn, text: str) -> bytes:
    if inspect.iscoroutinefunction(synthesize):
        audio = await synthesize(text)
    else:
        maybe = synthesize(text)
        if inspect.isawaitable(maybe):
            audio = await maybe
        else:
            audio = maybe
    if not isinstance(audio, (bytes, bytearray)) or not audio:
        raise RuntimeError("TTS returned empty audio")
    return bytes(audio)


def create_tts_app(
    synthesize: SynthesizeFn,
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    speaker_name: str = DEFAULT_SPEAKER_NAME,
    max_chars: int = MAX_TEXT_CHARS,
):
    """Build a FastAPI app that always speaks with the locked Huayin voice."""
    try:
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse, Response
    except ImportError as exc:
        raise RuntimeError(
            "TTS API 需要 FastAPI，请运行：pip install -e '.[web]'"
        ) from exc

    app = FastAPI(title="Huayin TTS", version="0.1.0")

    @app.get("/healthz")
    async def healthz():
        return {
            "status": "ok",
            "service": "huayin-tts",
            "engine": "style-bert-vits2",
            "model_name": model_name,
            "speaker_name": speaker_name,
        }

    @app.post("/tts")
    async def tts(payload: dict[str, Any]):
        try:
            text = parse_tts_request(payload, max_chars=max_chars)
        except (ValueError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        try:
            audio = await call_synthesize(synthesize, text)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)
        return Response(content=audio, media_type="audio/wav")

    return app
