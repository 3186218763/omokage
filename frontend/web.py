"""本地 Web 对话入口。

FastAPI 和 Uvicorn 只在启动 Web 时加载，数据管线和单元测试不需要 Web 运行时依赖。
"""

import asyncio
import base64
import json
import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import AppConfig, load_config
from dialogue.asr_client import WhisperTranscriber
from dialogue.conversation import Conversation
from dialogue.jev_client import JevClient
from dialogue.llm_client import LLMClient
from dialogue.memory import prepare_chat_messages
from dialogue.motion import MotionPolicy
from dialogue.performance import from_speaking_style
from dialogue.sentence_streamer import SentenceStreamer
from dialogue.speaking_style import SpeakingStyleRefBank, StylePrefixParser
from dialogue.speech_text import normalize_speech_text, strip_style_for_history
from dialogue.tts_api import parse_tts_request
from dialogue.tts_client import TTSClient
from scripts.check_live2d_assets import DEFAULT_LIVE2D_ROOT, assess


PROJECT_ROOT = Path(__file__).resolve().parents[1]
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
    reservations: int = 0
    interrupt: asyncio.Event = field(default_factory=asyncio.Event)


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


class WebChatService:
    """Stream sentence and audio events while keeping one conversation history."""

    def __init__(
        self,
        llm_client,
        tts_client,
        *,
        max_chars: int = 50,
        min_chars: int = 4,
        style_ref_bank: SpeakingStyleRefBank | None = None,
        jev_client: JevClient | None = None,
    ):
        self._llm = llm_client
        self._tts = tts_client
        self._max_chars = max_chars
        self._min_chars = min_chars
        self._style_bank = style_ref_bank or SpeakingStyleRefBank()
        self._jev = jev_client

    async def stream(
        self,
        user_text: str,
        conversation: Conversation,
        *,
        interrupt: asyncio.Event | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream events for one turn; honor the interrupt signal.

        让路（interrupt 置位）：停 LLM 流、取消未送达的音频，已说出的句子
        作为部分 assistant 消息进历史并发 ``interrupted`` 事件收尾。
        断连（CancelledError）仍整轮回滚——两者语义不同。
        """
        conversation.add_user_message(user_text)
        committed = False
        interrupted = False
        pending_audio = None
        jev_task: asyncio.Task | None = None

        def hit() -> bool:
            return interrupt is not None and interrupt.is_set()

        if interrupt is not None:
            interrupt.clear()  # 清掉上一轮可能残留的让路信号
        try:
            try:
                messages = await prepare_chat_messages(self._llm, conversation)
                streamer = SentenceStreamer(
                    self._max_chars, min_chars=self._min_chars
                )
                style_parser = StylePrefixParser()
                motion_policy = MotionPolicy()
                full_speech = ""
                spoken: list[str] = []
                ref_kwargs: dict[str, str] = {}
                performance_sent = False

                def take_performance() -> dict[str, Any] | None:
                    nonlocal performance_sent
                    if performance_sent or not style_parser.resolved:
                        return None
                    performance_sent = True
                    return from_speaking_style(style_parser.style).as_event()

                async for token in self._llm.stream_chat(messages):
                    if hit():
                        interrupted = True
                        break
                    speech_chunk = style_parser.feed(token)
                    performance = take_performance()
                    if performance is not None:
                        yield performance
                    if style_parser.resolved and not ref_kwargs:
                        clip = self._style_bank.resolve(style_parser.style)
                        if clip is not None:
                            ref_kwargs = {
                                "ref_audio_path": clip.audio_path,
                                "ref_text": clip.prompt_text,
                                "ref_language": clip.prompt_lang,
                            }
                    if not speech_chunk:
                        continue
                    full_speech += speech_chunk
                    for raw_sentence in streamer.add_token(speech_chunk):
                        motion, stripped = motion_policy.take(raw_sentence)
                        sentence = normalize_speech_text(stripped)
                        if not sentence:
                            continue
                        spoken.append(sentence)
                        if pending_audio is not None:
                            yield await self._audio_event(pending_audio)
                        if motion is not None:
                            yield {"type": "motion", "motion": motion}
                        yield {"type": "sentence", "text": sentence}
                        pending_audio = asyncio.create_task(
                            self._tts.synthesize(sentence, **ref_kwargs)
                        )
                        if hit():
                            interrupted = True
                            break
                    if interrupted:
                        break

                jev_decision = None
                if not interrupted:
                    tail = style_parser.flush()
                    performance = take_performance()
                    if performance is not None and (full_speech or tail):
                        yield performance
                    if tail:
                        full_speech += tail
                        for raw_sentence in streamer.add_token(tail):
                            motion, stripped = motion_policy.take(raw_sentence)
                            sentence = normalize_speech_text(stripped)
                            if not sentence:
                                continue
                            spoken.append(sentence)
                            if pending_audio is not None:
                                yield await self._audio_event(pending_audio)
                            if motion is not None:
                                yield {"type": "motion", "motion": motion}
                            yield {"type": "sentence", "text": sentence}
                            pending_audio = asyncio.create_task(
                                self._tts.synthesize(sentence, **ref_kwargs)
                            )

                    remaining = streamer.flush()
                    if remaining:
                        motion, stripped = motion_policy.take(remaining)
                        sentence = normalize_speech_text(stripped)
                        if sentence:
                            spoken.append(sentence)
                            if pending_audio is not None:
                                yield await self._audio_event(pending_audio)
                            if motion is not None:
                                yield {"type": "motion", "motion": motion}
                            yield {"type": "sentence", "text": sentence}
                            pending_audio = asyncio.create_task(
                                self._tts.synthesize(sentence, **ref_kwargs)
                            )
                    normalized_response = normalize_speech_text(
                        strip_style_for_history(full_speech)
                    )
                    if normalized_response is None:
                        raise RuntimeError("LLM returned an empty response")
                    if self._jev is not None:
                        history = [dict(item) for item in conversation.get_messages()]
                        jev_task = asyncio.create_task(
                            self._jev.ask_messages(history, normalized_response)
                        )
                    if pending_audio is not None:
                        yield await self._audio_event(pending_audio)
                        pending_audio = None
                    if jev_task is not None:
                        try:
                            jev_decision = await jev_task
                        except Exception:
                            jev_decision = None
                        jev_task = None
                else:
                    await self._cancel_audio(pending_audio)
                    pending_audio = None
            except asyncio.CancelledError:
                if jev_task is not None:
                    jev_task.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await jev_task
                await self._cancel_audio(pending_audio)
                raise
            except Exception as exc:
                if jev_task is not None:
                    jev_task.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await jev_task
                await self._cancel_audio(pending_audio)
                yield {"type": "error", "message": str(exc)}
                return

            if interrupted:
                # 「已播出」的工程近似 = 已作为 sentence 事件送出的句子；
                # 末句音频可能尚未送达即被让路，历史按半截台词记
                partial = normalize_speech_text("".join(spoken))
                if partial is not None:
                    conversation.add_assistant_message(partial)
                    committed = True
                yield {"type": "interrupted"}
                return

            conversation.add_assistant_message(normalized_response)
            committed = True
            if jev_decision is not None:
                yield jev_decision.as_event()
            yield {"type": "done"}
        finally:
            if not committed:
                conversation.rollback_last_user_message()

    async def _cancel_audio(self, task) -> None:
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task

    async def _audio_event(self, task) -> dict[str, str]:
        try:
            audio = await task
        except Exception as exc:
            return {"type": "audio_error", "message": str(exc)}
        return {"type": "audio", "audio": base64.b64encode(audio).decode("ascii")}


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
        """应用关闭时释放内部创建的 LLM 客户端连接池(热重载/退出不泄漏)。"""
        yield
        llm = getattr(chat_service, "_llm", None)
        close = getattr(llm, "aclose", None)
        if callable(close):
            await close()

    app = FastAPI(title="AI 花音", version="0.1.0", lifespan=lifespan)
    if WEB_ASSETS_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_ASSETS_DIR), name="assets")
    live2d_root = DEFAULT_LIVE2D_ROOT
    live2d_model_dir = ""
    if runtime_config is not None:
        live2d_model_dir = runtime_config.live2d.model_dir
    live2d_status = assess(live2d_root, live2d_model_dir)
    if live2d_root.is_dir():
        app.mount("/live2d", StaticFiles(directory=live2d_root), name="live2d")
    sessions: dict[str, _SessionState] = {}

    def evict_oldest_idle_session() -> bool:
        for candidate_id, candidate in tuple(sessions.items()):
            if candidate.reservations == 0 and not candidate.lock.locked():
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
            while len(sessions) >= max_sessions:
                if not evict_oldest_idle_session():
                    break
            state = _SessionState(
                conversation=Conversation(
                    recent_turns=(runtime_config.max_turns if runtime_config else 8),
                    summary_trigger_turns=(
                        runtime_config.summary_trigger_turns
                        if runtime_config
                        else 12
                    ),
                    summary_trigger_chars=(
                        runtime_config.summary_trigger_chars
                        if runtime_config
                        else 12_000
                    ),
                    summary_max_chars=(
                        runtime_config.summary_max_chars
                        if runtime_config
                        else 1_800
                    ),
                ),
                lock=asyncio.Lock(),
            )
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
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        session = get_session(session_id)
        # Reserve before StreamingResponse starts consuming the generator so
        # queued and in-flight sessions cannot be evicted in between.
        session.reservations += 1

        async def events():
            try:
                async with session.lock:
                    async for event in chat_service.stream(
                        message, session.conversation, interrupt=session.interrupt
                    ):
                        yield sse_event(event)
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
        if session is not None and session.lock.locked():
            session.interrupt.set()
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
            finally:
                session.reservations -= 1
                trim_idle_sessions()
        return {"status": "ok"}

    return app


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Start the AI Huayin web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("Web 入口需要额外依赖，请运行：pip install -e '.[web]'") from exc
    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
