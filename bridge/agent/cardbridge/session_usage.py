from __future__ import annotations

import asyncio
import heapq
import json
import logging
import os
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .usage import TokenUsageStore


LOG = logging.getLogger("cardbridge.codex.sessions")
SESSION_POLL_SECONDS = 1.0
SESSION_DISCOVERY_SECONDS = 30.0
MAX_RECENT_SESSION_FILES = 32
MAX_SESSION_LINE_BYTES = 512 * 1024

_TOP_LEVEL_TYPE = re.compile(
    rb'^\s*\{\s*"timestamp"\s*:\s*"[^"]*"\s*,\s*"type"\s*:\s*'
    rb'"(session_meta|turn_context|event_msg)"'
)
_TOP_LEVEL_TIMESTAMP = re.compile(
    rb'^\s*\{\s*"timestamp"\s*:\s*"([^"]{1,64})"'
)
_SESSION_ID = re.compile(
    rb'"(?:session_id|id)"\s*:\s*"([A-Za-z0-9._:-]{1,128})"'
)
_TURN_ID = re.compile(rb'"turn_id"\s*:\s*"([A-Za-z0-9._:-]{1,128})"')
_TOKEN_COUNT_PAYLOAD = re.compile(
    rb'"payload"\s*:\s*\{\s*"type"\s*:\s*"token_count"'
)
_UUID_IN_STEM = re.compile(
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)


def default_sessions_dir() -> Path:
    configured = os.environ.get("CODEX_HOME")
    codex_root = Path(configured).expanduser() if configured else Path.home() / ".codex"
    return codex_root / "sessions"


def _timestamp_ms(value: object) -> int:
    if not isinstance(value, str) or not value:
        return 0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, int(parsed.timestamp() * 1000))


def _safe_id(match: re.Match[bytes] | None) -> str:
    if match is None:
        return ""
    return match.group(1).decode("ascii", errors="ignore")[:128]


def _usage_breakdown(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}

    def integer(key: str) -> int:
        raw = value.get(key)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return 0
        return max(0, int(raw))

    return {
        "total": integer("total_tokens"),
        "input": integer("input_tokens"),
        "cached_input": integer("cached_input_tokens"),
        "output": integer("output_tokens"),
        "reasoning_output": integer("reasoning_output_tokens"),
    }


@dataclass
class _SessionCursor:
    offset: int = 0
    observed_size: int = -1
    observed_mtime_ns: int = -1
    session_id: str = ""
    turn_id: str = ""
    discarding_oversized_line: bool = False


