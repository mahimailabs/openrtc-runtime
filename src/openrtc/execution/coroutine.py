"""Coroutine-mode worker executor and pool (skeleton).

Implements the structural surface that ``livekit.agents.AgentServer`` and
``livekit.agents.ipc.proc_pool.ProcPool`` expose, so a future
``isolation="coroutine"`` AgentPool can swap our types in. Every real
behavior (job dispatch, drain, prewarm) is left as ``NotImplementedError``;
this iteration only locks down the Protocol shape so subsequent iterations
can fill methods one at a time without churning the surface.

Contracts derived from:

- ``docs/design/job-executor-protocol.md``
- ``docs/design/proc-pool-surface.md``
- ``docs/design/agent-server-integration.md``
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from multiprocessing.context import BaseContext
from typing import TYPE_CHECKING, Any, Literal

from livekit.agents import JobContext, JobExecutorType, JobProcess, utils
from livekit.agents.ipc import inference_executor as inference_executor_mod
from livekit.agents.ipc.job_executor import JobStatus
from livekit.agents.job import RunningJobInfo

if TYPE_CHECKING:
    from livekit.agents.ipc.job_executor import JobExecutor

EventTypes = Literal[
    "process_created",
    "process_started",
    "process_ready",
    "process_closed",
    "process_job_launched",
]

_SKELETON_HINT = "v0.1 coroutine runtime is not implemented yet (skeleton)."


class CoroutineJobExecutor:
    """Per-session executor satisfying the ``JobExecutor`` Protocol.

    All real behavior is deferred. This object is structurally compatible
    with ``livekit.agents.ipc.job_executor.JobExecutor`` so a downstream
    ``CoroutinePool`` can hand it back to ``AgentServer`` without type errors.
    """

    def __init__(self) -> None:
        self._id = uuid.uuid4().hex
        self._user_arguments: Any | None = None
        self._running_job: RunningJobInfo | None = None
        self._status: JobStatus = JobStatus.RUNNING
        self._started = False

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
        raise NotImplementedError(_SKELETON_HINT)

    async def aclose(self) -> None:
        raise NotImplementedError(_SKELETON_HINT)

    async def launch_job(self, info: RunningJobInfo) -> None:
        raise NotImplementedError(_SKELETON_HINT)

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
        raise NotImplementedError(_SKELETON_HINT)

    async def aclose(self) -> None:
        raise NotImplementedError(_SKELETON_HINT)

    async def launch_job(self, info: RunningJobInfo) -> None:
        raise NotImplementedError(_SKELETON_HINT)

    def set_target_idle_processes(self, num_idle_processes: int) -> None:
        self._target_idle_processes = num_idle_processes

    @property
    def target_idle_processes(self) -> int:
        return self._target_idle_processes
