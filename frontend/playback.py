"""Per-session playback ledger. Only the current turn can amend its history."""
from dataclasses import dataclass, field

from dialogue.conversation import Conversation


@dataclass
class PlaybackLedger:
    turn_id: str
    sentences: list[str] = field(default_factory=list)
    audio: set[int] = field(default_factory=set)
    started: set[int] = field(default_factory=set)
    event_seq: int = -1
    cancelled: bool = False
    committed_text: str | None = None

    def acknowledge(self, index: int, event_seq: int, kind: str) -> None:
        if self.cancelled or event_seq <= self.event_seq:
            return
        if index not in self.audio:
            raise ValueError("playback index was not sent as audio")
        self.event_seq = event_seq
        if kind in {"started", "ended"}:
            self.started.add(index)

    def cancel(self, highest_started: int | None = None, started_indices: list[int] | None = None) -> None:
        if self.cancelled:
            return
        if started_indices is not None:
            if any(type(i) is not int or i not in self.audio for i in started_indices):
                raise ValueError("playback index was not sent as audio")
            self.started = set(started_indices)
        elif highest_started is not None and highest_started >= 0:
            if highest_started not in self.audio:
                raise ValueError("playback index was not sent as audio")
            # Audio is delivered and played in order; failed synthesis has no audio entry.
            self.started.update(i for i in self.audio if i <= highest_started)
        self.cancelled = True

    def trim(self, conversation: Conversation) -> None:
        if self.cancelled and self.committed_text is not None:
            partial = "".join(text for i, text in enumerate(self.sentences) if i in self.started)
            conversation.replace_last_reply(self.committed_text, partial)
            self.committed_text = None
