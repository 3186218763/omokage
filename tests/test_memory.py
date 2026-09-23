from unittest.mock import AsyncMock

import pytest

from dialogue.conversation import Conversation
from dialogue.memory import compact_conversation, prepare_chat_messages


def _time() -> str:
    return "12:34"


def add_turn(conversation: Conversation, index: int) -> None:
    conversation.add_user_message(f"user-{index}")
    conversation.add_assistant_message(f"assistant-{index}")


@pytest.mark.asyncio
async def test_prepare_messages_compacts_old_turns_and_injects_memory(monkeypatch):
    monkeypatch.setattr("dialogue.conversation._now_hhmm", _time)
    conversation = Conversation(
        recent_turns=2,
        summary_trigger_turns=3,
        summary_trigger_chars=10_000,
    )
    for index in range(4):
        add_turn(conversation, index)
    conversation.add_user_message("current")
    llm = AsyncMock()
    llm.summarize_chat = AsyncMock(return_value="用户早先讨论了0和1。")

    messages = await prepare_chat_messages(llm, conversation)

    llm.summarize_chat.assert_awaited_once()
    assert messages[0]["role"] == "system"
    assert "真白花音" in messages[0]["content"]
    # 注入段（facts/examples）位于人设卡与记忆之间，均为 system 角色
    memory_index = next(
        index
        for index, message in enumerate(messages)
        if "用户早先讨论了0和1" in message["content"]
    )
    assert memory_index >= 2, "旧实现（无注入）下 memory_index==1，此断言保证红阶段有效"
    assert all(message["role"] == "system" for message in messages[1:memory_index])
    # 时间感知：逐条原文带 [HH:MM] 前缀进 prompt，但不落历史存储
    assert [message["content"] for message in messages[memory_index + 1 :]] == [
        f"[{_time()}] user-2",
        f"[{_time()}] assistant-2",
        f"[{_time()}] user-3",
        f"[{_time()}] assistant-3",
        f"[{_time()}] current",
    ]
    assert conversation.get_messages()[-1]["content"] == "current"


@pytest.mark.asyncio
async def test_prepare_messages_appends_stable_date_anchor(monkeypatch):
    monkeypatch.setattr("dialogue.memory._today_line", lambda: "今天是2026-09-23 星期三。")
    conversation = Conversation()
    llm = AsyncMock()

    first = await prepare_chat_messages(llm, conversation)
    second = await prepare_chat_messages(llm, conversation)

    # 日期锚点在人设之后；同一天内两次组 prompt 的 system 字节级一致（前缀缓存友好）
    assert first[0]["content"].endswith("今天是2026-09-23 星期三。")
    assert "真白花音" in first[0]["content"]
    assert first[0]["content"] == second[0]["content"]

    monkeypatch.setattr("dialogue.memory._today_line", lambda: "今天是2026-09-24 星期四。")
    next_day = await prepare_chat_messages(llm, conversation)
    assert next_day[0]["content"].endswith("今天是2026-09-24 星期四。")


@pytest.mark.asyncio
async def test_prepare_messages_prefixes_times_but_never_summary_system(monkeypatch):
    monkeypatch.setattr("dialogue.conversation._now_hhmm", _time)
    conversation = Conversation(
        recent_turns=1,
        summary_trigger_turns=2,
        summary_trigger_chars=10_000,
    )
    for index in range(2):
        conversation.add_user_message(f"msg{index}")
        conversation.add_assistant_message(f"reply{index}")
    llm = AsyncMock()
    llm.summarize_chat = AsyncMock(return_value="早前聊了两轮。")
    await prepare_chat_messages(llm, conversation)
    conversation.add_user_message("current")

    messages = await prepare_chat_messages(llm, conversation)

    summary = next(m for m in messages if "<conversation_memory>" in m["content"])
    assert summary["content"].startswith("以下是较早对话的压缩记忆")
    assert "[12:34]" in messages[-1]["content"]


