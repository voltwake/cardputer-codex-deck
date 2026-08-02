#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

LABEL = "local.cardbridge.service"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def run_launchctl(*arguments: str) -> None:
    subprocess.run(["launchctl", *arguments], check=False)


def build_launch_path(
    path_lookup: Callable[[str], str | None] | None = None,
    home: Path | None = None,
) -> str:
    """Build a deterministic service PATH that can run npm-installed Codex."""

    lookup = path_lookup or shutil.which
    user_home = home or Path.home()
    directories: list[Path] = []
    for command in ("node", "codex"):
        executable = lookup(command)
        if executable:
            directories.append(Path(executable).expanduser().parent)
    directories.extend(
        [
            user_home / ".npm-global" / "bin",
            user_home / ".local" / "bin",
            Path("/opt/homebrew/bin"),
            Path("/usr/local/bin"),
            Path("/usr/bin"),
            Path("/bin"),
            Path("/usr/sbin"),
            Path("/sbin"),
        ]
    )
    ordered: list[str] = []
    for directory in directories:
        value = str(directory)
        if value not in ordered:
            ordered.append(value)
    return os.pathsep.join(ordered)


def install(args: argparse.Namespace) -> None:
    bridge_dir = Path(__file__).resolve().parent
    config_dir = Path.home() / ".cardbridge"
    config_dir.mkdir(parents=True, exist_ok=True)
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    program_arguments = [
        sys.executable,
        "-m",
        "cardbridge",
        "--audio-device",
        args.audio_device,
        "--gain",
        str(args.gain),
        "--hook-port",
        str(args.hook_port),
    ]
    if args.verbose:
        program_arguments.append("-v")
    if args.no_audio:
        program_arguments.append("--no-audio")
    if args.no_codex:
        program_arguments.append("--no-codex")
    payload = {
        "Label": LABEL,
        "ProgramArguments": program_arguments,
        "WorkingDirectory": str(bridge_dir),
        "EnvironmentVariables": {
            "PYTHONPATH": str(bridge_dir),
            # launchd does not inherit the interactive shell PATH. The npm
            # Codex launcher uses `/usr/bin/env node`, so both directories must
            # be present or the monitor incorrectly falls back to bundled Codex.
            "PATH": build_launch_path(),
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Interactive",
        "StandardOutPath": str(config_dir / "bridge.log"),
        "StandardErrorPath": str(config_dir / "bridge-error.log"),
    }
    with path.open("wb") as handle:
        plistlib.dump(payload, handle)
    os.chmod(path, 0o644)
    domain = f"gui/{os.getuid()}"
    run_launchctl("bootout", domain, str(path))
    subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
    print(f"Installed and started {LABEL}: {path}")
    print(f"Logs: {config_dir / 'bridge.log'}")


def uninstall() -> None:
    path = plist_path()
    run_launchctl("bootout", f"gui/{os.getuid()}", str(path))
    path.unlink(missing_ok=True)
    print(f"Removed {LABEL}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Install/uninstall CardBridge LaunchAgent")
    parser.add_argument("action", choices=("install", "uninstall"))
    parser.add_argument("--audio-device", default="CardBridge Microphone Feed")
    parser.add_argument("--gain", type=float, default=20.0)
    parser.add_argument("--hook-port", type=int, default=7790)
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--no-codex", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    install(args) if args.action == "install" else uninstall()


if __name__ == "__main__":
    main()
