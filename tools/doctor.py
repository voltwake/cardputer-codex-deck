#!/usr/bin/env python3
"""Read-only Codex Deck environment diagnostics.

This intentionally uses only the Python standard library so it can run before
the project virtual environment exists.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def command_version(command: str, *args: str) -> str | None:
    path = shutil.which(command)
    if not path:
        return None
    try:
        result = subprocess.run(
            [path, *args], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (result.stdout or result.stderr).strip().splitlines()
    return output[0] if output else path


def add(
    checks: list[dict[str, Any]],
    name: str,
    status: str,
    detail: str,
    hint: str | None = None,
) -> None:
    item: dict[str, Any] = {"name": name, "status": status, "detail": detail}
    if hint:
        item["hint"] = hint
    checks.append(item)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Codex Deck build prerequisites")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []
    try:
        version_data = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
        release = str(version_data["release"])
        minimum_os = str(json.loads((ROOT / "project-install.json").read_text())["minimum_os"])
        add(checks, "repository", "ok", f"Codex Deck {release} at {ROOT}")
    except (OSError, ValueError, KeyError) as exc:
        release = "unknown"
        minimum_os = "13.0"
        add(checks, "repository", "error", f"cannot read project metadata: {exc}")

    if platform.system() != "Darwin":
        add(checks, "operating_system", "error", f"{platform.system()} is unsupported")
    else:
        add(checks, "operating_system", "ok", f"macOS {platform.mac_ver()[0] or 'unknown'}")

    architecture = platform.machine()
    if architecture != "arm64":
        add(
            checks,
            "architecture",
            "error",
            f"{architecture}; current packaged target is Apple Silicon arm64",
            "Use an arm64 Mac or publish a tested universal build before claiming Intel support.",
        )
    else:
        add(checks, "architecture", "ok", architecture)

    python_ok = sys.version_info >= (3, 10)
    add(
        checks,
        "python",
        "ok" if python_ok else "error",
        platform.python_version(),
        None if python_ok else "Install Python 3.10 or newer and set PYTHON_BIN.",
    )

    for command, label, args_for_version in (
        ("xcode-select", "xcode_command_line_tools", ("--version",)),
        ("swift", "swift", ("--version",)),
        ("codesign", "codesign", ("-h",)),
        ("curl", "curl", ("--version",)),
    ):
        found = command_version(command, *args_for_version)
        add(
            checks,
            label,
            "ok" if found else "error",
            found or "not found",
            f"Install or select the macOS developer tool: {command}",
        )

    pio = shutil.which("pio") or (
        str(ROOT / "tools/.venv/bin/pio")
        if (ROOT / "tools/.venv/bin/pio").exists()
        else None
    )
    add(
        checks,
        "platformio",
        "ok" if pio else "warning",
        pio or "not found before bootstrap",
        "Run ./scripts/bootstrap.sh to install the project-local PlatformIO tool.",
    )

    app = Path("/Applications/CardBridge.app")
    if app.exists():
        try:
            with (app / "Contents/Info.plist").open("rb") as stream:
                info = plistlib.load(stream)
            add(
                checks,
                "installed_app",
                "ok",
                f"{info.get('CFBundleShortVersionString', '?')} ({info.get('CFBundleVersion', '?')})",
            )
        except (OSError, plistlib.InvalidFileException) as exc:
            add(checks, "installed_app", "warning", f"cannot read App metadata: {exc}")
    else:
        add(checks, "installed_app", "warning", "not installed")

    driver = Path("/Library/Audio/Plug-Ins/HAL/CardBridgeMicrophone.driver")
    add(
        checks,
        "microphone_driver",
        "ok" if driver.exists() else "warning",
        "installed" if driver.exists() else "not installed; App will offer installation",
    )

    required = [
        "README.md",
        "AGENTS.md",
        "LICENSE",
        "docs/INSTALL.md",
        "firmware/m5stack-cardputer-adv/platformio.ini",
        "bridge/agent/pyproject.toml",
        "bridge/macos/Package.swift",
    ]
    missing = [path for path in required if not (ROOT / path).exists()]
    add(
        checks,
        "project_contract",
        "ok" if not missing else "error",
        "required entrypoints present" if not missing else f"missing: {', '.join(missing)}",
    )

    errors = sum(item["status"] == "error" for item in checks)
    warnings = sum(item["status"] == "warning" for item in checks)
    result = {
        "project": "Codex Deck",
        "internal_compatibility_name": "CardBridge",
        "release": release,
        "minimum_os": minimum_os,
        "root": str(ROOT),
        "checks": checks,
        "summary": {"errors": errors, "warnings": warnings},
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for item in checks:
            marker = {"ok": "OK", "warning": "WARN", "error": "ERROR"}[item["status"]]
            print(f"[{marker:5}] {item['name']}: {item['detail']}")
            if item.get("hint") and item["status"] != "ok":
                print(f"        hint: {item['hint']}")
        print(f"Summary: {errors} error(s), {warnings} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
