import asyncio
import base64
import json
from pathlib import Path

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock

from dialogue.conversation import Conversation
from dialogue.performance import from_jev_choice
from frontend.web import WebChatService, create_app, parse_chat_request, sse_event
from config import AppConfig, LLMConfig, TTSConfig


def _async_iter(tokens):
    async def _gen():
        for token in tokens:
            yield token

    return _gen()


class FakeService:
    async def stream(self, message, conversation, *, interrupt=None):
        yield {"type": "sentence", "text": f"收到：{message}"}
        yield {"type": "done"}


def test_persistent_web_history_and_opt_in_memories_survive_restart(tmp_path):
    from fastapi.testclient import TestClient

    class StoredService:
        async def stream(self, message, conversation, *, interrupt=None):
            conversation.add_user_message(message)
            conversation.add_assistant_message("收到。")
            yield {"type": "done"}

    config = AppConfig(
        llm=LLMConfig(api_key="key", base_url="https://example.test", model="model"),
        tts=TTSConfig(base_url="http://localhost:5000"),
        database_path=str(tmp_path / "sessions.db"),
    )
    first = TestClient(create_app(StoredService(), config=config))
    enabled = first.put("/api/memories", json={"session_id": "one", "enabled": True})
    assert enabled.status_code == 200
    response = first.post("/api/chat", json={"session_id": "one", "message": "我叫小林。"})
    assert response.status_code == 200
    assert first.get("/api/memories", params={"session_id": "one"}).json()["memories"][0]["value"] == "小林"

    second = TestClient(create_app(StoredService(), config=config))
    history = second.get("/api/history", params={"session_id": "one"}).json()["messages"]
    assert history == [
        {"role": "user", "content": "我叫小林。"},
        {"role": "assistant", "content": "收到。"},
    ]
    assert second.get("/api/memories", params={"session_id": "one"}).json()["enabled"] is True
    assert second.post("/api/reset", json={"session_id": "one"}).status_code == 200
    third = TestClient(create_app(StoredService(), config=config))
    assert third.get("/api/history", params={"session_id": "one"}).json()["messages"] == []
    assert third.get("/api/memories", params={"session_id": "one"}).json()["memories"] == []


