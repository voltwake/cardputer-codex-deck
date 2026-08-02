from __future__ import annotations

import asyncio
import logging
import os


LOG = logging.getLogger("cardbridge")
SHUTDOWN_FORCE_EXIT_SECONDS = 8.0


def request_shutdown(
    loop: asyncio.AbstractEventLoop,
    shutdown_requested: asyncio.Event,
) -> None:
    """Request graceful shutdown, with a bounded fallback for stuck cleanup."""

    shutdown_requested.set()

    def force_exit() -> None:
        LOG.error(
            "graceful shutdown exceeded %.1fs; forcing process exit",
            SHUTDOWN_FORCE_EXIT_SECONDS,
        )
        os._exit(0)

    loop.call_later(SHUTDOWN_FORCE_EXIT_SECONDS, force_exit)
