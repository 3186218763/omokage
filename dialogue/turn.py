"""领域级 Turn 类型。供应商适配器和 Web 层都只依赖这些稳定值。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic


class TurnStatus(StrEnum):
    ACTIVE = "active"
    DONE = "done"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


@dataclass(frozen=True)
class TurnRequest:
    session_id: str
    turn_id: str
    user_text: str
    generation: int


@dataclass
class Turn:
    request: TurnRequest
    status: TurnStatus = TurnStatus.ACTIVE
    started_at: float = field(default_factory=monotonic)
    finished_at: float | None = None
    spoken_sentences: list[str] = field(default_factory=list)
    played_indices: set[int] = field(default_factory=set)

    def finish(self, status: TurnStatus, *, played_indices: set[int] | None = None) -> None:
        self.status = status
        self.finished_at = monotonic()
        if played_indices is not None:
            self.played_indices = set(played_indices)