def test_storage_failure_warns_without_losing_the_live_reply(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from dialogue.session_store import SessionStore

    class StoredService:
        async def stream(self, message, conversation, *, interrupt=None):
            conversation.add_user_message(message)
            conversation.add_assistant_message("收到。")
            yield {"type": "done"}

    config = AppConfig(
        llm=LLMConfig(api_key="key", base_url="https://example.test", model="model"),
        tts=TTSConfig(base_url="http://localhost:5000"),
        database_path=str(tmp_path / "sessions.db"),
    )
    app = create_app(StoredService(), config=config)

    def fail_save(self, session_id, conversation):
        raise OSError("disk unavailable")

    monkeypatch.setattr(SessionStore, "save", fail_save)
    response = TestClient(app).post("/api/chat", json={"v": 2, "turn_id": "turn-one", "session_id": "one", "message": "你好"})
    events = [json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: ")]
    assert response.status_code == 200
    assert [event["type"] for event in events] == ["storage_warning", "done"]
    assert events[0]["turn_id"] == "turn-one"
    assert "未保存" in events[0]["message"]


@pytest.mark.asyncio
async def test_web_chat_streams_text_and_audio_events_in_order():
    llm = AsyncMock()
    llm.stream_chat = MagicMock(return_value=_async_iter(["你好呀。", "今天也要", "加油！"]))
    tts = AsyncMock()
    tts.synthesize = AsyncMock(side_effect=[b"wav-one", b"wav-two"])
    service = WebChatService(llm, tts, max_chars=25)

    events = [event async for event in service.stream("hello", Conversation())]

    # Ready audio may precede later text; each sentence still precedes its audio.
    types = [event["type"] for event in events]
    assert types[0] == "performance"
    assert types[-2:] == ["timing", "done"]
    sentences = [event for event in events if event["type"] == "sentence"]
    audios = [event for event in events if event["type"] == "audio"]
    assert [event["text"] for event in sentences] == ["你好呀。", "今天也要加油！"]
    assert [event["index"] for event in audios] == [0, 1]
    assert [base64.b64decode(event["audio"]) for event in audios] == [b"wav-one", b"wav-two"]
    assert all(events.index(sentences[i]) < events.index(audios[i]) for i in range(2))
    assert events[0]["emotion"] == "日常"
    assert events[0]["source"] == "speaking_style"


@pytest.mark.asyncio
async def test_web_tts_prefetch_synthesizes_ahead_of_delivery():
    """深度 2：第一条音频下发时，下一句的合成必须已经在飞（流水线不空等）。"""
    calls: list[str] = []

    async def slow_synthesize(text: str, **_kwargs) -> bytes:
        calls.append(text)
        await asyncio.sleep(0)
        return f"wav:{text}".encode()

    llm = AsyncMock()
    llm.stream_chat = MagicMock(
        return_value=_async_iter(["第一句。", "第二句。", "第三句。"])
    )
    tts = AsyncMock()
    tts.synthesize = slow_synthesize
    service = WebChatService(llm, tts, tts_prefetch_depth=2)

    events = [event async for event in service.stream("问题", Conversation())]

    audios = [event for event in events if event["type"] == "audio"]
    assert [event["index"] for event in audios] == [0, 1, 2]
    # 收到第一条音频时，第二句的合成已经发起
    first_audio_at = events.index(audios[0])
    sentences_before = [
        event for event in events[:first_audio_at] if event["type"] == "sentence"
    ]
    assert len(sentences_before) >= 2
    assert calls[:2] == ["第一句。", "第二句。"]


@pytest.mark.asyncio
async def test_web_tts_prefetch_depth_one_keeps_legacy_interleaving():
    """深度 1 = 逃生档：逐句「句子→音频」串行，等价旧管线次序。"""
    llm = AsyncMock()
    llm.stream_chat = MagicMock(
        return_value=_async_iter(["第一句。", "第二句。", "第三句。"])
    )
    tts = AsyncMock()
    tts.synthesize = AsyncMock(side_effect=[b"w1", b"w2", b"w3"])
    service = WebChatService(llm, tts, tts_prefetch_depth=1)

    events = [event async for event in service.stream("问题", Conversation())]

    types = [event["type"] for event in events]
    assert types == [
        "performance",
        "sentence",
        "audio",
        "sentence",
        "audio",
        "sentence",
        "audio",
        "timing",
        "done",
    ]


def test_web_rejects_out_of_range_prefetch_depth():
    llm = AsyncMock()
    tts = AsyncMock()
    with pytest.raises(ValueError, match="tts_prefetch_depth"):
        WebChatService(llm, tts, tts_prefetch_depth=0)
    with pytest.raises(ValueError, match="tts_prefetch_depth"):
        WebChatService(llm, tts, tts_prefetch_depth=4)


@pytest.mark.asyncio
async def test_web_timing_event_reports_latency_fields_and_respects_config():
    llm = AsyncMock()
    llm.stream_chat = MagicMock(return_value=_async_iter(["一句话。"]))
    tts = AsyncMock()
    tts.synthesize = AsyncMock(return_value=b"wav")
    conversation = Conversation()

    events = [
        event
        async for event in WebChatService(llm, tts, timing_event=True).stream(
            "问题", conversation
        )
    ]

    timing = next(event for event in events if event["type"] == "timing")
    assert events[-1] == {"type": "done"}
    assert timing["interrupted"] is False
    assert timing["sentences"] == 1
    assert timing["llm_first_token_ms"] >= 0
    assert timing["first_sentence_ms"] >= 0
    assert timing["first_audio_ms"] >= 0
    assert timing["jev_dispatch_ms"] is None  # 未配置 Jev
    assert timing["audio_gaps_ms"] == []

    silenced = [
        event
        async for event in WebChatService(llm, tts, timing_event=False).stream(
            "问题", Conversation()
        )
    ]
    assert all(event["type"] != "timing" for event in silenced)


@pytest.mark.asyncio
async def test_web_chat_updates_conversation_after_stream():
    llm = AsyncMock()
    llm.stream_chat = MagicMock(return_value=_async_iter(["回复。"]))
    tts = AsyncMock()
    tts.synthesize = AsyncMock(return_value=b"wav")
    conversation = Conversation()

    events = [event async for event in WebChatService(llm, tts).stream("问题", conversation)]

    assert events[-1] == {"type": "done"}
    assert conversation.get_messages() == [
        {"role": "user", "content": "问题"},
        {"role": "assistant", "content": "回复。"},
    ]


@pytest.mark.asyncio
async def test_web_tts_failure_emits_error_but_completes_text_stream():
    llm = AsyncMock()
    llm.stream_chat = MagicMock(return_value=_async_iter(["回复。", "继续。"]))
    tts = AsyncMock()
    tts.synthesize = AsyncMock(side_effect=[RuntimeError("tts offline"), b"wav"])
    conversation = Conversation()

    events = [
        event
        async for event in WebChatService(llm, tts).stream("问题", conversation)
    ]

    assert [event["type"] for event in events] == [
        "performance",
        "sentence",
        "audio_error",
        "timing",
        "done",
    ]
    # min_chars=4：两句 token 合并为一句（「回复。」3 字不成句）
    assert events[1]["text"] == "回复。继续。"
    assert events[2]["index"] == 0
    assert conversation.get_messages()[-1] == {
        "role": "assistant",
        "content": "回复。继续。",
    }


@pytest.mark.asyncio
async def test_web_empty_llm_response_emits_error_and_rolls_back():
    llm = AsyncMock()
    llm.stream_chat = MagicMock(return_value=_async_iter([]))
    tts = AsyncMock()
    conversation = Conversation()

    events = [
        event
        async for event in WebChatService(llm, tts).stream("问题", conversation)
    ]

    # error 轮也发 timing（失败轮恰是最需要观测的），随后 error 收尾
    assert [event["type"] for event in events] == ["timing", "error"]
    assert events[1] == {"type": "error", "message": "LLM returned an empty response"}
    assert events[0]["sentences"] == 0
    assert conversation.get_messages() == []


@pytest.mark.asyncio
async def test_web_filters_stage_directions_before_text_and_audio():
    llm = AsyncMock()
    llm.stream_chat = MagicMock(
        return_value=_async_iter(["（心里想着：好紧张。）", "见到你真开心！💕"])
    )
    tts = AsyncMock()
    tts.synthesize = AsyncMock(return_value=b"wav")
    conversation = Conversation()

    events = [
        event
        async for event in WebChatService(llm, tts).stream("你好", conversation)
    ]

    assert [event["type"] for event in events] == [
        "performance",
        "sentence",
        "audio",
        "timing",
        "done",
    ]
    assert events[1]["text"] == "见到你真开心！"
    assert "说话语气" not in events[1]["text"]
    assert events[2]["index"] == 0
    tts.synthesize.assert_awaited_once()
    assert tts.synthesize.await_args.args == ("见到你真开心！",)
    assert conversation.get_messages()[-1] == {
        "role": "assistant",
        "content": "见到你真开心！",
    }


@pytest.mark.asyncio
async def test_web_pause_tag_is_sentence_metadata_only():
    llm = AsyncMock()
    llm.stream_chat = MagicMock(return_value=_async_iter([
        "【说话语气:日常】【停顿:长】先接住你。【停顿:中】然后才说这句。",
    ]))
    tts = AsyncMock()
    tts.synthesize = AsyncMock(return_value=b"wav")
    conversation = Conversation()
    events = [event async for event in WebChatService(llm, tts).stream("在吗", conversation)]
    sentences = [event for event in events if event["type"] == "sentence"]
    assert [event["text"] for event in sentences] == ["先接住你。", "然后才说这句。"]
    assert "pause_ms" not in sentences[0]
    assert sentences[1]["pause_ms"] == 700
    assert "停顿" not in "".join(event["text"] for event in sentences)
    assert "停顿" not in conversation.get_messages()[-1]["content"]


class _FakeJev:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []

    async def ask_messages(self, messages, assistant_text):
        self.calls.append((messages, assistant_text))
        return self.decision


@pytest.mark.asyncio
async def test_web_performance_follows_style_then_jev_without_showing_the_tag():
    llm = AsyncMock()
    llm.stream_chat = MagicMock(
        return_value=_async_iter(["【说话语气:元气】", "早好音。"])
    )
    tts = AsyncMock()
    tts.synthesize = AsyncMock(return_value=b"wav")
    jev = _FakeJev(from_jev_choice("温柔", "mild", 0.9, min_confidence=0.4))
    conversation = Conversation()

    events = [
        event
        async for event in WebChatService(llm, tts, jev_client=jev).stream(
            "早上好", conversation
        )
    ]

    performances = [event for event in events if event["type"] == "performance"]
    sentences = [event["text"] for event in events if event["type"] == "sentence"]
    assert performances[0]["emotion"] == "元气"
    assert performances[0]["source"] == "speaking_style"
    assert performances[-1]["emotion"] == "温柔"
    assert performances[-1]["source"] == "jev"
    assert sentences == ["早好音。"]
    assert "说话语气" not in "".join(sentences)
    assert events[-1]["type"] == "done"
    assert jev.calls and "说话语气" not in jev.calls[0][1]


@pytest.mark.asyncio
async def test_web_jev_failure_still_finishes_the_reply():
    llm = AsyncMock()
    llm.stream_chat = MagicMock(return_value=_async_iter(["在的。"]))
    tts = AsyncMock()
    tts.synthesize = AsyncMock(return_value=b"wav")

    class _DownJev:
        async def ask_messages(self, messages, assistant_text):
            raise RuntimeError("jev down")

    events = [
        event
        async for event in WebChatService(llm, tts, jev_client=_DownJev()).stream(
            "在吗", Conversation()
        )
    ]

    assert [event["type"] for event in events] == [
        "performance",
        "sentence",
        "audio",
        "timing",
        "done",
    ]
    assert events[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_web_interrupt_cancels_all_inflight_tts_tasks():
    """让路时预取队列里所有在飞 TTS 必须被取消，不允许孤儿任务占着 GPU。"""
    states: dict[str, str] = {}
    release = asyncio.Event()
    interrupt = asyncio.Event()

    async def slow_synthesize(text: str, **_kwargs) -> bytes:
        states[text] = "started"
        # 首句快（先送达），后续句慢：打断时它们必然还在飞，命中取消路径
        delay = 0.05 if text == "第一句。" else 0.5
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            states[text] = "cancelled"
            raise
        states[text] = "done"
        return b"wav"

    async def slow_llm():
        yield "第一句。"
        yield "第二句。"
        yield "第三句。"
        await release.wait()

    llm = AsyncMock()
    llm.stream_chat = MagicMock(return_value=slow_llm())
    tts = AsyncMock()
    tts.synthesize = slow_synthesize
    conversation = Conversation()

    stream = WebChatService(llm, tts).stream("问题", conversation, interrupt=interrupt)
    seen: list[str] = []
    async for event in stream:
        seen.append(event["type"])
        if event["type"] == "audio":  # a1 已下发（约 0.3s 后）
            break
    interrupt.set()
    release.set()
    async for event in stream:
        seen.append(event["type"])

    assert seen[-2:] == ["timing", "interrupted"]
    # 未送达的句子全部取消，已送达的算 done：不允许 started 悬空
    # （「未启动」也合法：取消可能早于协程首步，此时 states 里没有记录）
    assert set(states.values()) <= {"done", "cancelled"}
    assert states["第一句。"] == "done"
    assert states["第二句。"] == "cancelled"
    assert states.get("第三句。") in (None, "cancelled")
    # 生成器停在 a1 的 yield 上：第三句从未作为 sentence 事件送出，不进半截历史
    assert conversation.get_messages()[-1]["content"] == "第一句。第二句。"


@pytest.mark.asyncio
async def test_web_client_disconnect_cancels_inflight_tts_tasks():
    """断连（aclose → GeneratorExit）也不泄漏预取队列里的在飞 TTS。"""
    states: dict[str, str] = {}

    async def slow_synthesize(text: str, **_kwargs) -> bytes:
        states[text] = "started"
        try:
            await asyncio.sleep(0.3)
        except asyncio.CancelledError:
            states[text] = "cancelled"
            raise
        states[text] = "done"
        return b"wav"

    llm = AsyncMock()
    llm.stream_chat = MagicMock(
        return_value=_async_iter(["第一句。", "第二句。"])
    )
    tts = AsyncMock()
    tts.synthesize = slow_synthesize
    conversation = Conversation()

    stream = WebChatService(llm, tts).stream("问题", conversation)
    assert (await anext(stream))["type"] == "performance"
    assert (await anext(stream))["type"] == "sentence"
    await stream.aclose()
    await asyncio.sleep(0)  # 让取消传播到合成协程

    # 生成器停在第一句的 yield 上：t1 要么尚未启动（取消早于首步），要么已捕获取消；
    # 唯一不允许的是 done（跑完还留在后台）
    assert states.get("第一句。") in (None, "cancelled")
    assert conversation.get_messages() == []  # 断连整轮回滚


def test_parse_chat_request_rejects_empty_or_oversized_messages():
    with pytest.raises(ValueError, match="message"):
        parse_chat_request({"message": "   "})
    with pytest.raises(ValueError, match="2000"):
        parse_chat_request({"message": "x" * 2001})


def test_parse_chat_request_normalizes_session_id_and_sse_format():
    assert parse_chat_request({"message": " hi ", "session_id": "abc-123"}) == (
        "hi",
        "abc-123",
    )
    payload = sse_event({"type": "done"})
    assert payload == 'data: {"type": "done"}\n\n'


def test_create_app_serves_ui_health_and_streaming_chat():
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from frontend.web import create_app

    class FakeTranscriber:
        async def transcribe(self, audio, *, filename, language=None):
            assert audio == b"fake-webm"
            assert filename.endswith(".webm")
            return {"text": "浏览器语音", "language": "zh"}

    class FakeTTS:
        async def synthesize(self, text):
            assert text == "你好"
            return b"RIFF-locked-voice"

        async def check_available(self):
            return None

    class ServiceWithTTS(FakeService):
        def __init__(self):
            self._tts = FakeTTS()

    client = TestClient(
        create_app(ServiceWithTTS(), transcriber=FakeTranscriber())
    )
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["llm_configured"] is False
    assert health.json()["asr_configured"] is True
    assert health.json()["tts_available"] is True

    tts = client.post("/tts", json={"text": "你好", "speaker_id": 3})
    assert tts.status_code == 200
    assert tts.content == b"RIFF-locked-voice"
    assert tts.headers["content-type"].startswith("audio/wav")

    response = client.post(
        "/api/chat",
        json={"message": "你好", "session_id": "test-session"},
    )
    assert response.status_code == 200
    assert '\"type\": \"sentence\"' in response.text
    assert "收到：你好" in response.text
    assert response.headers["content-type"].startswith("text/event-stream")

    reset = client.post("/api/reset", json={"session_id": "test-session"})
    assert reset.status_code == 200

    transcribe = client.post(
        "/api/transcribe",
        content=b"fake-webm",
        headers={"content-type": "audio/webm"},
    )
    assert transcribe.status_code == 200
    assert transcribe.json() == {"text": "浏览器语音", "language": "zh"}

    invalid = client.post(
        "/api/transcribe",
        content=b"not-audio",
        headers={"content-type": "text/plain"},
    )
    assert invalid.status_code == 400

    oversized = client.post(
        "/api/transcribe",
        content=b"small-body",
        headers={
            "content-type": "audio/webm",
            "content-length": str(16 * 1024 * 1024),
        },
    )
    assert oversized.status_code == 413


@pytest.mark.asyncio
async def test_same_session_chat_requests_are_serialized():
    class BlockingService:
        def __init__(self):
            self.active = 0
            self.max_active = 0
            self.entered: list[str] = []
            self.first_entered = asyncio.Event()
            self.release_first = asyncio.Event()
            self.conversation = None

        async def stream(self, message, conversation, *, interrupt=None):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.entered.append(message)
            self.conversation = conversation
            conversation.add_user_message(message)
            try:
                if message == "first":
                    self.first_entered.set()
                    await self.release_first.wait()
                conversation.add_assistant_message(f"reply-{message}")
                yield {"type": "done"}
            finally:
                self.active -= 1

    service = BlockingService()
    transport = httpx.ASGITransport(app=create_app(service))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        first = asyncio.create_task(
            client.post(
                "/api/chat",
                json={"message": "first", "session_id": "shared"},
            )
        )
        await asyncio.wait_for(service.first_entered.wait(), timeout=1)
        second = asyncio.create_task(
            client.post(
                "/api/chat",
                json={"message": "second", "session_id": "shared"},
            )
        )
        await asyncio.sleep(0.05)

        assert service.entered == ["first"]
        service.release_first.set()
        responses = await asyncio.gather(first, second)

    assert [response.status_code for response in responses] == [200, 200]
    assert service.max_active == 1
    assert service.entered == ["first", "second"]
    assert service.conversation.get_messages() == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply-first"},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": "reply-second"},
    ]


@pytest.mark.asyncio
async def test_reset_waits_for_an_active_chat_in_the_same_session():
    class BlockingService:
        def __init__(self):
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.conversation = None

        async def stream(self, message, conversation, *, interrupt=None):
            self.conversation = conversation
            conversation.add_user_message(message)
            self.entered.set()
            await self.release.wait()
            conversation.add_assistant_message("reply")
            yield {"type": "done"}

    service = BlockingService()
    transport = httpx.ASGITransport(app=create_app(service))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        chat = asyncio.create_task(
            client.post(
                "/api/chat",
                json={"message": "hello", "session_id": "shared"},
            )
        )
        await asyncio.wait_for(service.entered.wait(), timeout=1)
        reset = asyncio.create_task(
            client.post("/api/reset", json={"session_id": "shared"})
        )
        await asyncio.sleep(0.05)

        assert not reset.done()
        service.release.set()
        chat_response, reset_response = await asyncio.gather(chat, reset)

    assert chat_response.status_code == 200
    assert reset_response.status_code == 200
    assert service.conversation.get_messages() == []


@pytest.mark.asyncio
async def test_session_limit_does_not_evict_an_active_conversation():
    class EvictionProbeService:
        def __init__(self):
            self.first_started = asyncio.Event()
            self.followup_started = asyncio.Event()
            self.release_first = asyncio.Event()
            self.conversations = {}

        async def stream(self, message, conversation, *, interrupt=None):
            self.conversations[message] = conversation
            if message == "first":
                self.first_started.set()
                await self.release_first.wait()
            elif message == "followup":
                self.followup_started.set()
            yield {"type": "done"}

    service = EvictionProbeService()
    transport = httpx.ASGITransport(app=create_app(service, max_sessions=1))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        first = asyncio.create_task(
            client.post(
                "/api/chat",
                json={"message": "first", "session_id": "protected"},
            )
        )
        await asyncio.wait_for(service.first_started.wait(), timeout=1)

        other = await client.post(
            "/api/chat",
            json={"message": "other", "session_id": "other"},
        )
        assert other.status_code == 200

        followup = asyncio.create_task(
            client.post(
                "/api/chat",
                json={"message": "followup", "session_id": "protected"},
            )
        )
        try:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    service.followup_started.wait(), timeout=0.05
                )
        finally:
            service.release_first.set()
            first_response, followup_response = await asyncio.gather(
                first, followup
            )

    assert first_response.status_code == 200
    assert followup_response.status_code == 200
    assert service.conversations["first"] is service.conversations["followup"]


