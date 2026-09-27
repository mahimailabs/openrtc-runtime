"""``openrtc top`` for process isolation: one row per livekit job process.

In process mode every call runs in its own process, so the coroutine stack's
in-process samplers see nothing. The worker instead lists livekit's running jobs
(``AgentServer.active_jobs``, public API) and reads each job process's memory and
CPU from the OS. A job learns nothing about the worker, so it reports its own pid:
at session start it writes ``<job_pid_dir>/<job_id>`` holding ``os.getpid()``.

Memory is the job process's PSS where the OS reports it (Linux
``/proc/<pid>/smaps_rollup``), else its RSS through psutil (``openrtc[top]``),
else 0. PSS splits pages shared with the forkserver and sibling jobs between
them, so the column adds up; RSS would count each shared page once per job.
"""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openrtc.observability.introspection import SessionRow, TopSnapshot
from openrtc.observability.introspection_ipc import IntrospectionServer
from openrtc.observability.worker_stats import (
    WorkerContext,
    WorkerStatsSampler,
    build_worker_stats,
)
from openrtc.routing.request_filter import (
    _resolve_request_agent_name,
    _resolve_request_tenant,
)

if TYPE_CHECKING:
    from livekit.agents.job import RunningJobInfo

__all__ = [
    "ProcessIntrospectionRuntime",
    "job_pid_dir_for",
    "record_job_pid",
]

_MB = 1024 * 1024
_CLOCK_TICKS = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100

ActiveJobs = Callable[[], Iterable["RunningJobInfo"]]
WorkerContextProvider = Callable[[], WorkerContext]
TimeSource = Callable[[], float]


def job_pid_dir_for(socket_path: Path) -> Path:
    """The directory job processes report their pids into, next to the socket.

    Derived from the socket path so the worker and every job process agree on it
    without passing anything but configuration; private like the socket's own dir.
    """
    return socket_path.with_name(socket_path.name + ".jobs")


def record_job_pid(job_pid_dir: str, job_id: str) -> None:
    """Called in a job process: record its pid under its job id; never raises."""
    with contextlib.suppress(OSError):
        path = Path(job_pid_dir)
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        (path / job_id).write_text(str(os.getpid()))


def _read_pids(job_pid_dir: Path, job_ids: Iterable[str]) -> dict[str, int]:
    """Return ``{job_id: pid}`` for the given jobs that have reported one."""
    pids: dict[str, int] = {}
    for job_id in job_ids:
        with contextlib.suppress(OSError, ValueError):
            pids[job_id] = int((job_pid_dir / job_id).read_text())
    return pids


def _prune(job_pid_dir: Path, keep: Iterable[str]) -> None:
    """Remove pid files of jobs that are no longer running."""
    keep = set(keep)
    with contextlib.suppress(OSError):
        for entry in job_pid_dir.iterdir():
            if entry.name not in keep:
                with contextlib.suppress(OSError):
                    entry.unlink()


def _linux_pss_bytes(pid: int) -> int | None:
    """PSS of a process from ``/proc/<pid>/smaps_rollup``, or None."""
    with contextlib.suppress(OSError, ValueError):
        for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
            if line.startswith("Pss:"):
                return int(line.split()[1]) * 1024
    return None


def _linux_cpu_seconds(pid: int) -> float | None:
    """User + system CPU seconds of a process from ``/proc/<pid>/stat``, or None."""
    with contextlib.suppress(OSError, ValueError, IndexError):
        stat = Path(f"/proc/{pid}/stat").read_text()
        # Fields after the parenthesised command name; utime and stime are 14 and 15.
        fields = stat[stat.rindex(")") + 2 :].split()
        return (int(fields[11]) + int(fields[12])) / _CLOCK_TICKS
    return None


def _psutil_process(pid: int) -> Any:
    with contextlib.suppress(Exception):
        import psutil

        return psutil.Process(pid)
    return None


def read_process_usage(pid: int) -> tuple[int | None, float | None]:
    """Return ``(memory bytes, cpu seconds)`` for a pid; either may be None."""
    mem, cpu = _linux_pss_bytes(pid), _linux_cpu_seconds(pid)
    if mem is None or cpu is None:
        proc = _psutil_process(pid)
        if proc is not None:
            with contextlib.suppress(Exception):
                if mem is None:
                    mem = int(proc.memory_info().rss)
                if cpu is None:
                    times = proc.cpu_times()
                    cpu = float(times.user + times.system)
    return mem, cpu


UsageReader = Callable[[int], "tuple[int | None, float | None]"]


@dataclass(slots=True)
class _JobUsage:
    peak_bytes: int = 0
    cpu_s: float | None = None
    at: float = 0.0
    cpu_pct: float = 0.0


