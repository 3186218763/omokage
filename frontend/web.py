"""本地 Web 对话入口。

FastAPI 和 Uvicorn 只在启动 Web 时加载，数据管线和单元测试不需要 Web 运行时依赖。
"""

import asyncio
import base64
import json
import logging
import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from frontend.playback import PlaybackLedger
from frontend.audio_codec import encode_audio

from config import MAX_TTS_PREFETCH_DEPTH, AppConfig, load_config
from dialogue.asr_client import WhisperTranscriber
from dialogue.conversation import Conversation
from dialogue.jev_client import JevClient
from dialogue.llm_client import LLMClient
from dialogue.context_builder import ContextBuilder
from dialogue.performance import from_speaking_style
from dialogue.sentence_pipeline import SentencePipeline
from dialogue.session_store import SessionStore
from dialogue.speech_text import normalize_speech_text
from dialogue.tts_api import parse_tts_request
from dialogue.tts_client import TTSClient
from dialogue.turn import Turn, TurnRequest, TurnStatus
from frontend.turn_timing import TurnTiming, install_timing_log_file
from scripts.check_live2d_assets import DEFAULT_LIVE2D_ROOT, assess


PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)
WEB_HTML = PROJECT_ROOT / "frontend" / "dist" / "index.html"
WEB_ASSETS_DIR = PROJECT_ROOT / "frontend" / "dist" / "assets"
WEB_HINT_HTML = (
    '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
    "<title>AI 花音</title></head>"
    '<body style="background:#101416;color:#f1ece7;font:15px system-ui;'
    'display:grid;place-items:center;min-height:100vh">'
    "<p>Web 前端未构建，请先运行："
    "<code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code></p>"
    "</body></html>"
)
MAX_MESSAGE_CHARS = 2000
MAX_SESSION_ID_CHARS = 64
MAX_AUDIO_UPLOAD_BYTES = 15 * 1024 * 1024
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
AUDIO_SUFFIXES = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".mp4",
    "audio/mpeg": ".mp3",
}


@dataclass
class _SessionState:
    conversation: Conversation
    lock: asyncio.Lock
    playback: PlaybackLedger | None = None
    reservations: int = 0
    interrupt: asyncio.Event = field(default_factory=asyncio.Event)
    pending_memory_text: str | None = None
    pending_memory_turn_id: str | None = None
    generation: int = 0
    active_turn: Turn | None = None


def parse_session_id(payload: Mapping[str, Any]) -> str:
    """Validate and normalize a session_id (chat / reset / interrupt 共用)."""
    session_id = payload.get("session_id", "default")
    if not isinstance(session_id, str):
        raise ValueError("session_id must be a string")
    session_id = session_id.strip() or "default"
    if len(session_id) > MAX_SESSION_ID_CHARS or not SESSION_ID_RE.fullmatch(session_id):
        raise ValueError(
            "session_id must contain only letters, numbers, '-' or '_' "
            f"and be at most {MAX_SESSION_ID_CHARS} characters"
        )
    return session_id


def parse_chat_request(payload: Mapping[str, Any]) -> tuple[str, str]:
    """Validate and normalize a chat JSON body."""
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be a non-empty string")
    message = message.strip()
    if len(message) > MAX_MESSAGE_CHARS:
        raise ValueError(f"message must be at most {MAX_MESSAGE_CHARS} characters")
    return message, parse_session_id(payload)


def sse_event(payload: Mapping[str, Any]) -> str:
    """Encode one JSON event for a browser fetch reader."""
    return f"data: {json.dumps(dict(payload), ensure_ascii=False)}\n\n"


