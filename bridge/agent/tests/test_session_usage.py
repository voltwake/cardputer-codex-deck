from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cardbridge.session_usage import CodexSessionUsageMonitor
from cardbridge.usage import TokenUsageStore


def record(timestamp: str, kind: str, payload: dict[str, object]) -> bytes:
    return (
        json.dumps(
            {"timestamp": timestamp, "type": kind, "payload": payload},
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )


def token_record(timestamp: str, total: int, *, last: int | None = None) -> bytes:
    value = total if last is None else last
    return record(
        timestamp,
        "event_msg",
        {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "total_tokens": total,
                    "input_tokens": total // 2,
                    "cached_input_tokens": total // 10,
                    "cache_write_input_tokens": 0,
                    "output_tokens": total // 3,
                    "reasoning_output_tokens": total // 20,
                },
                "last_token_usage": {
                    "total_tokens": value,
                    "input_tokens": value // 2,
                    "cached_input_tokens": value // 10,
                    "cache_write_input_tokens": 0,
                    "output_tokens": value // 3,
                    "reasoning_output_tokens": value // 20,
                },
                "model_context_window": 258_400,
            },
            "rate_limits": {},
        },
    )


class CodexSessionUsageMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovers_and_tails_cumulative_session_usage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sessions = Path(directory) / "sessions"
            sessions.mkdir()
            path = sessions / "rollout-thread.jsonl"
            path.write_bytes(
                record(
                    "1970-01-01T00:00:00Z",
                    "session_meta",
                    {
                        "session_id": "thread-a",
                        "id": "thread-a",
                        "base_instructions": {"text": "private instructions"},
                    },
                )
                + record(
                    "1970-01-01T00:00:00.500Z",
                    "turn_context",
                    {"turn_id": "turn-a", "summary": "private transcript summary"},
                )
                + token_record("1970-01-01T00:00:01Z", 100)
                + token_record("1970-01-01T00:00:02Z", 160)
            )

            store = TokenUsageStore()
            monitor = CodexSessionUsageMonitor(store, sessions_dir=sessions)
            changed = await monitor.scan_once(force_discovery=True)

            self.assertEqual(changed, 2)
            snapshot = store.snapshot()
            self.assertTrue(snapshot["available"])
            self.assertEqual(snapshot["source"], "codex_session_jsonl")
            latest = snapshot["sessions"][0]
            self.assertEqual(latest["id"], "thread-a")
            self.assertEqual(latest["turn_id"], "turn-a")
            self.assertEqual(latest["total"]["total"], 160)
            self.assertEqual(latest["delta"]["total"], 60)
            self.assertEqual(latest["window_ms"], 1_000)

            partial = token_record("1970-01-01T00:00:03Z", 200).rstrip(b"\n")
            with path.open("ab") as stream:
                stream.write(partial)
            self.assertEqual(await monitor.scan_once(), 0)
            with path.open("ab") as stream:
                stream.write(b"\n")
            self.assertEqual(await monitor.scan_once(), 1)
            self.assertEqual(
                store.snapshot()["sessions"][0]["total"]["total"], 200
            )

    async def test_new_turn_uses_session_cumulative_delta_and_restart_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sessions = Path(directory) / "sessions"
            sessions.mkdir()
            path = sessions / "rollout-thread.jsonl"
            path.write_bytes(
                record(
                    "1970-01-01T00:00:00Z",
                    "session_meta",
                    {"session_id": "thread-a", "id": "thread-a"},
                )
                + record(
                    "1970-01-01T00:00:00.500Z",
                    "turn_context",
                    {"turn_id": "turn-a"},
                )
                + token_record("1970-01-01T00:00:01Z", 100)
                + record(
                    "1970-01-01T00:00:01.500Z",
                    "turn_context",
                    {"turn_id": "turn-b"},
                )
                + token_record("1970-01-01T00:00:02Z", 150)
            )

            first = TokenUsageStore()
            await CodexSessionUsageMonitor(first, sessions_dir=sessions).scan_once(
                force_discovery=True
            )
            latest = first.snapshot()["sessions"][0]
            self.assertEqual(latest["turn_id"], "turn-b")
            self.assertEqual(latest["delta"]["total"], 50)

            recovered = TokenUsageStore()
            await CodexSessionUsageMonitor(
                recovered, sessions_dir=sessions
            ).scan_once(force_discovery=True)
            self.assertEqual(
                recovered.snapshot()["sessions"][0]["total"]["total"], 150
            )

    async def test_only_token_count_lines_are_json_decoded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sessions = Path(directory) / "sessions"
            sessions.mkdir()
            path = sessions / "rollout-thread.jsonl"
            private_marker = "PRIVATE-CONTENT-MUST-NOT-BE-DECODED"
            path.write_bytes(
                record(
                    "1970-01-01T00:00:00Z",
                    "session_meta",
                    {
                        "session_id": "thread-a",
                        "base_instructions": {"text": private_marker},
                    },
                )
                + record(
                    "1970-01-01T00:00:00.500Z",
                    "turn_context",
                    {"turn_id": "turn-a", "summary": private_marker},
                )
                + record(
                    "1970-01-01T00:00:00.750Z",
                    "response_item",
                    {"type": "message", "content": private_marker + " token_count"},
                )
                + token_record("1970-01-01T00:00:01Z", 100)
            )

            original_loads = json.loads
            decoded: list[bytes] = []

            def guarded_loads(raw: bytes) -> object:
                decoded.append(raw)
                self.assertNotIn(private_marker.encode(), raw)
                return original_loads(raw)

            store = TokenUsageStore()
            monitor = CodexSessionUsageMonitor(store, sessions_dir=sessions)
            with patch("cardbridge.session_usage.json.loads", side_effect=guarded_loads):
                await monitor.scan_once(force_discovery=True)

            self.assertEqual(len(decoded), 1)
            self.assertTrue(store.snapshot()["available"])

    async def test_thread_paths_cannot_escape_the_sessions_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            sessions.mkdir()
            outside = root / "outside.jsonl"
            outside.write_bytes(token_record("1970-01-01T00:00:01Z", 100))

            monitor = CodexSessionUsageMonitor(
                TokenUsageStore(), sessions_dir=sessions
            )
            monitor.track_threads([{"path": str(outside)}])
            self.assertEqual(monitor._app_paths, set())


if __name__ == "__main__":
    unittest.main()
