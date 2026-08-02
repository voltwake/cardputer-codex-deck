from __future__ import annotations

import unittest

from cardbridge._generated_version import (
    DEVICE_PROTOCOL_MAJOR,
    DEVICE_PROTOCOL_MINOR,
)
from cardbridge.protocol import ProtocolError
from cardbridge.versioning import CompatibilityError, negotiate_device


class DeviceVersioningTests(unittest.TestCase):
    def test_missing_protocol_is_accepted_as_legacy_v1(self) -> None:
        result = negotiate_device({"t": "hello"})
        self.assertTrue(result.legacy)
        self.assertEqual(result.protocol_major, 1)
        self.assertEqual(result.negotiated_minor, 0)
        self.assertIn("control.keys.v1", result.capabilities)
        self.assertNotIn("agents.phase.v1", result.capabilities)

    def test_current_protocol_intersects_capabilities_and_negotiates_minor(self) -> None:
        result = negotiate_device(
            {
                "device": {
                    "model": "cardputer-adv",
                    "firmware": "0.2.0",
                    "build": 1,
                },
                "protocol": {"major": DEVICE_PROTOCOL_MAJOR, "minor": 99},
                "capabilities": ["control.keys.v1", "agents.phase.v1", "future.v9"],
            }
        )
        self.assertFalse(result.legacy)
        self.assertEqual(result.negotiated_minor, DEVICE_PROTOCOL_MINOR)
        self.assertEqual(
            result.capabilities,
            ("agents.phase.v1", "control.keys.v1"),
        )
        self.assertEqual(result.model, "cardputer-adv")
        self.assertEqual(result.firmware_build, "1")

    def test_unknown_protocol_major_returns_structured_upgrade(self) -> None:
        with self.assertRaises(CompatibilityError) as caught:
            negotiate_device(
                {
                    "device": {"firmware": "9.0.0"},
                    "protocol": {"major": 99, "minor": 0},
                }
            )
        response = caught.exception.response()
        self.assertEqual(response["t"], "upgrade_required")
        self.assertEqual(response["reason"], "protocol_major")
        self.assertEqual(response["current"]["protocol_major"], 99)
        self.assertEqual(
            response["required"]["protocol_major"],
            DEVICE_PROTOCOL_MAJOR,
        )

    def test_known_firmware_below_minimum_is_rejected(self) -> None:
        with self.assertRaises(CompatibilityError) as caught:
            negotiate_device(
                {
                    "device": {"firmware": "0.0.1"},
                    "protocol": {
                        "major": DEVICE_PROTOCOL_MAJOR,
                        "minor": DEVICE_PROTOCOL_MINOR,
                    },
                }
            )
        self.assertEqual(caught.exception.reason, "firmware_too_old")

    def test_malformed_protocol_is_not_treated_as_a_version_mismatch(self) -> None:
        with self.assertRaises(ProtocolError):
            negotiate_device({"protocol": {"major": True, "minor": 0}})


if __name__ == "__main__":
    unittest.main()
