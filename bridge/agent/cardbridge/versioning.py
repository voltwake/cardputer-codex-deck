from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ._generated_version import (
    AGENT_BUILD,
    AGENT_VERSION,
    AGENT_CAPABILITIES,
    DEVICE_PROTOCOL_MAJOR,
    DEVICE_PROTOCOL_MINOR,
    MIN_FIRMWARE_VERSION,
    SUPPORT_LEGACY_PROTOCOL_1,
)
from .protocol import ProtocolError


_SEMVER = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)$")
_LEGACY_CAPABILITIES = frozenset(
    {
        "control.keys.v1",
        "audio.pcm16-16k.v1",
        "agents.snapshot.v1",
    }
)


def _semver(value: str) -> tuple[int, int, int] | None:
    match = _SEMVER.fullmatch(value)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _short_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\x00", "").split())[:limit]


def _build_text(value: object) -> str:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return str(value)
    return _short_text(value, 40)


@dataclass(frozen=True)
class DeviceCompatibility:
    protocol_major: int
    protocol_minor: int
    negotiated_minor: int
    legacy: bool
    capabilities: tuple[str, ...]
    vendor: str
    name: str
    model: str
    firmware_version: str
    firmware_build: str

    def response_metadata(self) -> dict[str, object]:
        return {
            "app": {"version": AGENT_VERSION, "build": AGENT_BUILD},
            "protocol": {
                "major": self.protocol_major,
                "minor": self.negotiated_minor,
            },
            "capabilities": list(self.capabilities),
            "compatibility": "legacy" if self.legacy else "ok",
        }


class CompatibilityError(Exception):
    def __init__(
        self,
        reason: str,
        *,
        current: dict[str, object],
        required: dict[str, object],
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.current = current
        self.required = required

    def response(self) -> dict[str, object]:
        return {
            "t": "upgrade_required",
            "reason": self.reason,
            "current": self.current,
            "required": self.required,
            "app": {"version": AGENT_VERSION, "build": AGENT_BUILD},
        }


def negotiate_device(message: dict[str, Any]) -> DeviceCompatibility:
    device = message.get("device")
    if device is None:
        device = {}
    if not isinstance(device, dict):
        raise ProtocolError("device metadata must be an object")
    vendor = _short_text(device.get("vendor"), 48)
    name = _short_text(device.get("name"), 64)
    model = _short_text(device.get("model"), 48)
    firmware_version = _short_text(device.get("firmware"), 24)
    firmware_build = _build_text(device.get("build"))

    raw_protocol = message.get("protocol")
    if raw_protocol is None:
        if not SUPPORT_LEGACY_PROTOCOL_1:
            raise CompatibilityError(
                "legacy_protocol_disabled",
                current={"firmware": firmware_version or "unknown", "protocol_major": 1},
                required={
                    "min_firmware": MIN_FIRMWARE_VERSION,
                    "protocol_major": DEVICE_PROTOCOL_MAJOR,
                },
            )
        return DeviceCompatibility(
            protocol_major=1,
            protocol_minor=0,
            negotiated_minor=0,
            legacy=True,
            capabilities=tuple(sorted(_LEGACY_CAPABILITIES)),
            vendor=vendor,
            name=name,
            model=model,
            firmware_version=firmware_version,
            firmware_build=firmware_build,
        )
    if not isinstance(raw_protocol, dict):
        raise ProtocolError("protocol metadata must be an object")
    major = raw_protocol.get("major")
    minor = raw_protocol.get("minor")
    if (
        not isinstance(major, int)
        or isinstance(major, bool)
        or not isinstance(minor, int)
        or isinstance(minor, bool)
        or major < 0
        or minor < 0
    ):
        raise ProtocolError("protocol major/minor must be non-negative integers")

    legacy = major == 1 and SUPPORT_LEGACY_PROTOCOL_1
    if major != DEVICE_PROTOCOL_MAJOR and not legacy:
        raise CompatibilityError(
            "protocol_major",
            current={"firmware": firmware_version or "unknown", "protocol_major": major},
            required={
                "min_firmware": MIN_FIRMWARE_VERSION,
                "protocol_major": DEVICE_PROTOCOL_MAJOR,
            },
        )

    parsed_firmware = _semver(firmware_version) if firmware_version else None
    minimum_firmware = _semver(MIN_FIRMWARE_VERSION)
    if parsed_firmware is not None and minimum_firmware is not None:
        if parsed_firmware < minimum_firmware:
            raise CompatibilityError(
                "firmware_too_old",
                current={"firmware": firmware_version, "protocol_major": major},
                required={
                    "min_firmware": MIN_FIRMWARE_VERSION,
                    "protocol_major": DEVICE_PROTOCOL_MAJOR,
                },
            )

    raw_capabilities = message.get("capabilities", [])
    if not isinstance(raw_capabilities, list):
        raise ProtocolError("capabilities must be an array")
    clean_capabilities = {
        item for item in raw_capabilities
        if isinstance(item, str) and 0 < len(item) <= 64
    }
    supported = _LEGACY_CAPABILITIES if legacy else frozenset(AGENT_CAPABILITIES)
    negotiated = tuple(sorted(clean_capabilities & supported))
    return DeviceCompatibility(
        protocol_major=major,
        protocol_minor=minor,
        negotiated_minor=0 if legacy else min(minor, DEVICE_PROTOCOL_MINOR),
        legacy=legacy,
        capabilities=negotiated,
        vendor=vendor,
        name=name,
        model=model,
        firmware_version=firmware_version,
        firmware_build=firmware_build,
    )
