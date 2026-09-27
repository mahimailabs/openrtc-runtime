"""openrtc top in process mode: one row per livekit job process (public API only)."""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from livekit.agents import AgentServer

from openrtc.observability import process_top
from openrtc.observability.introspection_ipc import fetch_snapshot
from openrtc.observability.process_top import (
    ProcessIntrospectionRuntime,
    ProcessJobSampler,
    job_pid_dir_for,
    read_process_usage,
    record_job_pid,
)
from openrtc.observability.worker_stats import WorkerContext
from openrtc.runtime.process_runtime import _ProcessAgentServer

_AGENTS = {"sales": object(), "support": object()}
_MB = 1024 * 1024


def _job(
    job_id: str,
    *,
    room_name: str = "",
    job_metadata: str = "",
    room_metadata: str = "",
    launched_at: float = 100.0,
) -> SimpleNamespace:
    room = SimpleNamespace(name=room_name, metadata=room_metadata)
    return SimpleNamespace(
        job=SimpleNamespace(id=job_id, metadata=job_metadata, room=room),
        launched_at=launched_at,
        accepted_at=0.0,
    )


def _context() -> WorkerContext:
    return WorkerContext(
        name="w", max_sessions=5, uptime_s=1.0, started=0, failed=0, draining=False
    )


class _Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_job_pid_dir_sits_next_to_the_socket() -> None:
    assert job_pid_dir_for(Path("/run/x/top.sock")) == Path("/run/x/top.sock.jobs")


def test_record_job_pid_writes_the_pid_and_never_raises(tmp_path: Path) -> None:
    record_job_pid(str(tmp_path / "jobs"), "AJ_1")
    assert (tmp_path / "jobs" / "AJ_1").read_text() == str(os.getpid())

    blocker = tmp_path / "file"
    blocker.write_text("")
    record_job_pid(str(blocker / "jobs"), "AJ_2")  # a file in the way: no raise


def test_sampler_builds_rows_from_running_jobs(tmp_path: Path) -> None:
    (tmp_path / "AJ_a").write_text("11")
    (tmp_path / "AJ_b").write_text("not-a-pid")
    (tmp_path / "AJ_gone").write_text("33")
    usage = {11: (40 * _MB, 2.0)}
    clock = _Clock(110.0)
    jobs = [
        _job("AJ_a", job_metadata='{"agent": "support", "tenant": "acme"}'),
        _job("AJ_b", room_name="sales-1", launched_at=0.0),
    ]
    sampler = ProcessJobSampler(
        agents=_AGENTS,
        active_jobs=lambda: jobs,
        job_pid_dir=tmp_path,
        usage_reader=lambda pid: usage.get(pid, (None, None)),
        time_source=clock,
    )

    rows = {row.session_id: row for row in sampler.rows()}
    assert rows["AJ_a"].agent_name == "support"
    assert rows["AJ_a"].tenant == "acme"
    assert rows["AJ_a"].mem_mb == 40.0
    assert rows["AJ_a"].duration_s == 10.0
    assert rows["AJ_a"].cpu_pct == 0.0  # no previous sample yet
    assert rows["AJ_b"].agent_name == "sales"
    assert rows["AJ_b"].tenant == "default"
    assert rows["AJ_b"].mem_mb == 0.0  # its pid file is garbage
    assert rows["AJ_b"].duration_s == 0.0  # unknown launch time counts from now
    assert not (tmp_path / "AJ_gone").exists()  # stale pid files are pruned
    assert sampler.jobs_seen == 2

    usage[11] = (30 * _MB, 3.0)
    clock.now = 112.0
    row = next(r for r in sampler.rows() if r.session_id == "AJ_a")
    assert row.cpu_pct == 50.0  # 1 CPU second over 2 s
    assert row.mem_mb == 30.0
    assert row.peak_mb == 40.0
    assert sampler.jobs_seen == 2


def test_sampler_keeps_rows_without_cpu_readings(tmp_path: Path) -> None:
    (tmp_path / "AJ_a").write_text("11")
    sampler = ProcessJobSampler(
        agents={},
        active_jobs=lambda: [_job("AJ_a")],
        job_pid_dir=tmp_path,
        usage_reader=lambda _pid: (None, None),
    )
    (row,) = sampler.rows()
    assert row.agent_name == ""
    assert row.mem_mb == 0.0
    assert row.cpu_pct == 0.0


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")
def test_read_process_usage_reads_this_process() -> None:
    mem, cpu = read_process_usage(os.getpid())
    assert mem is not None
    assert mem > 0
    assert cpu is not None
    assert cpu >= 0


def test_read_process_usage_falls_back_to_psutil(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(process_top, "_linux_pss_bytes", lambda _pid: None)
    monkeypatch.setattr(process_top, "_linux_cpu_seconds", lambda _pid: None)
    fake = SimpleNamespace(
        memory_info=lambda: SimpleNamespace(rss=5 * _MB),
        cpu_times=lambda: SimpleNamespace(user=1.5, system=0.5),
    )
    monkeypatch.setattr(process_top, "_psutil_process", lambda _pid: fake)
    assert read_process_usage(1) == (5 * _MB, 2.0)

    monkeypatch.setattr(process_top, "_psutil_process", lambda _pid: None)
    assert read_process_usage(1) == (None, None)


def test_psutil_process_is_none_without_psutil(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "psutil", None)
    assert process_top._psutil_process(os.getpid()) is None


def test_proc_readers_tolerate_a_missing_process() -> None:
    assert process_top._linux_pss_bytes(-1) is None
    assert process_top._linux_cpu_seconds(-1) is None


def _short_socket() -> Path:
    # Unix socket paths cap at ~104 chars.
    return Path(tempfile.gettempdir()) / f"ortc-{uuid.uuid4().hex[:8]}.sock"


@pytest.mark.asyncio
async def test_runtime_serves_job_rows_over_the_socket() -> None:
    socket_path = _short_socket()
    jobs: list[Any] = [_job("AJ_a", job_metadata='{"agent": "sales"}')]
    runtime = ProcessIntrospectionRuntime(
        agents=_AGENTS,
        active_jobs=lambda: jobs,
        socket_path=socket_path,
        worker_context_provider=_context,
        usage_reader=lambda _pid: (8 * _MB, 1.0),
    )
    await runtime.start()
    try:
        record_job_pid(str(runtime.job_pid_dir), "AJ_a")
        snap = await fetch_snapshot(socket_path)
    finally:
        await runtime.aclose()

    assert [row["agent_name"] for row in snap["sessions"]] == ["sales"]
    assert snap["sessions"][0]["mem_mb"] == 8.0
    assert snap["worker"]["active_sessions"] == 1
    assert snap["worker"]["started"] == 1
    assert snap["worker"]["failed"] == 0
    assert not socket_path.exists()
    assert not runtime.job_pid_dir.exists()


@pytest.mark.asyncio
async def test_process_server_runs_top_around_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _run(_self: Any, *, devmode: bool, unregistered: bool) -> None:
        calls.append("run")

    monkeypatch.setattr(AgentServer, "run", _run)

    class _Top:
        async def start(self) -> None:
            calls.append("start")

        async def aclose(self) -> None:
            calls.append("close")

    server = _ProcessAgentServer()
    await server.run()
    assert calls == ["run"]

    calls.clear()
    server.attach_introspection(_Top())  # type: ignore[arg-type]
    await server.run()
    assert calls == ["start", "run", "close"]
