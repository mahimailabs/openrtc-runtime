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

import asyncio
import contextlib
import logging
import sys
from typing import TYPE_CHECKING, Any

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.workers.runner import WorkerRunner

from openrtc.observability.session_context import session_scope

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from openrtc.backends.pipecat.backend import PipecatBackend

__all__ = ["build_bot", "serve"]

logger = logging.getLogger("openrtc.backends.pipecat.serving")


def build_bot(backend: PipecatBackend) -> Callable[[Any], Awaitable[None]]:
    """Return the async ``bot(runner_args)`` pipecat's runner calls per connection.

    It routes and builds the observed session (``build_call``), assembles the
    processors into a ``PipelineWorker`` with the lifecycle observer attached, and
    runs it on a ``WorkerRunner``. The transport lives in the builder's processors,
    so this stays transport-agnostic.

    While the backend is draining it declines new calls so in-flight sessions can
    finish. Pipecat's runner owns the ``/start`` route, so the refusal is at the
    bot (after connection setup) rather than a ``/start`` rejection.
    """

    async def bot(runner_args: Any) -> None:
        if backend.draining:
            logger.info("Declining a new call: the pipecat backend is draining.")
            return
        processors, observer = backend.build_call(runner_args)
        # Bind the session id for the pipeline's lifetime so the introspection
        # task factory tags every task pipecat spawns for it; that is what lets
        # openrtc top attribute CPU to this session (memory is already attributed
        # via the session observer). Scoping the whole worker/runner build + run
        # covers task creation wherever pipecat does it.
        with session_scope(observer.session_info.job_id):
            worker = PipelineWorker(Pipeline(processors), observers=[observer])
            runner = WorkerRunner(
                handle_sigint=getattr(runner_args, "handle_sigint", False)
            )
            await runner.add_workers(worker)
            await runner.run()

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
    _install_introspection_lifespan(backend)
    # The runner parses sys.argv; a caller's args would make its argparse reject
    # them. Hand it a clean argv (host / port come from pipecat's env vars) and
    # restore the original once serving exits.
    saved_argv = sys.argv
    sys.argv = [saved_argv[0]]
    try:
        main()
    finally:
        sys.argv = saved_argv


def _install_introspection_lifespan(backend: PipecatBackend) -> None:
    """Bind ``openrtc top`` to pipecat's server lifespan when introspection is on.

    The introspection socket and samplers need the serving event loop, which does
    not exist until the runner starts. Attaching a FastAPI lifespan to pipecat's
    app starts the stack at server startup (so an idle worker is monitorable) and
    tears it down on shutdown. A no-op when introspection is disabled.
    """
    runtime = backend.introspection
    if runtime is None:
        return
    from pipecat.runner.run import _add_lifespan_to_app, app

    @contextlib.asynccontextmanager
    async def _introspection_lifespan(_app: Any) -> AsyncIterator[None]:
        await runtime.start(asyncio.get_running_loop())
        try:
            yield
        finally:
            await runtime.aclose()

    _add_lifespan_to_app(app, _introspection_lifespan)
