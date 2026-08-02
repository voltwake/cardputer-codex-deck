from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cardbridge._generated_version import CONFIG_SCHEMA
from cardbridge.config import BridgeConfig
from cardbridge.protocol import (
    AUDIO_PAYLOAD_SIZE,
    MAX_JSON_LINE,
    ProtocolError,
    decode_message,
    encode_message,
    pack_audio,
    unpack_audio,
)


class ProtocolTests(unittest.TestCase):
    def test_audio_round_trip_and_authentication(self) -> None:
        token = "12" * 32
        payload = bytes((index % 251 for index in range(AUDIO_PAYLOAD_SIZE)))
        datagram = pack_audio(token, 42, 123_456, payload)
        packet = unpack_audio(token, datagram)
        self.assertEqual(packet.sequence, 42)
        self.assertEqual(packet.timestamp_ms, 123_456)
        self.assertEqual(packet.payload, payload)

        corrupted = datagram[:-1] + bytes([datagram[-1] ^ 1])
        with self.assertRaises(ProtocolError):
            unpack_audio(token, corrupted)

    def test_json_line_round_trip(self) -> None:
        message = {"t": "key", "k": "\\", "m": ["cmd"], "a": "down"}
        self.assertEqual(decode_message(encode_message(message)), message)
        with self.assertRaises(ProtocolError):
            decode_message(json.dumps(["not", "an", "object"]).encode())

    def test_json_line_uses_compact_utf8_for_session_titles(self) -> None:
        message = {"t": "agent_status", "title": "会话管理与宠物动画"}
        encoded = encode_message(message)
        self.assertNotIn(b"\\u", encoded)
        self.assertEqual(decode_message(encoded), message)

    def test_json_encoder_rejects_records_above_device_limit(self) -> None:
        with self.assertRaises(ProtocolError):
            encode_message({"t": "oversized", "value": "x" * MAX_JSON_LINE})


class ConfigTests(unittest.TestCase):
    def test_production_config_directory_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config_directory = home / ".cardbridge"
            config_directory.mkdir(mode=0o755)
            with patch.object(Path, "home", return_value=home):
                BridgeConfig()
            self.assertEqual(os.stat(config_directory).st_mode & 0o777, 0o700)
            self.assertEqual(
                os.stat(config_directory / "config.json").st_mode & 0o777,
                0o600,
            )

    def test_pairing_persists_a_32_byte_random_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config = BridgeConfig(path)
            token = config.pair("device-1")
            self.assertEqual(len(bytes.fromhex(token)), 32)
            self.assertTrue(config.validate("device-1", token))
            self.assertFalse(config.validate("device-2", token))
            reloaded = BridgeConfig(path)
            self.assertEqual(reloaded.token_for("device-1"), token)
            self.assertEqual(reloaded.data["config_schema"], CONFIG_SCHEMA)
            self.assertNotIn("version", reloaded.data)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_plaintext_pairing_token_is_migrated_to_external_store(self) -> None:
        class MemoryTokenStore:
            def __init__(self) -> None:
                self.tokens: dict[str, str] = {}

            def get(self, device_id: str) -> str | None:
                return self.tokens.get(device_id)

            def put(self, device_id: str, token: str) -> None:
                self.tokens[device_id] = token

            def delete(self, device_id: str) -> None:
                self.tokens.pop(device_id, None)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            token = "ab" * 32
            path.write_text(
                json.dumps(
                    {
                        "config_schema": CONFIG_SCHEMA,
                        "bridge_id": "bridge-keychain-test",
                        "mac_name": "Test Mac",
                        "devices": {
                            "device-1": {
                                "name": "Cardputer",
                                "token": token,
                                "paired_at": 123,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            store = MemoryTokenStore()
            config = BridgeConfig(path, token_store=store)

            self.assertEqual(config.token_for("device-1"), token)
            self.assertEqual(store.tokens["device-1"], token)
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("token", persisted["devices"]["device-1"])

            reloaded = BridgeConfig(path, token_store=store)
            self.assertTrue(reloaded.validate("device-1", token))
            self.assertTrue(reloaded.unpair("device-1"))
            self.assertNotIn("device-1", store.tokens)

    def test_legacy_config_schema_is_migrated_without_changing_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "bridge_id": "bridge-123",
                        "mac_name": "Test Mac",
                        "devices": {},
                    }
                ),
                encoding="utf-8",
            )
            config = BridgeConfig(path)
            self.assertEqual(config.bridge_id, "bridge-123")
            self.assertEqual(config.mac_name, "Test Mac")
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["config_schema"], CONFIG_SCHEMA)
            self.assertNotIn("version", persisted)

    def test_newer_config_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps({"config_schema": CONFIG_SCHEMA + 1}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "newer than supported"):
                BridgeConfig(path)


if __name__ == "__main__":
    unittest.main()
