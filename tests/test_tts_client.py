import json

import httpx
import pytest
import respx

from dialogue.tts_client import TTSClient


@pytest.mark.asyncio
@respx.mock
async def test_synthesize_returns_audio():
    respx.post("http://127.0.0.1:5000/tts").mock(
        return_value=httpx.Response(200, content=b"fake_wav_bytes")
    )
    client = TTSClient(base_url="http://127.0.0.1:5000")
    result = await client.synthesize("你好世界")
    assert result == b"fake_wav_bytes"


@pytest.mark.asyncio
@respx.mock
async def test_synthesize_sends_only_text():
    route = respx.post("http://127.0.0.1:5000/tts").mock(
        return_value=httpx.Response(200, content=b"audio")
    )
    client = TTSClient(base_url="http://127.0.0.1:5000")
    await client.synthesize(
        "你好世界",
        ref_audio_path="/ref.wav",
        ref_text="参考文本",
        ref_language="zh",
    )

    assert route.called
    body = json.loads(route.calls[0].request.content)
    assert body == {"text": "你好世界"}


@pytest.mark.asyncio
@respx.mock
async def test_synthesize_normalizes_stage_directions_at_api_boundary():
    route = respx.post("http://127.0.0.1:5000/tts").mock(
        return_value=httpx.Response(200, content=b"audio")
    )
    client = TTSClient("http://127.0.0.1:5000")

    await client.synthesize("（脸红）你好呀！💕")

    body = json.loads(route.calls[0].request.content)
    assert body["text"] == "你好呀！"


@pytest.mark.asyncio
async def test_synthesize_rejects_action_only_text():
    client = TTSClient("http://127.0.0.1:5000")

    with pytest.raises(ValueError, match="no speakable content"):
        await client.synthesize("（轻轻点头）💕")


@pytest.mark.asyncio
@respx.mock
async def test_check_available_accepts_running_api():
    route = respx.get("http://127.0.0.1:5000/healthz").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    client = TTSClient("http://127.0.0.1:5000")

    await client.check_available()

    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_check_available_raises_clear_error_when_api_is_down():
    respx.get("http://127.0.0.1:5000/healthz").mock(
        return_value=httpx.Response(503)
    )
    client = TTSClient("http://127.0.0.1:5000")

    with pytest.raises(RuntimeError, match="TTS 服务未运行"):
        await client.check_available()


def test_rejects_non_positive_timeout():
    with pytest.raises(ValueError, match="timeout"):
        TTSClient("http://127.0.0.1:5000", timeout=0)
