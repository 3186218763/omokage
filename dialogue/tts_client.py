"""Style-Bert-VITS2 TTS API client.

The dedicated Huayin server locks speaker and style. Callers only send text:
``POST /tts {"text": "..."}``.
"""

from __future__ import annotations

import httpx

from .speech_text import normalize_speech_text


class TTSClient:
    """Call the locked Huayin Style-Bert-VITS2 API."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 60.0,
    ):
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def check_available(self) -> None:
        """Raise a user-facing error unless the local API responds."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self._base_url}/healthz", timeout=5.0
                )
                response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(
                "TTS 服务未运行，请先启动 Style-Bert-VITS2 API"
            ) from exc

    async def synthesize(
        self,
        text: str,
        text_language: str | None = None,
        *,
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        ref_language: str | None = None,
        style: str | None = None,
    ) -> bytes:
        """Synthesize ``text`` as WAV bytes.

        Extra kwargs are accepted for orchestrator compatibility but ignored:
        this engine always uses the locked Huayin voice.
        """
        del text_language, ref_audio_path, ref_text, ref_language, style
        normalized_text = normalize_speech_text(text)
        if normalized_text is None:
            raise ValueError("text contains no speakable content")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/tts",
                json={"text": normalized_text},
                timeout=self._timeout,
            )
            response.raise_for_status()
            return response.content
