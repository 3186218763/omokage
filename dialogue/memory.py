"""Shared rolling-memory preparation for CLI and Web conversations."""

from __future__ import annotations

from datetime import datetime

from .conversation import Conversation
from .persona import get_system_prompt
from .persona_context import build_persona_context


def _today_line() -> str:
    """系统提示末尾的日期锚点（一天内字节级不变，不击穿前缀缓存）。"""
    now = datetime.now()
    weekday = "一二三四五六日"[now.weekday()]
    return f"今天是{now.strftime('%Y-%m-%d')} 星期{weekday}。"


def _with_time(message: dict[str, str], hhmm: str | None) -> dict[str, str]:
    """给单条消息加 [HH:MM] 前缀；无时间戳时返回等值副本。"""
    if not hhmm:
        return dict(message)
    return {**message, "content": f"[{hhmm}] {message['content']}"}


def _prefixed(messages: list[dict[str, str]], times: list[str]) -> list[dict[str, str]]:
    """逐条消息加 [HH:MM] 前缀；时间与消息数量不齐时原样返回（防御旧会话）。"""
    if len(times) != len(messages):
        return [dict(message) for message in messages]
    return [
        _with_time(message, hhmm)
        for message, hhmm in zip(messages, times, strict=True)
    ]


async def compact_conversation(llm_client, conversation: Conversation) -> bool:
    """Compact old complete turns when supported, degrading safely on failure."""
    plan = conversation.plan_compaction()
    if plan is None:
        return False
    summarize = getattr(llm_client, "summarize_chat", None)
    if not callable(summarize):
        return False
    try:
        summary = await summarize(
            previous_summary=plan.previous_summary,
            # 摘要输入同样带时间前缀：压缩时保留「那晚/上午」级别的时间感
            messages=_prefixed(
                plan.messages(), conversation.message_times[: len(plan.prefix)]
            ),
            max_chars=conversation.summary_max_chars,
        )
    except Exception:
        # Memory maintenance is auxiliary. The full raw history remains intact
        # and the main response can still proceed when summarization is down.
        return False
    return conversation.apply_compaction(plan, summary)


def _last_user_text(conversation: Conversation) -> str | None:
    """回扫取最后一条 role=user 消息（容忍尾消息为 assistant 的补答/重试场景）；空会话返回 None。"""
    for message in reversed(conversation.get_messages()):
        if message["role"] == "user":
            return message["content"]
    return None


async def prepare_chat_messages(
    llm_client, conversation: Conversation
) -> list[dict[str, str]]:
    """Compact if needed, then build the ordered model context."""
    await compact_conversation(llm_client, conversation)
    messages = [
        {
            "role": "system",
            # 日期锚点追加在人设之后：她知道「今天」是哪天（时间感知，KV-cache 友好）
            "content": f"{get_system_prompt()}\n\n{_today_line()}",
        }
    ]
    messages.extend(build_persona_context(_last_user_text(conversation)))
    time_iter = iter(conversation.message_times)
    for message in conversation.get_context_messages():
        if message["role"] == "system":
            messages.append(message)  # 压缩记忆等 system 段不带时间前缀
            continue
        messages.append(_with_time(message, next(time_iter, None)))
    return messages
