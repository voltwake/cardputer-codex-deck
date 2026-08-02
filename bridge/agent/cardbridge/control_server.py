from __future__ import annotations

import asyncio
import ctypes
import json
import os
import socket
import stat
import struct
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ._generated_version import (
    AGENT_API_MAJOR,
    AGENT_API_MINOR,
    AGENT_BUILD,
    AGENT_VERSION,
)


MAX_CONTROL_LINE = 64 * 1024
SnapshotFactory = Callable[[], dict[str, object]]
CommandHandler = Callable[[dict[str, Any]], Awaitable[dict[str, object]]]


def default_control_socket() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "CardBridge"
        / "run"
        / "agent.sock"
    )


def _peer_uid(writer: asyncio.StreamWriter) -> int | None:
    peer_socket = writer.get_extra_info("socket")
    if peer_socket is None:
        return None
    file_descriptor = peer_socket.fileno()
    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        uid = ctypes.c_uint()
        gid = ctypes.c_uint()
        getpeereid = libc.getpeereid
        getpeereid.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
        getpeereid.restype = ctypes.c_int
        if getpeereid(file_descriptor, ctypes.byref(uid), ctypes.byref(gid)) == 0:
            return int(uid.value)
        return None
    if hasattr(socket, "SO_PEERCRED"):
        credentials = peer_socket.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        _pid, uid, _gid = struct.unpack("3i", credentials)
        return int(uid)
    return None


class AgentControlServer:
    """Owner-only local status/control channel for the future menu bar app."""

    def __init__(
        self,
        path: Path,
        snapshot_factory: SnapshotFactory,
        command_handler: CommandHandler,
    ) -> None:
        self.path = path
        self.snapshot_factory = snapshot_factory
        self.command_handler = command_handler
        self.server: asyncio.AbstractServer | None = None
        self.subscribers: set[asyncio.StreamWriter] = set()
        self._owns_socket = False

    async def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        if self.path.exists():
            mode = self.path.lstat().st_mode
            if not stat.S_ISSOCK(mode):
                raise RuntimeError(f"control path exists and is not a socket: {self.path}")
            self.path.unlink()
        self.server = await asyncio.start_unix_server(
            self._handle_client,
            path=self.path,
            limit=MAX_CONTROL_LINE + 1,
        )
        os.chmod(self.path, 0o600)
        self._owns_socket = True

    async def stop(self) -> None:
        for writer in tuple(self.subscribers):
            writer.close()
        self.subscribers.clear()
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        if self._owns_socket:
            self.path.unlink(missing_ok=True)
            self._owns_socket = False

    async def publish(self) -> None:
        if not self.subscribers:
            return
        message = self.snapshot_factory()
        for writer in tuple(self.subscribers):
            try:
                await self._send(writer, message)
            except (ConnectionError, OSError):
                self.subscribers.discard(writer)

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        if _peer_uid(writer) != os.getuid():
            writer.close()
            await writer.wait_closed()
            return
        try:
            hello = await self._read(reader)
            api = hello.get("api")
            if hello.get("t") != "hello" or not isinstance(api, dict):
                await self._send(writer, {"t": "error", "error": "hello_required"})
                return
            major = api.get("major")
            minor = api.get("minor")
            if major != AGENT_API_MAJOR or not isinstance(minor, int):
                await self._send(
                    writer,
                    {
                        "t": "api_incompatible",
                        "current": api,
                        "required": {
                            "major": AGENT_API_MAJOR,
                            "minor": AGENT_API_MINOR,
                        },
                    },
                )
                return
            await self._send(
                writer,
                {
                    "t": "hello_ok",
                    "agent": {"version": AGENT_VERSION, "build": AGENT_BUILD},
                    "api": {
                        "major": AGENT_API_MAJOR,
                        "minor": min(minor, AGENT_API_MINOR),
                    },
                },
            )
            while True:
                request = await self._read(reader)
                request_type = request.get("t")
                if request_type == "snapshot_req":
                    snapshot = self.snapshot_factory()
                    if "id" in request:
                        snapshot["request_id"] = request["id"]
                    await self._send(writer, snapshot)
                elif request_type == "subscribe":
                    self.subscribers.add(writer)
                    await self._send(writer, self.snapshot_factory())
                elif request_type == "command":
                    result = await self.command_handler(request)
                    await self._send(
                        writer,
                        {
                            "t": "result",
                            "id": request.get("id"),
                            **result,
                        },
                    )
                else:
                    await self._send(
                        writer,
                        {
                            "t": "error",
                            "id": request.get("id"),
                            "error": "unknown_request",
                        },
                    )
        except (asyncio.IncompleteReadError, ConnectionError, OSError, ValueError):
            pass
        finally:
            self.subscribers.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _read(self, reader: asyncio.StreamReader) -> dict[str, Any]:
        try:
            line = await reader.readline()
        except ValueError as exc:
            raise ValueError("control message exceeded limit") from exc
        if not line:
            raise asyncio.IncompleteReadError(b"", None)
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("control message must be an object")
        return value

    async def _send(self, writer: asyncio.StreamWriter, message: dict[str, object]) -> None:
        writer.write(
            (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
                "utf-8"
            )
        )
        await writer.drain()
