#!/usr/bin/env python3
"""Install, remove, or preview CardBridge's fail-open Codex hooks.

This developer-facing wrapper deliberately uses the same implementation as the
packaged menu bar app so both paths preserve unrelated hooks and migrate legacy
CardBridge reporter commands identically.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from cardbridge.codex_hooks import hook_command, transform, update_hooks


def load_document(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: root must be an object")
    return loaded


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "uninstall", "show"))
    parser.add_argument(
        "--config", type=Path, default=Path.home() / ".codex" / "hooks.json"
    )
    args = parser.parse_args()

    if args.action == "show":
        document = load_document(args.config)
        transformed = transform(document, command=hook_command(), install=True)
        print(json.dumps(transformed, ensure_ascii=False, indent=2))
        return

    installed = update_hooks(args.action == "install", args.config)
    state = "installed" if installed else "removed"
    print(f"CardBridge Codex hooks {state} in {args.config}")
    print(
        "Restart/reload Codex, review the hook trust prompt, and approve only "
        "if the CardBridgeAgent path is expected."
    )


if __name__ == "__main__":
    main()
