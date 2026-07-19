"""The pipecat serving front: bot assembly and runner wiring.

The blocking calls (pipecat's runner ``main`` -> uvicorn, and ``WorkerRunner.run``)
are mocked in the wiring tests, exactly as the livekit backend's ``run`` is tested
by mocking ``cli.run_app``. One end-to-end test drives the real worker/runner to
completion with a self-terminating pipeline (no mocks, no network); a genuinely
live transport connection is the remaining integration boundary.
"""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import sys
from types import SimpleNamespace
from typing import Any

import pytest
from pipecat.frames.frames import EndFrame, StartFrame
from pipecat.processors.frame_processor import Frame, FrameDirection, FrameProcessor

from openrtc.backends.pipecat import serving
from openrtc.backends.pipecat.backend import PipecatBackend
from openrtc.backends.pipecat.call_view import PipecatCallView
from openrtc.backends.pipecat.serving import build_bot, serve
from openrtc.core.wiring import _PoolRuntimeState
from openrtc.observability.base_observer import SessionStatus
from openrtc.observability.session_context import current_session_id
from openrtc.observability.task_attribution import (
    install_session_task_factory,
    task_session_id,
)
from openrtc.runtime.registry import ServerParams

_PARAMS = ServerParams(
    max_concurrent_sessions=10, consecutive_failure_limit=3, drain_timeout=30
)


class _Passthrough(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)


class _Recorder:
    def __init__(self) -> None:
        self.starts: list[Any] = []
        self.ends: list[Any] = []

    async def on_session_start(self, info: Any, session: Any) -> None:
        self.starts.append(info)

    async def on_session_end(self, info: Any, outcome: Any) -> None:
        self.ends.append(outcome)


class _EndOnStart(FrameProcessor):
    """A processor that ends the pipeline as soon as it starts (self-terminating)."""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)
        if isinstance(frame, StartFrame):
            await self.push_frame(EndFrame(), direction)


def _wired_backend(builder: Any) -> PipecatBackend:
    backend = PipecatBackend(_PARAMS)
    backend.wire(
        _PoolRuntimeState(agents={}, observers=[_Recorder()], observer_timeout=5.0),
        None,
        agent_name=None,
    )
    backend.register("support", builder)
    return backend


@pytest.mark.asyncio
async def test_build_bot_routes_assembles_and_runs_the_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _FakeWorker:
        def __init__(self, pipeline: Any, *, observers: Any = None, **_: Any) -> None:
            captured["observers"] = observers

    class _FakeRunner:
        def __init__(self, **kwargs: Any) -> None:
            captured["runner_kwargs"] = kwargs

        async def add_workers(self, workers: Any) -> None:
            captured["registered"] = workers

        async def run(self) -> None:
            captured["ran"] = True

    monkeypatch.setattr(serving, "Pipeline", lambda processors: processors)
    monkeypatch.setattr(serving, "PipelineWorker", _FakeWorker)
    monkeypatch.setattr(serving, "WorkerRunner", _FakeRunner)

    seen: list[Any] = []

    def builder(view: PipecatCallView) -> list[FrameProcessor]:
        seen.append(view.connection)  # build_call threaded the RunnerArguments
        return [_Passthrough()]

    backend = _wired_backend(builder)
    runner_args = SimpleNamespace(
        session_id="s1", body={"agent": "support"}, handle_sigint=True
    )

    bot = build_bot(backend)
    await bot(runner_args)

    assert seen == [runner_args]  # routed via body["agent"], connection threaded
    assert isinstance(captured["registered"], _FakeWorker)  # worker was registered
    assert captured["ran"] is True  # and run
    assert len(captured["observers"]) == 1  # lifecycle observer attached
    assert captured["runner_kwargs"]["handle_sigint"] is True  # forwarded from args


