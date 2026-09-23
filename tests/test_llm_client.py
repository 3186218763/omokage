from unittest.mock import AsyncMock, MagicMock

import pytest

from dialogue.llm_client import LLMClient, SUMMARY_SYSTEM_PROMPT


def _delta(text: str):
    event = MagicMock()
    event.type = "response.output_text.delta"
    event.delta = text
    return event


def _error_event(message: str):
    event = MagicMock()
    event.type = "error"
    event.message = message
    return event


def _failed_event(message: str):
    error = MagicMock()
    error.message = message
    response = MagicMock()
    response.error = error
    event = MagicMock(spec=["type", "response", "message"])
    event.type = "response.failed"
    event.response = response
    event.message = None
    return event


@pytest.mark.asyncio
async def test_stream_chat_yields_tokens():
    chunks = [_delta("你好"), _delta("呀"), _delta(""), _delta("世界")]

    async def mock_create(**kwargs):
        async def _stream():
            for chunk in chunks:
                yield chunk

        return _stream()

    mock_openai = AsyncMock()
    mock_openai.responses.create = mock_create

    client = LLMClient("fake", "fake", "test-model", client=mock_openai)
    tokens = [t async for t in client.stream_chat([{"role": "user", "content": "hi"}])]

    assert tokens == ["你好", "呀", "世界"]


@pytest.mark.asyncio
async def test_stream_chat_skips_empty_tokens():
    chunks = [_delta(""), _delta("内容")]

    async def mock_create(**kwargs):
        async def _stream():
            for chunk in chunks:
                yield chunk

        return _stream()

    mock_openai = AsyncMock()
    mock_openai.responses.create = mock_create

    client = LLMClient("fake", "fake", "test", client=mock_openai)
    tokens = [t async for t in client.stream_chat([])]

    assert tokens == ["内容"]


