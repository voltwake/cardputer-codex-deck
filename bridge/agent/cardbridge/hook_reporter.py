from __future__ import annotations

import json
import os
import re
import shlex
import socket
import sys
import time
from pathlib import Path


_PATCH_PATH = re.compile(r"^\*\*\* (?:Add|Update|Delete) File:\s*(.+)$", re.MULTILINE)
_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|token|secret|password)\s*[:=]\s*\S+"
)
_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}")
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")


def _basename(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return Path(value.strip("'\"")).name[:32]


def _command_activity(value: object) -> str:
    if not isinstance(value, str):
        return "Running a command"
    try:
        words = shlex.split(value)
    except ValueError:
        words = value.split()
    while words and "=" in words[0] and not words[0].startswith(("./", "/")):
        words.pop(0)
    if not words:
        return "Running a command"
    program = Path(words[0]).name.lower()
    arguments = [word.lower() for word in words[1:]]
    if program in {"pio", "platformio"}:
        return "Flashing firmware" if "upload" in arguments else "Building firmware"
    if program in {"pytest", "unittest"} or "pytest" in arguments:
        return "Running tests"
    if program in {"xcodebuild", "swift"}:
        return "Running Swift tests" if "test" in arguments else "Building the Mac app"
    if program in {"rg", "grep", "find"}:
        return "Searching project files"
    if program == "git":
        action = next((word for word in arguments if not word.startswith("-")), "")
        return f"Checking git {action}" if action in {"status", "diff", "log", "show"} else "Working with Git"
    return "Running a command"


def _activity_from_hook(raw: dict[str, object], tool_name: str) -> str:
    lowered = tool_name.lower()
    tool_input = raw.get("tool_input") or raw.get("toolInput")
    inputs = tool_input if isinstance(tool_input, dict) else {}
    if any(marker in lowered for marker in ("apply_patch", "edit", "write")):
        path = next(
            (_basename(inputs.get(key)) for key in ("file_path", "path") if inputs.get(key)),
            "",
        )
        patch_text = inputs.get("patch") or inputs.get("input")
        if not path and isinstance(patch_text, str):
            match = _PATCH_PATH.search(patch_text)
            if match:
                path = _basename(match.group(1))
        return f"Editing {path}" if path else "Editing project files"
    if any(marker in lowered for marker in ("bash", "shell", "exec", "terminal")):
        return _command_activity(inputs.get("cmd") or inputs.get("command"))
    if any(marker in lowered for marker in ("request_user_input", "askuser", "elicitation")):
        return "Waiting for your answer"
    if any(marker in lowered for marker in ("web", "search", "browser")):
        return "Searching references"
    if "image" in lowered:
        return "Working with an image"
    if "test" in lowered:
        return "Running tests"
    return "Working on the task"


def _public_message_activity(value: object) -> str:
    if not isinstance(value, str):
        return ""
    value = _SECRET.sub(lambda match: f"{match.group(1)}=…", value)
    value = _BEARER_TOKEN.sub("Bearer …", value)
    value = _OPENAI_KEY.sub("sk-…", value)
    lines = []
    for raw_line in value.replace("\x00", "").replace("```", " ").splitlines():
        line = re.sub(r"^\s*(?:[-*#>]+|\d+[.)])\s*", "", raw_line).strip(" `")
        if line:
            lines.append(line)
    text = " ".join(lines[:2])
    encoded = text.encode("utf-8")
    if len(encoded) <= 72:
        return text
    return encoded[:69].decode("utf-8", errors="ignore").rstrip() + "…"


def main() -> int:
    try:
        raw = json.load(sys.stdin)
        if not isinstance(raw, dict):
            return 0
        tool_name = raw.get("tool_name") or raw.get("toolName") or ""
        clean_tool_name = tool_name if isinstance(tool_name, str) else ""
        event = raw.get("hook_event_name") or raw.get("hookEventName") or ""
        activity = _activity_from_hook(raw, clean_tool_name)
        if isinstance(event, str) and event.replace("_", "").lower() in {
            "stop",
            "subagentstop",
        }:
            activity = _public_message_activity(
                raw.get("last_assistant_message") or raw.get("lastAssistantMessage")
            ) or activity
        payload = {
            "event": event,
            "session_id": raw.get("session_id") or "",
            "turn_id": raw.get("turn_id") or "",
            "cwd": raw.get("cwd") or "",
            "tool_name": clean_tool_name,
            "activity": activity,
            "timestamp_ms": int(time.time() * 1000),
        }
        port = int(os.environ.get("CARDBRIDGE_HOOK_PORT", "7790"))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(0.05)
            client.sendto(
                json.dumps(payload, separators=(",", ":")).encode(),
                ("127.0.0.1", port),
            )
    except Exception:
        pass
    return 0
