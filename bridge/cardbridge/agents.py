from __future__ import annotations

import re
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


AGENT_LIMIT = 8
QUOTA_MODES = frozenset({"subscription", "api", "unknown"})
_SESSION_ID_CHAR_LIMIT = 64
_TITLE_CHAR_LIMIT = 32
_PROJECT_CHAR_LIMIT = 20
# Four 106 px device lines cannot usefully display more than this. Keeping the
# public excerpt to 72 UTF-8 bytes also guarantees eight worst-case CJK
# sessions fit the authenticated 4 KiB device protocol record.
_ACTIVITY_BYTE_LIMIT = 72
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|token|secret|password)\s*[:=]\s*\S+"
)
_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}")
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _timestamp_ms(value: object) -> int:
    if not isinstance(value, (int, float)):
        return 0
    timestamp = int(value)
    # App Server history timestamps are seconds; Hooks use milliseconds.
    return timestamp if timestamp >= 10_000_000_000 else timestamp * 1000


def _text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    value = " ".join(value.replace("\x00", "").split())
    return value[:limit]


def _bounded_utf8(value: str, byte_limit: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= byte_limit:
        return value
    suffix = "…"
    room = max(0, byte_limit - len(suffix.encode("utf-8")))
    return encoded[:room].decode("utf-8", errors="ignore").rstrip() + suffix


def public_activity_text(value: object) -> str:
    """Return a small public UI excerpt without commands, secrets, or CoT."""

    if not isinstance(value, str):
        return ""
    value = value.replace("\x00", "").replace("```", " ").replace("`", "")
    value = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=…", value)
    value = _BEARER_TOKEN.sub("Bearer …", value)
    value = _OPENAI_KEY.sub("sk-…", value)
    lines = []
    for raw_line in value.splitlines():
        line = re.sub(r"^\s*(?:[-*#>]+|\d+[.)])\s*", "", raw_line).strip()
        if line:
            lines.append(line)
    if not lines:
        return ""
    # Agent messages are already public UI output. Prefer the newest visible
    # line so streamed commentary advances instead of pinning its first words.
    cleaned = " ".join(lines[-2:])
    cleaned = " ".join(cleaned.split())
    return _bounded_utf8(cleaned, _ACTIVITY_BYTE_LIMIT)


def _basename(value: object) -> str:
    path = _text(value, 256).strip("'\"")
    return _text(Path(path).name if path else "", 32)


def _activity_for_command(item: dict[str, Any]) -> str:
    actions = item.get("commandActions")
    if isinstance(actions, list):
        for raw_action in actions:
            if not isinstance(raw_action, dict):
                continue
            action = raw_action.get("type")
            name = _basename(raw_action.get("path"))
            if action == "read" and name:
                return f"Reading {name}"
            if action == "listFiles":
                return f"Listing files in {name}" if name else "Listing project files"
            if action == "search":
                return f"Searching {name}" if name else "Searching project files"

    command = _text(item.get("command"), 512)
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    while words and "=" in words[0] and not words[0].startswith(("./", "/")):
        words.pop(0)
    if not words:
        return "Running a command"
    program = Path(words[0]).name.lower()
    lowered = [word.lower() for word in words[1:]]
    if program in {"pio", "platformio"}:
        return "Flashing firmware" if "upload" in lowered else "Building firmware"
    if program in {"pytest", "unittest"} or "pytest" in lowered:
        return "Running tests"
    if program in {"xcodebuild", "swift"}:
        return "Running Swift tests" if "test" in lowered else "Building the Mac app"
    if program in {"rg", "grep", "find"}:
        return "Searching project files"
    if program == "git":
        subcommand = next((word for word in lowered if not word.startswith("-")), "")
        if subcommand in {"status", "diff", "log", "show"}:
            return f"Checking git {subcommand}"
        return "Working with Git"
    if program in {"npm", "pnpm", "yarn", "node"}:
        return "Running project tools"
    return "Running a command"


def _activity_for_app_item(item: dict[str, Any]) -> str:
    item_type = _text(item.get("type"), 48)
    if item_type == "agentMessage":
        return public_activity_text(item.get("text"))
    if item_type == "commandExecution":
        return _activity_for_command(item)
    if item_type == "fileChange":
        changes = item.get("changes")
        if isinstance(changes, list):
            names = [
                _basename(change.get("path"))
                for change in changes
                if isinstance(change, dict)
            ]
            names = [name for name in names if name]
            if len(names) == 1:
                return f"Editing {names[0]}"
            if names:
                return f"Editing {len(names)} files"
        return "Editing project files"
    if item_type in {"mcpToolCall", "dynamicToolCall"}:
        return _activity_for_tool(_text(item.get("tool"), 80))
    if item_type == "webSearch":
        return "Searching the web"
    if item_type == "imageView":
        name = _basename(item.get("path"))
        return f"Inspecting {name}" if name else "Inspecting an image"
    if item_type == "imageGeneration":
        return "Generating an image"
    if item_type == "plan":
        return "Updating the task plan"
    if item_type in {"collabAgentToolCall", "subAgentActivity"}:
        return "Coordinating agents"
    if item_type == "sleep":
        return "Waiting for a background task"
    return ""


@dataclass
class QuotaWindow:
    remaining_percent: int
    used_percent: int
    duration_mins: int | None
    resets_at: int | None

    def as_dict(self) -> dict[str, int | None]:
        return {
            "remaining": self.remaining_percent,
            "used": self.used_percent,
            "duration_mins": self.duration_mins,
            "resets_at": self.resets_at,
        }


@dataclass
class AgentSession:
    id: str
    title: str = "Codex session"
    project: str = ""
    status: str = "idle"
    # Running is split into two visual phases without changing its priority:
    # thinking between hooks, or actively executing a tool.
    phase: str = ""
    activity: str = "Session ready"
    unread: bool = False
    updated_ms: int = 0
    # Internal-only user-interaction order. Tool/output updates must not reorder
    # the 1/8 history while several sessions run concurrently.
    prompt_ms: int = 0

    def as_dict(self, *, acknowledged_at_ms: int | None = None) -> dict[str, object]:
        acknowledged = (
            acknowledged_at_ms is not None and acknowledged_at_ms == self.updated_ms
        )
        quiet_acknowledged = acknowledged and self.status in {"ready", "blocked"}
        return {
            "id": _text(self.id, _SESSION_ID_CHAR_LIMIT),
            "title": _text(self.title, _TITLE_CHAR_LIMIT),
            "project": _text(self.project, _PROJECT_CHAR_LIMIT),
            # Acknowledgement is device-scoped. Only the device that sent the
            # ack gets the quiet idle/ready presentation; the shared Agent
            # session remains unchanged for every other device.
            "status": "idle" if quiet_acknowledged else self.status,
            "phase": "" if quiet_acknowledged else self.phase,
            "activity": (
                "Session ready"
                if quiet_acknowledged
                else public_activity_text(self.activity) or "Session ready"
            ),
            "unread": self.unread
            and (acknowledged_at_ms is None or acknowledged_at_ms != self.updated_ms),
            "updated_ms": self.updated_ms,
        }


class AgentStore:
    """Small, privacy-trimmed view of Codex sessions for the Cardputer."""

    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        self.sessions: dict[str, AgentSession] = {}
        self.focus_id = ""
        self.focus_seq = 0
        self.weekly: QuotaWindow | None = None
        self.five_hour: QuotaWindow | None = None
        self.quota_mode = "unknown"
        self.seq = 0
        # Both turn/started and the first userMessage item/started describe the
        # same App Server turn. Remember the public turn id so the latter does
        # not steal focus a second time or reset a more specific activity.
        self._last_app_turn_ids: dict[str, str] = {}
        # Independent App Server processes do not broadcast each other's turn
        # events. recencyAt is the privacy-safe fallback when desktop Hooks are
        # disabled or have not yet been trusted.
        self._latest_prompt_ms = 0
        self._on_change = on_change

    def set_on_change(self, callback: Callable[[], None] | None) -> None:
        self._on_change = callback

    def _changed(self) -> None:
        self.seq += 1
        if self._on_change is not None:
            self._on_change()

    @property
    def quota_available(self) -> bool:
        """Compatibility alias for older status and test consumers."""

        return self.quota_mode == "subscription"

    def _session(self, session_id: str) -> AgentSession:
        session = self.sessions.get(session_id)
        if session is None:
            session = AgentSession(id=session_id)
            self.sessions[session_id] = session
        return session

    def apply_public_activity(
        self,
        session_id: object,
        activity: object,
        *,
        phase: str = "thinking",
        timestamp_ms: object = None,
    ) -> bool:
        session_key = _text(session_id, _SESSION_ID_CHAR_LIMIT)
        text = public_activity_text(activity)
        if not session_key or not text:
            return False
        session = self._session(session_key)
        updated_ms = int(timestamp_ms) if isinstance(timestamp_ms, (int, float)) else _now_ms()
        changed = (
            session.activity != text
            or session.status != "running"
            or session.phase != phase
            or session.unread
        )
        session.activity = text
        session.status = "running"
        session.phase = phase
        session.unread = False
        session.updated_ms = max(session.updated_ms, updated_ms)
        self._trim()
        if changed:
            self._changed()
        return changed

    def apply_app_event(self, method: str, params: dict[str, Any]) -> None:
        """Consume stable public app-server events; reasoning is ignored."""

        session_id = _text(params.get("threadId"), _SESSION_ID_CHAR_LIMIT)
        if method == "thread/name/updated" and session_id:
            title = _text(params.get("threadName"), _TITLE_CHAR_LIMIT)
            if title:
                session = self._session(session_id)
                if session.title != title:
                    session.title = title
                    self._changed()
            return
        if not session_id:
            return
        session = self._session(session_id)

        if method == "turn/started":
            turn = params.get("turn")
            turn_id = _text(
                turn.get("id") if isinstance(turn, dict) else params.get("turnId"),
                _SESSION_ID_CHAR_LIMIT,
            )
            if turn_id:
                if self._last_app_turn_ids.get(session_id) == turn_id:
                    return
                self._last_app_turn_ids[session_id] = turn_id
            elif session.status == "running":
                # Compatibility for older servers without turn ids: one
                # running turn per thread is the only state they expose.
                return
            session.status = "running"
            session.phase = "thinking"
            session.activity = "Understanding the task"
            session.unread = False
            event_ms = _timestamp_ms(
                turn.get("startedAt") if isinstance(turn, dict) else None
            ) or _now_ms()
            session.updated_ms = event_ms
            session.prompt_ms = max(session.prompt_ms, event_ms)
            self._latest_prompt_ms = max(self._latest_prompt_ms, event_ms)
            self.focus_id = session_id
            self.focus_seq += 1
            self._trim()
            self._changed()
            return

        if method == "turn/completed":
            turn = params.get("turn")
            status = turn.get("status") if isinstance(turn, dict) else None
            previous_phase = session.phase
            session.phase = ""
            session.updated_ms = _now_ms()
            if status == "failed":
                session.status = "blocked"
                session.activity = "Task encountered a problem"
            else:
                session.status = "ready"
                if previous_phase == "tool" or not public_activity_text(session.activity):
                    session.activity = "Task completed"
            session.unread = True
            self._trim()
            self._changed()
            return

        if method == "item/mcpToolCall/progress":
            self.apply_public_activity(session_id, params.get("message"), phase="tool")
            return

        if method not in {"item/started", "item/completed"}:
            return
        item = params.get("item")
        if not isinstance(item, dict):
            return
        item_type = _text(item.get("type"), 48)
        if item_type == "reasoning":
            return
        if item_type == "userMessage":
            if method == "item/started":
                self.apply_app_event(
                    "turn/started",
                    {"threadId": session_id, "turnId": params.get("turnId")},
                )
            return
        activity = _activity_for_app_item(item)
        if item_type == "agentMessage" and activity:
            self.apply_public_activity(session_id, activity, phase="thinking")
            return
        if method == "item/started" and activity:
            phase = "thinking" if item_type == "plan" else "tool"
            self.apply_public_activity(session_id, activity, phase=phase)
        elif method == "item/completed" and item_type not in {"agentMessage", "plan"}:
            self.apply_public_activity(session_id, "Reviewing the result", phase="thinking")

    def update_threads(self, threads: list[dict[str, Any]]) -> None:
        changed = False
        latest_prompt_id = ""
        latest_prompt_ms = 0
        for thread in threads:
            session_id = _text(thread.get("id"), _SESSION_ID_CHAR_LIMIT)
            if not session_id:
                continue
            session = self.sessions.get(session_id)
            if session is None:
                session = AgentSession(id=session_id)
                self.sessions[session_id] = session
                changed = True
            title = _text(
                thread.get("name") or thread.get("preview"), _TITLE_CHAR_LIMIT
            )
            cwd = _text(thread.get("cwd"), 256)
            project = _text(
                Path(cwd).name if cwd else "", _PROJECT_CHAR_LIMIT
            )
            updated_ms = _timestamp_ms(thread.get("updatedAt"))
            prompt_ms = _timestamp_ms(thread.get("recencyAt")) or updated_ms
            if prompt_ms > session.prompt_ms:
                session.prompt_ms = prompt_ms
                changed = True
            if prompt_ms > latest_prompt_ms:
                latest_prompt_id = session_id
                latest_prompt_ms = prompt_ms
            if title and title != session.title:
                session.title = title
                changed = True
            if project != session.project:
                session.project = project
                changed = True
            if updated_ms > session.updated_ms:
                session.updated_ms = updated_ms
                changed = True
        if latest_prompt_id and latest_prompt_ms > self._latest_prompt_ms:
            self._latest_prompt_ms = latest_prompt_ms
            self.focus_id = latest_prompt_id
            # Increment even for the already focused thread: the Cardputer user
            # may currently be browsing another item in the local history.
            self.focus_seq += 1
            changed = True
        elif not self.focus_id and threads:
            candidate = _text(
                threads[0].get("id"), _SESSION_ID_CHAR_LIMIT
            )
            if candidate:
                self.focus_id = candidate
                self.focus_seq += 1
                changed = True
        self._trim()
        if changed:
            self._changed()

    def apply_hook_event(self, payload: dict[str, Any]) -> None:
        session_id = _text(payload.get("session_id"), _SESSION_ID_CHAR_LIMIT)
        if not session_id:
            return
        event = _text(payload.get("event") or payload.get("hook_event_name"), 48)
        event_key = event.replace("_", "").lower()
        cwd = _text(payload.get("cwd"), 256)
        tool_name = _text(payload.get("tool_name"), 80)
        activity_hint = public_activity_text(payload.get("activity"))
        session = self._session(session_id)
        if cwd:
            session.project = _text(Path(cwd).name, _PROJECT_CHAR_LIMIT)
        session.updated_ms = _timestamp_ms(payload.get("timestamp_ms")) or _now_ms()

        if event_key == "sessionstart":
            session.status = "idle"
            session.phase = ""
            session.activity = "Session ready"
            session.unread = False
            if not self.focus_id:
                self.focus_id = session_id
        elif event_key == "userpromptsubmit":
            session.status = "running"
            session.phase = "thinking"
            session.activity = "Understanding the task..."
            session.unread = False
            self.focus_id = session_id
            session.prompt_ms = max(session.prompt_ms, session.updated_ms)
            self._latest_prompt_ms = max(self._latest_prompt_ms, session.updated_ms)
            # Increment even if the same session receives another prompt; a
            # Cardputer user may currently be browsing a different session
            # and should be returned to this newly operated one.
            self.focus_seq += 1
        elif event_key == "permissionrequest":
            session.status = "needs_input"
            session.phase = ""
            session.activity = "Waiting for your approval"
            session.unread = True
        elif event_key in {"pretooluse", "posttooluse"}:
            asks_user = any(
                marker in tool_name.lower()
                for marker in ("request_user_input", "askuserquestion", "elicitation")
            )
            if event_key == "pretooluse" and asks_user:
                session.status = "needs_input"
                session.phase = ""
                session.activity = "Waiting for your answer"
                session.unread = True
            elif event_key == "posttooluse":
                # PostToolUse means the command has returned and Codex is
                # reasoning over its result. Do not leave the device claiming
                # that the command is still running.
                session.status = "running"
                session.phase = "thinking"
                session.activity = "Thinking..."
                session.unread = False
            else:
                session.status = "running"
                session.phase = "tool"
                session.activity = activity_hint or _activity_for_tool(tool_name)
                session.unread = False
        elif event_key in {"stop", "subagentstop"}:
            session.status = "ready"
            session.phase = ""
            session.activity = activity_hint or "Task completed"
            session.unread = True
        elif event_key in {"error", "systemerror", "failed"}:
            session.status = "blocked"
            session.phase = ""
            session.activity = "Task encountered a problem"
            session.unread = True
        else:
            return
        self._trim()
        self._changed()

    def set_quota_mode(self, mode: str) -> None:
        clean_mode = mode if mode in QUOTA_MODES else "unknown"
        changed = clean_mode != self.quota_mode
        if changed or clean_mode != "subscription":
            # Never carry subscription windows across an auth-mode change.
            changed = changed or self.weekly is not None or self.five_hour is not None
            self.weekly = None
            self.five_hour = None
        self.quota_mode = clean_mode
        if changed:
            self._changed()

    def set_quota_available(self, available: bool) -> None:
        self.set_quota_mode("subscription" if available else "unknown")

    def clear_rate_limits(self) -> None:
        if self.weekly is None and self.five_hour is None:
            return
        self.weekly = None
        self.five_hour = None
        self._changed()

    def update_rate_limits(self, result: dict[str, Any]) -> None:
        if not self.quota_available:
            return
        buckets = result.get("rateLimitsByLimitId")
        snapshot: dict[str, Any] | None = None
        if isinstance(buckets, dict):
            candidate = buckets.get("codex")
            if isinstance(candidate, dict):
                snapshot = candidate
            else:
                snapshot = next((v for v in buckets.values() if isinstance(v, dict)), None)
        if snapshot is None and isinstance(result.get("rateLimits"), dict):
            snapshot = result["rateLimits"]
        if snapshot is None:
            self.clear_rate_limits()
            return

        weekly: QuotaWindow | None = None
        five_hour: QuotaWindow | None = None
        for key in ("primary", "secondary"):
            raw = snapshot.get(key)
            if not isinstance(raw, dict) or not isinstance(raw.get("usedPercent"), int):
                continue
            used = max(0, min(100, int(raw["usedPercent"])))
            duration = raw.get("windowDurationMins")
            duration = int(duration) if isinstance(duration, int) else None
            window = QuotaWindow(
                remaining_percent=100 - used,
                used_percent=used,
                duration_mins=duration,
                resets_at=int(raw["resetsAt"]) if isinstance(raw.get("resetsAt"), int) else None,
            )
            if duration is not None and 280 <= duration <= 320:
                five_hour = window
            elif duration is not None and 9_500 <= duration <= 10_500:
                weekly = window
            elif weekly is None:
                weekly = window
            elif five_hour is None:
                five_hour = window
        if weekly != self.weekly or five_hour != self.five_hour:
            self.weekly = weekly
            self.five_hour = five_hour
            self._changed()

    def acknowledge(self, session_id: str) -> bool:
        session = self.sessions.get(session_id)
        if session is None:
            return False
        changed = session.unread or session.status in {"ready", "blocked"}
        session.unread = False
        if session.status in {"ready", "blocked"}:
            session.status = "idle"
            session.phase = ""
            session.activity = "Session ready"
        if changed:
            self._changed()
        return changed

    def snapshot(
        self,
        limit: int = AGENT_LIMIT,
        *,
        acknowledged: dict[str, int] | None = None,
    ) -> dict[str, object]:
        # Left/right is session history, so keep its wire order recent-first.
        # Status priority previously let old completed work crowd out a newly
        # discovered desktop session when Hooks were unavailable.
        sessions = sorted(
            self.sessions.values(),
            key=lambda item: -(item.prompt_ms or item.updated_ms),
        )
        selected = sessions[: max(1, min(AGENT_LIMIT, limit))]
        # Focus must never be evicted, otherwise the device could not follow the
        # latest prompt after a manual history selection.
        focused = self.sessions.get(self.focus_id)
        if focused is not None and focused not in selected:
            selected[-1] = focused
            selected.sort(key=lambda item: -(item.prompt_ms or item.updated_ms))
        return {
            "seq": self.seq,
            "focus_id": _text(self.focus_id, _SESSION_ID_CHAR_LIMIT),
            "focus_seq": self.focus_seq,
            "quota": {
                "mode": self.quota_mode,
                "available": self.quota_available,
                "weekly": self.weekly.as_dict()
                if self.quota_available and self.weekly
                else None,
                "five_hour": self.five_hour.as_dict()
                if self.quota_available and self.five_hour
                else None,
            },
            "items": [
                session.as_dict(
                    acknowledged_at_ms=(acknowledged or {}).get(session.id)
                )
                for session in selected
            ],
        }

    def _trim(self) -> None:
        if len(self.sessions) <= 32:
            return
        keep = sorted(self.sessions.values(), key=lambda item: item.updated_ms, reverse=True)[:32]
        self.sessions = {item.id: item for item in keep}
        self._last_app_turn_ids = {
            session_id: turn_id
            for session_id, turn_id in self._last_app_turn_ids.items()
            if session_id in self.sessions
        }


def _activity_for_tool(tool_name: str) -> str:
    lowered = tool_name.lower()
    if any(token in lowered for token in ("apply_patch", "edit", "write")):
        return "Editing project files"
    if any(token in lowered for token in ("bash", "shell", "exec", "terminal")):
        return "Running a command"
    if any(token in lowered for token in ("web", "search", "browser")):
        return "Searching references"
    if "image" in lowered:
        return "Working with an image"
    if "test" in lowered:
        return "Running tests"
    return "Working on the task"
