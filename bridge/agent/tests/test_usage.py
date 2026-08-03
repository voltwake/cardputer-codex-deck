from __future__ import annotations

import unittest

from cardbridge.protocol import MAX_JSON_LINE, encode_message
from cardbridge.usage import TokenUsageStore


def event(
    total: int,
    timestamp_ms: int,
    *,
    thread_id: str = "thread-1",
    turn_id: str = "turn-1",
) -> dict[str, object]:
    return {
        "threadId": thread_id,
        "turnId": turn_id,
        "timestamp_ms": timestamp_ms,
        "tokenUsage": {
            "total": {
                "totalTokens": total,
                "inputTokens": total // 2,
                "cachedInputTokens": total // 10,
                "outputTokens": total // 3,
                "reasoningOutputTokens": total // 20,
            },
            "last": {"totalTokens": total},
            "modelContextWindow": 258400,
        },
    }


class TokenUsageStoreTests(unittest.TestCase):
    def test_unavailable_is_not_zero_or_unlimited(self) -> None:
        snapshot = TokenUsageStore().snapshot()
        self.assertFalse(snapshot["available"])
        self.assertEqual(snapshot["source"], "unavailable")
        self.assertNotEqual(snapshot.get("reason"), "zero")

    def test_cumulative_updates_produce_delta_and_rate(self) -> None:
        store = TokenUsageStore()
        self.assertTrue(store.update_notification(event(100, 1_000)))
        self.assertTrue(store.update_notification(event(160, 2_000)))
        session = store.snapshot()["sessions"][0]
        self.assertEqual(session["total"]["total"], 160)
        self.assertEqual(session["delta"]["total"], 60)
        self.assertEqual(session["window_ms"], 1_000)
        self.assertEqual(session["tokens_per_second"], 60.0)

    def test_duplicate_reset_and_out_of_order_events_never_go_negative(self) -> None:
        store = TokenUsageStore()
        store.update_notification(event(100, 1_000))
        self.assertFalse(store.update_notification(event(100, 2_000)))
        self.assertTrue(store.update_notification(event(50, 3_000)))
        self.assertFalse(store.update_notification(event(40, 2_500)))
        self.assertTrue(store.update_notification(event(80, 4_000)))
        session = store.snapshot()["sessions"][0]
        self.assertEqual(session["delta"]["total"], 30)
        self.assertGreaterEqual(session["tokens_per_second"], 0)
        self.assertLessEqual(len(encode_message({"t": "sync_update", "data": store.snapshot()})), MAX_JSON_LINE)

    def test_new_turn_establishes_a_zero_delta_baseline(self) -> None:
        store = TokenUsageStore()
        store.update_notification(event(100, 1_000))
        store.update_notification(event(20, 2_000, turn_id="turn-2"))
        session = store.snapshot()["sessions"][0]
        self.assertEqual(session["turn_id"], "turn-2")
        self.assertEqual(session["delta"]["total"], 0)

    def test_session_file_counter_continues_across_turns(self) -> None:
        store = TokenUsageStore()
        store.update_notification(
            event(100, 1_000),
            source="codex_session_jsonl",
            cumulative_across_turns=True,
        )
        store.update_notification(
            event(150, 2_000, turn_id="turn-2"),
            source="codex_session_jsonl",
            cumulative_across_turns=True,
        )
        session = store.snapshot()["sessions"][0]
        self.assertEqual(session["turn_id"], "turn-2")
        self.assertEqual(session["delta"]["total"], 50)
        self.assertEqual(store.snapshot()["source"], "codex_session_jsonl")

    def test_device_usage_snapshot_with_eight_long_sessions_stays_under_4k(self) -> None:
        store = TokenUsageStore()
        for index in range(8):
            store.update_notification(
                event(
                    10**15,
                    1_000 + index,
                    thread_id=(str(index) * 128),
                    turn_id="t" * 128,
                )
            )
        message = {
            "t": "sync_update",
            "topic": "codex.usage",
            "schema": 1,
            "seq": 8,
            "generated_at_ms": 1_785_690_000_000,
            "data": store.snapshot(limit=4),
            "token": "ab" * 32,
        }
        self.assertLessEqual(len(encode_message(message)), MAX_JSON_LINE)
        self.assertEqual(len(store.snapshot()["sessions"]), 8)


if __name__ == "__main__":
    unittest.main()
