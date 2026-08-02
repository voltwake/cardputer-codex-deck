from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable


BREAKDOWN_FIELDS = (
    "total",
    "input",
    "cached_input",
    "output",
    "reasoning_output",
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    return 0


def _field(mapping: dict[str, Any], camel: str, snake: str) -> int:
    return _integer(mapping.get(camel, mapping.get(snake)))


@dataclass(frozen=True)
class TokenBreakdown:
    total: int = 0
    input: int = 0
    cached_input: int = 0
    output: int = 0
    reasoning_output: int = 0

    @classmethod
    def from_mapping(cls, value: object) -> "TokenBreakdown":
        if not isinstance(value, dict):
            return cls()
        return cls(
            total=_field(value, "totalTokens", "total"),
            input=_field(value, "inputTokens", "input"),
            cached_input=_field(value, "cachedInputTokens", "cached_input"),
            output=_field(value, "outputTokens", "output"),
            reasoning_output=_field(
                value, "reasoningOutputTokens", "reasoning_output"
            ),
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "input": self.input,
            "cached_input": self.cached_input,
            "output": self.output,
            "reasoning_output": self.reasoning_output,
        }

    def non_decreasing_from(self, previous: "TokenBreakdown") -> bool:
        return all(
            getattr(self, field) >= getattr(previous, field)
            for field in BREAKDOWN_FIELDS
        )

    def subtract(self, previous: "TokenBreakdown") -> "TokenBreakdown":
        return TokenBreakdown(
            **{
                field: max(0, getattr(self, field) - getattr(previous, field))
                for field in BREAKDOWN_FIELDS
            }
        )


@dataclass
class TokenUsageSession:
    id: str
    turn_id: str
    total: TokenBreakdown
    last: TokenBreakdown
    model_context_window: int | None
    delta: TokenBreakdown
    window_ms: int
    tokens_per_second: float
    updated_at_ms: int

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "turn_id": self.turn_id,
            "total": self.total.as_dict(),
            "last": self.last.as_dict(),
            "delta": self.delta.as_dict(),
            "window_ms": self.window_ms,
            "tokens_per_second": self.tokens_per_second,
            "model_context_window": self.model_context_window,
        }


class TokenUsageStore:
    """Privacy-safe thread token accounting sourced only from App Server events."""

    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        self.available = False
        self.source = "unavailable"
        self.reason = "not_observed"
        self.updated_at_ms = 0
        self.sessions: dict[str, TokenUsageSession] = {}
        self._previous: dict[str, tuple[str, TokenBreakdown, int]] = {}
        self._on_change = on_change

    def set_on_change(self, callback: Callable[[], None] | None) -> None:
        self._on_change = callback

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()

    def set_unavailable(self, reason: str = "provider_unsupported") -> None:
        clean_reason = reason if reason else "unavailable"
        changed = (
            self.available
            or self.source != "unavailable"
            or self.reason != clean_reason
            or bool(self.sessions)
        )
        self.available = False
        self.source = "unavailable"
        self.reason = clean_reason
        self.updated_at_ms = _now_ms()
        self.sessions.clear()
        self._previous.clear()
        if changed:
            self._changed()

    def update_notification(self, params: dict[str, Any]) -> bool:
        thread_id = params.get("threadId")
        turn_id = params.get("turnId")
        raw_usage = params.get("tokenUsage")
        if not isinstance(thread_id, str) or not thread_id or not isinstance(raw_usage, dict):
            return False
        clean_thread_id = thread_id[:128]
        clean_turn_id = turn_id[:128] if isinstance(turn_id, str) else ""
        total = TokenBreakdown.from_mapping(raw_usage.get("total"))
        last = TokenBreakdown.from_mapping(raw_usage.get("last"))
        context = raw_usage.get("modelContextWindow")
        context_window = _integer(context) or None
        event_ms = _integer(
            params.get("timestamp_ms", params.get("timestamp"))
        ) or _now_ms()

        previous = self._previous.get(clean_thread_id)
        if (
            previous is not None
            and previous[0] == clean_turn_id
            and event_ms < previous[2]
        ):
            # App Server notifications can arrive after a newer event when
            # several turns are completing together. Do not move the
            # high-water mark backwards: doing so would make the next valid
            # cumulative update look like a larger delta than it really is.
            return False

        if (
            previous is not None
            and previous[0] == clean_turn_id
            and total.non_decreasing_from(previous[1])
        ):
            delta = total.subtract(previous[1])
            window_ms = max(0, event_ms - previous[2])
        else:
            # A new turn or a provider reset establishes a new baseline. Never
            # invent the pre-baseline count as a stream delta.
            delta = TokenBreakdown()
            window_ms = 0

        if previous is not None and previous[0] == clean_turn_id and total == previous[1]:
            # Duplicate notifications are harmless and do not create fake rate
            # spikes or unnecessary device broadcasts. Keep the original
            # timestamp so a later real delta measures the whole interval.
            return False

        rate = delta.total / (window_ms / 1000.0) if window_ms > 0 else 0.0
        record = TokenUsageSession(
            id=clean_thread_id,
            turn_id=clean_turn_id,
            total=total,
            last=last,
            model_context_window=context_window,
            delta=delta,
            window_ms=window_ms,
            tokens_per_second=round(max(0.0, rate), 3),
            updated_at_ms=event_ms,
        )
        self.sessions[clean_thread_id] = record
        self._previous[clean_thread_id] = (clean_turn_id, total, event_ms)
        self.available = True
        self.source = "codex_app_server"
        self.reason = ""
        self.updated_at_ms = max(self.updated_at_ms, event_ms)
        self._trim()
        self._changed()
        return True

    def _trim(self) -> None:
        if len(self.sessions) <= 8:
            return
        ordered = sorted(
            self.sessions.values(), key=lambda item: item.updated_at_ms, reverse=True
        )[:8]
        keep = {item.id for item in ordered}
        self.sessions = {key: value for key, value in self.sessions.items() if key in keep}
        self._previous = {
            key: value for key, value in self._previous.items() if key in keep
        }

    def snapshot(self, *, limit: int | None = None) -> dict[str, object]:
        result: dict[str, object] = {
            "available": self.available,
            "source": self.source,
            "updated_at_ms": self.updated_at_ms,
        }
        if not self.available:
            result["reason"] = self.reason
            result["sessions"] = []
            return result
        records = sorted(
            self.sessions.values(), key=lambda item: item.updated_at_ms, reverse=True
        )
        if limit is not None:
            records = records[: max(1, min(8, limit))]
        result["sessions"] = [record.as_dict() for record in records]
        return result