@pytest.mark.asyncio
async def test_web_motion_stays_attached_to_its_sentence_and_out_of_text():
    llm = AsyncMock()
    llm.stream_chat = MagicMock(
        return_value=_async_iter(
            [
                "【说话语气:元气】【动作:点头】早好音。",
                "【动作:点头】又一句。",
                "【动作:歪头】歪一下。",
            ]
        )
    )
    tts = AsyncMock()
    tts.synthesize = AsyncMock(side_effect=[b"wav-one", b"wav-two", b"wav-three"])
    conversation = Conversation()

    events = [
        event
        async for event in WebChatService(llm, tts).stream("早上好", conversation)
    ]

    types = [event["type"] for event in events]
    sentences = [event for event in events if event["type"] == "sentence"]

    assert [event["text"] for event in sentences] == ["早好音。", "又一句。", "歪一下。"]
    assert [event["motion"] for event in sentences] == ["点头", "点头", "歪头"]
    for event in sentences:
        assert "动作" not in event["text"]
    assert types[-1] == "done"
    assert tts.synthesize.await_args_list[0].args == ("早好音。",)
    assert conversation.get_messages()[-1]["content"] == "早好音。又一句。歪一下。"


@pytest.mark.asyncio
async def test_web_motion_repeats_are_preserved_and_tags_stripped():
    llm = AsyncMock()
    llm.stream_chat = MagicMock(
        return_value=_async_iter(
            [
                "【动作:点头】一。",
                "【动作:摇头】二。",
                "【动作:歪头】三。",
            ]
        )
    )
    tts = AsyncMock()
    tts.synthesize = AsyncMock(return_value=b"wav")
    conversation = Conversation()

    events = [
        event
        async for event in WebChatService(llm, tts).stream("嗨", conversation)
    ]

    sentences = [event for event in events if event["type"] == "sentence"]
    assert [event["motion"] for event in sentences] == ["点头", "摇头", "歪头"]
    assert [event["text"] for event in sentences] == ["一。", "二。", "三。"]


