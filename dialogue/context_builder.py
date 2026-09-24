"""ContextBuilder seam for the LLM context.

The implementation remains backed by the existing rolling-memory code while
callers stop knowing how persona, facts, user memory and summaries are joined.
"""

from __future__ import annotations

from .conversation import Conversation
from .memory import prepare_chat_messages


class ContextBuilder:
    """Deep interface for building an ordered, size-bounded LLM context."""

    def __init__(self, llm_client, *, max_chars: int = 24_000):
        self._llm = llm_client
        self._max_chars = max_chars

    async def build(self, conversation: Conversation) -> list[dict[str, str]]:
        messages = await prepare_chat_messages(self._llm, conversation)
        total = sum(len(message.get("content", "")) for message in messages)
        if total <= self._max_chars:
            return messages
        # Preserve the persona/system prefix and latest user input. Discard
        # oldest transcript entries first; user memory is already injected
        # before transcript and therefore survives longer than raw history.
        kept = list(messages)
        while len(kept) > 2 and total > self._max_chars:
            transcript_index = next(
                (i for i in range(1, len(kept) - 1) if kept[i].get("role") in {"user", "assistant"}),
                1,
            )
            total -= len(kept.pop(transcript_index).get("content", ""))
        return kept