@pytest.mark.asyncio
async def test_stream_chat_retries_initial_request_once():
    calls = 0

    async def mock_create(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary timeout")

        async def _stream():
            yield _delta("重试成功")

        return _stream()

    mock_openai = AsyncMock()
    mock_openai.responses.create = mock_create

    client = LLMClient("fake", "fake", "test", client=mock_openai)
    tokens = [t async for t in client.stream_chat([])]

    assert tokens == ["重试成功"]
    assert calls == 2


@pytest.mark.asyncio
async def test_stream_chat_does_not_retry_after_partial_response():
    calls = 0

    async def mock_create(**kwargs):
        nonlocal calls
        calls += 1

        async def _stream():
            yield _delta("部分")
            raise RuntimeError("connection lost")

        return _stream()

    mock_openai = AsyncMock()
    mock_openai.responses.create = mock_create

    client = LLMClient("fake", "fake", "test", client=mock_openai)
    with pytest.raises(RuntimeError, match="connection lost"):
        _ = [t async for t in client.stream_chat([])]

    assert calls == 1


@pytest.mark.asyncio
async def test_stream_chat_sends_responses_parameters():
    captured = {}

    async def mock_create(**kwargs):
        captured.update(kwargs)

        async def _stream():
            yield _delta("自然回复")

        return _stream()

    mock_openai = AsyncMock()
    mock_openai.responses.create = mock_create
    client = LLMClient(
        "fake",
        "fake",
        "test",
        client=mock_openai,
        temperature=0.75,
        max_tokens=320,
    )

    _ = [
        token
        async for token in client.stream_chat(
            [
                {"role": "system", "content": "人设"},
                {"role": "user", "content": "hi"},
            ]
        )
    ]

    assert captured["temperature"] == 0.75
    assert captured["max_output_tokens"] == 320
    assert captured["stream"] is True
    assert captured["model"] == "test"
    assert "frequency_penalty" not in captured
    assert "max_tokens" not in captured
    assert captured["input"] == [
        {"role": "system", "content": "人设"},
        {"role": "user", "content": "hi"},
    ]


@pytest.mark.asyncio
async def test_summarize_chat_merges_previous_memory_and_archived_turns():
    captured = {}
    response = MagicMock()
    response.output_text = " 用户叫小明，喜欢爵士乐。 "

    async def mock_create(**kwargs):
        captured.update(kwargs)
        return response

    mock_openai = AsyncMock()
    mock_openai.responses.create = mock_create
    client = LLMClient("fake", "fake", "test", client=mock_openai)

    summary = await client.summarize_chat(
        previous_summary="用户住在上海。",
        messages=[
            {"role": "user", "content": "我叫小明，喜欢爵士乐"},
            {"role": "assistant", "content": "记住啦"},
        ],
        max_chars=100,
    )

    assert summary == "用户叫小明，喜欢爵士乐。"
    assert captured["stream"] is False
    assert captured["temperature"] == 0.2
    assert captured["max_output_tokens"] == 128
    assert captured["input"][0]["content"] == SUMMARY_SYSTEM_PROMPT
    assert "用户住在上海" in captured["input"][1]["content"]
    assert "我叫小明" in captured["input"][1]["content"]
    assert "frequency_penalty" not in captured


@pytest.mark.parametrize(
    "kwargs",
    [
        {"temperature": 0},
        {"max_tokens": 0},
        {"max_retries": -1},
    ],
)
def test_rejects_invalid_generation_settings(kwargs):
    with pytest.raises(ValueError):
        LLMClient("fake", "fake", "test", client=AsyncMock(), **kwargs)


@pytest.mark.asyncio
async def test_summarize_raises_on_empty_text_without_retry():
    calls = 0
    response = MagicMock()
    response.output_text = ""

    async def mock_create(**kwargs):
        nonlocal calls
        calls += 1
        return response

    mock_openai = AsyncMock()
    mock_openai.responses.create = mock_create

    client = LLMClient("fake", "fake", "test", client=mock_openai, max_retries=2)
    with pytest.raises(RuntimeError, match="empty"):
        await client.summarize_chat(
            previous_summary="", messages=[], max_chars=100
        )

    # 空摘要是确定性失败,不应在重试循环里重复请求
    assert calls == 1


@pytest.mark.asyncio
async def test_stream_error_event_retries_before_first_token():
    calls = 0

    async def mock_create(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:

            async def _fail():
                yield _error_event("Overloaded")

            return _fail()

        async def _ok():
            yield _delta("重试成功")

        return _ok()

    mock_openai = AsyncMock()
    mock_openai.responses.create = mock_create

    client = LLMClient("fake", "fake", "test", client=mock_openai)
    tokens = [t async for t in client.stream_chat([{"role": "user", "content": "hi"}])]

    assert tokens == ["重试成功"]
    assert calls == 2


@pytest.mark.asyncio
async def test_stream_failed_event_after_text_does_not_retry():
    calls = 0

    async def mock_create(**kwargs):
        nonlocal calls
        calls += 1

        async def _stream():
            yield _delta("部分")
            yield _failed_event("Overloaded")

        return _stream()

    mock_openai = AsyncMock()
    mock_openai.responses.create = mock_create

    client = LLMClient("fake", "fake", "test", client=mock_openai)
    with pytest.raises(RuntimeError, match="Overloaded"):
        _ = [t async for t in client.stream_chat([{"role": "user", "content": "hi"}])]

    assert calls == 1


@pytest.mark.asyncio
async def test_stream_skips_non_text_events():
    events = [
        MagicMock(type="response.created"),
        MagicMock(type="response.reasoning_text.delta", delta="内部推理"),
        _delta("你好"),
        MagicMock(type="response.completed"),
    ]

    async def mock_create(**kwargs):
        async def _stream():
            for event in events:
                yield event

        return _stream()

    mock_openai = AsyncMock()
    mock_openai.responses.create = mock_create

    client = LLMClient("fake", "fake", "test", client=mock_openai)
    tokens = [t async for t in client.stream_chat([{"role": "user", "content": "hi"}])]

    assert tokens == ["你好"]


@pytest.mark.asyncio
async def test_stream_tolerates_message_without_content():
    captured = {}

    async def mock_create(**kwargs):
        captured.update(kwargs)

        async def _stream():
            yield _delta("回复")

        return _stream()

    mock_openai = AsyncMock()
    mock_openai.responses.create = mock_create
    client = LLMClient("fake", "fake", "test", client=mock_openai)
    tokens = [
        t
        async for t in client.stream_chat(
            [{"role": "system"}, {"role": "user", "content": "hi"}]
        )
    ]

    assert tokens == ["回复"]
    assert captured["input"] == [
        {"role": "system", "content": ""},
        {"role": "user", "content": "hi"},
    ]


@pytest.mark.asyncio
async def test_aclose_closes_openai_client():
    mock_openai = AsyncMock()
    mock_openai.close = AsyncMock()

    client = LLMClient("fake", "fake", "test", client=mock_openai)
    await client.aclose()

    mock_openai.close.assert_awaited_once()