@pytest.mark.asyncio
async def test_web_interrupt_commits_spoken_part_and_ends_with_interrupted():
    release = asyncio.Event()
    interrupt = asyncio.Event()

    async def slow_llm():
        yield "第一句话。"
        await release.wait()
        yield "第二句话。"

    llm = AsyncMock()
    llm.stream_chat = MagicMock(return_value=slow_llm())
    tts = AsyncMock()
    tts.synthesize = AsyncMock(return_value=b"wav")
    conversation = Conversation()

    stream = WebChatService(llm, tts).stream("问题", conversation, interrupt=interrupt)
    first = await anext(stream)
    assert first["type"] == "performance"
    second = await anext(stream)
    assert second == {"type": "sentence", "text": "第一句话。"}

    interrupt.set()
    release.set()
    rest = [event async for event in stream]

    # 让路：预取队列里未送达的音频全部取消，不再有 audio/done，收尾是 timing + interrupted
    assert [event["type"] for event in rest] == ["timing", "interrupted"]
    assert rest[0]["interrupted"] is True
    assert rest[0]["sentences"] == 1
    assert conversation.get_messages() == [
        {"role": "user", "content": "问题"},
        {"role": "assistant", "content": "第一句话。"},
    ]


@pytest.mark.asyncio
async def test_web_interrupt_before_anything_spoken_rolls_back():
    release = asyncio.Event()
    interrupt = asyncio.Event()

    async def slow_llm():
        await release.wait()
        yield "太慢了。"

    llm = AsyncMock()
    llm.stream_chat = MagicMock(return_value=slow_llm())
    tts = AsyncMock()
    conversation = Conversation()

    async def collect():
        return [event async for event in WebChatService(llm, tts).stream(
            "问题", conversation, interrupt=interrupt
        )]

    consumer = asyncio.create_task(collect())
    await asyncio.sleep(0.05)  # 已进入 token 循环、还什么都没说
    interrupt.set()
    release.set()
    rest = await asyncio.wait_for(consumer, timeout=1)

    assert [event["type"] for event in rest] == ["timing", "interrupted"]
    assert conversation.get_messages() == []


