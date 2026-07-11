"""The pipecat serving front: bot assembly and runner wiring.

The blocking calls (pipecat's runner ``main`` -> uvicorn, and ``PipelineRunner.run``)
are mocked, exactly as the livekit backend's ``run`` is tested by mocking
``cli.run_app``. A genuinely live transport connection is the integration boundary
(a manual / integration smoke), not exercised here.
"""

from __future__ import annotations

import builtins
import sys
from types import SimpleNamespace
from typing import Any

import pytest
from pipecat.processors.frame_processor import Frame, FrameDirection, FrameProcessor

from openrtc.backends.pipecat import serving
from openrtc.backends.pipecat.backend import PipecatBackend
from openrtc.backends.pipecat.call_view import PipecatCallView
from openrtc.backends.pipecat.serving import build_bot, serve
from openrtc.core.wiring import _PoolRuntimeState
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

    async def on_session_start(self, info: Any, session: Any) -> None:
        self.starts.append(info)

    async def on_session_end(self, info: Any, outcome: Any) -> None:
        pass


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

    class _FakeTask:
        def __init__(self, pipeline: Any, *, observers: Any = None, **_: Any) -> None:
            captured["observers"] = observers

    class _FakeRunner:
        def __init__(self, **kwargs: Any) -> None:
            captured["runner_kwargs"] = kwargs

        async def run(self, task: Any) -> None:
            captured["ran"] = task

    monkeypatch.setattr(serving, "Pipeline", lambda processors: processors)
    monkeypatch.setattr(serving, "PipelineTask", _FakeTask)
    monkeypatch.setattr(serving, "PipelineRunner", _FakeRunner)

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
    assert isinstance(captured["ran"], _FakeTask)  # a task was run
    assert len(captured["observers"]) == 1  # lifecycle observer attached
    assert captured["runner_kwargs"]["handle_sigint"] is True  # forwarded from args


@pytest.mark.asyncio
async def test_build_bot_declines_new_calls_while_draining(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[Any] = []
    seen: list[Any] = []

    class _FakeTask:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class _FakeRunner:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def run(self, task: Any) -> None:
            ran.append(task)

    monkeypatch.setattr(serving, "Pipeline", lambda processors: processors)
    monkeypatch.setattr(serving, "PipelineTask", _FakeTask)
    monkeypatch.setattr(serving, "PipelineRunner", _FakeRunner)

    def builder(view: PipecatCallView) -> list[FrameProcessor]:
        seen.append(view.connection)
        return [_Passthrough()]

    backend = _wired_backend(builder)
    backend.begin_drain()  # drain started: decline new calls

    bot = build_bot(backend)
    await bot(SimpleNamespace(session_id="s1", body={"agent": "support"}))

    assert seen == []  # the builder is never invoked (no session started)
    assert ran == []  # nothing runs while draining


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
