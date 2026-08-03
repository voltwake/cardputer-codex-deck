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
from .audio import (
    CARDBRIDGE_FEED_DEVICE,
    BlackHoleAudioOutput,
    JitterBuffer,
    NullAudioOutput,
)
from .codex_monitor import CodexMonitor, start_hook_receiver
from .codex_hooks import hooks_installed, update_hooks
from .config import BridgeConfig
from .control_server import AgentControlServer
from .devices import DeviceRegistry, DeviceSession, PairingRequest
from .keyboard import KeyInjector
from .protocol import (
    MAX_SUBSCRIPTION_INTERVAL_MS,
    MAX_JSON_LINE,
    MIN_SUBSCRIPTION_INTERVAL_MS,
    TOPIC_READ_CAPABILITY,
    TOPIC_SUBSCRIPTION_CAPABILITIES,
    ProtocolError,
    decode_message,
    encode_message,
    unpack_audio,
)
from .shutdown import request_shutdown
from ._generated_version import (
    AGENT_API_MAJOR,
    AGENT_API_MINOR,
    AGENT_BUILD,
    AGENT_VERSION,
    DEVICE_PROTOCOL_MAJOR,
    DEVICE_PROTOCOL_MINOR,
)
from .usage import TokenUsageStore
from .versioning import CompatibilityError, DeviceCompatibility, negotiate_device

