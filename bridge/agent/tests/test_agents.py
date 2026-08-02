from __future__ import annotations

import unittest

from cardbridge.agents import AgentSession, AgentStore, public_activity_text
from cardbridge.protocol import MAX_JSON_LINE, encode_message


class AgentStoreTests(unittest.TestCase):
    def test_device_ack_does_not_hide_an_active_session(self) -> None:
        session = AgentSession(
            id="active-session",
            status="running",
            phase="tool",
            activity="Running a command",
            updated_ms=123,
        )

        snapshot = session.as_dict(acknowledged_at_ms=123)

        self.assertEqual(snapshot["status"], "running")
        self.assertEqual(snapshot["phase"], "tool")
        self.assertEqual(snapshot["activity"], "Running a command")

    def test_focus_follows_latest_user_prompt_and_ack_clears_ready(self) -> None:
        store = AgentStore()
        store.update_threads(
            [
                {
                    "id": "session-a",
                    "name": "First task",
                    "cwd": "/tmp/project-a",
                    "updatedAt": 100,
                },
                {
                    "id": "session-b",
                    "preview": "Second task",
                    "cwd": "/tmp/project-b",
                    "updatedAt": 90,
                },
            ]
        )
        store.apply_hook_event(
            {"event": "UserPromptSubmit", "session_id": "session-b", "timestamp_ms": 1_000}
        )
        self.assertEqual(store.focus_id, "session-b")
        self.assertEqual(store.sessions["session-b"].status, "running")
        self.assertEqual(store.sessions["session-b"].phase, "thinking")
        first_focus_seq = store.focus_seq
        store.apply_hook_event(
            {"event": "UserPromptSubmit", "session_id": "session-b", "timestamp_ms": 1_500}
        )
        self.assertGreater(store.focus_seq, first_focus_seq)

        store.apply_hook_event(
            {"event": "Stop", "session_id": "session-b", "timestamp_ms": 2_000}
        )
        self.assertEqual(store.sessions["session-b"].status, "ready")
        self.assertTrue(store.sessions["session-b"].unread)
        self.assertTrue(store.acknowledge("session-b"))
        self.assertEqual(store.sessions["session-b"].status, "idle")
        self.assertFalse(store.sessions["session-b"].unread)

    def test_history_recency_follows_desktop_prompt_without_hooks(self) -> None:
        store = AgentStore()
        store.update_threads(
            [
                {
                    "id": "session-a",
                    "name": "Older prompt",
                    "updatedAt": 105,
                    "recencyAt": 100,
                },
                {
                    "id": "session-b",
                    "name": "Older session",
                    "updatedAt": 95,
                    "recencyAt": 90,
                },
            ]
        )
        self.assertEqual(store.focus_id, "session-a")
        first_focus_seq = store.focus_seq

        # Completion/background output may change updatedAt, but must not steal
        # the pet because recencyAt did not record a newer user prompt.
        store.update_threads(
            [
                {
                    "id": "session-b",
                    "name": "Older session",
                    "updatedAt": 120,
                    "recencyAt": 90,
                },
                {
                    "id": "session-a",
                    "name": "Older prompt",
                    "updatedAt": 105,
                    "recencyAt": 100,
                },
            ]
        )
        self.assertEqual(store.focus_id, "session-a")
        self.assertEqual(store.focus_seq, first_focus_seq)

        # A prompt sent through another App Server advances recencyAt and is
        # therefore followed even when the desktop Hook is disabled.
        store.update_threads(
            [
                {
                    "id": "session-b",
                    "name": "New desktop prompt",
                    "updatedAt": 131,
                    "recencyAt": 130,
                },
                {
                    "id": "session-a",
                    "name": "Older prompt",
                    "updatedAt": 125,
                    "recencyAt": 100,
                },
            ]
        )
        self.assertEqual(store.focus_id, "session-b")
        self.assertGreater(store.focus_seq, first_focus_seq)
        self.assertEqual(
            [item["id"] for item in store.snapshot(2)["items"]],
            ["session-b", "session-a"],
        )

    def test_rate_limit_windows_are_classified_by_duration(self) -> None:
        store = AgentStore()
        store.set_quota_available(True)
        store.update_rate_limits(
            {
                "rateLimitsByLimitId": {
                    "codex": {
                        "primary": {
                            "usedPercent": 55,
                            "windowDurationMins": 10_080,
                            "resetsAt": 123,
                        },
                        "secondary": None,
                    }
                }
            }
        )
        snapshot = store.snapshot()
        self.assertEqual(snapshot["quota"]["mode"], "subscription")
        self.assertTrue(snapshot["quota"]["available"])
        self.assertEqual(snapshot["quota"]["weekly"]["remaining"], 45)
        self.assertIsNone(snapshot["quota"]["five_hour"])

    def test_api_mode_clears_subscription_windows_and_is_explicit(self) -> None:
        store = AgentStore()
        store.set_quota_available(True)
        store.update_rate_limits(
            {
                "rateLimits": {
                    "primary": {
                        "usedPercent": 10,
                        "windowDurationMins": 300,
                    },
                    "secondary": {
                        "usedPercent": 20,
                        "windowDurationMins": 10_080,
                    },
                }
            }
        )
        self.assertIsNotNone(store.snapshot()["quota"]["weekly"])

        store.set_quota_mode("api")
        store.update_rate_limits(
            {
                "rateLimits": {
                    "primary": {
                        "usedPercent": 99,
                        "windowDurationMins": 300,
                    }
                }
            }
        )
        quota = store.snapshot()["quota"]
        self.assertEqual(quota["mode"], "api")
        self.assertFalse(quota["available"])
        self.assertIsNone(quota["weekly"])
        self.assertIsNone(quota["five_hour"])

    def test_missing_rate_limit_response_clears_stale_windows(self) -> None:
        store = AgentStore()
        store.set_quota_mode("subscription")
        store.update_rate_limits(
            {
                "rateLimits": {
                    "primary": {
                        "usedPercent": 10,
                        "windowDurationMins": 300,
                    },
                    "secondary": {
                        "usedPercent": 20,
                        "windowDurationMins": 10_080,
                    },
                }
            }
        )
        self.assertIsNotNone(store.weekly)
        self.assertIsNotNone(store.five_hour)

        store.update_rate_limits({})

        self.assertEqual(store.quota_mode, "subscription")
        self.assertIsNone(store.weekly)
        self.assertIsNone(store.five_hour)

    def test_tool_events_produce_short_status_text(self) -> None:
        store = AgentStore()
        store.apply_hook_event(
            {
                "event": "PreToolUse",
                "session_id": "session-a",
                "tool_name": "apply_patch",
            }
        )
        self.assertEqual(store.sessions["session-a"].activity, "Editing project files")
        self.assertEqual(store.sessions["session-a"].phase, "tool")

        store.apply_hook_event(
            {
                "event": "PostToolUse",
                "session_id": "session-a",
                "tool_name": "apply_patch",
            }
        )
        self.assertEqual(store.sessions["session-a"].activity, "Thinking...")
        self.assertEqual(store.sessions["session-a"].phase, "thinking")

    def test_hook_prefers_safe_specific_activity(self) -> None:
        store = AgentStore()
        store.apply_hook_event(
            {
                "event": "PreToolUse",
                "session_id": "session-a",
                "tool_name": "apply_patch",
                "activity": "Editing src/ui.cpp",
            }
        )
        self.assertEqual(store.sessions["session-a"].activity, "Editing src/ui.cpp")
        store.apply_hook_event(
            {
                "event": "Stop",
                "session_id": "session-a",
                "activity": "Implemented the final 1:1 layout",
            }
        )
        self.assertEqual(
            store.sessions["session-a"].activity,
            "Implemented the final 1:1 layout",
        )

    def test_public_app_events_expose_messages_but_ignore_reasoning(self) -> None:
        store = AgentStore()
        store.apply_app_event(
            "item/started",
            {
                "threadId": "session-a",
                "item": {
                    "type": "fileChange",
                    "id": "file-1",
                    "changes": [{"path": "/private/project/src/ui.cpp"}],
                },
            },
        )
        self.assertEqual(store.sessions["session-a"].activity, "Editing ui.cpp")
        store.apply_app_event(
            "item/started",
            {
                "threadId": "session-a",
                "item": {
                    "type": "reasoning",
                    "id": "reasoning-1",
                    "summary": ["must never appear"],
                    "content": ["hidden chain of thought"],
                },
            },
        )
        self.assertEqual(store.sessions["session-a"].activity, "Editing ui.cpp")
        store.apply_app_event(
            "item/completed",
            {
                "threadId": "session-a",
                "item": {
                    "type": "agentMessage",
                    "id": "message-1",
                    "text": "I checked the renderer.\nNow enlarging the pet safely.",
                },
            },
        )
        self.assertIn("enlarging the pet", store.sessions["session-a"].activity)

    def test_app_server_turn_and_user_message_only_focus_once(self) -> None:
        store = AgentStore()
        store.apply_app_event(
            "turn/started",
            {
                "threadId": "session-a",
                "turn": {"id": "turn-1", "status": "inProgress", "items": []},
            },
        )
        focus_seq = store.focus_seq
        change_seq = store.seq

        store.apply_app_event(
            "item/started",
            {
                "threadId": "session-a",
                "turnId": "turn-1",
                "item": {"type": "userMessage", "id": "message-1", "content": []},
            },
        )

        self.assertEqual(store.focus_seq, focus_seq)
        self.assertEqual(store.seq, change_seq)
        self.assertEqual(store.sessions["session-a"].activity, "Understanding the task")

    def test_public_activity_redacts_secrets_and_is_utf8_bounded(self) -> None:
        text = public_activity_text(
            "Checking API_KEY=super-secret-value and sk-abcdefghijklmnop "
            + "界" * 100
        )
        self.assertNotIn("super-secret-value", text)
        self.assertNotIn("abcdefghijklmnop", text)
        self.assertLessEqual(len(text.encode("utf-8")), 72)

    def test_request_user_input_is_needs_input_until_tool_returns(self) -> None:
        store = AgentStore()
        event = {
            "event": "PreToolUse",
            "session_id": "session-a",
            "tool_name": "request_user_input",
        }
        store.apply_hook_event(event)
        self.assertEqual(store.sessions["session-a"].status, "needs_input")
        event["event"] = "PostToolUse"
        store.apply_hook_event(event)
        self.assertEqual(store.sessions["session-a"].status, "running")
        self.assertEqual(store.sessions["session-a"].phase, "thinking")

    def test_focused_session_is_kept_in_bounded_snapshot(self) -> None:
        store = AgentStore()
        for index in range(10):
            store.sessions[str(index)] = AgentSession(
                id=str(index), status="needs_input", updated_ms=index
            )
        store.sessions["focus"] = AgentSession(id="focus", status="idle")
        store.focus_id = "focus"
        snapshot = store.snapshot(8)
        self.assertEqual(len(snapshot["items"]), 8)
        self.assertIn("focus", [item["id"] for item in snapshot["items"]])

    def test_worst_case_cjk_snapshot_fits_control_line(self) -> None:
        store = AgentStore()
        store.set_quota_available(True)
        store.update_rate_limits(
            {
                "rateLimits": {
                    "primary": {
                        "usedPercent": 0,
                        "windowDurationMins": 300,
                        "resetsAt": 2_147_483_647,
                    },
                    "secondary": {
                        "usedPercent": 100,
                        "windowDurationMins": 10_080,
                        "resetsAt": 2_147_483_647,
                    },
                }
            }
        )
        store.seq = 4_294_967_295
        store.focus_seq = 4_294_967_295
        for index in range(8):
            session_id = str(index) * 64
            store.sessions[session_id] = AgentSession(
                id=session_id,
                title="会" * 100,
                project="项" * 100,
                status="needs_input",
                phase="thinking",
                activity="做" * 100,
                unread=True,
                updated_ms=9_999_999_999_999,
            )
        store.focus_id = "7" * 64
        message = store.snapshot()
        message.update(t="agent_status", provider="codex", token="ab" * 32)
        encoded = encode_message(message)
        self.assertLessEqual(len(encoded), MAX_JSON_LINE)
        self.assertLessEqual(len(message["items"][0]["title"]), 32)
        self.assertLessEqual(len(message["items"][0]["project"]), 20)
        self.assertLessEqual(
            len(message["items"][0]["activity"].encode("utf-8")), 72
        )


if __name__ == "__main__":
    unittest.main()