@pytest.mark.asyncio
async def test_build_bot_declines_new_calls_while_draining(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[Any] = []
    seen: list[Any] = []

    class _FakeWorker:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class _FakeRunner:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def add_workers(self, workers: Any) -> None:
            ran.append(workers)

        async def run(self) -> None:
            ran.append("run")

    monkeypatch.setattr(serving, "Pipeline", lambda processors: processors)
    monkeypatch.setattr(serving, "PipelineWorker", _FakeWorker)
    monkeypatch.setattr(serving, "WorkerRunner", _FakeRunner)

    def builder(view: PipecatCallView) -> list[FrameProcessor]:
        seen.append(view.connection)
        return [_Passthrough()]

    backend = _wired_backend(builder)
    backend.begin_drain()  # drain started: decline new calls

    bot = build_bot(backend)
    await bot(SimpleNamespace(session_id="s1", body={"agent": "support"}))

    assert seen == []  # the builder is never invoked (no session started)
    assert ran == []  # nothing runs while draining


@pytest.mark.asyncio
async def test_bot_runs_the_pipeline_under_the_session_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The worker/runner build + run must happen with the session_id contextvar
    # bound so the introspection task factory tags every task pipecat spawns for
    # the session; that tag is what lets openrtc top attribute CPU to it. Install
    # the real factory and prove a task created during the run carries the job_id
    # tag (no 10s real pipeline needed to exercise the attribution link).
    loop = asyncio.get_running_loop()
    restore = install_session_task_factory(loop)
    seen: dict[str, str | None] = {}

    async def _noop() -> None:
        return None

    class _FakeWorker:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            # Construction is inside the scope too, so tasks pipecat spawns in
            # __init__ would be tagged, not just those from run().
            seen["at_build"] = current_session_id()

    class _FakeRunner:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def add_workers(self, workers: Any) -> None:
            pass

        async def run(self) -> None:
            task = loop.create_task(_noop())
            seen["task_tag"] = task_session_id(task)  # factory tagged the task
            await task

    monkeypatch.setattr(serving, "Pipeline", lambda processors: processors)
    monkeypatch.setattr(serving, "PipelineWorker", _FakeWorker)
    monkeypatch.setattr(serving, "WorkerRunner", _FakeRunner)

    backend = _wired_backend(lambda view: [_Passthrough()])
    bot = build_bot(backend)
    try:
        await bot(SimpleNamespace(session_id="sess-xyz", body={"agent": "support"}))
    finally:
        restore()

    # Scope covers construction, and a task spawned during the run is tagged with
    # the job_id: the exact link CPU attribution walks.
    assert seen == {"at_build": "sess-xyz", "task_tag": "sess-xyz"}
    assert current_session_id() is None  # and restored after the run


@pytest.mark.asyncio
async def test_build_bot_runs_a_real_pipeline_end_to_end() -> None:
    # Drive the real bot (real PipelineWorker + WorkerRunner) to completion with a
    # self-terminating pipeline: no mocks, no network. This proves the serving
    # assembly (route -> build_call -> worker -> runner -> lifecycle observer) works
    # against real pipecat. Only the FastAPI accept + live transport I/O remains
    # the infra boundary.
    recorder = _Recorder()
    backend = PipecatBackend(_PARAMS)
    backend.wire(
        _PoolRuntimeState(agents={}, observers=[recorder], observer_timeout=5.0),
        None,
        agent_name=None,
    )
    backend.register("support", lambda view: [_EndOnStart()])

    bot = build_bot(backend)
    runner_args = SimpleNamespace(
        session_id="s1", body={"agent": "support"}, handle_sigint=False
    )
    await asyncio.wait_for(bot(runner_args), timeout=10.0)

    assert len(recorder.starts) == 1  # observer fired from real frame flow
    assert recorder.starts[0].agent_name == "support"  # routed via body["agent"]
    assert recorder.starts[0].job_id == "s1"  # for_pipecat mapped session_id
    assert len(recorder.ends) == 1
    assert recorder.ends[0].status is SessionStatus.SUCCESS


def test_serve_registers_the_bot_on_main_and_starts_the_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[bool] = []
    monkeypatch.setattr("pipecat.runner.run.main", lambda: started.append(True))

    main_module = sys.modules["__main__"]
    had_bot = hasattr(main_module, "bot")
    original = getattr(main_module, "bot", None)
    try:
        serve(_wired_backend(lambda view: [_Passthrough()]))
        assert started == [True]  # handed control to pipecat's runner
        assert callable(main_module.bot)  # OpenRTC's dispatcher is discoverable
    finally:
        if had_bot:
            main_module.bot = original
        else:
            delattr(main_module, "bot")


def test_serve_gives_the_runner_a_clean_argv_and_restores_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # pipecat's runner parses sys.argv; a caller's args (a script's, or a CLI's)
    # would make its argparse reject "unrecognized arguments". serve() must hand it
    # a clean argv and restore the original afterwards.
    seen_argv: list[list[str]] = []
    monkeypatch.setattr(
        "pipecat.runner.run.main", lambda: seen_argv.append(list(sys.argv))
    )
    monkeypatch.setattr(sys, "argv", ["openrtc", "serve", "./agents", "--foo"])

    main_module = sys.modules["__main__"]
    had_bot = hasattr(main_module, "bot")
    original = getattr(main_module, "bot", None)
    try:
        serve(_wired_backend(lambda view: [_Passthrough()]))
    finally:
        if had_bot:
            main_module.bot = original
        else:
            delattr(main_module, "bot")

    assert seen_argv == [["openrtc"]]  # the runner sees only the program name
    assert sys.argv == ["openrtc", "serve", "./agents", "--foo"]  # restored after


class _FakeRuntime:
    """Records the lifespan's start/stop so the socket wiring can be asserted."""

    def __init__(self) -> None:
        self.events: list[str] = []

    async def start(self, _loop: Any) -> None:
        self.events.append("start")

    async def aclose(self) -> None:
        self.events.append("aclose")


@pytest.fixture
def _restore_main_bot() -> Any:
    """Save and restore ``__main__.bot`` around a serve() call."""
    main_module = sys.modules["__main__"]
    had_bot = hasattr(main_module, "bot")
    original = getattr(main_module, "bot", None)
    yield
    if had_bot:
        main_module.bot = original
    else:
        with contextlib.suppress(AttributeError):
            delattr(main_module, "bot")


@pytest.mark.usefixtures("_restore_main_bot")
@pytest.mark.asyncio
async def test_serve_installs_a_lifespan_that_starts_and_stops_introspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pipecat.runner.run.main", lambda: None)
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "pipecat.runner.run._add_lifespan_to_app",
        lambda app, lifespan: captured.__setitem__("lifespan", lifespan),
    )
    runtime = _FakeRuntime()
    backend = _wired_backend(lambda view: [_Passthrough()])
    backend.attach_introspection(runtime)  # type: ignore[arg-type]

    serve(backend)

    lifespan = captured["lifespan"]  # serve installed one
    async with lifespan(None):
        assert runtime.events == ["start"]  # socket started at server startup
    assert runtime.events == ["start", "aclose"]  # and torn down on shutdown


@pytest.mark.usefixtures("_restore_main_bot")
def test_serve_skips_the_lifespan_when_introspection_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pipecat.runner.run.main", lambda: None)
    installed: list[Any] = []
    monkeypatch.setattr(
        "pipecat.runner.run._add_lifespan_to_app",
        lambda app, lifespan: installed.append(lifespan),
    )
    # A backend with no introspection attached (the default).
    serve(_wired_backend(lambda view: [_Passthrough()]))
    assert installed == []  # nothing to serve, no lifespan installed


def test_serve_raises_the_install_hint_when_the_runner_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def _without_runner(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "pipecat.runner.run":
            raise ModuleNotFoundError("No module named 'fastapi'", name="fastapi")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _without_runner)
    with pytest.raises(ImportError, match=r"openrtc\[pipecat-serve\]"):
        serve(_wired_backend(lambda view: [_Passthrough()]))
