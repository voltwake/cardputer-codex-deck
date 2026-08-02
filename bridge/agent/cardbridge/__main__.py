from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from .audio import CARDBRIDGE_FEED_DEVICE
from .control_server import default_control_socket
from .server import BridgeApp


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Cardputer ADV Mac bridge")
    result.add_argument("--host", default="0.0.0.0")
    result.add_argument("--port", type=int, default=7788, help="TCP control port")
    result.add_argument("--udp-port", type=int, default=7789)
    result.add_argument("--audio-device", default=CARDBRIDGE_FEED_DEVICE)
    result.add_argument("--jitter-ms", type=int, default=100)
    result.add_argument("--gain", type=float, default=20.0, help="software make-up gain into the microphone bridge")
    result.add_argument("--config", type=Path)
    result.add_argument("--no-audio", action="store_true", help="validate/drop audio without sound output")
    result.add_argument("--dry-run", action="store_true", help="log key events instead of injecting them")
    result.add_argument("--no-mdns", action="store_true", help="disable service discovery advertisement")
    result.add_argument("--record", type=Path, help="also write received PCM to this WAV file (diagnostic)")
    result.add_argument("--no-codex", action="store_true", help="disable Codex session monitoring")
    result.add_argument("--hook-port", type=int, default=7790, help="local-only Codex Hook UDP port")
    result.add_argument(
        "--control-socket",
        type=Path,
        default=default_control_socket(),
        help="owner-only local status/control socket for the menu bar app",
    )
    result.add_argument(
        "--no-control-socket",
        action="store_true",
        help="disable the local menu bar status/control socket",
    )
    result.add_argument("-v", "--verbose", action="store_true")
    return result


async def run(args: argparse.Namespace) -> None:
    app = BridgeApp(
        host=args.host,
        tcp_port=args.port,
        udp_port=args.udp_port,
        config_path=args.config,
        audio_device=args.audio_device,
        jitter_ms=args.jitter_ms,
        gain=args.gain,
        no_audio=args.no_audio,
        dry_run=args.dry_run,
        advertise=not args.no_mdns,
        record_path=args.record,
        enable_agents=not args.no_codex,
        hook_port=args.hook_port,
        control_socket_path=None if args.no_control_socket else args.control_socket,
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            pass
    started = False
    try:
        await app.start()
        started = True
        waiters = {
            asyncio.create_task(stop.wait()),
            asyncio.create_task(app.shutdown_requested.wait()),
        }
        _done, pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    finally:
        if started or app.service_state != "stopped":
            await app.stop()


def main() -> None:
    if sys.argv[1:] == ["--cardbridge-codex-hook"]:
        from .hook_reporter import main as report_hook

        raise SystemExit(report_hook())
    args = parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(run(args))
    except RuntimeError as exc:
        raise SystemExit(f"CardBridge startup failed: {exc}") from exc


if __name__ == "__main__":
    main()
