"""Coroutine-mode worker executor and pool.

Implements the structural surface that ``livekit.agents.AgentServer`` and
``livekit.agents.ipc.proc_pool.ProcPool`` expose, so a future
``isolation="coroutine"`` AgentPool can swap our types in. Lifecycle methods
land one iteration at a time; remaining stubs raise ``NotImplementedError``.

Contracts derived from:

- ``docs/design/job-executor-protocol.md``
- ``docs/design/proc-pool-surface.md``
- ``docs/design/agent-server-integration.md``
"""

from __future__ import annotations

import asyncio
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
from livekit.agents.job import RunningJobInfo

if TYPE_CHECKING:
    from livekit.agents.ipc.job_executor import JobExecutor


class _NoOpInferenceExecutor:
    """Minimal :class:`InferenceExecutor` Protocol stub.

    JobContext requires a non-None ``inference_executor`` even when the worker
    has no inference runners registered. ProcPool side-steps this by piping a
    real IPC client; coroutine mode passes this no-op when no real executor
    is configured. Calling :meth:`do_inference` raises so a misconfigured
    plugin fails loudly instead of silently returning ``None``.
    """

    async def do_inference(self, method: str, data: bytes) -> bytes | None:
        raise RuntimeError(
            "CoroutinePool was constructed without an inference_executor; "
            f"plugin requested inference method {method!r}."
        )


_NOOP_INFERENCE_EXECUTOR = _NoOpInferenceExecutor()

logger = logging.getLogger("openrtc.execution.coroutine")

EventTypes = Literal[
    "process_created",
    "process_started",
    "process_ready",
    "process_closed",
    "process_job_launched",
]

_SKELETON_HINT = "v0.1 coroutine runtime is not implemented yet (skeleton)."


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
    """Per-session executor satisfying the ``JobExecutor`` Protocol.

    Construction takes its dependencies as keyword args so the executor can
    run in isolation (tests) without being wired through a CoroutinePool.

    Args:
        entrypoint_fnc: The user-defined ``Callable[[JobContext],
            Awaitable[None]]`` that runs the actual session. Required to
            call :meth:`launch_job`.
        session_end_fnc: Optional callback awaited after the entrypoint
            returns or raises (mirrors ``ProcPool``'s ``session_end_fnc``).
        context_factory: Builder that turns the ``RunningJobInfo`` payload
            into a JobContext referencing the shared JobProcess. Required to
            call :meth:`launch_job`. Owning this as a callable lets the
            CoroutinePool inject a real factory while tests substitute a
            stub.
        loop: Event loop the entrypoint task is scheduled on. Defaults to
            ``asyncio.get_event_loop()`` at launch time.
    """

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
        raise NotImplementedError(_SKELETON_HINT)

    async def join(self) -> None:
        raise NotImplementedError(_SKELETON_HINT)

    async def initialize(self) -> None:
        """No-op handshake hook.

        Process-mode executors complete a child handshake here; coroutine mode
        runs in the same loop so there is nothing to negotiate. Kept idempotent
        and safe to call multiple times so ``ProcPool.start()``-style callers
        work unchanged.
        """
        return None

    async def aclose(self) -> None:
        """Cancel any in-flight ``launch_job`` task and clear ``started``.

        Idempotent: a second call (or a call before any ``launch_job``) returns
        without raising. If a still-pending task is cancelled, the executor's
        status flips to :class:`JobStatus.FAILED` per
        ``docs/design/job-executor-protocol.md`` (cancellation maps to FAILED
        because the upstream enum has no CANCELLED value).
        """
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                # The launch_job wrapper will already have set status to FAILED.
                pass
            if self._status is JobStatus.RUNNING:
                self._status = JobStatus.FAILED
        self._started = False

    def kill(self) -> None:
        """Forcefully cancel the in-flight job task without awaiting cleanup.

        Synchronous escalation path beyond :meth:`aclose`. Cancels the task
        with a ``"killed"`` message, marks status :class:`JobStatus.FAILED`
        immediately, and clears ``started``. A done callback consumes the
        eventual :class:`asyncio.CancelledError` so the event loop does not
        log an unhandled-exception warning.

        Use when graceful shutdown is too slow (drain timeout exceeded,
        supervisor escalation, etc.). Idempotent: safe to call before any
        ``launch_job`` or after the task is already done.

        Not part of the upstream ``JobExecutor`` Protocol; this is an
        OpenRTC-internal escalation hook.
        """
        task = self._task
        if task is not None and not task.done():
            task.cancel("killed by CoroutineJobExecutor.kill()")
            task.add_done_callback(_consume_cancelled_task_exception)
            if self._status is JobStatus.RUNNING:
                self._status = JobStatus.FAILED
        self._started = False

    async def launch_job(self, info: RunningJobInfo) -> None:
        """Schedule the user entrypoint as an ``asyncio.Task`` and return.

        Constructs a ``JobContext`` via ``context_factory`` (referencing the
        shared ``JobProcess`` the factory closes over), schedules the
        entrypoint coroutine on this executor's loop, and stores the task on
        ``self._task`` so :meth:`aclose` can cancel it.

        The entrypoint runs inside :meth:`_run_entrypoint`, which:
        - flips ``status`` to :class:`JobStatus.SUCCESS` on clean completion,
        - flips ``status`` to :class:`JobStatus.FAILED` on any exception or
          cancellation, and **suppresses** the exception so a sibling job in
          the same worker is unaffected,
        - awaits ``session_end_fnc(ctx)`` in a ``finally`` block (success or
          failure), suppressing any exception from that callback.

        Returns once the task is **scheduled**, not after it completes, so
        the pool can issue the next ``launch_job`` immediately.
        """
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
        assert self._entrypoint_fnc is not None  # checked in launch_job
        try:
            await self._entrypoint_fnc(ctx)
            if self._status is JobStatus.RUNNING:
                self._status = JobStatus.SUCCESS
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
        finally:
            if self._session_end_fnc is not None:
                try:
                    await self._session_end_fnc(ctx)
                except Exception:
                    logger.exception(
                        "session_end_fnc raised in CoroutineJobExecutor",
                        extra=self.logging_extra(),
                    )

    def logging_extra(self) -> dict[str, Any]:
        return {"executor_id": self._id}