@pytest.mark.asyncio
async def test_web_stale_interrupt_flag_is_cleared_at_turn_start():
    llm = AsyncMock()
    llm.stream_chat = MagicMock(return_value=_async_iter(["正常回复。"]))
    tts = AsyncMock()
    tts.synthesize = AsyncMock(return_value=b"wav")
    interrupt = asyncio.Event()
    interrupt.set()  # 上一轮残留的让路信号
    conversation = Conversation()

    events = [
        event
        async for event in WebChatService(llm, tts).stream("问题", conversation, interrupt=interrupt)
    ]

    assert events[-1] == {"type": "done"}
    assert conversation.get_messages()[-1]["content"] == "正常回复。"


@pytest.mark.asyncio
async def test_interrupt_endpoint_stops_active_stream_via_http():
    class SlowService:
        def __init__(self):
            self.first_sentence = asyncio.Event()
            self.release = asyncio.Event()
            self.conversation = None

        async def stream(self, message, conversation, *, interrupt=None):
            self.conversation = conversation
            conversation.add_user_message(message)
            yield {"type": "sentence", "text": "第一句。"}
            self.first_sentence.set()
            while interrupt is None or not interrupt.is_set():
                await asyncio.sleep(0.01)
            conversation.add_assistant_message("第一句。")
            yield {"type": "interrupted"}

    service = SlowService()
    transport = httpx.ASGITransport(app=create_app(service))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        chat = asyncio.create_task(
            client.post(
                "/api/chat",
                json={"message": "你好", "session_id": "s"},
            )
        )
        await asyncio.wait_for(service.first_sentence.wait(), timeout=1)

        unknown = await client.post(
            "/api/interrupt", json={"session_id": "not-exist"}
        )
        assert unknown.status_code == 200

        hit = await client.post("/api/interrupt", json={"session_id": "s"})
        assert hit.status_code == 200
        response = await asyncio.wait_for(chat, timeout=1)

    assert response.status_code == 200
    assert '"type": "interrupted"' in response.text
    assert service.conversation.get_messages() == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "第一句。"},
    ]


