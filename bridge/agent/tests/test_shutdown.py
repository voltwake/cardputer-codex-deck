from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from cardbridge.shutdown import request_shutdown


class ShutdownDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_stuck_shutdown_forces_process_exit_after_deadline(self) -> None:
        loop = asyncio.get_running_loop()
        shutdown_requested = asyncio.Event()

        with (
            patch("cardbridge.shutdown.SHUTDOWN_FORCE_EXIT_SECONDS", 0.01),
            patch("cardbridge.shutdown.os._exit") as force_exit,
            patch("cardbridge.shutdown.LOG.error"),
        ):
            request_shutdown(loop, shutdown_requested)
            self.assertTrue(shutdown_requested.is_set())
            force_exit.assert_not_called()
            await asyncio.sleep(0.03)

        force_exit.assert_called_once_with(0)


if __name__ == "__main__":
    unittest.main()
