"""System One 客户端。只问表演情绪，不生成台词。

本地 Kev 与托管 Jev 用同一路径：base_url 以 /v1/systemone 结尾时不再把密钥拼进 URL。

密钥只出现在请求 URL 与 Authorization 头，不写入异常文本。
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from .performance import (
    EMOTION_CRITERIA,
    EMOTION_INSTRUCTIONS,
    INTENSITY_CRITERIA,
    INTENSITY_INSTRUCTIONS,
    PerformanceDecision,
    build_jev_state,
    from_jev_choice,
)


class JevClient:
    def __init__(
        self,
        *,
        enabled: bool = False,
        base_url: str = "https://api.typesafe.ai",
        api_key: str = "",
        model: str = "jev-latest",
        timeout_seconds: float = 2.0,
        min_confidence: float = 0.4,
        fail_cooldown_seconds: float = 60.0,
        clock=time.monotonic,
    ):
        self.enabled = enabled
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.min_confidence = min_confidence
        self.fail_cooldown_seconds = fail_cooldown_seconds
        self._clock = clock
        self._cooldown_until = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.api_key and self.base_url)

    def _endpoint(self) -> str:
        if self.base_url.endswith("/v1/systemone"):
            return self.base_url
        return f"{self.base_url}/{self.api_key}/v1/systemone"

    def _questions(self) -> dict[str, Any]:
        return {
            "emotion": {
                "type": "choice",
                "instructions": EMOTION_INSTRUCTIONS,
                "criteria": EMOTION_CRITERIA,
            },
            "intensity": {
                "type": "choice",
                "instructions": INTENSITY_INSTRUCTIONS,
                "criteria": INTENSITY_CRITERIA,
            },
        }

    async def ask(self, state: str) -> PerformanceDecision | None:
        if not self.configured or not state.strip():
            return None
        if self._clock() < self._cooldown_until:
            return None
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    self._endpoint(),
                    json={
                        "model": self.model,
                        "state": state,
                        "questions": self._questions(),
                    },
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            self._cooldown_until = self._clock() + self.fail_cooldown_seconds
            return None
        if not isinstance(payload, dict):
            self._cooldown_until = self._clock() + self.fail_cooldown_seconds
            return None
        answers = payload.get("answers")
        if not isinstance(answers, dict):
            self._cooldown_until = self._clock() + self.fail_cooldown_seconds
            return None
        emotion = answers.get("emotion") if isinstance(answers.get("emotion"), dict) else {}
        intensity = answers.get("intensity") if isinstance(answers.get("intensity"), dict) else {}
        decision = from_jev_choice(
            emotion.get("choice"),
            intensity.get("choice"),
            emotion.get("confidence"),
            min_confidence=self.min_confidence,
        )
        if decision is None and not emotion.get("choice"):
            self._cooldown_until = self._clock() + self.fail_cooldown_seconds
        return decision

    async def ask_messages(
        self, messages: list[dict[str, str]], assistant_text: str
    ) -> PerformanceDecision | None:
        return await self.ask(build_jev_state(messages, assistant_text))
