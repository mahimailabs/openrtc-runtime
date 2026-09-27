"""Run the coroutine-mode worker on uvloop when it is installed.

In coroutine mode every call shares one event loop, and livekit's Rust runtime
hands each audio frame and room event to that loop under the GIL. A faster loop
holds the GIL for less time per pass, so those threads wait less: measured on
livekit-agents 1.8.3, worker CPU fell to about process-per-call levels. livekit
builds its loop with ``asyncio.new_event_loop()``, so setting the policy before
the worker starts is enough. ``OPENRTC_UVLOOP=0`` turns it off.
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger("openrtc")

__all__ = ["use_uvloop"]


def use_uvloop() -> bool:
    """Install uvloop's event-loop policy; return whether it was installed."""
    if os.environ.get("OPENRTC_UVLOOP", "").strip() == "0":
        logger.info("OPENRTC_UVLOOP=0: coroutine mode runs on the asyncio loop.")
        return False
    try:
        import uvloop
    except ImportError:
        logger.info("uvloop is not installed: coroutine mode runs on the asyncio loop.")
        return False
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    logger.info("Coroutine mode runs on uvloop.")
    return True
