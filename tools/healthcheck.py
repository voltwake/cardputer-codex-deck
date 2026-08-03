#!/usr/bin/env python3
"""Verify an installed Codex Deck App, Agent, driver, and local API."""

from __future__ import annotations

import argparse
import json
import plistlib
import socket
import subprocess
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOCKET = Path.home() / "Library/Application Support/CardBridge/run/agent.sock"
APP = Path("/Applications/CardBridge.app")
DRIVER = Path("/Library/Audio/Plug-Ins/HAL/CardBridgeMicrophone.driver")


def process_exists(pattern: str) -> bool:
    try:
        result = subprocess.run(["pgrep", "-f", pattern], capture_output=True, check=False)
    except OSError:
        return False
    return result.returncode == 0


def read_plist(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as stream:
            value = plistlib.load(stream)
        return value if isinstance(value, dict) else None
    except (OSError, plistlib.InvalidFileException):
        return None


def agent_matches_expected(
    snapshot: dict[str, Any], expected_app: dict[str, Any]
) -> bool:
    agent = snapshot.get("agent", {})
    return (
        agent.get("version") == expected_app.get("version")
        and str(agent.get("build")) == str(expected_app.get("build"))
    )


def agent_has_settled(snapshot: dict[str, Any]) -> bool:
    agent = snapshot.get("agent", {})
    return agent.get("state") not in {"starting", "stopping", "stopped", None}


def local_snapshot(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    client: socket.socket | None = None
    stream = None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(3)
        client.connect(str(path))
        stream = client.makefile("rb")
        client.sendall(b'{"t":"hello","api":{"major":1,"minor":0}}\n')
        hello = stream.readline()
        if not hello:
            return None, "Agent closed the control socket during hello"
        hello_value = json.loads(hello.decode("utf-8"))
        if hello_value.get("t") != "hello_ok":
            return None, f"unexpected hello response: {hello_value.get('t')}"
        client.sendall(b'{"t":"snapshot_req"}\n')
        snapshot = stream.readline()
        if not snapshot:
            return None, "Agent returned no snapshot"
        parsed = json.loads(snapshot.decode("utf-8"))
        return parsed if isinstance(parsed, dict) else None, None
    except (OSError, ValueError, UnicodeError) as exc:
        return None, str(exc)
    finally:
        try:
            if stream is not None:
                stream.close()
            if client is not None:
                client.close()
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Check an installed Codex Deck")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--socket", type=Path, default=SOCKET)
    parser.add_argument(
        "--wait",
        type=float,
        default=10,
        help="seconds to wait for the Agent after an App launch (default: 10)",
    )
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []
    expected = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
    expected_app = expected["mac_app"]

    app_info = read_plist(APP / "Contents/Info.plist")
    app_version = app_info.get("CFBundleShortVersionString") if app_info else None
    app_build = app_info.get("CFBundleVersion") if app_info else None
    app_ok = app_version == expected_app["version"] and str(app_build) == str(expected_app["build"])
    checks.append(
        {
            "name": "app",
            "status": "ok" if app_ok else "error",
            "detail": (
                f"{app_version} ({app_build})" if app_info else "not installed"
            ),
            "expected": f"{expected_app['version']} ({expected_app['build']})",
        }
    )
    app_running = process_exists("/Applications/CardBridge.app/Contents/MacOS/CardBridge")
    checks.append(
        {
            "name": "app_process",
            "status": "ok" if app_running else "error",
            "detail": "running" if app_running else "not running",
        }
    )
    checks.append(
        {
            "name": "microphone_driver",
            "status": "ok" if DRIVER.exists() else "warning",
            "detail": "installed" if DRIVER.exists() else "not installed",
        }
    )
    snapshot: dict[str, Any] | None = None
    error: str | None = "socket missing"
    deadline = time.monotonic() + max(0, args.wait if app_running else 0)
    while True:
        if args.socket.exists():
            candidate, error = local_snapshot(args.socket)
            if candidate:
                snapshot = candidate
            if (
                snapshot
                and agent_matches_expected(snapshot, expected_app)
                and agent_has_settled(snapshot)
            ):
                break
        if time.monotonic() >= deadline:
            break
        time.sleep(0.25)

    if args.socket.exists():
        socket_mode = args.socket.stat().st_mode & 0o777
        checks.append(
            {
                "name": "control_socket_permissions",
                "status": "ok" if socket_mode == 0o600 else "error",
                "detail": oct(socket_mode),
                "expected": "0o600",
            }
        )
    checks.append(
        {
            "name": "agent_api",
            "status": "ok" if snapshot else "error",
            "detail": "snapshot received" if snapshot else error,
        }
    )
    if snapshot:
        agent = snapshot.get("agent", {})
        agent_version_ok = agent_matches_expected(snapshot, expected_app)
        checks.append(
            {
                "name": "agent_version",
                "status": "ok" if agent_version_ok else "error",
                "detail": f"{agent.get('version')} ({agent.get('build')})",
                "expected": f"{expected_app['version']} ({expected_app['build']})",
            }
        )
        checks.append(
            {
                "name": "agent_state",
                "status": "ok" if agent.get("state") in {"ready", "connected"} else "warning",
                "detail": str(agent.get("state", "unknown")),
            }
        )

    errors = sum(item["status"] == "error" for item in checks)
    warnings = sum(item["status"] == "warning" for item in checks)
    result = {
        "project": "Codex Deck",
        "internal_compatibility_name": "CardBridge",
        "expected": expected_app,
        "socket": str(args.socket),
        "checks": checks,
        "summary": {"errors": errors, "warnings": warnings},
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for item in checks:
            marker = {"ok": "OK", "warning": "WARN", "error": "ERROR"}[item["status"]]
            print(f"[{marker:5}] {item['name']}: {item['detail']}")
        print(f"Summary: {errors} error(s), {warnings} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
