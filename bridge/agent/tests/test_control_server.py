from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path

from cardbridge._generated_version import AGENT_API_MAJOR, AGENT_API_MINOR, AGENT_VERSION
from cardbridge.control_server import AgentControlServer
from cardbridge.protocol import encode_message
from cardbridge.server import BridgeApp


class AgentControlServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "run" / "agent.sock"
        self.sequence = 1
        self.commands: list[dict[str, object]] = []

        def snapshot() -> dict[str, object]:
            return {"t": "snapshot", "seq": self.sequence, "devices": []}

        async def command(request: dict[str, object]) -> dict[str, object]:
            self.commands.append(request)
            return {"ok": True, "command": request.get("name")}

        self.server = AgentControlServer(self.path, snapshot, command)
        await self.server.start()

    async def asyncTearDown(self) -> None:
        await self.server.stop()
        self.temporary.cleanup()

    async def connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.open_unix_connection(self.path)
        writer.write(
            (
                json.dumps(
                    {
                        "t": "hello",
                        "api": {"major": AGENT_API_MAJOR, "minor": AGENT_API_MINOR},
                    }
                )
                + "\n"
            ).encode()
        )
        await writer.drain()
        response = json.loads(await asyncio.wait_for(reader.readline(), 2))
        self.assertEqual(response["t"], "hello_ok")
        return reader, writer

    async def test_socket_permissions_snapshot_subscription_and_command(self) -> None:
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.path.parent).st_mode & 0o777, 0o700)
        reader, writer = await self.connect()
        writer.write(b'{"t":"subscribe"}\n')
        await writer.drain()
        snapshot = json.loads(await asyncio.wait_for(reader.readline(), 2))
        self.assertEqual(snapshot["seq"], 1)

        self.sequence = 2
        await self.server.publish()
        published = json.loads(await asyncio.wait_for(reader.readline(), 2))
        self.assertEqual(published["seq"], 2)

        writer.write(b'{"t":"command","id":7,"name":"restart"}\n')
        await writer.drain()
        result = json.loads(await asyncio.wait_for(reader.readline(), 2))
        self.assertEqual(result, {"t": "result", "id": 7, "ok": True, "command": "restart"})
        self.assertEqual(self.commands[0]["name"], "restart")
        writer.close()
        await writer.wait_closed()

    async def test_api_major_mismatch_is_explicit(self) -> None:
        reader, writer = await asyncio.open_unix_connection(self.path)
        writer.write(b'{"t":"hello","api":{"major":99,"minor":0}}\n')
        await writer.drain()
        response = json.loads(await asyncio.wait_for(reader.readline(), 2))
        self.assertEqual(response["t"], "api_incompatible")
        self.assertEqual(response["required"]["major"], AGENT_API_MAJOR)
        self.assertEqual(await asyncio.wait_for(reader.readline(), 2), b"")
        writer.close()
        await writer.wait_closed()


class BridgeControlIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.socket_path = root / "run" / "agent.sock"
        self.app = BridgeApp(
            host="127.0.0.1",
            tcp_port=0,
            udp_port=0,
            config_path=root / "config.json",
            no_audio=True,
            dry_run=True,
            advertise=False,
            enable_agents=False,
            pair_code_factory=lambda: "483291",
            control_socket_path=self.socket_path,
        )
        await self.app.start()

    async def asyncTearDown(self) -> None:
        await self.app.stop()
        self.temporary.cleanup()

    async def read(self, reader: asyncio.StreamReader) -> dict[str, object]:
        return json.loads(await asyncio.wait_for(reader.readline(), 2))

    async def connect_control(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.open_unix_connection(self.socket_path)
        writer.write(
            encode_message(
                {
                    "t": "hello",
                    "api": {"major": AGENT_API_MAJOR, "minor": AGENT_API_MINOR},
                }
            )
        )
        await writer.drain()
        self.assertEqual((await self.read(reader))["t"], "hello_ok")
        return reader, writer

    async def snapshot(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> dict[str, object]:
        writer.write(b'{"t":"snapshot_req"}\n')
        await writer.drain()
        return await self.read(reader)

    async def test_real_bridge_snapshot_is_live_and_never_exposes_pairing_token(self) -> None:
        control_reader, control_writer = await self.connect_control()
        initial = await self.snapshot(control_reader, control_writer)
        self.assertEqual(initial["agent"]["state"], "ready")
        self.assertEqual(initial["agent"]["version"], AGENT_VERSION)
        self.assertEqual(initial["devices"], [])

        device_reader, device_writer = await asyncio.open_connection(
            "127.0.0.1", self.app.tcp_port
        )
        device_writer.write(
            encode_message({"t": "hello", "dev_id": "aabbccddeeff", "token": None})
        )
        await device_writer.drain()
        self.assertEqual((await self.read(device_reader))["t"], "pair_required")
        pairing = await self.snapshot(control_reader, control_writer)
        self.assertEqual(
            pairing["pairing"],
            {
                "device_id": "aabbccddeeff",
                "code": "483291",
                "created_at_ms": pairing["pairing"]["created_at_ms"],
            },
        )
        device_writer.write(encode_message({"t": "pair", "code": "483291"}))
        await device_writer.drain()
        paired = await self.read(device_reader)
        self.assertEqual(paired["t"], "paired")
        token = str(paired["token"])
        self.assertEqual((await self.read(device_reader))["t"], "agent_status")

        connected = await self.snapshot(control_reader, control_writer)
        self.assertEqual(connected["agent"]["state"], "connected")
        self.assertEqual(connected["devices"][0]["id"], "aabbccddeeff")
        self.assertEqual(connected["devices"][0]["compatibility"], "legacy")
        self.assertEqual(connected["paired_devices"][0]["id"], "aabbccddeeff")
        self.assertNotIn(token, json.dumps(connected))
        self.assertNotIn("token", connected["paired_devices"][0])

        control_writer.write(
            b'{"t":"command","id":4,"name":"set_gain","value":2}\n'
        )
        await control_writer.drain()
        gain_result = await self.read(control_reader)
        self.assertEqual(gain_result["error"], "audio_disabled")

        control_writer.write(
            b'{"t":"command","id":5,"name":"unpair","device_id":"aabbccddeeff"}\n'
        )
        await control_writer.drain()
        unpair_result = await self.read(control_reader)
        self.assertTrue(unpair_result["ok"])
        self.assertEqual(await asyncio.wait_for(device_reader.readline(), 2), b"")

        for _ in range(10):
            disconnected = await self.snapshot(control_reader, control_writer)
            if disconnected["devices"] == []:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(disconnected["devices"], [])
        self.assertEqual(disconnected["paired_devices"], [])

        device_writer.close()
        await device_writer.wait_closed()
        control_writer.close()
        await control_writer.wait_closed()


if __name__ == "__main__":
    unittest.main()