class CoroutinePool(utils.EventEmitter[EventTypes]):
    """Multi-session coroutine pool satisfying the ``ProcPool`` surface.

    Constructor signature mirrors ``ipc.proc_pool.ProcPool`` so
    ``AgentServer.run()`` can construct us with the same kwargs (see
    ``docs/design/proc-pool-surface.md``). All real behavior is deferred.
    """

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
        self._executors: list[JobExecutor] = []
        self._target_idle_processes = num_idle_processes
        self._started = False
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
        """Construct the singleton ``JobProcess`` and run ``setup_fnc`` once.

        Coroutine mode shares one ``JobProcess`` across every executor (and
        therefore every session) in the worker, so ``setup_fnc`` runs **once**
        — not once per session as in process mode. The shared instance lives
        on ``self.shared_process`` and is what each executor's
        ``context_factory`` will close over.

        Wraps the call in :func:`asyncio.wait_for` with the configured
        ``initialize_timeout``. Idempotent: a second call after a successful
        start is a no-op.
        """
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
        """Return the singleton ``JobProcess`` populated by :meth:`start`.

        ``None`` until ``start()`` completes successfully. Read by the
        per-executor ``context_factory`` so every ``JobContext`` references
        the same prewarmed userdata.
        """
        return self._shared_proc

    @property
    def started(self) -> bool:
        """True after :meth:`start` has completed successfully."""
        return self._started

    async def aclose(self) -> None:
        raise NotImplementedError(_SKELETON_HINT)

    async def launch_job(self, info: RunningJobInfo) -> None:
        """Allocate a per-session executor and schedule its entrypoint.

        Builds a :class:`CoroutineJobExecutor` wired with the pool's
        callbacks and a ``context_factory`` that produces a real
        :class:`JobContext` referencing the singleton ``JobProcess``. Tracks
        the executor in :attr:`processes` and emits the standard
        ``process_*`` events in the order documented in
        ``docs/design/proc-pool-surface.md``.

        Order: ``process_created`` -> ``process_started`` ->
        ``process_ready`` -> entrypoint task scheduled ->
        ``process_job_launched``. ``process_closed`` fires later from the
        task's done callback once the entrypoint coroutine exits (success or
        failure), at which point the executor is removed from
        :attr:`processes`.
        """
        if not self._started:
            raise RuntimeError("CoroutinePool.start() must complete before launch_job.")

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

        ``loop`` is intentionally not forwarded to the executor: the
        executor schedules its task at launch time, so it must use the
        loop that is running ``launch_job`` (``asyncio.get_running_loop()``).
        Forwarding the constructor-time loop would couple the executor to
        whatever loop existed when ``ProcPool`` was instantiated, which
        in tests (and in some real scenarios) does not match the loop
        running ``AgentServer.run()``.
        """
        return CoroutineJobExecutor(
            entrypoint_fnc=self._job_entrypoint_fnc,
            session_end_fnc=self._session_end_fnc,
            context_factory=self._build_job_context,
        )

    def _build_job_context(self, info: RunningJobInfo) -> JobContext:
        """Construct a fresh :class:`JobContext` for one session.

        Mirrors the construction in
        ``livekit/agents/ipc/job_proc_lazy_main.py:_start_job`` so the
        coroutine path matches process-mode semantics: real ``rtc.Room`` for
        live jobs, ``create_mock_room`` for ``info.fake_job`` (which
        ``simulate_job`` and the density benchmark use).

        Tests override this method to return a stub instead of constructing
        a real Room (which loads native libraries).
        """
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
        """Remove a finished executor and emit ``process_closed``.

        Idempotent — a second call (or a call on an executor that was never
        tracked) is a no-op except for the event emission, which is
        suppressed on the second call.
        """
        if executor not in self._executors:
            return
        self._executors.remove(executor)
        self.emit("process_closed", executor)

    def set_target_idle_processes(self, num_idle_processes: int) -> None:
        self._target_idle_processes = num_idle_processes

    @property
    def target_idle_processes(self) -> int:
        return self._target_idle_processes
