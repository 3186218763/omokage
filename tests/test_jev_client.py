import json

import httpx
import pytest
import respx

from dialogue.jev_client import JevClient
from dialogue.performance import EMOTION_CHOICE_TO_LABEL, PerformanceDecision


def _client(**overrides) -> JevClient:
    clock = overrides.pop("clock", None) or (lambda: 0.0)
    return JevClient(
        enabled=True,
        base_url="https://jev.test",
        api_key="secret-token",
        timeout_seconds=2.0,
        min_confidence=0.4,
        fail_cooldown_seconds=60,
        clock=clock,
        **overrides,
    )


@pytest.mark.asyncio
async def test_jev_disabled_or_missing_key_does_not_call_network():
    client = JevClient(enabled=False, api_key="secret-token")
    assert await client.ask("state") is None
    empty = JevClient(enabled=True, api_key="  ")
    assert await empty.ask("state") is None


@pytest.mark.asyncio
@respx.mock
async def test_local_systemone_url_does_not_embed_the_key():
    route = respx.post("http://127.0.0.1:8009/v1/systemone").mock(
        return_value=httpx.Response(
            200,
            json={
                "answers": {
                    "emotion": {"choice": "gentle", "confidence": 0.7},
                    "intensity": {"choice": "moderate"},
                }
            },
        )
    )
    client = JevClient(
        enabled=True,
        base_url="http://127.0.0.1:8009/v1/systemone",
        api_key="local",
        clock=lambda: 0.0,
    )

    decision = await client.ask("User: thank you")

    assert route.called
    assert "/local/" not in str(route.calls.last.request.url)
    assert decision is not None
    assert decision.emotion == "温柔"


@pytest.mark.asyncio
@respx.mock
async def test_jev_parses_choice_and_hides_key_from_errors():
    route = respx.post("https://jev.test/secret-token/v1/systemone").mock(
        return_value=httpx.Response(
            200,
            json={
                "answers": {
                    "emotion": {
                        "choice": "温柔",
                        "confidence": 0.82,
                        "probabilities": {"温柔": 0.82, "日常": 0.1},
                    },
                    "intensity": {"choice": "moderate"},
                }
            },
        )
    )

    decision = await _client().ask("User: 谢谢")

    assert route.called
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer secret-token"
    body = json.loads(request.content)
    assert set(body["questions"]["emotion"]["criteria"]) == set(EMOTION_CHOICE_TO_LABEL)
    assert "日常" not in body["questions"]["emotion"]["criteria"]
    assert isinstance(decision, PerformanceDecision)
    assert decision.emotion == "温柔"
    assert decision.intensity == 0.9
    assert decision.confidence == 0.82
    assert decision.source == "jev"


@pytest.mark.asyncio
@respx.mock
async def test_jev_low_confidence_returns_none_without_cooldown_block():
    respx.post("https://jev.test/secret-token/v1/systemone").mock(
        return_value=httpx.Response(
            200,
            json={"answers": {"emotion": {"choice": "元气", "confidence": 0.1}}},
        )
    )
    now = {"t": 0.0}
    client = _client(clock=lambda: now["t"])

    assert await client.ask("state") is None
    now["t"] = 1.0
    assert await client.ask("state") is None
    assert respx.calls.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_jev_http_error_and_timeout_return_none_and_cool_down():
    respx.post("https://jev.test/secret-token/v1/systemone").mock(
        return_value=httpx.Response(503, json={"error": "down"})
    )
    now = {"t": 10.0}
    client = _client(clock=lambda: now["t"])

    assert await client.ask("state") is None
    now["t"] = 20.0
    assert await client.ask("state") is None
    assert respx.calls.call_count == 1

    now["t"] = 80.0
    respx.post("https://jev.test/secret-token/v1/systemone").mock(
        side_effect=httpx.TimeoutException("slow")
    )
    assert await client.ask("state") is None


@pytest.mark.asyncio
@respx.mock
async def test_jev_missing_choice_cools_down():
    respx.post("https://jev.test/secret-token/v1/systemone").mock(
        return_value=httpx.Response(200, json={"answers": {}})
    )
    now = {"t": 0.0}
    client = _client(clock=lambda: now["t"])

    assert await client.ask("state") is None
    now["t"] = 5.0
    assert await client.ask("state") is None
    assert respx.calls.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_total_deadline_busy_fallback_and_cancellation_release_client():
    import asyncio

    entered = asyncio.Event()
    release = asyncio.Event()

    async def delayed(_request):
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"answers": {"emotion": {"choice": "gentle", "confidence": .8}}})

    respx.post("https://jev.test/secret-token/v1/systemone").mock(side_effect=delayed)
    client = _client()
    client.timeout_seconds = .05
    task = asyncio.create_task(client.ask("state"))
    await entered.wait()
    assert await client.ask("second") is None
    assert client.last_reason == "busy"
    assert await task is None
    assert client.last_reason == "timeout"
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_intensity_requires_own_confidence_and_pool_can_be_reused():
    route = respx.post("https://jev.test/secret-token/v1/systemone").mock(return_value=httpx.Response(200, json={
        "answers": {"emotion": {"choice": "gentle", "confidence": .8},
                    "intensity": {"choice": "strong", "confidence": .1}}
    }))
    client = _client()
    try:
        assert (await client.ask("one")).intensity == .9
        route.mock(return_value=httpx.Response(200, json={
            "answers": {"emotion": {"choice": "gentle", "confidence": .8},
                        "intensity": {"choice": "strong", "confidence": .8}}
        }))
        assert (await client.ask("two")).intensity == 1
    finally:
        await client.aclose()
