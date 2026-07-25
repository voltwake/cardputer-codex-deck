from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import secrets
import socket
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .agents import AgentStore
from .audio import CARDBRIDGE_FEED_DEVICE, BlackHoleAudioOutput, NullAudioOutput
from .codex_monitor import CodexMonitor, start_hook_receiver
from .codex_hooks import hooks_installed, update_hooks
from .config import BridgeConfig
from .control_server import AgentControlServer
from .keyboard import KeyInjector
from .protocol import (
    MAX_JSON_LINE,
    ProtocolError,
    decode_message,
    encode_message,
    unpack_audio,
)
from ._generated_version import (
    AGENT_API_MAJOR,
    AGENT_API_MINOR,
    AGENT_BUILD,
    AGENT_VERSION,
    DEVICE_PROTOCOL_MAJOR,
    DEVICE_PROTOCOL_MINOR,
)
from .status import ConnectedDevice
from .versioning import CompatibilityError, DeviceCompatibility, negotiate_device

LOG = logging.getLogger("cardbridge")


def _mdns_instance_label(mac_name: str, bridge_id: str) -> str:
    """Return a DNS-SD instance label bounded to the 63-byte DNS limit."""

    safe_name = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in mac_name
    )
    suffix = f"-{bridge_id[:6]}"
    prefix_budget = max(0, 63 - len(suffix.encode("utf-8")))
    prefix = safe_name.encode("utf-8")[:prefix_budget].decode(
        "utf-8", errors="ignore"
    )
    return f"{prefix or 'Mac'}{suffix}"


class AudioDatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self, app: "BridgeApp") -> None:
        self.app = app

    def datagram_received(self, data: bytes, address: tuple[str, int]) -> None:
        self.app.receive_audio(data, address)

    def error_received(self, exc: Exception) -> None:
        LOG.warning("UDP receiver error: %s", exc)


