from __future__ import annotations

import hashlib
import hmac
import json
import struct
from dataclasses import dataclass
from typing import Any

AUDIO_SAMPLE_RATE = 16_000
AUDIO_SAMPLES_PER_FRAME = 320
AUDIO_PAYLOAD_SIZE = AUDIO_SAMPLES_PER_FRAME * 2
AUDIO_HEADER = struct.Struct("!II8s")
AUDIO_PACKET_SIZE = AUDIO_HEADER.size + AUDIO_PAYLOAD_SIZE
MAX_JSON_LINE = 4096
MIN_SUBSCRIPTION_INTERVAL_MS = 250
MAX_SUBSCRIPTION_INTERVAL_MS = 60_000
MAX_USAGE_STREAM_HZ = 4

# Topic capability requirements are deliberately data-driven. The Agent may
# support a topic globally, but a device only receives it after the capability
# was negotiated in its own hello.
TOPIC_READ_CAPABILITY = {
    "bridge.status": "bridge.status.v1",
    "network.status": "network.status.v1",
    "codex.sessions": "agents.snapshot.v1",
    "codex.usage": "usage.tokens.v1",
}
TOPIC_SUBSCRIPTION_CAPABILITIES = {
    "bridge.status": ("sync.subscribe.v1",),
    "network.status": ("sync.subscribe.v1",),
    "codex.sessions": ("sync.subscribe.v1",),
    "codex.usage": ("sync.subscribe.v1", "usage.tokens.stream.v1"),
}


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class AudioPacket:
    sequence: int
    timestamp_ms: int
    payload: bytes


def token_bytes(token: str) -> bytes:
    if len(token) != 64:
        raise ProtocolError("token must encode exactly 32 random bytes")
    try:
        return bytes.fromhex(token)
    except ValueError as exc:
        raise ProtocolError("token is not hexadecimal") from exc


def audio_hmac(token: str, sequence: int, timestamp_ms: int, payload: bytes) -> bytes:
    if len(payload) != AUDIO_PAYLOAD_SIZE:
        raise ProtocolError(f"audio payload must be {AUDIO_PAYLOAD_SIZE} bytes")
    authenticated = struct.pack("!II", sequence & 0xFFFFFFFF, timestamp_ms & 0xFFFFFFFF) + payload
    return hmac.new(token_bytes(token), authenticated, hashlib.sha256).digest()[:8]


def pack_audio(token: str, sequence: int, timestamp_ms: int, payload: bytes) -> bytes:
    signature = audio_hmac(token, sequence, timestamp_ms, payload)
    return AUDIO_HEADER.pack(sequence & 0xFFFFFFFF, timestamp_ms & 0xFFFFFFFF, signature) + payload


def unpack_audio(token: str, datagram: bytes) -> AudioPacket:
    if len(datagram) != AUDIO_PACKET_SIZE:
        raise ProtocolError(f"audio datagram must be {AUDIO_PACKET_SIZE} bytes")
    sequence, timestamp_ms, signature = AUDIO_HEADER.unpack_from(datagram)
    payload = datagram[AUDIO_HEADER.size :]
    expected = audio_hmac(token, sequence, timestamp_ms, payload)
    if not hmac.compare_digest(signature, expected):
        raise ProtocolError("audio HMAC mismatch")
    return AudioPacket(sequence, timestamp_ms, payload)


def encode_message(message: dict[str, Any]) -> bytes:
    # UTF-8 is both what ArduinoJson expects and materially smaller than six
    # byte ``\\uXXXX`` escapes for CJK session titles on the 4 KiB control
    # channel.
    encoded = (
        json.dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")
    if len(encoded) > MAX_JSON_LINE:
        raise ProtocolError("JSON line is too large")
    return encoded


def decode_message(line: bytes) -> dict[str, Any]:
    if len(line) > MAX_JSON_LINE:
        raise ProtocolError("JSON line is too large")
    try:
        value = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid JSON line") from exc
    if not isinstance(value, dict) or not isinstance(value.get("t"), str):
        raise ProtocolError("message must be an object with a string 't'")
    return value
