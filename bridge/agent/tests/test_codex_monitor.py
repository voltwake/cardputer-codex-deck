from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cardbridge.agents import AgentStore
from cardbridge.codex_monitor import (
    ACCOUNT_REFRESH_SECONDS,
    APP_SERVER_STREAM_LIMIT,
    THREAD_REFRESH_SECONDS,
    CodexMonitor,
    find_codex_candidates,
    quota_available_from_account,
    quota_mode_from_account,
)
from cardbridge.usage import TokenUsageStore


class CodexMonitorHelpersTests(unittest.TestCase):
    def test_account_mode_requires_active_chatgpt_auth_for_quota(self) -> None:
        self.assertTrue(
            quota_available_from_account(
                {
                    "requiresOpenaiAuth": True,
                    "account": {"type": "chatgpt", "planType": "plus"},
                }
            )
        )
        self.assertFalse(
            quota_available_from_account(
                {"requiresOpenaiAuth": True, "account": {"type": "apiKey"}}
            )
        )
        self.assertFalse(
            quota_available_from_account(
                {"requiresOpenaiAuth": False, "account": {"type": "chatgpt"}}
            )
        )
        self.assertFalse(
            quota_available_from_account(
                {"requiresOpenaiAuth": False, "account": None}
            )
        )
        self.assertEqual(
            quota_mode_from_account(
                {
                    "requiresOpenaiAuth": True,
                    "account": {"type": "chatgpt", "planType": "plus"},
                }
            ),
            "subscription",
        )
        self.assertEqual(
            quota_mode_from_account(
                {"requiresOpenaiAuth": False, "account": None}
            ),
            "api",
        )
        self.assertEqual(quota_mode_from_account({}), "unknown")

    def test_path_cli_precedes_common_install_and_bundled_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path_cli = root / "path-bin" / "codex"
            common_cli = root / "home" / ".npm-global" / "bin" / "codex"
            bundled_cli = root / "ChatGPT.app" / "codex"
            for executable in (path_cli, common_cli, bundled_cli):
                executable.parent.mkdir(parents=True, exist_ok=True)
                executable.touch()
                executable.chmod(0o700)

            candidates = find_codex_candidates(
                path_lookup=lambda _name: str(path_cli),
                home=root / "home",
                bundled=bundled_cli,
            )

        self.assertEqual(candidates[0], str(path_cli))
        self.assertEqual(candidates[1], str(common_cli))
        self.assertEqual(candidates[-1], str(bundled_cli))

    def test_app_server_stream_limit_allows_large_thread_list_records(self) -> None:
        self.assertGreater(APP_SERVER_STREAM_LIMIT, 64 * 1024)

    def test_history_poll_is_fast_but_account_poll_stays_coarse(self) -> None:
        self.assertLessEqual(THREAD_REFRESH_SECONDS, 2)
        self.assertGreaterEqual(ACCOUNT_REFRESH_SECONDS, 30)


class CodexMonitorFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_token_usage_notification_updates_the_public_store(self) -> None:
        store = AgentStore()
        usage = TokenUsageStore()
        monitor = CodexMonitor(store, executable="/fake/codex", usage=usage)

        await monitor._notification(
            "thread/tokenUsage/updated",
            {
                "threadId": "thread-a",
                "turnId": "turn-a",
                "timestamp_ms": 1_000,
                "tokenUsage": {
                    "total": {
                        "totalTokens": 25,
                        "inputTokens": 10,
                        "cachedInputTokens": 2,
                        "outputTokens": 12,
                        "reasoningOutputTokens": 1,
                    },
                    "last": {"totalTokens": 25},
                    "modelContextWindow": 1000,
                },
            },
        )

        snapshot = usage.snapshot()
        self.assertTrue(snapshot["available"])
        self.assertEqual(snapshot["source"], "codex_app_server")
        self.assertEqual(snapshot["sessions"][0]["total"]["total"], 25)

    async def test_rate_limit_failure_clears_stale_values_but_keeps_subscription(self) -> None:
        class FailingLimitsClient:
            async def request(self, method: str, params: object) -> dict:
                if method == "thread/list":
                    return {"data": []}
                if method == "account/read":
                    return {
                        "requiresOpenaiAuth": True,
                        "account": {"type": "chatgpt", "planType": "plus"},
                    }
                if method == "account/rateLimits/read":
                    raise RuntimeError("temporarily unavailable")
                raise AssertionError(method)

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
        monitor = CodexMonitor(store, executable="/fake/codex")
        monitor.client = FailingLimitsClient()  # type: ignore[assignment]

        await monitor.refresh()

        self.assertEqual(store.quota_mode, "subscription")
        self.assertIsNone(store.weekly)
        self.assertIsNone(store.five_hour)

    async def test_account_notification_never_guesses_unlimited_for_unknown_mode(self) -> None:
        store = AgentStore()
        monitor = CodexMonitor(store, executable="/fake/codex")

        await monitor._notification("account/updated", {"authMode": "apikey"})
        self.assertEqual(store.quota_mode, "api")

        await monitor._notification(
            "account/updated", {"authMode": "chatgptAuthTokens"}
        )
        self.assertEqual(store.quota_mode, "unknown")

        await monitor._notification(
            "account/updated", {"authMode": "futureProviderMode"}
        )
        self.assertEqual(store.quota_mode, "unknown")
        await asyncio.sleep(0)

    async def test_public_agent_delta_updates_activity_without_reasoning(self) -> None:
        store = AgentStore()
        monitor = CodexMonitor(store, executable="/fake/codex")
        await monitor._notification(
            "item/agentMessage/delta",
            {
                "threadId": "thread-a",
                "turnId": "turn-a",
                "itemId": "message-a",
                "delta": "Now checking the CardBridge renderer layout.",
            },
        )
        self.assertIn("renderer layout", store.sessions["thread-a"].activity)
        await monitor._notification(
            "item/reasoning/textDelta",
            {
                "threadId": "thread-a",
                "turnId": "turn-a",
                "itemId": "reasoning-a",
                "delta": "hidden reasoning",
            },
        )
        self.assertNotIn("hidden reasoning", store.sessions["thread-a"].activity)

    async def test_monitor_falls_back_without_losing_api_mode_sessions(self) -> None:
        attempts: list[str] = []

        class FakeClient:
            def __init__(self, executable: str, notification_handler=None) -> None:
                self.executable = executable

            async def start(self) -> None:
                attempts.append(self.executable)
                if self.executable == "/bad/codex":
                    raise RuntimeError("provider-incompatible binary")

            async def stop(self) -> None:
                return None

            async def request(self, method: str, params: object) -> dict:
                if method == "thread/list":
                    return {
                        "data": [
                            {
                                "id": "api-session",
                                "name": "API mode still syncs",
                                "cwd": "/tmp/cardbridge",
                                "updatedAt": 123,
                            }
                        ]
                    }
                if method == "account/read":
                    return {"requiresOpenaiAuth": False, "account": None}
                raise AssertionError(f"unexpected request in API mode: {method}")

        store = AgentStore()
        with (
            patch(
                "cardbridge.codex_monitor.find_codex_candidates",
                return_value=["/bad/codex", "/good/codex"],
            ),
            patch("cardbridge.codex_monitor.CodexAppServerClient", FakeClient),
        ):
            monitor = CodexMonitor(store)
            await monitor.start()
            for _ in range(100):
                if "api-session" in store.sessions:
                    break
                await asyncio.sleep(0.01)
            await monitor.stop()

        self.assertEqual(attempts[:2], ["/bad/codex", "/good/codex"])
        self.assertIn("api-session", store.sessions)
        self.assertEqual(store.snapshot()["quota"]["mode"], "api")
        self.assertFalse(store.snapshot()["quota"]["available"])


if __name__ == "__main__":
    unittest.main()