class BridgeApp:
    def __init__(
        self,
        *,
        host: str = "0.0.0.0",
        tcp_port: int = 7788,
        udp_port: int = 7789,
        config_path: Path | None = None,
        audio_device: str = CARDBRIDGE_FEED_DEVICE,
        jitter_ms: int = 100,
        gain: float = 20.0,
        no_audio: bool = False,
        dry_run: bool = False,
        advertise: bool = True,
        record_path: Path | None = None,
        pair_code_factory: Callable[[], str] | None = None,
        enable_agents: bool = True,
        hook_port: int = 7790,
        control_socket_path: Path | None = None,
    ) -> None:
        self.host = host
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.config = BridgeConfig(config_path)
        self.keyboard = KeyInjector(dry_run=dry_run)
        # Diagnostic tap: raw device PCM (pre-jitter) straight to a WAV file so
        # the mic->UDP->bridge path can be verified without a loopback driver.
        self._record_path = record_path
        self._record_bytes = bytearray()
        self.audio = (
            NullAudioOutput(jitter_ms)
            if no_audio
            else BlackHoleAudioOutput(audio_device, jitter_ms, gain)
        )
        self.dry_run = dry_run
        self.advertise = advertise
        self.pair_code_factory = pair_code_factory or (lambda: f"{secrets.randbelow(1_000_000):06d}")
        self.enable_agents = enable_agents
        self.hook_port = hook_port
        self.control_socket_path = control_socket_path
        self.audio_disabled = no_audio
        self.started_at_ms = 0
        self.service_state = "stopped"
        self.lan_address = ""
        self.network_available = False
        self.last_error = ""
        self.audio_error = ""
        self.status_seq = 0
        self.status_task: asyncio.Task[None] | None = None
        self.shutdown_requested = asyncio.Event()
        self.connected_devices: dict[asyncio.StreamWriter, ConnectedDevice] = {}
        self.pairing_status: dict[str, object] | None = None
        self.agents = AgentStore()
        self.codex_monitor = CodexMonitor(self.agents)
        self.hook_transport: asyncio.DatagramTransport | None = None
        self.codex_hooks_installed = hooks_installed() if enable_agents else False
        self._agent_clients: dict[asyncio.StreamWriter, str] = {}
        self._agent_broadcast_pending = False
        self.active_tokens: dict[str, tuple[str, str]] = {}
        self.tcp_server: asyncio.AbstractServer | None = None
        self.udp_transport: asyncio.DatagramTransport | None = None
        self.zeroconf: Any = None
        self.service_info: Any = None
        self.control_server = (
            AgentControlServer(
                control_socket_path,
                self.status_snapshot,
                self.handle_control_command,
            )
            if control_socket_path is not None
            else None
        )

    async def start(self) -> None:
        self.service_state = "starting"
        self.started_at_ms = int(time.time() * 1000)
        self.lan_address = _local_ipv4()
        self.network_available = self.lan_address != "127.0.0.1"
        self.last_error = ""
        self.agents.set_on_change(self._agent_changed)
        self._start_audio_output()
        self.keyboard.check_accessibility(prompt=not self.dry_run)
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: AudioDatagramProtocol(self), local_addr=(self.host, self.udp_port)
        )
        self.udp_transport = transport
        udp_socket = transport.get_extra_info("socket")
        self.udp_port = int(udp_socket.getsockname()[1])

        self.tcp_server = await asyncio.start_server(
            self.handle_client,
            self.host,
            self.tcp_port,
            limit=MAX_JSON_LINE + 1,
        )
        self.tcp_port = int(self.tcp_server.sockets[0].getsockname()[1])
        if self.advertise:
            await self._start_mdns()
        if self.enable_agents:
            try:
                self.hook_transport, self.hook_port = await start_hook_receiver(
                    self.agents, self.hook_port
                )
            except OSError as exc:
                LOG.warning("Codex Hook receiver unavailable: %s", exc)
                self.last_error = f"Codex Hook receiver unavailable: {exc}"
            await self.codex_monitor.start()
        if self.control_server is not None:
            await self.control_server.start()
        self.status_task = asyncio.create_task(self._publish_status_periodically())
        self.service_state = "ready"
        self._status_changed()
        LOG.info(
            "CardBridge ready: TCP %d, UDP %d, Mac name %s",
            self.tcp_port,
            self.udp_port,
            self.config.mac_name,
        )

    def _write_wav(self) -> None:
        if self._record_path is None or not self._record_bytes:
            return
        import wave

        with wave.open(str(self._record_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(bytes(self._record_bytes))
        LOG.info(
            "wrote %d samples (%.1fs) to %s",
            len(self._record_bytes) // 2,
            len(self._record_bytes) / 2 / 16000,
            self._record_path,
        )

    async def stop(self) -> None:
        if self.service_state == "stopped":
            return
        self.service_state = "stopping"
        await self._publish_status()
        if self.status_task is not None:
            self.status_task.cancel()
            try:
                await self.status_task
            except asyncio.CancelledError:
                pass
            self.status_task = None
        self.agents.set_on_change(None)
        await self.codex_monitor.stop()
        if self.hook_transport is not None:
            self.hook_transport.close()
            self.hook_transport = None
        self._write_wav()
        await self._stop_mdns()
        if self.tcp_server is not None:
            self.tcp_server.close()
            await self.tcp_server.wait_closed()
            self.tcp_server = None
        for writer in tuple(self.connected_devices):
            writer.close()
        self.connected_devices.clear()
        self.active_tokens.clear()
        if self.udp_transport is not None:
            self.udp_transport.close()
            self.udp_transport = None
        self.audio.stop()
        self.service_state = "stopped"
        await self._publish_status()
        if self.control_server is not None:
            await self.control_server.stop()

    def status_snapshot(self) -> dict[str, object]:
        accessibility = self.keyboard.check_accessibility(prompt=False)
        audio_running = self.audio.is_running()
        codex_client = self.codex_monitor.client
        codex_process = codex_client.process if codex_client is not None else None
        codex_connected = codex_process is not None and codex_process.returncode is None
        state = self.service_state
        issues: list[str] = []
        if state == "ready":
            if not self.network_available:
                issues.append("network")
            state = "connected" if self.connected_devices else "ready"
            if self.connected_devices:
                if not accessibility:
                    issues.append("accessibility")
                if not audio_running:
                    issues.append("audio")
            if issues:
                state = "degraded"
        jitter = self.audio.jitter
        return {
            "t": "snapshot",
            "seq": self.status_seq,
            "agent": {
                "state": state,
                "version": AGENT_VERSION,
                "build": AGENT_BUILD,
                "api": {"major": AGENT_API_MAJOR, "minor": AGENT_API_MINOR},
                "pid": os.getpid(),
                "started_at_ms": self.started_at_ms,
                "bridge_id": self.config.bridge_id,
                "mac_name": self.config.mac_name,
                "lan_address": self.lan_address,
                "tcp_port": self.tcp_port,
                "udp_port": self.udp_port,
                "hook_port": self.hook_port if self.enable_agents else None,
                "issues": issues,
                "last_error": self.last_error,
            },
            "permissions": {
                "accessibility": accessibility,
            },
            "audio": {
                "enabled": not self.audio_disabled,
                "running": audio_running,
                "device": getattr(self.audio, "device_name", None),
                "gain": getattr(self.audio, "gain", 1.0),
                "sample_rate": getattr(self.audio, "output_rate", None),
                "received": jitter.received,
                "lost": jitter.lost,
                "late": jitter.late,
                "resyncs": jitter.resyncs,
            },
            "codex": {
                "enabled": self.enable_agents,
                "connected": codex_connected,
                "executable": self.codex_monitor.executable if self.enable_agents else None,
                "hooks_listening": self.hook_transport is not None,
                "hooks_installed": self.codex_hooks_installed,
                "sessions": len(self.agents.sessions),
                "quota_mode": self.agents.quota_mode,
                "quota_available": self.agents.quota_available,
            },
            "devices": [
                device.snapshot()
                for device in sorted(
                    self.connected_devices.values(),
                    key=lambda item: item.connected_at_ms,
                )
            ],
            "paired_devices": self.config.paired_devices(),
            "pairing": dict(self.pairing_status) if self.pairing_status else None,
        }

    async def handle_control_command(
        self, request: dict[str, Any]
    ) -> dict[str, object]:
        name = request.get("name")
        if name == "set_gain":
            value = request.get("value")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return {"ok": False, "error": "invalid_gain"}
            gain = max(0.1, min(50.0, float(value)))
            if not hasattr(self.audio, "gain"):
                return {"ok": False, "error": "audio_disabled"}
            self.audio.gain = gain
            self._status_changed()
            return {"ok": True, "gain": gain}
        if name == "unpair":
            device_id = request.get("device_id")
            if not isinstance(device_id, str) or not device_id:
                return {"ok": False, "error": "invalid_device_id"}
            removed = self.config.unpair(device_id)
            if removed:
                for writer, device in tuple(self.connected_devices.items()):
                    if device.device_id == device_id:
                        writer.close()
                self._status_changed()
            return {"ok": removed, "device_id": device_id}
        if name in {"install_hooks", "uninstall_hooks"}:
            try:
                self.codex_hooks_installed = update_hooks(name == "install_hooks")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                return {"ok": False, "error": str(exc)}
            self._status_changed()
            return {
                "ok": True,
                "hooks_installed": self.codex_hooks_installed,
            }
        if name in {"restart", "shutdown"}:
            asyncio.get_running_loop().call_later(0.1, self.shutdown_requested.set)
            return {"ok": True, "action": name}
        return {"ok": False, "error": "unknown_command"}

    def _status_changed(self) -> None:
        self.status_seq += 1
        try:
            asyncio.get_running_loop().call_soon(
                lambda: asyncio.create_task(self._publish_status())
            )
        except RuntimeError:
            pass

    async def _publish_status(self) -> None:
        if self.control_server is not None:
            await self.control_server.publish()

    async def _publish_status_periodically(self) -> None:
        ticks = 0
        while True:
            await asyncio.sleep(2)
            ticks += 1
            if ticks % 3 == 0:
                await self._refresh_network()
            if ticks % 5 == 0 and (self.audio_error or not self.audio.is_running()):
                self._start_audio_output()
            await self._publish_status()

    def _start_audio_output(self) -> None:
        if self.audio_disabled:
            self.audio.start()
            self.audio_error = ""
            return
        previous_error = self.audio_error
        try:
            self.audio.start()
            self.audio_error = ""
            if previous_error and self.last_error == previous_error:
                self.last_error = ""
            if previous_error:
                LOG.info("audio output recovered: %s", getattr(self.audio, "device_name", ""))
        except Exception as exc:
            self.audio_error = str(exc)
            self.last_error = self.audio_error
            if self.audio_error != previous_error:
                LOG.warning("audio output unavailable: %s", exc)

    async def _refresh_network(self) -> None:
        address = await asyncio.to_thread(_local_ipv4)
        available = address != "127.0.0.1"
        availability_changed = available != self.network_available
        self.network_available = available
        if not available:
            self.last_error = "No active local network interface"
            if availability_changed:
                self._status_changed()
            return
        if self.last_error == "No active local network interface":
            self.last_error = ""
        if address == self.lan_address:
            if availability_changed:
                self._status_changed()
            return

        previous = self.lan_address
        self.lan_address = address
        if self.advertise:
            try:
                await self._restart_mdns()
            except Exception as exc:  # zeroconf errors must not stop the bridge
                self.last_error = f"mDNS refresh failed: {exc}"
                LOG.warning("mDNS refresh failed after network change: %s", exc)
        LOG.info("LAN address changed from %s to %s", previous, address)
        self._status_changed()

    async def serve_forever(self) -> None:
        if self.tcp_server is None:
            raise RuntimeError("bridge has not been started")
        async with self.tcp_server:
            await self.tcp_server.serve_forever()

    async def _start_mdns(self) -> None:
        try:
            from zeroconf import ServiceInfo
            from zeroconf.asyncio import AsyncZeroconf
        except ImportError as exc:
            raise RuntimeError("zeroconf is missing; install bridge/requirements.txt") from exc
        address = self.lan_address or _local_ipv4()
        service_type = "_cardbridge._tcp.local."
        instance_label = _mdns_instance_label(
            self.config.mac_name, self.config.bridge_id
        )
        service_name = f"{instance_label}.{service_type}"
        self.service_info = ServiceInfo(
            service_type,
            service_name,
            addresses=[socket.inet_aton(address)],
            port=self.tcp_port,
            properties={
                b"id": self.config.bridge_id.encode(),
                b"name": self.config.mac_name.encode(),
                b"udp": str(self.udp_port).encode(),
                b"app": AGENT_VERSION.encode(),
                b"pmaj": str(DEVICE_PROTOCOL_MAJOR).encode(),
                b"pmin": str(DEVICE_PROTOCOL_MINOR).encode(),
            },
            server=f"cardbridge-{self.config.bridge_id[:8]}.local.",
        )
        self.zeroconf = AsyncZeroconf()
        await self.zeroconf.async_register_service(self.service_info)
        LOG.info("mDNS: %s at %s", service_name, address)

    async def _stop_mdns(self) -> None:
        if self.zeroconf is None:
            self.service_info = None
            return
        try:
            if self.service_info is not None:
                await self.zeroconf.async_unregister_service(self.service_info)
        finally:
            await self.zeroconf.async_close()
            self.service_info = None
            self.zeroconf = None

    async def _restart_mdns(self) -> None:
        await self._stop_mdns()
        await self._start_mdns()

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        peer_ip = str(peer[0]) if peer else "unknown"
        device_id: str | None = None
        authenticated_token: str | None = None
        pending_code: str | None = None
        compatibility: DeviceCompatibility | None = None
        connected_device: ConnectedDevice | None = None
        pair_attempts = 0
        pressed: dict[str, list[str]] = {}
        LOG.info("control connection from %s", peer_ip)
        try:
            while authenticated_token is None:
                message = await self._read_message(reader, timeout=15)
                message_type = message["t"]
                if message_type == "hello":
                    candidate = message.get("dev_id")
                    if not isinstance(candidate, str) or not (4 <= len(candidate) <= 64):
                        raise ProtocolError("invalid dev_id")
                    device_id = candidate
                    try:
                        compatibility = negotiate_device(message)
                    except CompatibilityError as exc:
                        await self._send(writer, exc.response())
                        return
                    supplied_token = message.get("token")
                    if self.config.validate(device_id, supplied_token):
                        authenticated_token = str(supplied_token)
                        assert compatibility is not None
                        await self._send(
                            writer,
                            {
                                "t": "hello_ok",
                                "mac_id": self.config.bridge_id,
                                "mac_name": self.config.mac_name,
                                "udp_port": self.udp_port,
                                **compatibility.response_metadata(),
                            },
                        )
                    elif supplied_token is not None:
                        await self._send(writer, {"t": "auth_error"})
                    else:
                        pending_code = self.pair_code_factory()
                        self._show_pair_code(pending_code, device_id)
                        assert compatibility is not None
                        await self._send(
                            writer,
                            {
                                "t": "pair_required",
                                "mac_id": self.config.bridge_id,
                                "mac_name": self.config.mac_name,
                                **compatibility.response_metadata(),
                            },
                        )
                elif message_type == "pair" and device_id and pending_code:
                    if str(message.get("code", "")) != pending_code:
                        # A six-digit code must not be brute-forceable: after a
                        # few misses drop the link. Reconnecting shows a fresh
                        # code, so an attacker cannot enumerate one code.
                        pair_attempts += 1
                        if pair_attempts >= 3:
                            raise ProtocolError("too many wrong pairing codes")
                        await self._send(writer, {"t": "pair_error"})
                        continue
                    authenticated_token = self.config.pair(device_id)
                    if compatibility is None:
                        raise ProtocolError("pairing attempted before hello")
                    await self._send(
                        writer,
                        {
                            "t": "paired",
                            "mac_id": self.config.bridge_id,
                            "mac_name": self.config.mac_name,
                            "token": authenticated_token,
                            "udp_port": self.udp_port,
                            **compatibility.response_metadata(),
                        },
                    )
                elif message_type == "ping":
                    # Pair-code entry can take longer than one heartbeat window.
                    await self._send(writer, {"t": "pong"})
                else:
                    # Unknown and phase-two messages never tear down the link.
                    continue

            assert device_id is not None
            if compatibility is None:
                raise ProtocolError("authenticated without protocol negotiation")
            connected_device = ConnectedDevice(
                device_id=device_id,
                peer_ip=peer_ip,
                token=authenticated_token,
                compatibility=compatibility,
            )
            self.active_tokens[authenticated_token] = (device_id, peer_ip)
            self._agent_clients[writer] = authenticated_token
            self.connected_devices[writer] = connected_device
            self.pairing_status = None
            self._status_changed()
            LOG.info("device %s authenticated", device_id)
            await self._send_agent_snapshot(writer, authenticated_token, "agent_status")
            await self._authenticated_loop(
                reader, writer, pressed, authenticated_token, connected_device
            )
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            LOG.info("control connection timed out/closed: %s", peer_ip)
        except (ProtocolError, ConnectionError, OSError) as exc:
            LOG.warning("control connection rejected from %s: %s", peer_ip, exc)
        finally:
            for key, modifiers in pressed.items():
                self.keyboard.inject(key, "up", modifiers)
            if authenticated_token and self.active_tokens.get(authenticated_token) == (
                device_id,
                peer_ip,
            ):
                self.active_tokens.pop(authenticated_token, None)
            self._agent_clients.pop(writer, None)
            self.connected_devices.pop(writer, None)
            if self.pairing_status and self.pairing_status.get("device_id") == device_id:
                self.pairing_status = None
            if connected_device is not None or device_id is not None:
                self._status_changed()
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _authenticated_loop(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        pressed: dict[str, list[str]],
        token: str,
        device: ConnectedDevice,
    ) -> None:
        missed = 0
        while True:
            try:
                message = await self._read_message(reader, timeout=5)
                missed = 0
            except asyncio.TimeoutError:
                missed += 1
                if missed >= 3:
                    raise
                await self._send(writer, {"t": "ping", "token": token})
                continue

            message_type = message["t"]
            supplied_token = message.get("token")
            if not isinstance(supplied_token, str) or not secrets.compare_digest(
                supplied_token, token
            ):
                LOG.warning("ignored unauthenticated TCP message type %s", message_type)
                continue
            device.touch()
            if message_type == "ping":
                # Piggyback audio liveness on the existing heartbeat. Older
                # firmware ignores these fields; newer firmware can distinguish
                # a healthy TCP keyboard link from a stalled UDP/audio path.
                await self._send(
                    writer,
                    {
                        "t": "pong",
                        "token": token,
                        "audio_received": device.audio_packets,
                        "audio_output_ready": self.audio.is_running(),
                    },
                )
            elif message_type == "pong":
                continue
            elif message_type == "key":
                key = message.get("k")
                action = message.get("a")
                modifiers = message.get("m", [])
                if not isinstance(key, str) or not isinstance(modifiers, list):
                    continue
                allowed = {"cmd", "shift", "alt", "ctrl"}
                clean_modifiers = [item for item in modifiers if item in allowed]
                if self.keyboard.inject(key, str(action), clean_modifiers):
                    if action == "down":
                        pressed[key] = clean_modifiers
                    elif action == "up":
                        pressed.pop(key, None)
            elif message_type == "agent_list_req":
                limit = message.get("limit", 8)
                clean_limit = max(1, min(8, int(limit))) if isinstance(limit, int) else 8
                await self._send_agent_snapshot(writer, token, "agent_list", clean_limit)
            elif message_type == "agent_ack":
                session_id = message.get("id")
                if isinstance(session_id, str):
                    self.agents.acknowledge(session_id)
            else:
                # Forward-compatible parser: ignore every unknown message type.
                continue

    async def _read_message(
        self, reader: asyncio.StreamReader, timeout: float
    ) -> dict[str, Any]:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout)
        except ValueError as exc:
            raise ProtocolError("JSON line exceeded limit") from exc
        if not line:
            raise asyncio.IncompleteReadError(b"", None)
        return decode_message(line)

    async def _send(self, writer: asyncio.StreamWriter, message: dict[str, Any]) -> None:
        writer.write(encode_message(message))
        await writer.drain()

    def _agent_changed(self) -> None:
        self._status_changed()
        if self._agent_broadcast_pending:
            return
        self._agent_broadcast_pending = True
        asyncio.get_running_loop().call_soon(
            lambda: asyncio.create_task(self._broadcast_agent_status())
        )

    async def _broadcast_agent_status(self) -> None:
        self._agent_broadcast_pending = False
        for writer, token in tuple(self._agent_clients.items()):
            if writer.is_closing():
                self._agent_clients.pop(writer, None)
                continue
            try:
                await self._send_agent_snapshot(writer, token, "agent_status")
            except (ConnectionError, OSError):
                self._agent_clients.pop(writer, None)

    async def _send_agent_snapshot(
        self,
        writer: asyncio.StreamWriter,
        token: str,
        message_type: str,
        limit: int = 8,
    ) -> None:
        message = self.agents.snapshot(limit)
        message["t"] = message_type
        message["provider"] = "codex"
        message["token"] = token
        await self._send(writer, message)

    def _show_pair_code(self, code: str, device_id: str) -> None:
        self.pairing_status = {
            "device_id": device_id,
            "code": code,
            "created_at_ms": int(time.time() * 1000),
        }
        self._status_changed()
        # flush + log: stdout is block-buffered when redirected to a file, and
        # the code must be visible wherever the operator is watching.
        print("\n" + "=" * 50, flush=True)
        print(f"CardBridge pairing code for {device_id}: {code}", flush=True)
        print("Enter this code on the Cardputer ADV.", flush=True)
        print("=" * 50 + "\n", flush=True)
        LOG.info("pairing code for %s: %s", device_id, code)
        if platform.system() == "Darwin" and not self.dry_run:
            script = f'display notification "Code: {code}" with title "CardBridge pairing"'
            try:
                subprocess.run(
                    ["osascript", "-e", script],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass

    def receive_audio(self, datagram: bytes, address: tuple[str, int]) -> None:
        peer_ip = str(address[0])
        for token, (_device_id, active_ip) in tuple(self.active_tokens.items()):
            if active_ip != peer_ip:
                continue
            try:
                packet = unpack_audio(token, datagram)
            except ProtocolError:
                continue
            self.audio.feed(packet.sequence, packet.payload)
            for device in self.connected_devices.values():
                if device.token == token:
                    device.touch()
                    device.audio_packets += 1
                    break
            if self._record_path is not None:
                self._record_bytes.extend(packet.payload)
            return
        LOG.debug("ignored unauthenticated UDP audio from %s", peer_ip)


def _local_ipv4() -> str:
    # Ask the primary LAN interfaces first. The default-route probe below can
    # pick a VPN utun address (e.g. 198.18.0.0/15 fake-IP) that LAN devices
    # cannot reach, which would advertise an unusable mDNS address.
    for interface in ("en0", "en1"):
        try:
            result = subprocess.run(
                ["ipconfig", "getifaddr", interface],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        address = result.stdout.strip()
        if address:
            return address
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return str(probe.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()
