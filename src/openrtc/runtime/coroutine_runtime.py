"""Coroutine-mode worker executor and pool."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import inspect
import logging
import uuid
from collections.abc import Awaitable, Callable
from multiprocessing.context import BaseContext
from typing import TYPE_CHECKING, Any, Literal, cast

from livekit import rtc
from livekit.agents import JobContext, JobExecutorType, JobProcess, utils
from livekit.agents.ipc import inference_executor as inference_executor_mod
from livekit.agents.ipc.job_executor import JobStatus
from livekit.agents.job import RunningJobInfo, _JobContextVar

from openrtc.utils.validation import require_positive_int

if TYPE_CHECKING:
    from livekit.agents.ipc.job_executor import JobExecutor


class _NoOpInferenceExecutor:
    """Stub ``InferenceExecutor`` for coroutine mode; raises on ``do_inference``."""

    async def do_inference(self, method: str, data: bytes) -> bytes | None:
        raise RuntimeError(
            "CoroutinePool was constructed without an inference_executor; "
            f"plugin requested inference method {method!r}."
        )


_NOOP_INFERENCE_EXECUTOR = _NoOpInferenceExecutor()

logger = logging.getLogger("openrtc.runtime.coroutine_runtime")

EventTypes = Literal[
    "process_created",
    "process_started",
    "process_ready",
    "process_closed",
    "process_job_launched",
]


def _consume_cancelled_task_exception(task: asyncio.Task[Any]) -> None:
    """Mark a cancelled/failed task's exception as retrieved.

    Without this, asyncio logs ``Task exception was never retrieved`` when
    :meth:`CoroutineJobExecutor.kill` cancels a task without awaiting it.
    """
    try:
        task.exception()
    except asyncio.CancelledError:
        pass
    except asyncio.InvalidStateError:
        pass


class CoroutineJobExecutor:
    """Per-session executor satisfying the ``JobExecutor`` Protocol."""

    def __init__(
        self,
        *,
        entrypoint_fnc: Callable[[JobContext], Awaitable[None]] | None = None,
        session_end_fnc: Callable[[JobContext], Awaitable[None]] | None = None,
        context_factory: Callable[[RunningJobInfo], JobContext] | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._id = uuid.uuid4().hex
        self._user_arguments: Any | None = None
        self._running_job: RunningJobInfo | None = None
        self._status: JobStatus = JobStatus.RUNNING
        self._started = False
        self._task: asyncio.Task[None] | None = None
        self._entrypoint_fnc = entrypoint_fnc
        self._session_end_fnc = session_end_fnc
        self._context_factory = context_factory
        self._loop = loop
        self._shutdown_fut: asyncio.Future[str] | None = None

    @property
    def id(self) -> str:
        return self._id

    @property
    def started(self) -> bool:
        return self._started

    @property
    def user_arguments(self) -> Any | None:
        return self._user_arguments

    @user_arguments.setter
    def user_arguments(self, value: Any | None) -> None:
        self._user_arguments = value

    @property
    def running_job(self) -> RunningJobInfo | None:
        return self._running_job

    @property
    def status(self) -> JobStatus:
        return self._status

    async def start(self) -> None:
        """No-op startup hook; coroutine mode has no subprocess to spawn."""
        self._started = True

    async def join(self) -> None:
        """Wait until the in-flight entrypoint task finishes; idempotent."""
        task = self._task
        if task is None or task.done():
            return
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001 - wrapper has already set FAILED + logged
            pass

    async def initialize(self) -> None:
        """No-op handshake hook; coroutine mode has no child process to negotiate with."""

    async def aclose(self) -> None:
        """Cancel any in-flight task and clear ``started``; idempotent."""
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001 - wrapper has already set FAILED + logged
                pass
            if self._status is JobStatus.RUNNING:
                self._status = JobStatus.FAILED
        self._started = False

    def kill(self) -> None:
        """Forcefully cancel the in-flight task without awaiting cleanup; idempotent."""
        task = self._task
        if task is not None and not task.done():
            task.cancel("killed by CoroutineJobExecutor.kill()")
            task.add_done_callback(_consume_cancelled_task_exception)
            if self._status is JobStatus.RUNNING:
                self._status = JobStatus.FAILED
        self._started = False

    async def launch_job(self, info: RunningJobInfo) -> None:
        """Schedule the user entrypoint as an ``asyncio.Task`` and return immediately."""
        if self._entrypoint_fnc is None:
            raise RuntimeError(
                "CoroutineJobExecutor requires entrypoint_fnc to launch a job."
            )
        if self._context_factory is None:
            raise RuntimeError(
                "CoroutineJobExecutor requires context_factory to launch a job."
            )
        if self._task is not None and not self._task.done():
            raise RuntimeError(
                "CoroutineJobExecutor already has an in-flight job; "
                "construct a new executor for each session."
            )

        self._running_job = info
        self._status = JobStatus.RUNNING

        ctx = self._context_factory(info)
        loop = self._loop or asyncio.get_running_loop()
        self._task = loop.create_task(self._run_entrypoint(ctx))

    async def _run_entrypoint(self, ctx: JobContext) -> None:
        """Run the session lifecycle, mirroring upstream ``_run_job_task``."""
        assert self._entrypoint_fnc is not None  # checked in launch_job
        loop = asyncio.get_running_loop()
        shutdown_fut: asyncio.Future[str] = loop.create_future()
        self._shutdown_fut = shutdown_fut

        def _request_shutdown(reason: str = "shutdown") -> None:
            if not shutdown_fut.done():
                shutdown_fut.set_result(reason)

        # Per-job log fields, then the contextvar (the MAH-158 fix).
        _on_setup = getattr(ctx, "_on_setup", None)
        if callable(_on_setup):
            _on_setup()
        token: contextvars.Token[JobContext] | None = None
        with contextlib.suppress(Exception):
            token = _JobContextVar.set(ctx)

        # Shutdown triggers (all optional for stub contexts): ctx.shutdown()
        # via on_shutdown, and the room "disconnected" event (mirrors
        # job_proc_lazy_main's room-disconnected handler).
        if hasattr(ctx, "_on_shutdown"):

            def _on_shutdown(reason: str = "") -> None:
                _request_shutdown(reason or "shutdown")

            ctx._on_shutdown = _on_shutdown
        _room_on = getattr(getattr(ctx, "room", None), "on", None)
        if callable(_room_on):
            _room_on("disconnected", lambda *_a: _request_shutdown("room disconnected"))

        try:
            try:
                await self._entrypoint_fnc(ctx)
            except asyncio.CancelledError:
                if self._status is JobStatus.RUNNING:
                    self._status = JobStatus.FAILED
                raise
            except Exception:
                if self._status is JobStatus.RUNNING:
                    self._status = JobStatus.FAILED
                logger.exception(
                    "entrypoint raised in CoroutineJobExecutor",
                    extra=self.logging_extra(),
                )
                return
            # Entrypoint returned cleanly. Hold a real job open until the call
            # ends (the MAH-160 fix), then run teardown. A setup-only entrypoint
            # (no live session) or a fake job (simulate_job, which has no live
            # room to disconnect) completes on return instead.
            _is_fake = getattr(ctx, "is_fake_job", None)
            fake_job = bool(_is_fake()) if callable(_is_fake) else False
            if (
                getattr(ctx, "_primary_agent_session", None) is not None
                and not fake_job
            ):
                try:
                    await shutdown_fut
                except asyncio.CancelledError:
                    if self._status is JobStatus.RUNNING:
                        self._status = JobStatus.FAILED
                    raise
                await self._teardown(ctx, shutdown_fut.result())
            if self._status is JobStatus.RUNNING:
                self._status = JobStatus.SUCCESS
        finally:
            if self._session_end_fnc is not None:
                try:
                    await self._session_end_fnc(ctx)
                except Exception:
                    logger.exception(
                        "session_end_fnc raised in CoroutineJobExecutor",
                        extra=self.logging_extra(),
                    )
            if token is not None:
                with contextlib.suppress(Exception):
                    _JobContextVar.reset(token)

    async def _teardown(self, ctx: JobContext, reason: str) -> None:
        """Run the post-shutdown lifecycle (mirrors upstream ``_run_job_task``)."""
        primary = getattr(ctx, "_primary_agent_session", None)
        if primary is not None and hasattr(primary, "aclose"):
            with contextlib.suppress(Exception):
                await primary.aclose()
        _on_session_end = getattr(ctx, "_on_session_end", None)
        if callable(_on_session_end):
            with contextlib.suppress(Exception):
                await _on_session_end()
        for callback in list(getattr(ctx, "_shutdown_callbacks", None) or []):
            try:
                await callback(reason)
            except Exception:
                logger.exception(
                    "shutdown callback raised in CoroutineJobExecutor",
                    extra=self.logging_extra(),
                )
        pending = list(getattr(ctx, "_pending_tasks", None) or [])
        if pending:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        _on_cleanup = getattr(ctx, "_on_cleanup", None)
        if callable(_on_cleanup):
            with contextlib.suppress(Exception):
                _on_cleanup()

    def logging_extra(self) -> dict[str, Any]:
        return {"executor_id": self._id}


class CoroutinePool(utils.EventEmitter[EventTypes]):
    """Multi-session coroutine pool satisfying the ``ProcPool`` surface."""

    def __init__(
        self,
        *,
        initialize_process_fnc: Callable[[JobProcess], Any],
        job_entrypoint_fnc: Callable[[JobContext], Awaitable[None]],
        session_end_fnc: Callable[[JobContext], Awaitable[None]] | None,
        num_idle_processes: int,
        initialize_timeout: float,
        close_timeout: float,
        inference_executor: inference_executor_mod.InferenceExecutor | None,
        job_executor_type: JobExecutorType,
        mp_ctx: BaseContext,
        memory_warn_mb: float,
        memory_limit_mb: float,
        http_proxy: str | None,
        loop: asyncio.AbstractEventLoop,
        max_concurrent_sessions: int = 50,
        consecutive_failure_limit: int = 5,
        on_consecutive_failure_limit: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__()
        self._initialize_process_fnc = initialize_process_fnc
        self._job_entrypoint_fnc = job_entrypoint_fnc
        self._session_end_fnc = session_end_fnc
        self._num_idle_processes = num_idle_processes
        self._initialize_timeout = initialize_timeout
        self._close_timeout = close_timeout
        self._inference_executor = inference_executor
        self._job_executor_type = job_executor_type
        self._mp_ctx = mp_ctx
        self._memory_warn_mb = memory_warn_mb
        self._memory_limit_mb = memory_limit_mb
        self._http_proxy = http_proxy
        self._loop = loop
        # Backpressure threshold: extra to ProcPool's signature so the
        # constructor stays compatible with AgentServer (which only passes
        # the ProcPool kwargs); the AgentPool wiring sets this via a
        # closure when it monkey-patches ProcPool.
        self._max_concurrent_sessions = require_positive_int(
            "max_concurrent_sessions", max_concurrent_sessions
        )
        self._consecutive_failure_limit = require_positive_int(
            "consecutive_failure_limit", consecutive_failure_limit
        )
        self._on_consecutive_failure_limit = on_consecutive_failure_limit
        self._consecutive_failures = 0
        self._failure_limit_fired = False
        self._executors: list[JobExecutor] = []
        self._target_idle_processes = num_idle_processes
        self._started = False
        self._draining = False
        self._shared_proc: JobProcess | None = None

    @property
    def processes(self) -> list[JobExecutor]:
        return self._executors

    def get_by_job_id(self, job_id: str) -> JobExecutor | None:
        return next(
            (
                x
                for x in self._executors
                if x.running_job and x.running_job.job.id == job_id
            ),
            None,
        )

    async def start(self) -> None:
        """Construct the singleton ``JobProcess`` and run ``setup_fnc`` once; idempotent."""
        if self._started:
            return

        proc = JobProcess(
            executor_type=self._job_executor_type,
            user_arguments=None,
            http_proxy=self._http_proxy,
        )

        async def _do_setup() -> None:
            result = self._initialize_process_fnc(proc)
            if inspect.isawaitable(result):
                await result

        try:
            await asyncio.wait_for(_do_setup(), timeout=self._initialize_timeout)
        except TimeoutError:
            logger.error(
                "CoroutinePool setup_fnc timed out after %.1fs",
                self._initialize_timeout,
            )
            raise

        self._shared_proc = proc
        self._started = True

    @property
    def shared_process(self) -> JobProcess | None:
        """Return the singleton ``JobProcess`` populated by :meth:`start`."""
        return self._shared_proc

    @property
    def started(self) -> bool:
        """True after :meth:`start` has completed successfully."""
        return self._started

    async def drain(self) -> None:
        """Stop accepting new jobs and await every in-flight executor; idempotent."""
        if self._draining:
            return
        self._draining = True

        while self._executors:
            in_flight = list(self._executors)
            await asyncio.gather(
                *(ex.join() for ex in in_flight),
                return_exceptions=True,
            )
            # If new launches slipped in just before the flag was set,
            # the next iteration drains them too.

    @property
    def draining(self) -> bool:
        """``True`` after :meth:`drain` (or :meth:`aclose`) has started."""
        return self._draining

    async def aclose(self) -> None:
        """Cancel every active executor and wait for cleanup; idempotent."""
        if not self._started:
            return
        self._started = False

        executors = list(self._executors)
        if not executors:
            return

        async def _close_all() -> None:
            await asyncio.gather(
                *(ex.aclose() for ex in executors),
                return_exceptions=True,
            )

        try:
            await asyncio.wait_for(_close_all(), timeout=self._close_timeout)
        except TimeoutError:
            logger.warning(
                "CoroutinePool aclose timed out after %.1fs; "
                "escalating to kill for %d executor(s)",
                self._close_timeout,
                len(executors),
            )
            for ex in executors:
                kill_method = getattr(ex, "kill", None)
                if callable(kill_method):
                    kill_method()

    async def launch_job(self, info: RunningJobInfo) -> None:
        """Allocate a per-session executor, emit lifecycle events, and schedule its entrypoint."""
        if not self._started:
            raise RuntimeError("CoroutinePool.start() must complete before launch_job.")
        if self._draining:
            raise RuntimeError(
                "CoroutinePool is draining; new jobs cannot be launched."
            )

        executor = self._build_executor()
        self._executors.append(executor)
        self.emit("process_created", executor)
        self.emit("process_started", executor)
        self.emit("process_ready", executor)

        try:
            await executor.launch_job(info)
        except Exception:
            # If the executor refuses (missing factory, in-flight, etc.) treat
            # the slot as never-occupied and emit process_closed so worker
            # accounting stays balanced.
            self._on_executor_done(executor)
            raise

        task = executor._task
        if task is not None:

            def _done(_t: asyncio.Task[None], ex: JobExecutor = executor) -> None:
                self._on_executor_done(ex)

            task.add_done_callback(_done)

        self.emit("process_job_launched", executor)

    def _build_executor(self) -> CoroutineJobExecutor:
        """Construct a per-session executor wired with this pool's callbacks.

        ``loop`` is not forwarded: the executor must use the loop running
        ``launch_job``, not the constructor-time loop, which may differ in
        tests and some real scenarios.
        """
        return CoroutineJobExecutor(
            entrypoint_fnc=self._job_entrypoint_fnc,
            session_end_fnc=self._session_end_fnc,
            context_factory=self._build_job_context,
        )

    def _build_job_context(self, info: RunningJobInfo) -> JobContext:
        """Construct a fresh ``JobContext`` for one session."""
        if self._shared_proc is None:
            raise RuntimeError(
                "CoroutinePool.start() must complete before _build_job_context."
            )

        if info.fake_job:
            from livekit.agents.ipc.mock_room import create_mock_room

            room = cast("rtc.Room", create_mock_room())
        else:
            room = rtc.Room()

        def _on_connect() -> None:
            pass

        def _on_shutdown(_reason: str) -> None:
            pass

        return JobContext(
            proc=self._shared_proc,
            info=info,
            room=room,
            on_connect=_on_connect,
            on_shutdown=_on_shutdown,
            inference_executor=self._inference_executor or _NOOP_INFERENCE_EXECUTOR,
        )

    def _on_executor_done(self, executor: JobExecutor) -> None:
        """Remove a finished executor and emit ``process_closed``; idempotent."""
        if executor not in self._executors:
            return
        self._executors.remove(executor)
        self.emit("process_closed", executor)
        self._observe_executor_status(executor)

    def _observe_executor_status(self, executor: JobExecutor) -> None:
        """Track consecutive failures and trip the supervisor at the limit."""
        status = executor.status
        if status is JobStatus.SUCCESS:
            self._consecutive_failures = 0
            self._failure_limit_fired = False
            return

        # FAILED (or any non-SUCCESS terminal status).
        self._consecutive_failures += 1

        if (
            self._consecutive_failures >= self._consecutive_failure_limit
            and not self._failure_limit_fired
        ):
            self._failure_limit_fired = True
            logger.error(
                "CoroutinePool tripped consecutive_failure_limit=%d "
                "(failures observed=%d); invoking supervisor callback",
                self._consecutive_failure_limit,
                self._consecutive_failures,
            )
            if self._on_consecutive_failure_limit is not None:
                try:
                    self._on_consecutive_failure_limit(self._consecutive_failures)
                except Exception:
                    logger.exception("consecutive_failure_limit callback raised")

    @property
    def consecutive_failures(self) -> int:
        """Failure count since the last SUCCESS (or start)."""
        return self._consecutive_failures

    @property
    def consecutive_failure_limit(self) -> int:
        """Threshold that fires :attr:`on_consecutive_failure_limit`."""
        return self._consecutive_failure_limit

    def set_target_idle_processes(self, num_idle_processes: int) -> None:
        self._target_idle_processes = num_idle_processes

    @property
    def target_idle_processes(self) -> int:
        return self._target_idle_processes

    @property
    def max_concurrent_sessions(self) -> int:
        """Backpressure threshold this pool was configured with."""
        return self._max_concurrent_sessions

    def current_load(self) -> float:
        """Return active-session fraction (``active / max_concurrent_sessions``) for ``load_fnc``."""
        return len(self._executors) / self._max_concurrent_sessions