class LiveConversation:
    """Own one live turn: LLM, sentence timeline, Kev, TTS and cancellation."""

    def __init__(
        self,
        llm_client,
        tts_client,
        *,
        max_chars: int = 50,
        min_chars: int = 4,
        jev_client: JevClient | None = None,
        tts_prefetch_depth: int = 2,
        timing_event: bool = True,
        audio_encoding: str = "wav",
        audio_bitrate_kbps: int = 96,
    ):
        if not 1 <= tts_prefetch_depth <= MAX_TTS_PREFETCH_DEPTH:
            raise ValueError(
                f"tts_prefetch_depth must be between 1 and {MAX_TTS_PREFETCH_DEPTH}"
            )
        self._llm = llm_client
        self._tts = tts_client
        self._max_chars = max_chars
        self._min_chars = min_chars
        self._jev = jev_client
        self._tts_prefetch_depth = tts_prefetch_depth
        self._timing_event = timing_event
        self._audio_encoding = audio_encoding
        self._audio_bitrate_kbps = audio_bitrate_kbps

    async def stream(
        self,
        user_text: str,
        conversation: Conversation,
        *,
        interrupt: asyncio.Event | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """One scheduler owns all output; auxiliary tasks never block cancellation."""
        conversation.add_user_message(user_text)
        committed = False
        interrupted = False
        pending: list[tuple[int, asyncio.Task]] = []
        jev_task = None
        token_task = None
        prepare_task = None
        llm_stream = None
        signal = interrupt or asyncio.Event()
        signal.clear()
        interrupt_task = asyncio.create_task(signal.wait())
        timing = TurnTiming()
        spoken: list[str] = []
        ready_sentences: list = []  # SentencePipeline 产出、待派发 TTS 的句子
        pipeline = SentencePipeline(self._max_chars, min_chars=self._min_chars)
        performance_sent = False
        llm_done = False
        jev_started = False
        try:
            prepare_task = asyncio.create_task(ContextBuilder(self._llm).build(conversation))
            await asyncio.wait({prepare_task, interrupt_task}, return_when=asyncio.FIRST_COMPLETED)
            if not signal.is_set():
                llm_stream = self._llm.stream_chat(prepare_task.result()).__aiter__()
            while not signal.is_set():
                if pipeline.style_resolved and not performance_sent and (not llm_done or ready_sentences):
                    performance_sent = True
                    yield from_speaking_style(pipeline.style).as_event()
                if signal.is_set():
                    break
                if jev_task is not None and jev_task.done():
                    try:
                        decision = jev_task.result()
                    except Exception:
                        decision = None
                    jev_task = None
                    timing.mark("jev_done")
                    if decision is not None:
                        yield decision.as_event()
                    continue
                if ready_sentences and len(pending) < self._tts_prefetch_depth:
                    utterance = ready_sentences.pop(0)
                    index = len(spoken)
                    spoken.append(utterance.text)
                    timing.mark("first_sentence")
                    timing.sentences += 1
                    # Keep the motion on the sentence it annotates. The web
                    # protocol can then pair it with the same audio index
                    # without a separate "next motion" buffer.
                    sentence_event = {"type": "sentence", "text": utterance.text}
                    if utterance.motion is not None:
                        sentence_event["motion"] = utterance.motion
                    if utterance.pause_ms:
                        sentence_event["pause_ms"] = utterance.pause_ms
                    yield sentence_event
                    if signal.is_set():
                        break
                    pending.append((index, asyncio.create_task(self._synthesize_audio(utterance.text))))
                    if self._jev is not None and not jev_started:
                        jev_started = True
                        jev_task = asyncio.create_task(self._jev.ask_messages(
                            conversation.get_messages(), utterance.text))
                        timing.mark("jev_dispatch")
                    continue
                if pending and pending[0][1].done():
                    index, task = pending.pop(0)
                    yield await self._audio_event(task, index, timing)
                    continue
                if llm_done and not ready_sentences and not pending:
                    break  # Do not extend generation to wait for an auxiliary decision.
                if not llm_done and not ready_sentences and len(pending) < self._tts_prefetch_depth and token_task is None:
                    token_task = asyncio.create_task(anext(llm_stream))
                tasks = {interrupt_task}
                if token_task is not None:
                    tasks.add(token_task)
                if pending:
                    tasks.add(pending[0][1])
                if jev_task is not None:
                    tasks.add(jev_task)
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                if signal.is_set():
                    break
                if token_task is not None and token_task.done():
                    try:
                        token = token_task.result()
                    except StopAsyncIteration:
                        llm_done = True
                        ready_sentences.extend(pipeline.close())
                    else:
                        timing.mark("llm_first_token")
                        ready_sentences.extend(pipeline.feed(token))
                    token_task = None
            interrupted = signal.is_set()
            response = normalize_speech_text("".join(spoken))
            if response:
                conversation.add_assistant_message(response)
                committed = True
            elif not interrupted:
                raise RuntimeError("LLM returned an empty response")
            timing.interrupted = interrupted
            timing.log()
            if self._timing_event:
                yield timing.as_dict()
            yield {"type": "interrupted" if interrupted else "done"}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            timing.log()
            if self._timing_event:
                yield timing.as_dict()
            yield {"type": "error", "message": str(exc)}
        finally:
            for task in (prepare_task, token_task, jev_task, interrupt_task):
                await self._cancel_task(task)
            await self._cancel_pending(pending)
            if llm_stream is not None:
                with suppress(Exception):
                    await llm_stream.aclose()
            if not committed:
                conversation.rollback_last_user_message()

    async def aclose(self) -> None:
        """释放内部 LLM 连接池（热重载/退出不泄漏）；客户端无 aclose 时静默。"""
        for client in (self._llm, self._jev):
            close = getattr(client, "aclose", None)
            if callable(close):
                await close()

    async def _cancel_pending(self, pending: list[tuple[int, asyncio.Task]]) -> None:
        """让路/断连/出错：按序取消全部在飞 TTS，队列清空。"""
        while pending:
            _index, task = pending.pop(0)
            await self._cancel_task(task)

    async def _cancel_task(self, task) -> None:
        """取消并吞掉结果：音频与 Jev 决策都是可丢弃的辅助任务。"""
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task

    async def _synthesize_audio(self, sentence: str) -> tuple[bytes, str]:
        audio = await self._tts.synthesize(sentence)
        return await encode_audio(
            audio, encoding=self._audio_encoding,
            bitrate_kbps=self._audio_bitrate_kbps,
        )

    async def _audio_event(
        self, task, index: int, timing: TurnTiming
    ) -> dict[str, Any]:
        try:
            encoded, mime_type = await task
        except Exception as exc:
            return {"type": "audio_error", "message": str(exc), "index": index}
        timing.mark_audio()
        return {
            "type": "audio",
            "audio": base64.b64encode(encoded).decode("ascii"),
            "mime_type": mime_type,
            "index": index,
        }


# Compatibility name for CLI integrations and existing callers.
WebChatService = LiveConversation


def _default_service(config: AppConfig | None = None) -> WebChatService:
    config = config or load_config()
    return WebChatService(
        LLMClient(
            api_key=config.llm.api_key,
            base_url=config.llm.base_url,
            model=config.llm.model,
            temperature=config.llm.temperature,
            max_tokens=config.llm.max_tokens,
        ),
        TTSClient(base_url=config.tts.base_url, timeout=config.tts.timeout),
        max_chars=config.max_sentence_chars,
        min_chars=config.min_sentence_chars,
        tts_prefetch_depth=config.tts_prefetch_depth,
        timing_event=config.timing_event,
        audio_encoding=config.audio_encoding,
        audio_bitrate_kbps=config.audio_bitrate_kbps,
        jev_client=JevClient(
            enabled=config.jev.enabled,
            base_url=config.jev.base_url,
            api_key=config.jev.api_key,
            model=config.jev.model,
            timeout_seconds=config.jev.timeout_seconds,
            min_confidence=config.jev.min_confidence,
            fail_cooldown_seconds=config.jev.fail_cooldown_seconds,
        ),
    )


def _is_configured(value: str | None, placeholder: str) -> bool:
    return bool(value and value.strip() and value.strip() != placeholder)


def create_app(
    service: WebChatService | None = None,
    *,
    config: AppConfig | None = None,
    transcriber=None,
    max_sessions: int = 128,
    index_html: str | Path | None = None,
):
    """Create the FastAPI app and keep configuration/model loading explicit."""
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise RuntimeError(
            "Web 入口需要额外依赖，请运行：pip install -e '.[web]'"
        ) from exc

    if max_sessions < 1:
        raise ValueError("max_sessions must be positive")
    runtime_config = config
    if service is None and runtime_config is None:
        runtime_config = load_config()
    chat_service = service or _default_service(runtime_config)
    speech_transcriber = transcriber
    if speech_transcriber is None and runtime_config is not None:
        speech_transcriber = WhisperTranscriber(
            model_size=runtime_config.asr.model,
            device=runtime_config.asr.device,
            compute_type=runtime_config.asr.compute_type,
            beam_size=runtime_config.asr.beam_size,
        )
    max_audio_upload_bytes = MAX_AUDIO_UPLOAD_BYTES
    default_asr_language = "auto"
    if runtime_config is not None:
        max_audio_upload_bytes = max(
            1, int(runtime_config.asr.max_upload_mb * 1024 * 1024)
        )
        default_asr_language = runtime_config.asr.language
    @asynccontextmanager
    async def lifespan(app):
        """应用关闭时释放服务持有的连接池（热重载/退出不泄漏）。"""
        yield
        close = getattr(chat_service, "aclose", None)
        if callable(close):
            await close()

    app = FastAPI(title="AI 花音", version="0.1.0", lifespan=lifespan)
    if WEB_ASSETS_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_ASSETS_DIR), name="assets")
    live2d_root = DEFAULT_LIVE2D_ROOT
    live2d_model_dir = ""
    live2d_background = ""
    if runtime_config is not None:
        live2d_model_dir = runtime_config.live2d.model_dir
        live2d_background = runtime_config.live2d.background
    live2d_status = assess(live2d_root, live2d_model_dir, live2d_background)
    if live2d_root.is_dir():
        app.mount("/live2d", StaticFiles(directory=live2d_root), name="live2d")
    sessions: dict[str, _SessionState] = {}
    session_store = (
        SessionStore(runtime_config.database_path)
        if runtime_config is not None and runtime_config.database_path
        else None
    )

    async def finalize_pending_memory(session_id: str, session: _SessionState) -> None:
        """Persist user memory only after this turn's audio has settled."""
        if session_store is None or session.pending_memory_text is None:
            return
        text = session.pending_memory_text
        try:
            messages = session.conversation.get_messages()
            source_seq = next(
                (i for i in range(len(messages) - 1, -1, -1) if messages[i]["role"] == "user"),
                None,
            )
            # SQLite 写入走线程，不占事件循环；失败不影响本轮对话。
            await asyncio.to_thread(
                session_store.remember_user_message,
                session_id,
                text,
                source_seq=source_seq,
            )
            session.pending_memory_text = None
            session.pending_memory_turn_id = None
        except Exception:
            logger.exception("Failed to remember user message for session %s", session_id)

    def evict_oldest_idle_session() -> bool:
        for candidate_id, candidate in tuple(sessions.items()):
            if (candidate.reservations == 0 and not candidate.lock.locked()
                    and candidate.pending_memory_text is None):
                sessions.pop(candidate_id)
                return True
        return False

    def trim_idle_sessions() -> None:
        while len(sessions) > max_sessions and evict_oldest_idle_session():
            pass

    def get_session(session_id: str) -> _SessionState:
        state = sessions.pop(session_id, None)
        if state is None:
            # Busy sessions may temporarily put the cache above its target;
            # preserving an active history is more important than a hard cap.
            while len(sessions) >= max_sessions and evict_oldest_idle_session():
                pass
            if runtime_config is not None:
                conversation = Conversation(
                    recent_turns=runtime_config.recent_turns,
                    summary_trigger_turns=runtime_config.summary_trigger_turns,
                    summary_trigger_chars=runtime_config.summary_trigger_chars,
                    summary_max_chars=runtime_config.summary_max_chars,
                )
            else:
                conversation = Conversation()
            state = _SessionState(conversation=conversation, lock=asyncio.Lock())
            if session_store is not None:
                snapshot = session_store.load(session_id)
                if snapshot is not None:
                    state.conversation.restore(snapshot)
        # Reinsert an existing session so insertion order acts as LRU order.
        sessions[session_id] = state
        return state

    @app.get("/", response_class=HTMLResponse)
    async def index():
        page = Path(index_html) if index_html is not None else WEB_HTML
        if not page.exists():
            return HTMLResponse(WEB_HINT_HTML, status_code=503)
        return page.read_text(encoding="utf-8")

    @app.get("/api/live2d")
    async def live2d_manifest():
        if not live2d_status.ready or live2d_status.model_url is None:
            return JSONResponse({"ready": False}, status_code=404)
        return {
            "ready": True,
            "model_url": live2d_status.model_url,
            "core_url": live2d_status.core_url,
            "background_url": live2d_status.background_url,
        }

    @app.get("/healthz")
    async def healthz():
        tts_available = None
        tts_checker = getattr(chat_service, "_tts", None)
        tts_checker = getattr(tts_checker, "check_available", None)
        if callable(tts_checker):
            try:
                await tts_checker()
            except Exception:
                tts_available = False
            else:
                tts_available = True
        return {
            "status": "ok",
            "service": "omokage",
            "llm_configured": bool(
                runtime_config
                and _is_configured(runtime_config.llm.api_key, "sk-your-deepseek-api-key")
            ),
            "tts_configured": bool(
                runtime_config and runtime_config.tts.base_url
            ),
            "tts_available": tts_available,
            "asr_configured": speech_transcriber is not None,
            "asr_available": bool(
                speech_transcriber
                and getattr(speech_transcriber, "available", True)
            ),
            "live2d_ready": live2d_status.ready,
            "jev_configured": bool(
                runtime_config
                and runtime_config.jev.enabled
                and _is_configured(runtime_config.jev.api_key, "")
            ),
        }

    @app.get("/api/history")
    async def history(session_id: str):
        try:
            parsed = parse_session_id({"session_id": session_id})
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        session = get_session(parsed)
        return {"messages": session.conversation.get_messages()}

    @app.post("/tts")
    async def tts(request: Request):
        """Locked-voice synthesis: body is ``{"text": "..."}`` only."""
        tts_client = getattr(chat_service, "_tts", None)
        synthesize = getattr(tts_client, "synthesize", None)
        if not callable(synthesize):
            return JSONResponse({"error": "TTS is not configured"}, status_code=503)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("JSON object required")
            text = parse_tts_request(payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        try:
            audio = await synthesize(text)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)
        return Response(content=audio, media_type="audio/wav")

    @app.post("/api/chat")
    async def chat(request: Request):
        try:
            payload = await request.json()
            message, session_id = parse_chat_request(payload)
            turn_id = payload.get("turn_id", str(uuid4()))
            if not isinstance(turn_id, str) or not SESSION_ID_RE.fullmatch(turn_id):
                raise ValueError("invalid turn_id")
            v2 = payload.get("v") == 2
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        session = get_session(session_id)
        if session_store is not None:
            session.conversation.user_memory_context = session_store.recall(session_id, message)
        # Reserve before StreamingResponse starts consuming the generator so
        # queued and in-flight sessions cannot be evicted in between.
        session.reservations += 1

        async def events():
            terminal_seen = False

            def storage_warning(message: str) -> str:
                warning = {"type": "storage_warning", "message": message}
                if v2:
                    warning.update(v=2, turn_id=turn_id)
                return sse_event(warning)

            def finalize_turn(event: dict, turn: Turn, ledger: PlaybackLedger) -> None:
                """done/interrupted：对账历史、收敛 ledger、落 turn 状态。"""
                history = session.conversation.get_messages()
                if (ledger.sentences and history and history[-1]["role"] == "assistant"
                        and history[-1]["content"] == "".join(ledger.sentences)):
                    ledger.committed_text = history[-1]["content"]
                if event["type"] == "interrupted":
                    ledger.cancel()
                ledger.trim(session.conversation)
                event["sentence_count"] = len(ledger.sentences)
                status = (
                    TurnStatus.INTERRUPTED
                    if event["type"] == "interrupted"
                    else TurnStatus.DONE
                )
                turn.finish(status, played_indices=ledger.settled)
                if session_store is not None:
                    session_store.finish_turn(
                        session_id, turn_id, status.value, ledger.settled
                    )

            def persist_history() -> str | None:
                """落盘本轮历史；失败时返回给用户的警告文案。"""
                if session_store is None:
                    return None
                try:
                    session_store.save(session_id, session.conversation)
                except Exception:
                    logger.exception("Failed to persist session %s", session_id)
                    return "本轮对话未保存，重启后可能丢失。"
                return None

            async def settle_memory(kind: str, ledger: PlaybackLedger | None) -> None:
                """done 后的用户记忆：无回执通道或音频全部确认才写，否则挂起等回执。"""
                history = session.conversation.get_messages()
                if not (kind == "done" and history and history[-1]["role"] == "assistant"):
                    return
                session.pending_memory_text = message
                session.pending_memory_turn_id = turn_id
                # v1 没有 /api/playback 回执通道；本轮无音频也不需要等。
                if ledger is None or not ledger.audio or ledger.audio.issubset(ledger.settled):
                    await finalize_pending_memory(session_id, session)

            try:
                async with session.lock:
                    session.generation += 1
                    turn = Turn(
                        TurnRequest(
                            session_id=session_id,
                            turn_id=turn_id,
                            user_text=message,
                            generation=session.generation,
                        )
                    )
                    session.active_turn = turn
                    if session_store is not None:
                        session_store.begin_turn(session_id, turn_id, session.generation, message)
                    if session.playback is not None:
                        session.playback.trim(session.conversation)
                    ledger = PlaybackLedger(turn_id) if v2 else None
                    session.playback = ledger
                    async for event in chat_service.stream(
                        message, session.conversation, interrupt=session.interrupt
                    ):
                        if not v2 and event["type"] == "sentence" and event.get("motion"):
                            # Keep the legacy unversioned stream shape for
                            # older clients; v2 carries the motion on its
                            # sentence so index pairing is explicit.
                            legacy_motion = event.pop("motion")
                            yield sse_event({"type": "motion", "motion": legacy_motion})
                        if ledger is not None:
                            event = dict(event, v=2, turn_id=turn_id)
                            kind = event["type"]
                            if kind == "sentence":
                                event["index"] = len(ledger.sentences)
                                event.setdefault("motion", None)
                                ledger.sentences.append(event["text"])
                            elif kind == "audio":
                                ledger.audio.add(event["index"])
                            elif kind == "performance":
                                event["revision"] = 0 if event["source"] == "speaking_style" else 1
                            elif kind in {"done", "interrupted"}:
                                finalize_turn(event, turn, ledger)
                        if event["type"] in {"done", "interrupted"}:
                            terminal_seen = True
                            warning = persist_history()
                            if warning is not None:
                                yield storage_warning(warning)
                            else:
                                await settle_memory(event["type"], ledger)
                        yield sse_event(event)
                    session.active_turn = None
                    if ledger is not None:
                        ledger.trim(session.conversation)
                    if not terminal_seen:
                        # 流没给终止事件（中途异常退出）：补落历史并标 FAILED。
                        if session_store is not None:
                            try:
                                session_store.save(session_id, session.conversation)
                            except Exception:
                                logger.exception(
                                    "Failed to persist session %s after stream exit",
                                    session_id,
                                )
                        turn.finish(TurnStatus.FAILED)
                        if session_store is not None:
                            session_store.finish_turn(
                                session_id, turn_id, TurnStatus.FAILED.value, set()
                            )
            finally:
                session.reservations -= 1
                trim_idle_sessions()

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/interrupt")
    async def interrupt(request: Request):
        """让路：用户开口/点击时停掉该会话正在说的话。

        不抢会话锁（否则会排在她后面）；没人在说话就当无事发生。
        """
        try:
            payload = await request.json()
            session_id = parse_session_id(payload)
        except (ValueError, TypeError, AttributeError, json.JSONDecodeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        session = sessions.get(session_id)
        if session is not None:
            ledger = session.playback
            requested_turn = payload.get("turn_id")
            if requested_turn is not None and (ledger is None or ledger.turn_id != requested_turn):
                return {"status": "stale"}
            if ledger is not None:
                highest = payload.get("highest_started")
                if highest is not None and (type(highest) is not int or highest < -1):
                    return JSONResponse({"error": "invalid highest_started"}, status_code=400)
                try:
                    indices = payload.get("started_indices")
                    if indices is not None and not isinstance(indices, list):
                        raise ValueError("invalid started_indices")
                    ledger.cancel(highest, indices)
                except ValueError as exc:
                    return JSONResponse({"error": str(exc)}, status_code=400)
            if session.lock.locked():
                session.interrupt.set()
            else:
                async with session.lock:
                    if ledger is not None:
                        ledger.trim(session.conversation)
                        if session_store is not None:
                            session_store.save(session_id, session.conversation)
        return {"status": "ok"}

    @app.post("/api/playback")
    async def playback(request: Request):
        try:
            payload = await request.json()
            session_id = parse_session_id(payload)
            index, seq, kind = payload.get("index"), payload.get("event_seq"), payload.get("kind")
            if type(index) is not int or index < 0 or type(seq) is not int or seq < 0 or kind not in {"started", "ended", "failed"}:
                raise ValueError("invalid playback acknowledgement")
            session = sessions.get(session_id)
            ledger = session.playback if session else None
            if ledger is None or ledger.turn_id != payload.get("turn_id"):
                return {"status": "stale"}
            # No await while changing the ledger: atomic with stream handling on this loop.
            ledger.acknowledge(index, seq, kind)
            if kind in {"ended", "failed"} and ledger.audio.issubset(ledger.settled):
                await finalize_pending_memory(session_id, session)
        except (ValueError, TypeError, AttributeError, json.JSONDecodeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return {"status": "ok"}

    @app.post("/api/transcribe")
    async def transcribe_audio(request: Request, language: str | None = None):
        if speech_transcriber is None:
            return JSONResponse(
                {"error": "ASR is not configured"},
                status_code=503,
            )
        media_type = request.headers.get("content-type", "").partition(";")[0].lower()
        suffix = AUDIO_SUFFIXES.get(media_type)
        if suffix is None:
            return JSONResponse(
                {"error": "content-type must be a supported audio format"},
                status_code=400,
            )
        try:
            declared_length = int(request.headers.get("content-length", "0"))
        except ValueError:
            declared_length = 0
        if declared_length > max_audio_upload_bytes:
            return JSONResponse(
                {"error": "audio upload exceeds the configured limit"},
                status_code=413,
            )
        audio = await request.body()
        if not audio:
            return JSONResponse({"error": "audio must not be empty"}, status_code=400)
        if len(audio) > max_audio_upload_bytes:
            return JSONResponse(
                {"error": "audio upload exceeds the configured limit"},
                status_code=413,
            )
        language = language or default_asr_language
        if language not in {None, "", "auto", "zh", "ja", "en"}:
            return JSONResponse({"error": "unsupported language"}, status_code=400)
        try:
            result = await speech_transcriber.transcribe(
                audio,
                filename=f"recording{suffix}",
                language=language,
            )
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=503)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"transcription failed: {exc}"}, status_code=500)
        if not str(result.get("text") or "").strip():
            return JSONResponse({"error": "no speech recognized"}, status_code=422)
        return result

    @app.post("/api/reset")
    async def reset(request: Request):
        try:
            payload = await request.json()
            session_id = parse_session_id(payload)
        except (ValueError, TypeError, AttributeError, json.JSONDecodeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        session = sessions.get(session_id)
        if session is not None:
            session.reservations += 1
            try:
                async with session.lock:
                    session.conversation.clear()
                    session.playback = None
            finally:
                session.reservations -= 1
                trim_idle_sessions()
        if session_store is not None:
            session_store.delete(session_id)
        return {"status": "ok"}

    @app.get("/api/memories")
    async def list_memories(session_id: str):
        if session_store is None:
            return {"enabled": False, "memories": []}
        try:
            parsed = parse_session_id({"session_id": session_id})
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return {
            "enabled": session_store.memory_enabled(parsed),
            "memories": session_store.list_memories(parsed),
        }

    @app.put("/api/memories")
    async def set_memories(request: Request):
        if session_store is None:
            return JSONResponse({"error": "session storage is disabled"}, status_code=503)
        try:
            payload = await request.json()
            session_id = parse_session_id(payload)
            enabled = payload.get("enabled")
            if type(enabled) is not bool:
                raise ValueError("enabled must be a boolean")
        except (ValueError, TypeError, AttributeError, json.JSONDecodeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        session_store.set_memory_enabled(session_id, enabled)
        return {"enabled": enabled, "memories": session_store.list_memories(session_id)}

    @app.delete("/api/memories/{memory_id}")
    async def delete_memory(memory_id: int, session_id: str):
        if session_store is None:
            return JSONResponse({"error": "session storage is disabled"}, status_code=503)
        try:
            parsed = parse_session_id({"session_id": session_id})
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        session_store.delete_memory(parsed, memory_id)
        return {"status": "ok"}

    return app


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Start the AI Huayin web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    runtime_config = load_config()
    if runtime_config.database_path and args.host not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("会话落盘时仅允许本机监听；局域网部署请先配置访问鉴权或关闭 conversation.database_path")
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("Web 入口需要额外依赖，请运行：pip install -e '.[web]'") from exc
    install_timing_log_file(PROJECT_ROOT / "logs")
    uvicorn.run(create_app(config=runtime_config), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
