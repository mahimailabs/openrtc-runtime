"""The pipecat serving front: accept live calls over a transport via pipecat's runner.

Pipecat's runner (``pipecat.runner.run``, behind ``openrtc[pipecat-serve]``) is a
FastAPI server that accepts transports at ``/start`` and calls one
``bot(runner_args)`` per connection. OpenRTC supplies that bot: it routes the call
and runs the observed session (``PipecatBackend.build_call``), so a single worker
serves many calls under OpenRTC's routing, shared prewarm, and observability.

The runner discovers ``bot`` on ``__main__`` (its documented extension point), so
``serve`` registers OpenRTC's dispatcher there and hands over. Starting the FastAPI
server (``main`` runs ``uvicorn``) is the transport integration boundary, exercised
by a manual / integration smoke; the wiring here is unit-tested by mocking the
blocking ``main`` and ``PipelineRunner.run``, the same way the livekit backend
mocks ``cli.run_app``.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from openrtc.backends.pipecat.backend import PipecatBackend

__all__ = ["build_bot", "serve"]


def build_bot(backend: PipecatBackend) -> Callable[[Any], Awaitable[None]]:
    """Return the async ``bot(runner_args)`` pipecat's runner calls per connection.

    It routes and builds the observed session (``build_call``), assembles the
    processors into a ``PipelineTask`` with the lifecycle observer attached, and
    runs it. The transport lives in the builder's processors, so this stays
    transport-agnostic.
    """

    async def bot(runner_args: Any) -> None:
        processors, observer = backend.build_call(runner_args)
        task = PipelineTask(Pipeline(processors), observers=[observer])
        runner = PipelineRunner(
            handle_sigint=getattr(runner_args, "handle_sigint", False)
        )
        await runner.run(task)

    return bot


def serve(backend: PipecatBackend) -> None:
    """Start pipecat's FastAPI runner, dispatching each connection through OpenRTC.

    Registers OpenRTC's bot on ``__main__`` (where pipecat's runner discovers
    ``bot``) and hands control to the runner, blocking until it exits. Raises a
    clear install hint when the serving extra is absent.
    """
    try:
        from pipecat.runner.run import main
    except ModuleNotFoundError as exc:
        raise ImportError(
            "The pipecat serving front needs pipecat's runner. "
            "Install it with: pip install openrtc[pipecat-serve]"
        ) from exc
    sys.modules["__main__"].bot = build_bot(backend)  # type: ignore[attr-defined]
    # The runner parses sys.argv; a caller's args would make its argparse reject
    # them. Hand it a clean argv (host / port come from pipecat's env vars) and
    # restore the original once serving exits.
    saved_argv = sys.argv
    sys.argv = [saved_argv[0]]
    try:
        main()
    finally:
        sys.argv = saved_argv
