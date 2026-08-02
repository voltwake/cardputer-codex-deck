from __future__ import annotations

import asyncio
import json
import socket
import struct
import tempfile
import time
import unittest
from pathlib import Path

from cardbridge._generated_version import AGENT_CAPABILITIES, FIRMWARE_CAPABILITIES
from cardbridge.protocol import encode_message, pack_audio
from cardbridge.server import BridgeApp


class MultiDeviceServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        codes = iter(["111111", "222222", "333333", "444444", "555555"])
        self.app = BridgeApp(
            host="127.0.0.1",
            tcp_port=0,
            udp_port=0,
            config_path=Path(self.temporary.name) / "config.json",
            no_audio=True,
            dry_run=True,
            advertise=False,
            enable_agents=False,
            pair_code_factory=lambda: next(codes),
        )
        await self.app.start()

    async def asyncTearDown(self) -> None:
        await self.app.stop()
        self.temporary.cleanup()

    async def read(self, reader: asyncio.StreamReader) -> dict[str, object]:
        return json.loads(await asyncio.wait_for(reader.readline(), 2))

    async def read_until(
        self, reader: asyncio.StreamReader, predicate: object
    ) -> dict[str, object]:
        for _ in range(8):
            message = await self.read(reader)
            if callable(predicate) and predicate(message):
                return message
        raise AssertionError("expected protocol message was not received")

    async def connect(
        self,
        device_id: str,
        *,
        pair_code: str | None = None,
        token: str | None = None,
        capabilities: list[str] | None = None,
        protocol_minor: int = 1,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, str]:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.app.tcp_port)
        declared = list(AGENT_CAPABILITIES if capabilities is None else capabilities)
        writer.write(
            encode_message(
                {
                    "t": "hello",
                    "dev_id": device_id,
                    "token": token,
                    "device": {
                        "vendor": "waveshare",
                        "model": "esp32-s3-touch-amoled-1.75c",
                        "name": device_id,
                        "firmware": "0.3.0",
                        "build": 1,
                    },
                    "protocol": {"major": 2, "minor": protocol_minor},
                    "capabilities": declared,
                }
            )
        )
        await writer.drain()
        response = await self.read(reader)
        if response["t"] == "pair_required":
            assert pair_code is not None
            writer.write(encode_message({"t": "pair", "code": pair_code}))
            await writer.drain()
            response = await self.read(reader)
        self.assertIn(response["t"], {"paired", "hello_ok"})
        session_token = token or str(response["token"])
        if "agents.snapshot.v1" in declared:
            self.assertEqual((await self.read(reader))["t"], "agent_status")
        return reader, writer, session_token

    async def test_two_vendor_neutral_devices_sync_keyboard_and_audio_are_isolated(self) -> None:
        reader_a, writer_a, token_a = await self.connect("waveshare-a", pair_code="111111")
        reader_b, writer_b, token_b = await self.connect("waveshare-b", pair_code="222222")
        self.assertEqual(len(self.app.status_snapshot()["devices"]), 2)
        self.assertEqual(
            self.app.status_snapshot()["devices"][0]["model"],
            "esp32-s3-touch-amoled-1.75c",
        )

        writer_a.write(
            encode_message(
                {
                    "t": "sync_req",
                    "id": 7,
                    "topics": ["bridge.status", "network.status", "codex.usage"],
                    "token": token_a,
                }
            )
        )
        await writer_a.drain()
        responses = [await self.read(reader_a) for _ in range(3)]
        self.assertEqual({item["t"] for item in responses}, {"sync_snapshot"})
        self.assertEqual(
            {item["topic"] for item in responses},
            {"bridge.status", "network.status", "codex.usage"},
        )

        for device_token in (token_a, token_b):
            writer = writer_a if device_token == token_a else writer_b
            writer.write(
                encode_message(
                    {"t": "key", "k": "x", "a": "down", "m": [], "token": device_token}
                )
            )
            await writer.drain()
        await asyncio.sleep(0.03)
        writer_a.write(encode_message({"t": "key", "k": "x", "a": "up", "m": [], "token": token_a}))
        writer_b.write(encode_message({"t": "key", "k": "x", "a": "up", "m": [], "token": token_b}))
        await writer_a.drain()
        await writer_b.drain()
        await asyncio.sleep(0.03)
        self.assertEqual(
            [(item["k"], item["a"]) for item in self.app.keyboard.events],
            [("x", "down"), ("x", "up")],
        )

        payload = struct.pack("<320h", *([321] * 320))
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.sendto(pack_audio(token_a, 1, 1, payload), ("127.0.0.1", self.app.udp_port))
        udp.sendto(pack_audio(token_b, 1, 1, payload), ("127.0.0.1", self.app.udp_port))
        udp.close()
        await asyncio.sleep(0.05)
        session_a = self.app.registry.get("waveshare-a")
        session_b = self.app.registry.get("waveshare-b")
        assert session_a is not None and session_b is not None
        self.assertEqual(session_a.audio_packets, 1)
        self.assertEqual(session_b.audio_packets, 1)
        self.assertEqual(self.app.audio_lease_owner_id, "waveshare-a")
        self.assertIs(self.app.audio.jitter, session_a.jitter)
        lease_snapshot = {
            item["id"]: item["audio_lease"]
            for item in self.app.status_snapshot()["devices"]
        }
        self.assertEqual(lease_snapshot, {"waveshare-a": "owner", "waveshare-b": "busy"})

        self.app._release_audio_lease(session_a)
        # B accumulated a non-owner packet above. It must not leak into the
        # new stream, and the first frame after takeover must be B's fresh data.
        fresh_payload = struct.pack("<320h", *([654] * 320))
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for sequence in range(2, 7):
            udp.sendto(
                pack_audio(token_b, sequence, sequence, fresh_payload),
                ("127.0.0.1", self.app.udp_port),
            )
        udp.close()
        await asyncio.sleep(0.05)
        self.assertEqual(self.app.audio_lease_owner_id, "waveshare-b")
        self.assertIs(self.app.audio.jitter, session_b.jitter)
        self.assertEqual(self.app.audio.jitter.read_samples(320), [654] * 320)
        lease_snapshot = {
            item["id"]: item["audio_lease"]
            for item in self.app.status_snapshot()["devices"]
        }
        self.assertEqual(lease_snapshot, {"waveshare-a": "busy", "waveshare-b": "owner"})
        writer_a.close()
        await writer_a.wait_closed()
        await asyncio.sleep(0.03)
        self.assertIsNotNone(self.app.registry.get("waveshare-b"))
        writer_b.close()
        await writer_b.wait_closed()

    async def test_different_keys_and_last_same_key_holder_have_stable_injection(self) -> None:
        reader_a, writer_a, token_a = await self.connect("keys-a", pair_code="111111")
        reader_b, writer_b, token_b = await self.connect("keys-b", pair_code="222222")
        async def send_key(
            writer: asyncio.StreamWriter,
            token: str,
            key: str,
            action: str,
            modifiers: list[str],
        ) -> None:
            writer.write(
                encode_message(
                    {"t": "key", "k": key, "a": action, "m": modifiers, "token": token}
                )
            )
            await writer.drain()
            await asyncio.sleep(0.02)

        await send_key(writer_a, token_a, "a", "down", ["shift"])
        await send_key(writer_b, token_b, "b", "down", [])
        await send_key(writer_a, token_a, "a", "up", ["shift"])
        await send_key(writer_b, token_b, "b", "up", [])
        # Both devices hold the same key, but only the first down and final up
        # reach macOS. The final up retains the modifiers from the injected
        # first holder even if a later holder used a different modifier set.
        await send_key(writer_a, token_a, "x", "down", ["cmd"])
        await send_key(writer_b, token_b, "x", "down", [])
        await send_key(writer_a, token_a, "x", "up", ["cmd"])
        await send_key(writer_b, token_b, "x", "up", [])
        self.assertEqual(
            [(item["k"], item["a"], item["m"]) for item in self.app.keyboard.events],
            [
                ("a", "down", ["shift"]),
                ("b", "down", []),
                ("a", "up", ["shift"]),
                ("b", "up", []),
                ("x", "down", ["cmd"]),
                ("x", "up", ["cmd"]),
            ],
        )
        writer_a.close()
        writer_b.close()
        await writer_a.wait_closed()
        await writer_b.wait_closed()

    async def test_same_id_replacement_clears_subscription_and_audio_lease(self) -> None:
        reader_a, writer_a, token = await self.connect("replace-all", pair_code="111111")
        writer_a.write(
            encode_message(
                {
                    "t": "sync_subscribe",
                    "id": 1,
                    "topics": ["bridge.status"],
                    "token": token,
                }
            )
        )
        await writer_a.drain()
        self.assertEqual((await self.read(reader_a))["t"], "sync_subscribed")
        payload = struct.pack("<320h", *([321] * 320))
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.sendto(pack_audio(token, 1, 1, payload), ("127.0.0.1", self.app.udp_port))
        udp.close()
        await asyncio.sleep(0.05)
        old = self.app.registry.get("replace-all")
        assert old is not None
        self.assertEqual(self.app.audio_lease_owner_id, "replace-all")

        reader_b, writer_b, _ = await self.connect("replace-all", token=token)
        for _ in range(8):
            if not await asyncio.wait_for(reader_a.readline(), 2):
                break
        else:
            self.fail("replaced device connection did not close")
        writer_a.close()
        await writer_a.wait_closed()
        self.assertEqual(len(self.app.status_snapshot()["devices"]), 1)
        self.assertEqual(old.held_keys, {})
        self.assertEqual(old.subscriptions, set())
        self.assertEqual(old.audio_lease_state, "none")
        self.assertIsNone(self.app.audio_lease_owner_id)

        writer_b.close()
        await writer_b.wait_closed()

    async def test_audio_lease_expires_after_owner_silence(self) -> None:
        _reader, writer, token = await self.connect("silent-owner", pair_code="111111")
        payload = struct.pack("<320h", *([222] * 320))
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.sendto(pack_audio(token, 1, 1, payload), ("127.0.0.1", self.app.udp_port))
        udp.close()
        await asyncio.sleep(0.05)
        owner = self.app.registry.get("silent-owner")
        assert owner is not None
        self.assertEqual(self.app.audio_lease_owner_id, "silent-owner")
        owner.last_audio_ms = int(time.time() * 1000) - self.app.audio_lease_idle_ms - 1
        self.app._expire_audio_lease()
        self.assertIsNone(self.app.audio_lease_owner_id)
        self.assertEqual(owner.audio_lease_state, "none")
        writer.close()
        await writer.wait_closed()

    async def test_current_m5_profile_keeps_legacy_wire_behavior_and_auto_claims_audio(self) -> None:
        reader, writer, token = await self.connect(
            "current-m5",
            pair_code="111111",
            capabilities=list(FIRMWARE_CAPABILITIES),
            protocol_minor=0,
        )
        session = self.app.registry.get("current-m5")
        assert session is not None
        self.assertEqual(session.compatibility.legacy, False)
        self.assertNotIn("sync.subscribe.v1", session.capabilities)
        self.assertNotIn("usage.tokens.v1", session.capabilities)
        self.assertNotIn("audio.lease.v1", session.capabilities)

        writer.write(encode_message({"t": "ping", "token": token}))
        await writer.drain()
        self.assertEqual((await self.read(reader))["t"], "pong")
        payload = struct.pack("<320h", *([111] * 320))
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.sendto(pack_audio(token, 4, 4, payload), ("127.0.0.1", self.app.udp_port))
        udp.close()
        await asyncio.sleep(0.05)
        self.assertEqual(self.app.audio_lease_owner_id, "current-m5")
        self.assertIs(self.app.audio.jitter, session.jitter)

        self.app.agents.apply_hook_event(
            {"event": "Stop", "session_id": "legacy-session", "timestamp_ms": 1234}
        )
        self.assertEqual((await self.read(reader))["t"], "agent_status")
        self.app.usage.update_notification(
            {
                "threadId": "legacy-session",
                "turnId": "legacy-turn",
                "timestamp_ms": 2000,
                "tokenUsage": {"total": {"totalTokens": 12}},
            }
        )
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(reader.readline(), 0.05)
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(reader.readline(), 0.05)
        writer.close()
        await writer.wait_closed()

    async def test_concurrent_pairing_requests_and_failures_are_isolated(self) -> None:
        reader_a, writer_a = await asyncio.open_connection("127.0.0.1", self.app.tcp_port)
        reader_b, writer_b = await asyncio.open_connection("127.0.0.1", self.app.tcp_port)
        for writer, device_id in ((writer_a, "pending-a"), (writer_b, "pending-b")):
            writer.write(
                encode_message(
                    {
                        "t": "hello",
                        "dev_id": device_id,
                        "token": None,
                        "device": {"vendor": "test", "model": "board"},
                    }
                )
            )
            await writer.drain()
        self.assertEqual((await self.read(reader_a))["t"], "pair_required")
        self.assertEqual((await self.read(reader_b))["t"], "pair_required")
        self.assertEqual(
            {item["device_id"] for item in self.app.status_snapshot()["pairings"]},
            {"pending-a", "pending-b"},
        )
        for _ in range(2):
            writer_a.write(encode_message({"t": "pair", "code": "000000"}))
            await writer_a.drain()
            self.assertEqual((await self.read(reader_a))["t"], "pair_error")
        writer_b.write(encode_message({"t": "pair", "code": "222222"}))
        await writer_b.drain()
        self.assertEqual((await self.read(reader_b))["t"], "paired")
        writer_a.write(encode_message({"t": "pair", "code": "111111"}))
        await writer_a.drain()
        self.assertEqual((await self.read(reader_a))["t"], "paired")
        writer_a.close()
        writer_b.close()
        await writer_a.wait_closed()
        await writer_b.wait_closed()

    async def test_same_id_replacement_releases_old_keys_without_duplicate_online_device(self) -> None:
        reader_a, writer_a, token = await self.connect("replace-me", pair_code="111111")
        writer_a.write(encode_message({"t": "key", "k": "z", "a": "down", "m": [], "token": token}))
        await writer_a.drain()
        await asyncio.sleep(0.02)
        reader_b, writer_b, _ = await self.connect("replace-me", token=token)
        self.assertEqual(await asyncio.wait_for(reader_a.readline(), 2), b"")
        writer_a.close()
        await writer_a.wait_closed()
        self.assertEqual(len(self.app.status_snapshot()["devices"]), 1)
        writer_b.write(encode_message({"t": "key", "k": "z", "a": "up", "m": [], "token": token}))
        await writer_b.drain()
        await asyncio.sleep(0.03)
        self.assertEqual([(item["a"]) for item in self.app.keyboard.events], ["down", "up"])
        writer_b.close()
        await writer_b.wait_closed()

    async def test_capability_gate_rejects_unadvertised_topic(self) -> None:
        reader, writer, token = await self.connect(
            "minimal-device",
            pair_code="111111",
            capabilities=["control.keys.v1"],
        )
        writer.write(
            encode_message(
                {
                    "t": "sync_req",
                    "id": 9,
                    "topics": ["network.status"],
                    "token": token,
                }
            )
        )
        await writer.drain()
        response = await self.read(reader)
        self.assertEqual(response["code"], "capability_required")
        self.assertEqual(response["required_capability"], "network.status.v1")

        writer.write(
            encode_message(
                {
                    "t": "sync_req",
                    "id": "unsupported-topic",
                    "topics": ["future.topic"],
                    "token": token,
                }
            )
        )
        await writer.drain()
        response = await self.read(reader)
        self.assertEqual(response["t"], "error")
        self.assertEqual(response["code"], "unsupported_topic")
        self.assertEqual(response["topic"], "future.topic")
        self.assertEqual(response["id"], "unsupported-topic")

        writer.write(encode_message({"t": "ping", "token": token}))
        await writer.drain()
        self.assertEqual((await self.read(reader))["t"], "pong")
        writer.close()
        await writer.wait_closed()

    async def test_ack_cursor_is_per_device_and_subscription_is_clamped(self) -> None:
        reader_a, writer_a, token_a = await self.connect("ack-a", pair_code="111111")
        reader_b, writer_b, token_b = await self.connect("ack-b", pair_code="222222")
        writer_a.write(
            encode_message(
                {
                    "t": "sync_subscribe",
                    "id": 4,
                    "topics": ["bridge.status", "network.status", "codex.usage"],
                    "min_interval_ms": 1,
                    "token": token_a,
                }
            )
        )
        await writer_a.drain()
        subscribed = await self.read(reader_a)
        self.assertEqual(subscribed["t"], "sync_subscribed")
        self.assertEqual(subscribed["min_interval_ms"], 250)

        self.app.agents.apply_hook_event(
            {"event": "Stop", "session_id": "ack-session", "timestamp_ms": 1234}
        )
        await asyncio.sleep(0.03)
        await self.read_until(reader_a, lambda item: item.get("t") == "agent_status")
        status_b = await self.read_until(
            reader_b, lambda item: item.get("t") == "agent_status"
        )
        self.assertEqual(status_b["items"][0]["status"], "ready")
        self.assertTrue(status_b["items"][0]["unread"])

        writer_a.write(
            encode_message(
                {"t": "agent_ack", "id": "ack-session", "token": token_a}
            )
        )
        await writer_a.drain()
        acknowledged = await self.read_until(
            reader_a,
            lambda item: item.get("t") == "agent_status"
            and not item.get("items", [{}])[0].get("unread", True),
        )
        self.assertEqual(acknowledged["items"][0]["id"], "ack-session")
        self.assertEqual(acknowledged["items"][0]["status"], "idle")
        self.assertEqual(acknowledged["items"][0]["activity"], "Session ready")

        writer_b.write(
            encode_message(
                {
                    "t": "sync_req",
                    "id": 5,
                    "topics": ["codex.sessions"],
                    "token": token_b,
                }
            )
        )
        await writer_b.drain()
        sessions = await self.read(reader_b)
        self.assertEqual(sessions["t"], "sync_snapshot")
        self.assertTrue(sessions["data"]["items"][0]["unread"])
        self.assertEqual(sessions["data"]["items"][0]["status"], "ready")
        self.assertEqual(sessions["data"]["items"][0]["activity"], status_b["items"][0]["activity"])

        writer_a.close()
        writer_b.close()
        await writer_a.wait_closed()
        await writer_b.wait_closed()


if __name__ == "__main__":
    unittest.main()