class ProcessJobSampler:
    """Turn livekit's running jobs into ``openrtc top`` rows, one per job process."""

    def __init__(
        self,
        *,
        agents: Mapping[str, Any],
        active_jobs: ActiveJobs,
        job_pid_dir: Path,
        usage_reader: UsageReader = read_process_usage,
        time_source: TimeSource = time.time,
    ) -> None:
        self._agents = agents
        self._active_jobs = active_jobs
        self._job_pid_dir = job_pid_dir
        self._read_usage = usage_reader
        self._now = time_source
        self._usage: dict[str, _JobUsage] = {}
        self.jobs_seen = 0

    def rows(self) -> list[SessionRow]:
        """Sample every running job once and return its row."""
        jobs = list(self._active_jobs())
        ids = [info.job.id for info in jobs]
        pids = _read_pids(self._job_pid_dir, ids)
        now = self._now()
        self.jobs_seen += len(set(ids) - self._usage.keys())
        self._usage = {jid: self._usage.get(jid, _JobUsage()) for jid in ids}
        rows = []
        for info in jobs:
            job_id = info.job.id
            usage = self._usage[job_id]
            mem_bytes = 0
            pid = pids.get(job_id)
            if pid is not None:
                mem, cpu_s = self._read_usage(pid)
                mem_bytes = mem or 0
                usage.peak_bytes = max(usage.peak_bytes, mem_bytes)
                if cpu_s is not None:
                    if usage.cpu_s is not None and now > usage.at:
                        usage.cpu_pct = round(
                            100 * (cpu_s - usage.cpu_s) / (now - usage.at), 1
                        )
                    usage.cpu_s, usage.at = cpu_s, now
            room = info.job.room
            started = info.launched_at or info.accepted_at or now
            rows.append(
                SessionRow(
                    session_id=job_id,
                    agent_name=_resolve_request_agent_name(
                        self._agents,
                        room_name=room.name,
                        job_metadata=info.job.metadata,
                        room_metadata=room.metadata,
                    )
                    or "",
                    tenant=_resolve_request_tenant(
                        job_metadata=info.job.metadata, room_metadata=room.metadata
                    ),
                    duration_s=round(max(0.0, now - started), 1),
                    mem_mb=round(mem_bytes / _MB, 1),
                    peak_mb=round(usage.peak_bytes / _MB, 1),
                    cpu_pct=usage.cpu_pct,
                    status="active",
                    pinned=False,
                )
            )
        _prune(self._job_pid_dir, ids)
        return rows


class ProcessIntrospectionRuntime:
    """Serve ``openrtc top`` for a process-mode worker over its Unix socket."""

    def __init__(
        self,
        *,
        agents: Mapping[str, Any],
        active_jobs: ActiveJobs,
        socket_path: Path,
        worker_context_provider: WorkerContextProvider,
        usage_reader: UsageReader = read_process_usage,
        worker_stats_sampler: WorkerStatsSampler | None = None,
    ) -> None:
        self.socket_path = socket_path
        self.job_pid_dir = job_pid_dir_for(socket_path)
        self._sampler = ProcessJobSampler(
            agents=agents,
            active_jobs=active_jobs,
            job_pid_dir=self.job_pid_dir,
            usage_reader=usage_reader,
        )
        self._worker_context = worker_context_provider
        self._worker_sampler = worker_stats_sampler or WorkerStatsSampler()
        self._server = IntrospectionServer(
            snapshot_provider=self.top_snapshot, socket_path=socket_path
        )

    def top_snapshot(self) -> TopSnapshot:
        """Rows for the running jobs plus the worker header.

        The worker cannot see how a job process's session ended, so the header's
        ``started`` counts jobs this worker has run and ``failed`` stays 0.
        """
        sessions = self._sampler.rows()
        context = self._worker_context()
        context = WorkerContext(
            name=context.name,
            max_sessions=context.max_sessions,
            uptime_s=context.uptime_s,
            started=self._sampler.jobs_seen,
            failed=0,
            draining=context.draining,
        )
        worker = build_worker_stats(
            context=context,
            system=self._worker_sampler.sample(),
            cpu_history=self._worker_sampler.cpu_history,
            active_sessions=len(sessions),
        )
        return TopSnapshot(worker=worker, sessions=sessions)

    async def start(self) -> None:
        """Serve the socket; job processes report pids into ``job_pid_dir``."""
        with contextlib.suppress(OSError):
            self.job_pid_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        await self._server.start()

    async def aclose(self) -> None:
        """Stop serving and remove the socket and the pid files."""
        await self._server.aclose()
        _prune(self.job_pid_dir, ())
        with contextlib.suppress(OSError):
            self.job_pid_dir.rmdir()