class CodexSessionUsageMonitor:
    """Tail privacy-safe usage counters from Codex session JSONL files.

    Only token_count records are JSON-decoded. Session and turn identifiers are
    extracted from bounded byte prefixes; response items, summaries, prompts,
    reasoning, tool arguments, and command output are never decoded or retained.
    """

    def __init__(
        self,
        store: TokenUsageStore,
        *,
        sessions_dir: Path | None = None,
        poll_seconds: float = SESSION_POLL_SECONDS,
        discovery_seconds: float = SESSION_DISCOVERY_SECONDS,
        max_recent_files: int = MAX_RECENT_SESSION_FILES,
    ) -> None:
        self.store = store
        self.sessions_dir = (sessions_dir or default_sessions_dir()).expanduser()
        self.poll_seconds = max(0.05, poll_seconds)
        self.discovery_seconds = max(self.poll_seconds, discovery_seconds)
        self.max_recent_files = max(8, max_recent_files)
        self._root = self.sessions_dir.resolve(strict=False)
        self._cursors: dict[Path, _SessionCursor] = {}
        self._recent_paths: set[Path] = set()
        self._app_paths: set[Path] = set()
        self._next_discovery = 0.0
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopping = False
        self._next_discovery = 0.0
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def track_threads(self, records: list[dict[str, Any]]) -> None:
        paths: set[Path] = set()
        for record in records:
            value = record.get("path")
            if not isinstance(value, str) or not value:
                continue
            path = self._safe_session_path(Path(value))
            if path is not None:
                paths.add(path)
        if paths != self._app_paths:
            self._app_paths = paths
            self._wake.set()

    async def scan_once(self, *, force_discovery: bool = False) -> int:
        loop = asyncio.get_running_loop()
        now = loop.time()
        if force_discovery or now >= self._next_discovery:
            self._recent_paths = set(await asyncio.to_thread(self._discover_recent))
            self._next_discovery = now + self.discovery_seconds

        paths = self._recent_paths | self._app_paths
        for stale_path in self._cursors.keys() - paths:
            self._cursors.pop(stale_path, None)
        notifications = await asyncio.to_thread(self._read_paths, paths)
        changed = 0
        for notification in notifications:
            if self.store.update_notification(
                notification,
                source="codex_session_jsonl",
                cumulative_across_turns=True,
            ):
                changed += 1
        return changed

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOG.warning("Codex session usage scan failed: %s", type(exc).__name__)

            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass

    def _safe_session_path(self, candidate: Path) -> Path | None:
        if not candidate.is_absolute():
            candidate = self.sessions_dir / candidate
        resolved = candidate.expanduser().resolve(strict=False)
        if resolved.suffix != ".jsonl" or not resolved.is_relative_to(self._root):
            return None
        return resolved

    def _discover_recent(self) -> list[Path]:
        if not self.sessions_dir.is_dir():
            return []
        newest: list[tuple[int, str, Path]] = []
        try:
            candidates = self.sessions_dir.rglob("*.jsonl")
            for candidate in candidates:
                path = self._safe_session_path(candidate)
                if path is None:
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                item = (stat.st_mtime_ns, str(path), path)
                if len(newest) < self.max_recent_files:
                    heapq.heappush(newest, item)
                elif item[:2] > newest[0][:2]:
                    heapq.heapreplace(newest, item)
        except OSError:
            return []
        return [item[2] for item in sorted(newest)]

    def _read_paths(self, paths: set[Path]) -> list[dict[str, object]]:
        notifications: list[dict[str, object]] = []
        ordered: list[tuple[int, str, Path]] = []
        for path in paths:
            try:
                stat = path.stat()
            except OSError:
                continue
            ordered.append((stat.st_mtime_ns, str(path), path))
        for _, _, path in sorted(ordered):
            notifications.extend(self._read_path(path))
        return notifications

    def _read_path(self, path: Path) -> list[dict[str, object]]:
        cursor = self._cursors.setdefault(path, _SessionCursor())
        try:
            stat = path.stat()
        except OSError:
            return []
        if (
            stat.st_size == cursor.observed_size
            and stat.st_mtime_ns == cursor.observed_mtime_ns
        ):
            return []
        if stat.st_size < cursor.offset:
            cursor = _SessionCursor()
            self._cursors[path] = cursor

        recovered = deque(maxlen=2)
        try:
            with path.open("rb") as stream:
                stream.seek(cursor.offset)
                while True:
                    line_start = stream.tell()
                    raw = stream.readline(MAX_SESSION_LINE_BYTES + 1)
                    if not raw:
                        break

                    complete = raw.endswith(b"\n")
                    oversized = len(raw) > MAX_SESSION_LINE_BYTES and not complete
                    if cursor.discarding_oversized_line:
                        cursor.offset = stream.tell()
                        if complete:
                            cursor.discarding_oversized_line = False
                        continue

                    if oversized:
                        self._read_metadata_prefix(raw, cursor)
                        cursor.discarding_oversized_line = True
                        cursor.offset = stream.tell()
                        continue

                    if not complete:
                        stream.seek(line_start)
                        break

                    cursor.offset = stream.tell()
                    notification = self._read_complete_line(raw, path, cursor)
                    if notification is not None:
                        recovered.append(notification)
        except OSError:
            return []

        cursor.observed_size = stat.st_size
        cursor.observed_mtime_ns = stat.st_mtime_ns
        return list(recovered)

    def _read_metadata_prefix(self, raw: bytes, cursor: _SessionCursor) -> None:
        match = _TOP_LEVEL_TYPE.search(raw)
        if match is None:
            return
        kind = match.group(1)
        if kind == b"session_meta":
            session_id = _safe_id(_SESSION_ID.search(raw))
            if session_id:
                cursor.session_id = session_id
        elif kind == b"turn_context":
            turn_id = _safe_id(_TURN_ID.search(raw))
            if turn_id:
                cursor.turn_id = turn_id

    def _read_complete_line(
        self, raw: bytes, path: Path, cursor: _SessionCursor
    ) -> dict[str, object] | None:
        match = _TOP_LEVEL_TYPE.search(raw)
        if match is None:
            return None
        kind = match.group(1)
        if kind != b"event_msg":
            self._read_metadata_prefix(raw, cursor)
            return None
        if _TOKEN_COUNT_PAYLOAD.search(raw) is None:
            return None

        try:
            event = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        payload = event.get("payload") if isinstance(event, dict) else None
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            return None
        info = payload.get("info")
        if not isinstance(info, dict):
            return None
        total = _usage_breakdown(info.get("total_token_usage"))
        if total.get("total", 0) <= 0:
            return None
        last = _usage_breakdown(info.get("last_token_usage"))
        context = info.get("model_context_window")
        context_window = (
            max(0, int(context))
            if isinstance(context, (int, float)) and not isinstance(context, bool)
            else 0
        )

        session_id = cursor.session_id or self._session_id_from_path(path)
        if not session_id:
            return None
        timestamp_match = _TOP_LEVEL_TIMESTAMP.search(raw)
        timestamp = _timestamp_ms(
            timestamp_match.group(1).decode("ascii", errors="ignore")
            if timestamp_match is not None
            else event.get("timestamp")
        )
        return {
            "threadId": session_id,
            "turnId": cursor.turn_id,
            "timestamp_ms": timestamp,
            "tokenUsage": {
                "total": total,
                "last": last,
                "modelContextWindow": context_window,
            },
        }

    @staticmethod
    def _session_id_from_path(path: Path) -> str:
        match = _UUID_IN_STEM.search(path.stem)
        return match.group(1) if match is not None else path.stem[-128:]