LOG = logging.getLogger("cardbridge")
MDNS_SHUTDOWN_TIMEOUT_SECONDS = 2.0
DEVICE_SEND_TIMEOUT_SECONDS = 2.0
MODIFIER_KEYS = frozenset({"cmd", "shift", "alt", "ctrl"})


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
        self.jitter_ms = jitter_ms
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
        self.registry = DeviceRegistry()
        # Kept as a read-only compatibility view for source integrations that
        # used the pre-registry attribute. All business logic uses registry.
        self.connected_devices: dict[asyncio.StreamWriter, DeviceSession] = {}
        self.pairing_status: dict[str, object] | None = None
        self.audio_lease_owner_id: str | None = None
        self.audio_lease_idle_ms = 3_000
        self._held_key_owners: dict[str, dict[int, list[str]]] = {}
        self._injected_key_modifiers: dict[str, list[str]] = {}
        self.agents = AgentStore()
        self.usage = TokenUsageStore()
        self.codex_monitor = CodexMonitor(self.agents, usage=self.usage)
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
        self.usage.set_on_change(self._usage_changed)
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
        for session in self.registry.clear():
            self._cleanup_session(session, close_writer=True)
        self.connected_devices.clear()
        self.active_tokens.clear()
        self.audio_lease_owner_id = None
        self._held_key_owners.clear()
        self._injected_key_modifiers.clear()
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
            state = "connected" if self.registry.all() else "ready"
            if self.registry.all():
                if not accessibility:
                    issues.append("accessibility")
                if not audio_running:
                    issues.append("audio")
            if issues:
                state = "degraded"
        jitter = self.audio.jitter
        pairing_requests = self.registry.pairing_snapshots()
        # Preserve the original single-object field for old App builds while
        # exposing the complete concurrent pairing set to new clients.
        pairing = pairing_requests[0] if pairing_requests else None
        legacy_pairing = None
        if pairing_requests:
            first = pairing_requests[0]
            legacy_pairing = {
                "device_id": first["device_id"],
                "code": first["code"],
                "created_at_ms": first["created_at_ms"],
            }
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
                "lease_owner_id": self.audio_lease_owner_id,
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
                "usage": self.usage.snapshot(),
            },
            "devices": [
                device.snapshot(audio_owner_id=self.audio_lease_owner_id)
                for device in self.registry.all()
            ],
            "paired_devices": self.config.paired_devices(),
            "pairing": legacy_pairing or pairing,
            "pairings": pairing_requests,
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
                session = self.registry.get(device_id)
                if session is not None:
                    self._cleanup_session(session, close_writer=True)
                    self.registry.remove(session)
                    self._sync_connected_devices()
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
            loop = asyncio.get_running_loop()
            loop.call_later(
                0.1,
                request_shutdown,
                loop,
                self.shutdown_requested,
            )
            return {"ok": True, "action": name}
        return {"ok": False, "error": "unknown_command"}

    def _status_changed(self) -> None:
        self.status_seq += 1
        for device in self.registry.all():
            device.pending_topics.update({"bridge.status", "network.status"})
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
        loop = asyncio.get_running_loop()
        next_network = loop.time() + 6.0
        next_audio = loop.time() + 10.0
        next_status = loop.time() + 2.0
        while True:
            await asyncio.sleep(0.05)
            now = loop.time()
            await self._flush_topic_subscriptions()
            if now >= next_network:
                await self._refresh_network()
                next_network = now + 6.0
            if now >= next_audio and (self.audio_error or not self.audio.is_running()):
                self._start_audio_output()
                next_audio = now + 10.0
            if now >= next_status:
                self._expire_audio_lease()
                await self._publish_status()
                next_status = now + 2.0

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
        zeroconf = self.zeroconf
        service_info = self.service_info
        self.zeroconf = None
        self.service_info = None
        if zeroconf is None:
            return
        try:
            if service_info is not None:
                await asyncio.wait_for(
                    zeroconf.async_unregister_service(service_info),
                    MDNS_SHUTDOWN_TIMEOUT_SECONDS,
                )
        except asyncio.TimeoutError:
            LOG.warning("mDNS unregister timed out during shutdown")
        except Exception as exc:
            LOG.warning("mDNS unregister failed during shutdown: %s", exc)
        try:
            await asyncio.wait_for(
                zeroconf.async_close(), MDNS_SHUTDOWN_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            LOG.warning("mDNS close timed out during shutdown")
        except Exception as exc:
            LOG.warning("mDNS close failed during shutdown: %s", exc)

    async def _restart_mdns(self) -> None:
        await self._stop_mdns()
        await self._start_mdns()

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        peer_ip = str(peer[0]) if peer else "unknown"
        connection_id = id(writer)
        device_id: str | None = None
        authenticated_token: str | None = None
        pending_code: str | None = None
        compatibility: DeviceCompatibility | None = None
        session: DeviceSession | None = None
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
                        self.registry.remove_pairing(connection_id)
                        assert compatibility is not None
                        try:
                            self.config.update_device_metadata(
                                device_id,
                                name=compatibility.name or compatibility.model,
                                vendor=compatibility.vendor,
                                model=compatibility.model,
                                firmware=compatibility.firmware_version,
                                firmware_build=compatibility.firmware_build,
                            )
                        except OSError as exc:
                            # Metadata freshness must not turn a valid pairing
                            # into an unavailable keyboard/audio connection.
                            LOG.warning(
                                "could not refresh metadata for %s: %s",
                                device_id,
                                exc,
                            )
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
                        assert compatibility is not None
                        request = PairingRequest(
                            connection_id=connection_id,
                            device_id=device_id,
                            code=pending_code,
                            vendor=compatibility.vendor,
                            name=compatibility.name,
                            model=compatibility.model,
                        )
                        self.registry.add_pairing(request)
                        self._show_pair_code(request)
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
                    request = self.registry.pairing_for(connection_id)
                    if request is None:
                        raise ProtocolError("pairing code expired")
                    if str(message.get("code", "")) != request.code:
                        # A six-digit code must not be brute-forceable: after a
                        # few misses drop the link. Reconnecting shows a fresh
                        # code, so an attacker cannot enumerate one code.
                        request.failures += 1
                        if request.failures >= 3:
                            raise ProtocolError("too many wrong pairing codes")
                        await self._send(writer, {"t": "pair_error"})
                        continue
                    if compatibility is None:
                        raise ProtocolError("pairing attempted before hello")
                    authenticated_token = self.config.pair(
                        device_id,
                        compatibility.name
                        or compatibility.model
                        or ("Cardputer" if compatibility.legacy else "Device"),
                        vendor=compatibility.vendor,
                        model=compatibility.model,
                        firmware=compatibility.firmware_version,
                        firmware_build=compatibility.firmware_build,
                    )
                    self.registry.remove_pairing(connection_id)
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
            session = DeviceSession(
                device_id=device_id,
                peer_ip=peer_ip,
                token=authenticated_token,
                compatibility=compatibility,
                writer=writer,
                jitter=self._new_jitter_buffer(),
            )
            old_session = self.registry.register(session)
            if old_session is not None:
                self._cleanup_session(old_session, close_writer=True)
            self.active_tokens[authenticated_token] = (device_id, peer_ip)
            self._agent_clients[writer] = authenticated_token
            self._sync_connected_devices()
            self._status_changed()
            LOG.info("device %s authenticated", device_id)
            if session.has_capability("agents.snapshot.v1"):
                await self._send_agent_snapshot(session, "agent_status")
            await self._authenticated_loop(reader, writer, authenticated_token, session)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            LOG.info("control connection timed out/closed: %s", peer_ip)
        except (ProtocolError, ConnectionError, OSError) as exc:
            LOG.warning("control connection rejected from %s: %s", peer_ip, exc)
        finally:
            self.registry.remove_pairing(connection_id)
            if session is not None:
                self._cleanup_session(session, close_writer=False)
                self.registry.remove(session)
            if (
                authenticated_token
                and session is not None
                and self.registry.get(device_id or "") is session
                and self.active_tokens.get(authenticated_token) == (device_id, peer_ip)
            ):
                self.active_tokens.pop(authenticated_token, None)
            self._agent_clients.pop(writer, None)
            self._sync_connected_devices()
            if session is not None or device_id is not None:
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
        token: str,
        device: DeviceSession,
    ) -> None:
        missed = 0
        while True:
            if not self._session_is_current(device):
                return
            try:
                message = await self._read_message(reader, timeout=5)
                missed = 0
            except asyncio.TimeoutError:
                if not self._session_is_current(device):
                    return
                missed += 1
                if missed >= 3:
                    raise
                await self._send(writer, {"t": "ping", "token": token})
                continue

            # A same-ID replacement can happen while the old task is awaiting
            # input. Never let already-buffered authenticated messages from the
            # superseded connection mutate global keyboard/audio/topic state.
            if not self._session_is_current(device):
                return
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
                if not device.has_capability("control.keys.v1"):
                    await self._send_capability_error(writer, token, "control.keys.v1")
                    continue
                key = message.get("k")
                action = message.get("a")
                modifiers = message.get("m", [])
                if not isinstance(key, str) or not isinstance(modifiers, list):
                    continue
                # Vendor keyboards may spell ASCII key names differently.
                # Canonicalize before global ownership so "X" and "x" (or
                # "CTRL" and "ctrl") cannot become duplicate macOS events.
                key = key.lower() if key.isascii() else key
                allowed = {"cmd", "shift", "alt", "ctrl"}
                clean_modifiers: list[str] = []
                for item in modifiers:
                    if not isinstance(item, str):
                        continue
                    canonical = item.lower() if item.isascii() else item
                    if canonical in allowed and canonical not in clean_modifiers:
                        clean_modifiers.append(canonical)
                self._handle_key(device, key, str(action), clean_modifiers)
            elif message_type == "agent_list_req":
                if not device.has_capability("agents.snapshot.v1"):
                    await self._send_capability_error(
                        writer, token, "agents.snapshot.v1"
                    )
                    continue
                limit = message.get("limit", 8)
                clean_limit = max(1, min(8, int(limit))) if isinstance(limit, int) else 8
                await self._send_agent_snapshot(device, "agent_list", clean_limit)
            elif message_type == "agent_ack":
                if not device.has_capability("agents.snapshot.v1"):
                    await self._send_capability_error(
                        writer, token, "agents.snapshot.v1"
                    )
                    continue
                session_id = message.get("id")
                if isinstance(session_id, str):
                    agent_session = self.agents.sessions.get(session_id)
                    if agent_session is not None:
                        device.acknowledge(session_id, agent_session.updated_ms)
                        device.pending_topics.add("codex.sessions")
                        await self._send_agent_snapshot(device, "agent_status")
            elif message_type == "sync_req":
                await self._handle_sync_request(device, message)
            elif message_type == "sync_subscribe":
                await self._handle_sync_subscribe(device, message)
            elif message_type == "sync_unsubscribe":
                await self._handle_sync_unsubscribe(device, message)
            elif message_type == "audio_claim":
                await self._handle_audio_claim(device)
            elif message_type == "audio_release":
                await self._handle_audio_release(device)
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
        await asyncio.wait_for(writer.drain(), DEVICE_SEND_TIMEOUT_SECONDS)

    def _session_is_current(self, device: DeviceSession) -> bool:
        return (
            not device.replaced
            and self.registry.get(device.device_id) is device
        )

    @staticmethod
    def _close_failed_writer(writer: Any) -> None:
        if not writer.is_closing():
            writer.close()

    def _new_jitter_buffer(self) -> JitterBuffer:
        return JitterBuffer(self.jitter_ms)

    def _sync_connected_devices(self) -> None:
        self.connected_devices = {
            session.writer: session for session in self.registry.all() if session.writer
        }

    def _handle_key(
        self, device: DeviceSession, key: str, action: str, modifiers: list[str]
    ) -> None:
        if not key or len(key) > 64 or action not in {"down", "up"}:
            return
        connection_id = id(device.writer)
        owners = self._held_key_owners.setdefault(key, {})
        if action == "down":
            if key in device.held_keys:
                return
            if not owners:
                if not self.keyboard.inject(key, "down", modifiers):
                    return
                self._injected_key_modifiers[key] = list(modifiers)
            owners[connection_id] = list(modifiers)
            device.held_keys[key] = list(modifiers)
            return

        held_modifiers = device.held_keys.pop(key, None)
        if held_modifiers is None:
            return
        owners.pop(connection_id, None)
        if not owners:
            self._held_key_owners.pop(key, None)
            injected_modifiers = self._injected_key_modifiers.pop(key, held_modifiers)
            # Modifier key-up events must not carry their own flag. The device
            # already sends that invariant, but the global multi-device owner
            # map intentionally preserves the first key-down flags and must
            # restore the invariant at the final injection boundary.
            release_modifiers = (
                [item for item in injected_modifiers if item != key]
                if key in MODIFIER_KEYS
                else injected_modifiers
            )
            self.keyboard.inject(key, "up", release_modifiers)

    def _release_session_keys(self, device: DeviceSession) -> None:
        for key, modifiers in tuple(device.held_keys.items()):
            self._handle_key(device, key, "up", modifiers)

    def _cleanup_session(self, device: DeviceSession, *, close_writer: bool) -> None:
        self._release_session_keys(device)
        if self.audio_lease_owner_id == device.device_id:
            current = self.registry.get(device.device_id)
            if current is device or current is None:
                self._release_audio_lease(device)
            else:
                # A same-ID replacement is already visible in the registry;
                # release the old lease without touching the new session.
                device.audio_lease_state = "none"
                device.jitter.reset()
                self.audio_lease_owner_id = None
                self.audio.reset_stream()
                self._notify_audio_lease()
        device.jitter.reset()
        device.subscriptions.clear()
        device.pending_topics.clear()
        if (
            self.registry.get(device.device_id) is device
            and self.active_tokens.get(device.token) == (device.device_id, device.peer_ip)
        ):
            self.active_tokens.pop(device.token, None)
        if device.writer is not None:
            self._agent_clients.pop(device.writer, None)
            if close_writer and not device.writer.is_closing():
                device.writer.close()

    def _audio_owner(self) -> DeviceSession | None:
        if self.audio_lease_owner_id is None:
            return None
        owner = self.registry.get(self.audio_lease_owner_id)
        if owner is None:
            self.audio_lease_owner_id = None
        return owner

    def _set_audio_lease(self, device: DeviceSession) -> None:
        previous = self._audio_owner()
        if previous is device:
            device.audio_lease_state = "owner"
            return
        if previous is not None:
            previous.audio_lease_state = "none"
            previous.jitter.reset()
        # Packets received while this session was not the owner are not a
        # playback queue. Clear them before selecting the new stream, then let
        # receive_audio append the packet that actually triggered takeover.
        device.jitter.reset()
        self.audio_lease_owner_id = device.device_id
        device.audio_lease_state = "owner"
        # AudioOutput's callback reads this active per-device buffer. It is not
        # a shared input queue: ownership changes reset its boundary first.
        self.audio.reset_stream()
        self.audio.jitter = device.jitter
        self._notify_audio_lease()
        self._status_changed()

    def _release_audio_lease(self, device: DeviceSession | None = None) -> None:
        owner = self._audio_owner()
        if owner is None:
            return
        if device is not None and owner is not device:
            return
        owner.audio_lease_state = "none"
        owner.jitter.reset()
        self.audio_lease_owner_id = None
        self.audio.reset_stream()
        self._notify_audio_lease()
        self._status_changed()

    def _expire_audio_lease(self) -> None:
        owner = self._audio_owner()
        if owner is None or owner.last_audio_ms <= 0:
            return
        if int(time.time() * 1000) - owner.last_audio_ms > self.audio_lease_idle_ms:
            LOG.info("audio lease expired for %s after silence", owner.device_id)
            self._release_audio_lease(owner)

    def _notify_audio_lease(self) -> None:
        try:
            asyncio.get_running_loop().create_task(self._broadcast_audio_lease())
        except RuntimeError:
            pass

    async def _broadcast_audio_lease(self) -> None:
        owner = self._audio_owner()
        for device in tuple(self.registry.all()):
            if (
                not self._session_is_current(device)
                or not device.has_capability("audio.lease.v1")
                or device.writer.is_closing()
            ):
                continue
            state = "available" if owner is None else (
                "owner" if owner is device else "busy"
            )
            try:
                await self._send(
                    device.writer,
                    {
                        "t": "audio_lease",
                        "state": state,
                        "owner_id": owner.device_id if owner else None,
                        "token": device.token,
                    },
                )
            except (asyncio.TimeoutError, ConnectionError, OSError, ProtocolError):
                self._close_failed_writer(device.writer)
                continue

    def _agent_changed(self) -> None:
        self._status_changed()
        for device in self.registry.all():
            device.pending_topics.add("codex.sessions")
        if self._agent_broadcast_pending:
            return
        self._agent_broadcast_pending = True
        asyncio.get_running_loop().call_soon(
            lambda: asyncio.create_task(self._broadcast_agent_status())
        )

    async def _broadcast_agent_status(self) -> None:
        self._agent_broadcast_pending = False
        for device in tuple(self.registry.all()):
            if (
                not self._session_is_current(device)
                or device.writer.is_closing()
                or not device.has_capability("agents.snapshot.v1")
            ):
                continue
            try:
                await self._send_agent_snapshot(device, "agent_status")
            except (asyncio.TimeoutError, ConnectionError, OSError, ProtocolError):
                self._close_failed_writer(device.writer)
                continue

    def _usage_changed(self) -> None:
        for device in self.registry.all():
            device.pending_topics.add("codex.usage")
        self._status_changed()

    async def _send_agent_snapshot(
        self,
        device: DeviceSession,
        message_type: str,
        limit: int = 8,
    ) -> None:
        message = self.agents.snapshot(limit, acknowledged=device.ack_cursors)
        message["t"] = message_type
        message["provider"] = "codex"
        message["token"] = device.token
        await self._send(device.writer, message)

    async def _send_capability_error(
        self,
        writer: asyncio.StreamWriter,
        token: str,
        required: str,
        *,
        topic: str | None = None,
        request_id: object = None,
    ) -> None:
        message: dict[str, Any] = {
            "t": "error",
            "code": "capability_required",
            "required_capability": required,
            "token": token,
        }
        if topic is not None:
            message["topic"] = topic
        if request_id is not None:
            message["id"] = request_id
        await self._send(writer, message)

    @staticmethod
    def _requested_topics(message: dict[str, Any]) -> list[str]:
        raw_topics = message.get("topics")
        if not isinstance(raw_topics, list):
            return []
        result: list[str] = []
        for item in raw_topics:
            if isinstance(item, str) and item in TOPIC_READ_CAPABILITY and item not in result:
                result.append(item)
        return result

    @staticmethod
    def _unsupported_topics(message: dict[str, Any]) -> list[str]:
        raw_topics = message.get("topics")
        if not isinstance(raw_topics, list):
            return []
        result: list[str] = []
        for item in raw_topics:
            if (
                isinstance(item, str)
                and item not in TOPIC_READ_CAPABILITY
                and item not in result
            ):
                result.append(item)
        return result

    async def _send_unsupported_topic(
        self,
        device: DeviceSession,
        topic: str,
        request_id: object,
    ) -> None:
        message: dict[str, Any] = {
            "t": "error",
            "code": "unsupported_topic",
            "topic": topic,
            "token": device.token,
        }
        if request_id is not None:
            message["id"] = request_id
        await self._send(device.writer, message)

    async def _handle_sync_request(
        self, device: DeviceSession, message: dict[str, Any]
    ) -> None:
        request_id = message.get("id")
        for topic in self._unsupported_topics(message):
            await self._send_unsupported_topic(device, topic, request_id)
        topics = self._requested_topics(message)
        if not topics:
            if self._unsupported_topics(message):
                return
            await self._send(
                device.writer,
                {
                    "t": "error",
                    "code": "invalid_topics",
                    "id": request_id,
                    "token": device.token,
                },
            )
            return
        for topic in topics:
            required = TOPIC_READ_CAPABILITY[topic]
            if not device.has_capability(required):
                await self._send_capability_error(
                    device.writer,
                    device.token,
                    required,
                    topic=topic,
                    request_id=request_id,
                )
                continue
            await self._send_topic(device, topic, "sync_snapshot", request_id)

    async def _handle_sync_subscribe(
        self, device: DeviceSession, message: dict[str, Any]
    ) -> None:
        request_id = message.get("id")
        if not device.has_capability("sync.subscribe.v1"):
            await self._send_capability_error(
                device.writer,
                device.token,
                "sync.subscribe.v1",
                request_id=request_id,
            )
            return
        for topic in self._unsupported_topics(message):
            await self._send_unsupported_topic(device, topic, request_id)
        topics = self._requested_topics(message)
        accepted: list[str] = []
        for topic in topics:
            required = [TOPIC_READ_CAPABILITY[topic], *TOPIC_SUBSCRIPTION_CAPABILITIES[topic]]
            missing = next((item for item in required if not device.has_capability(item)), None)
            if missing is not None:
                await self._send_capability_error(
                    device.writer,
                    device.token,
                    missing,
                    topic=topic,
                    request_id=request_id,
                )
                continue
            accepted.append(topic)

        raw_interval = message.get("min_interval_ms")
        if isinstance(raw_interval, int) and not isinstance(raw_interval, bool):
            min_interval = max(
                MIN_SUBSCRIPTION_INTERVAL_MS,
                min(MAX_SUBSCRIPTION_INTERVAL_MS, raw_interval),
            )
        else:
            min_interval = 1000
        device.subscriptions.update(accepted)
        if accepted:
            device.min_interval_ms = min_interval
        device.pending_topics.update(accepted)
        await self._send(
            device.writer,
            {
                "t": "sync_subscribed",
                "id": request_id,
                "topics": sorted(device.subscriptions),
                "min_interval_ms": device.min_interval_ms,
                "token": device.token,
            },
        )

    async def _handle_sync_unsubscribe(
        self, device: DeviceSession, message: dict[str, Any]
    ) -> None:
        request_id = message.get("id")
        if not device.has_capability("sync.subscribe.v1"):
            # Treat the new request as unsupported for legacy/current M5
            # clients rather than sending them a sync_* response they cannot
            # negotiate or parse.
            await self._send_capability_error(
                device.writer,
                device.token,
                "sync.subscribe.v1",
                request_id=request_id,
            )
            return
        raw_topics = message.get("topics")
        if isinstance(raw_topics, list):
            removed = {
                topic for topic in raw_topics if isinstance(topic, str)
            }
            device.subscriptions.difference_update(removed)
            device.pending_topics.difference_update(removed)
            for topic in removed:
                device.subscription_last_sent_ms.pop(topic, None)
        else:
            device.subscriptions.clear()
            device.pending_topics.clear()
            device.subscription_last_sent_ms.clear()
        await self._send(
            device.writer,
            {
                "t": "sync_unsubscribed",
                "id": request_id,
                "topics": sorted(device.subscriptions),
                "token": device.token,
            },
        )

    def _topic_data(self, device: DeviceSession, topic: str) -> dict[str, object]:
        if topic == "bridge.status":
            owner = self._audio_owner()
            return {
                "state": self.service_state,
                "version": AGENT_VERSION,
                "build": AGENT_BUILD,
                "api": {"major": AGENT_API_MAJOR, "minor": AGENT_API_MINOR},
                "protocol": {
                    "major": device.compatibility.protocol_major,
                    "minor": device.compatibility.negotiated_minor,
                },
                "uptime_ms": max(0, int(time.time() * 1000) - self.started_at_ms),
                "permissions": {
                    "accessibility": self.keyboard.check_accessibility(prompt=False),
                },
                "audio_output_ready": self.audio.is_running(),
                "audio_device_id": getattr(self.audio, "device_name", None),
                "active_microphone_device_id": owner.device_id if owner else None,
                "issues": self.status_snapshot()["agent"]["issues"],
            }
        if topic == "network.status":
            return {
                "available": self.network_available,
                "lan_address": self.lan_address,
                "tcp_port": self.tcp_port,
                "udp_port": self.udp_port,
                "mdns_service": "_cardbridge._tcp",
            }
        if topic == "codex.sessions":
            return self.agents.snapshot(8, acknowledged=device.ack_cursors)
        if topic == "codex.usage":
            # Device lines remain capped at 4096 bytes even when the local
            # App Server has eight sessions with long opaque IDs and full
            # total/last/delta breakdowns. The owner-only App snapshot keeps
            # the complete bounded store; device clients receive the newest
            # four records, which is enough for the live stream and leaves
            # wire headroom for the authenticated envelope.
            return self.usage.snapshot(limit=4)
        return {}

    async def _send_topic(
        self,
        device: DeviceSession,
        topic: str,
        message_type: str,
        request_id: object = None,
    ) -> None:
        message: dict[str, Any] = {
            "t": message_type,
            "topic": topic,
            "schema": 1,
            "seq": device.next_topic_sequence(topic),
            "generated_at_ms": int(time.time() * 1000),
            "data": self._topic_data(device, topic),
            "token": device.token,
        }
        if request_id is not None:
            message["id"] = request_id
        await self._send(device.writer, message)

    async def _flush_topic_subscriptions(self) -> None:
        timestamp = int(time.time() * 1000)
        for device in tuple(self.registry.all()):
            if (
                not self._session_is_current(device)
                or not device.pending_topics
                or device.writer.is_closing()
            ):
                continue
            for topic in tuple(device.pending_topics):
                if topic not in device.subscriptions:
                    device.pending_topics.discard(topic)
                    continue
                last_sent = device.subscription_last_sent_ms.get(topic, 0)
                if timestamp - last_sent < device.min_interval_ms:
                    continue
                try:
                    await self._send_topic(device, topic, "sync_update")
                except (asyncio.TimeoutError, ConnectionError, OSError, ProtocolError):
                    self._close_failed_writer(device.writer)
                    break
                if not self._session_is_current(device):
                    break
                device.subscription_last_sent_ms[topic] = timestamp
                device.pending_topics.discard(topic)

    async def _handle_audio_claim(self, device: DeviceSession) -> None:
        if not device.has_capability("audio.lease.v1"):
            await self._send_capability_error(
                device.writer, device.token, "audio.lease.v1"
            )
            return
        owner = self._audio_owner()
        if owner is not None and owner is not device:
            await self._send(
                device.writer,
                {
                    "t": "audio_lease",
                    "state": "busy",
                    "owner_id": owner.device_id,
                    "token": device.token,
                },
            )
            return
        self._set_audio_lease(device)
        await self._send(
            device.writer,
            {
                "t": "audio_lease",
                "state": "owner",
                "owner_id": device.device_id,
                "token": device.token,
            },
        )

    async def _handle_audio_release(self, device: DeviceSession) -> None:
        if not device.has_capability("audio.lease.v1"):
            await self._send_capability_error(
                device.writer, device.token, "audio.lease.v1"
            )
            return
        owner = self._audio_owner()
        if owner is not device:
            await self._send(
                device.writer,
                {
                    "t": "audio_lease",
                    "state": "busy" if owner else "available",
                    "owner_id": owner.device_id if owner else None,
                    "token": device.token,
                },
            )
            return
        self._release_audio_lease(device)
        await self._send(
            device.writer,
            {
                "t": "audio_lease",
                "state": "released",
                "owner_id": None,
                "token": device.token,
            },
        )

    def _show_pair_code(self, request: PairingRequest) -> None:
        self.pairing_status = {
            "device_id": request.device_id,
            "code": request.code,
            "created_at_ms": request.created_at_ms,
        }
        self._status_changed()
        # flush + log: stdout is block-buffered when redirected to a file, and
        # the code must be visible wherever the operator is watching.
        print("\n" + "=" * 50, flush=True)
        print(f"CardBridge pairing code for {request.device_id}: {request.code}", flush=True)
        print("Enter this code on the device.", flush=True)
        print("=" * 50 + "\n", flush=True)
        LOG.info("pairing code for %s: %s", request.device_id, request.code)
        if platform.system() == "Darwin" and not self.dry_run:
            script = f'display notification "Code: {request.code}" with title "CardBridge pairing"'
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
        # A source IP may host multiple devices. Validate the HMAC against each
        # token and route the datagram to the matching DeviceSession, never to a
        # global jitter queue.
        for device in tuple(self.registry.all()):
            if device.peer_ip != peer_ip:
                continue
            try:
                packet = unpack_audio(device.token, datagram)
            except ProtocolError:
                continue
            if not device.has_capability("audio.pcm16-16k.v1"):
                device.audio_invalid_packets += 1
                return
            if self.audio_lease_owner_id is None:
                # Clear any packets cached while this device was previously a
                # non-owner before selecting it. The current packet is fed
                # after _set_audio_lease so it becomes the new stream's first
                # real frame instead of being cleared as stale data.
                self._set_audio_lease(device)
            elif self.audio_lease_owner_id != device.device_id:
                # Non-owner packets are authenticated and counted, but must
                # not accumulate an old stream that could leak across a later
                # lease handoff.
                device.jitter.reset()
            device.jitter.feed(packet.sequence, packet.payload)
            device.touch_audio()
            if self.audio_lease_owner_id == device.device_id:
                # The output callback already reads this exact session buffer.
                self.audio.jitter = device.jitter
            if self.audio_lease_owner_id == device.device_id and self._record_path is not None:
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