@pytest.mark.asyncio
async def test_closing_web_stream_mid_response_rolls_back_pending_user():
    llm = AsyncMock()
    llm.stream_chat = MagicMock(
        return_value=_async_iter(["第一句话。", "第二句话。"])
    )
    tts = AsyncMock()
    conversation = Conversation()

    stream = WebChatService(llm, tts).stream("问题", conversation)
    assert (await anext(stream))["type"] == "performance"
    assert await anext(stream) == {"type": "sentence", "text": "第一句话。"}
    await stream.aclose()

    assert conversation.get_messages() == []


def test_index_serves_built_frontend_when_present(tmp_path):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from frontend.web import create_app

    page = tmp_path / "index.html"
    page.write_text('<title>AI 花音</title><div id="root"></div>', encoding="utf-8")
    client = TestClient(create_app(FakeService(), index_html=page))
    response = client.get("/")
    assert response.status_code == 200
    assert "AI 花音" in response.text
    assert '<div id="root">' in response.text


def test_index_missing_frontend_returns_build_hint():
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from frontend.web import create_app

    client = TestClient(
        create_app(FakeService(), index_html=Path("/nonexistent/index.html"))
    )
    response = client.get("/")
    assert response.status_code == 503
    assert "npm run build" in response.text


def test_frontend_src_references_api_paths():
    src_root = Path(__file__).resolve().parents[1] / "frontend" / "src"
    if not src_root.is_dir():
        pytest.skip("frontend/src 尚未创建")
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(src_root.rglob("*.ts")) + sorted(src_root.rglob("*.tsx"))
    )
    for endpoint in ("/api/chat", "/api/transcribe", "/api/reset", "/api/interrupt", "/healthz"):
        assert endpoint in sources, f"前端源码未引用 {endpoint}"