@pytest.mark.asyncio
async def test_summarize_input_carries_time_prefixes(monkeypatch):
    monkeypatch.setattr("dialogue.conversation._now_hhmm", _time)
    conversation = Conversation(
        recent_turns=1,
        summary_trigger_turns=2,
        summary_trigger_chars=10_000,
    )
    for index in range(2):
        conversation.add_user_message(f"msg{index}")
        conversation.add_assistant_message(f"reply{index}")
    captured: dict = {}

    class CapturingSummarizer:
        async def summarize_chat(self, *, previous_summary, messages, max_chars):
            captured["messages"] = messages
            return "早前聊了两轮。"

    await compact_conversation(CapturingSummarizer(), conversation)

    assert [m["content"] for m in captured["messages"]] == [
        "[12:34] msg0",
        "[12:34] reply0",
    ]


@pytest.mark.asyncio
async def test_empty_conversation_skips_persona_injection():
    conversation = Conversation(recent_turns=2, summary_trigger_turns=3)
    llm = AsyncMock()

    messages = await prepare_chat_messages(llm, conversation)

    assert len(messages) == 1
    assert messages[0]["role"] == "system"


@pytest.mark.asyncio
async def test_persona_context_uses_last_user_message():
    conversation = Conversation(recent_turns=2, summary_trigger_turns=3)
    conversation.add_user_message("为什么毕业")
    conversation.add_assistant_message("……")
    llm = AsyncMock()

    messages = await prepare_chat_messages(llm, conversation)

    facts = [m for m in messages if "<persona_facts>" in m["content"]]
    assert facts, "应基于最后一条 user 消息注入事实"
    assert "F012" in facts[0]["content"]


@pytest.mark.asyncio
async def test_summary_failure_keeps_raw_history_and_main_context():
    conversation = Conversation(
        recent_turns=1,
        summary_trigger_turns=2,
        summary_trigger_chars=10_000,
    )
    add_turn(conversation, 0)
    add_turn(conversation, 1)
    llm = AsyncMock()
    llm.summarize_chat = AsyncMock(side_effect=RuntimeError("summary offline"))

    compacted = await compact_conversation(llm, conversation)

    assert compacted is False
    assert len(conversation.get_messages()) == 4
    assert conversation.summary == ""


@pytest.mark.asyncio
async def test_missing_summarizer_degrades_without_losing_history():
    conversation = Conversation(
        recent_turns=1,
        summary_trigger_turns=2,
        summary_trigger_chars=10_000,
    )
    add_turn(conversation, 0)
    add_turn(conversation, 1)

    assert await compact_conversation(object(), conversation) is False
    assert len(conversation.get_messages()) == 4


@pytest.mark.asyncio
async def test_fifty_turns_keep_early_facts_in_summary_and_recent_raw_turns():
    conversation = Conversation(
        recent_turns=8,
        summary_trigger_turns=12,
        summary_trigger_chars=100_000,
        summary_max_chars=10_000,
    )

    class DeterministicSummarizer:
        async def summarize_chat(
            self, *, previous_summary, messages, max_chars
        ):
            archived_users = [
                message["content"]
                for message in messages
                if message["role"] == "user"
            ]
            return " | ".join(
                value for value in [previous_summary, *archived_users] if value
            )[:max_chars]

    llm = DeterministicSummarizer()
    for index in range(50):
        user_text = "我叫小明，喜欢爵士乐" if index == 0 else f"第{index}轮"
        conversation.add_user_message(user_text)
        await compact_conversation(llm, conversation)
        conversation.add_assistant_message(f"回复{index}")

    # Prepare one more in-flight turn after several rolling compactions.
    conversation.add_user_message("还记得我吗")
    await compact_conversation(llm, conversation)

    assert "我叫小明，喜欢爵士乐" in conversation.summary
    raw_messages = conversation.get_messages()
    # Compaction has hysteresis: the raw window grows from recent_turns up to
    # summary_trigger_turns - 1 before the next summary call.
    assert len(raw_messages) <= (12 - 1) * 2 + 1
    assert [message["content"] for message in raw_messages[-17:-1:2]] == [
        f"第{index}轮" for index in range(42, 50)
    ]
    assert raw_messages[-1]["content"] == "还记得我吗"
