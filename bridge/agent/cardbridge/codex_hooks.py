from __future__ import annotations

import json
import os
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Any


EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "Stop",
)
OWNED_MARKERS = ("--cardbridge-codex-hook", "cardbridge_codex.py")


def hook_command() -> str:
    executable = shlex.quote(str(Path(sys.executable).resolve()))
    if getattr(sys, "frozen", False):
        return f"{executable} --cardbridge-codex-hook"
    return f"{executable} -m cardbridge --cardbridge-codex-hook"


def is_ours(hook: object) -> bool:
    return (
        isinstance(hook, dict)
        and hook.get("type") == "command"
        and any(marker in str(hook.get("command", "")) for marker in OWNED_MARKERS)
    )


def is_current(hook: object) -> bool:
    return (
        isinstance(hook, dict)
        and hook.get("type") == "command"
        and "--cardbridge-codex-hook" in str(hook.get("command", ""))
    )


def transform(document: dict[str, Any], *, command: str, install: bool) -> dict[str, Any]:
    root = document.setdefault("hooks", {})
    if not isinstance(root, dict):
        raise ValueError("top-level 'hooks' must be an object")
    for event in EVENTS:
        groups = root.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"hooks.{event} must be a list")
        cleaned = []
        for group in groups:
            if not isinstance(group, dict):
                cleaned.append(group)
                continue
            hooks = group.get("hooks")
            if not isinstance(hooks, list):
                cleaned.append(group)
                continue
            remaining = [hook for hook in hooks if not is_ours(hook)]
            if remaining:
                replacement = dict(group)
                replacement["hooks"] = remaining
                cleaned.append(replacement)
        if install:
            cleaned.append(
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": command,
                            "timeout": 2,
                        }
                    ]
                }
            )
        if cleaned:
            root[event] = cleaned
        else:
            root.pop(event, None)
    if not root:
        document.pop("hooks", None)
    return document


def hooks_installed(path: Path | None = None) -> bool:
    config = path or Path.home() / ".codex" / "hooks.json"
    try:
        document = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    root = document.get("hooks") if isinstance(document, dict) else None
    if not isinstance(root, dict):
        return False
    for event in EVENTS:
        groups = root.get(event)
        if not isinstance(groups, list) or not any(
            isinstance(group, dict)
            and isinstance(group.get("hooks"), list)
            and any(is_current(hook) for hook in group["hooks"])
            for group in groups
        ):
            return False
    return True


def update_hooks(install: bool, path: Path | None = None) -> bool:
    config = path or Path.home() / ".codex" / "hooks.json"
    document: dict[str, Any] = {}
    if config.exists():
        loaded = json.loads(config.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"{config}: root must be an object")
        document = loaded
    transform(document, command=hook_command(), install=install)
    _write_atomic(config, document)
    return hooks_installed(config)


def _write_atomic(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="hooks.", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(document, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