def _config_yaml() -> str:
    return """
llm:
  api_key: key
  base_url: https://example.test
  model: model
tts:
  base_url: http://localhost:5000
"""


@pytest.mark.asyncio
async def test_default_service_passes_llm_settings_from_config(tmp_path):
    from openai import AsyncOpenAI

    from config import load_config
    from dialogue.llm_client import LLMClient
    from frontend.web import _default_service

    path = tmp_path / "config.yaml"
    path.write_text(_config_yaml(), encoding="utf-8")

    service = _default_service(load_config(str(path)))

    assert isinstance(service._llm, LLMClient)
    assert service._llm._model == "model"
    assert service._llm._temperature == 0.8
    assert service._llm._max_tokens == 400
    assert isinstance(service._llm._client, AsyncOpenAI)
    await service._llm.aclose()


def test_cli_does_not_pass_legacy_protocol():
    cli_path = Path(__file__).resolve().parents[1] / "frontend" / "cli.py"
    source = cli_path.read_text(encoding="utf-8")
    assert "protocol=" not in source
    assert "frequency_penalty" not in source


def test_create_app_lifespan_closes_llm_client(tmp_path):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from openai import AsyncOpenAI

    from config import load_config
    from frontend.web import _default_service, create_app

    path = tmp_path / "config.yaml"
    path.write_text(_config_yaml(), encoding="utf-8")
    service = _default_service(load_config(str(path)))
    client = service._llm._client
    assert isinstance(client, AsyncOpenAI)
    assert client.is_closed() is False

    with TestClient(create_app(service)) as test_client:
        assert test_client.get("/healthz").status_code == 200

    assert client.is_closed() is True
