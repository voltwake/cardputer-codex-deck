from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .audio import JitterBuffer
from .versioning import DeviceCompatibility


MAX_ACK_CURSORS = 64


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class PairingRequest:
    """One isolated short-code challenge for one TCP connection."""

    connection_id: int
    device_id: str
    code: str
    created_at_ms: int = field(default_factory=now_ms)
    expires_at_ms: int = 0
    failures: int = 0
    vendor: str = ""
    name: str = ""
    model: str = ""

    def __post_init__(self) -> None:
        if self.expires_at_ms <= 0:
            self.expires_at_ms = self.created_at_ms + 5 * 60 * 1000

    @property
    def expired(self) -> bool:
        return now_ms() >= self.expires_at_ms

    def snapshot(self) -> dict[str, object]:
        # The code is intentionally exposed only through the owner-only local
        # control snapshot. It is never included in device or diagnostic data.
        return {
            "connection_id": self.connection_id,
            "device_id": self.device_id,
            "code": self.code,
            "created_at_ms": self.created_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "failures": self.failures,
            "vendor": self.vendor,
            "name": self.name,
            "model": self.model,
        }


@dataclass
class DeviceSession:
    """All mutable state belonging to exactly one authenticated connection."""

    device_id: str
    peer_ip: str
    token: str = field(repr=False)
    compatibility: DeviceCompatibility = field(repr=False)
    writer: Any = field(default=None, repr=False, compare=False)
    jitter: JitterBuffer = field(default_factory=JitterBuffer, repr=False, compare=False)
    connected_at_ms: int = field(default_factory=now_ms)
    last_seen_ms: int = field(default_factory=now_ms)
    last_audio_ms: int = 0
    audio_packets: int = 0
    audio_invalid_packets: int = 0
    held_keys: dict[str, list[str]] = field(default_factory=dict)
    subscriptions: set[str] = field(default_factory=set)
    min_interval_ms: int = 1000
    subscription_last_sent_ms: dict[str, int] = field(default_factory=dict)
    pending_topics: set[str] = field(default_factory=set)
    topic_sequences: dict[str, int] = field(default_factory=dict)
    ack_cursors: dict[str, int] = field(default_factory=dict)
    audio_lease_state: str = "none"
    replaced: bool = False

    @property
    def vendor(self) -> str:
        return self.compatibility.vendor or "unknown"

    @property
    def name(self) -> str:
        return (
            self.compatibility.name
            or self.compatibility.model
            or ("Cardputer" if self.compatibility.legacy else "Device")
        )

    @property
    def model(self) -> str:
        return self.compatibility.model or "unknown"

    @property
    def capabilities(self) -> tuple[str, ...]:
        return self.compatibility.capabilities

    def has_capability(self, capability: str) -> bool:
        return capability in self.compatibility.capabilities

    def touch(self) -> None:
        self.last_seen_ms = now_ms()

    def touch_audio(self) -> None:
        timestamp = now_ms()
        self.last_seen_ms = timestamp
        self.last_audio_ms = timestamp
        self.audio_packets += 1

    def next_topic_sequence(self, topic: str) -> int:
        sequence = self.topic_sequences.get(topic, 0) + 1
        self.topic_sequences[topic] = sequence
        return sequence

    def acknowledge(self, session_id: str, updated_ms: int) -> None:
        # Keep the cursor map bounded and refresh insertion order when an
        # existing session is acknowledged again. Codex sessions are already
        # bounded, but a long-lived device can otherwise retain IDs that have
        # aged out of the shared store forever.
        self.ack_cursors.pop(session_id, None)
        self.ack_cursors[session_id] = updated_ms
        while len(self.ack_cursors) > MAX_ACK_CURSORS:
            oldest = next(iter(self.ack_cursors))
            self.ack_cursors.pop(oldest, None)

    def is_acknowledged(self, session_id: str, updated_ms: int) -> bool:
        return self.ack_cursors.get(session_id) == updated_ms

    def snapshot(self, *, audio_owner_id: str | None = None) -> dict[str, object]:
        return {
            "id": self.device_id,
            "name": self.name,
            "vendor": self.vendor,
            "model": self.model,
            "ip": self.peer_ip,
            "firmware": self.compatibility.firmware_version or "unknown",
            "firmware_build": self.compatibility.firmware_build or "unknown",
            "protocol": {
                "major": self.compatibility.protocol_major,
                "minor": self.compatibility.negotiated_minor,
            },
            "compatibility": "legacy" if self.compatibility.legacy else "ok",
            "capabilities": list(self.compatibility.capabilities),
            "connected_at_ms": self.connected_at_ms,
            "last_seen_ms": self.last_seen_ms,
            "audio_packets": self.audio_packets,
            "audio_invalid_packets": self.audio_invalid_packets,
            "audio_lease": (
                "owner"
                if audio_owner_id == self.device_id
                else ("busy" if audio_owner_id else "available")
            ),
            "subscriptions": sorted(self.subscriptions),
            "min_interval_ms": self.min_interval_ms,
        }


# The old name is kept for code and integrations that imported the status type
# before DeviceSession became the canonical model.
ConnectedDevice = DeviceSession


class DeviceRegistry:
    """Single source of truth for authenticated online device sessions."""

    def __init__(self) -> None:
        self._by_id: dict[str, DeviceSession] = {}
        self._by_connection: dict[int, DeviceSession] = {}
        self._pairings: dict[int, PairingRequest] = {}

    @property
    def sessions(self) -> dict[str, DeviceSession]:
        return self._by_id

    def register(self, session: DeviceSession) -> DeviceSession | None:
        old = self._by_id.get(session.device_id)
        if old is not None and old is not session:
            old.replaced = True
            self._by_connection.pop(id(old.writer), None)
        self._by_id[session.device_id] = session
        self._by_connection[id(session.writer)] = session
        return old

    def get(self, device_id: str) -> DeviceSession | None:
        return self._by_id.get(device_id)

    def for_writer(self, writer: Any) -> DeviceSession | None:
        return self._by_connection.get(id(writer))

    def remove(self, session: DeviceSession) -> bool:
        self._by_connection.pop(id(session.writer), None)
        if self._by_id.get(session.device_id) is not session:
            return False
        self._by_id.pop(session.device_id, None)
        return True

    def by_token(self, token: str, peer_ip: str | None = None) -> DeviceSession | None:
        for session in self._by_id.values():
            if session.token == token and (peer_ip is None or session.peer_ip == peer_ip):
                return session
        return None

    def all(self) -> list[DeviceSession]:
        return sorted(self._by_id.values(), key=lambda item: item.connected_at_ms)

    def add_pairing(self, request: PairingRequest) -> None:
        self._pairings[request.connection_id] = request

    def pairing_for(self, connection_id: int) -> PairingRequest | None:
        request = self._pairings.get(connection_id)
        if request is not None and request.expired:
            self._pairings.pop(connection_id, None)
            return None
        return request

    def remove_pairing(self, connection_id: int) -> PairingRequest | None:
        return self._pairings.pop(connection_id, None)

    def pairing_snapshots(self) -> list[dict[str, object]]:
        for connection_id, request in tuple(self._pairings.items()):
            if request.expired:
                self._pairings.pop(connection_id, None)
        return [
            request.snapshot()
            for request in sorted(
                self._pairings.values(), key=lambda item: item.created_at_ms
            )
        ]

    def clear(self) -> list[DeviceSession]:
        sessions = self.all()
        self._by_id.clear()
        self._by_connection.clear()
        self._pairings.clear()
        return sessions
