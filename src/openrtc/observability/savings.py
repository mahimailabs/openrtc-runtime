"""Shared-worker memory savings estimate and its one-line readout."""

from __future__ import annotations

from openrtc.observability.snapshot import SavingsEstimate

__all__ = ["estimate_shared_worker_savings", "format_prewarm_savings"]


def estimate_shared_worker_savings(
    *,
    agent_count: int,
    shared_worker_bytes: int | None,
) -> SavingsEstimate:
    """Estimate the value of one shared worker versus one worker per agent.

    The estimate intentionally uses only the current shared worker memory as a
    baseline. It assumes separate workers would each pay approximately the same
    base worker cost before per-call overhead.
    """
    assumptions = (
        "Estimated separate-worker memory multiplies the current shared-worker "
        "baseline by the number of registered agents.",
        "This is a best-effort comparison, not a container-orchestrator metric.",
        "Actual memory depends on active sessions, providers, and model loading.",
    )
    if agent_count <= 0 or shared_worker_bytes is None:
        return SavingsEstimate(
            agent_count=agent_count,
            shared_worker_bytes=shared_worker_bytes,
            estimated_separate_workers_bytes=None,
            estimated_saved_bytes=None,
            assumptions=assumptions,
        )

    separate_workers = shared_worker_bytes * agent_count
    saved_bytes = max(separate_workers - shared_worker_bytes, 0)
    return SavingsEstimate(
        agent_count=agent_count,
        shared_worker_bytes=shared_worker_bytes,
        estimated_separate_workers_bytes=separate_workers,
        estimated_saved_bytes=saved_bytes,
        assumptions=assumptions,
    )


def format_prewarm_savings(*, agent_count: int, shared_worker_bytes: int | None) -> str:
    """One honest, human-readable line about the shared-worker idle-baseline win.

    Emitted once per worker at prewarm so the fleet-collapse saving is visible on
    first run. It claims only idle-baseline memory saved by hosting N per-agent
    workers as one shared worker; it never implies per-session density or a speed
    multiple, and it names its equal-baseline assumption whenever it shows a
    number. Stays graceful when RSS is unavailable (e.g. Windows).
    """
    estimate = estimate_shared_worker_savings(
        agent_count=agent_count, shared_worker_bytes=shared_worker_bytes
    )
    agents = "1 agent" if agent_count == 1 else f"{agent_count} agents"

    if estimate.shared_worker_bytes is None or estimate.estimated_saved_bytes is None:
        return (
            f"OpenRTC: {agents} in 1 worker; per-worker memory estimate "
            "unavailable on this platform."
        )

    baseline_mb = estimate.shared_worker_bytes / (1024 * 1024)
    if agent_count <= 1:
        return (
            f"OpenRTC: {agents} in this worker (baseline ~{baseline_mb:.0f} MB). "
            "Register more agents on the pool to amortize the shared prewarm."
        )

    separate_mb = (estimate.estimated_separate_workers_bytes or 0) / (1024 * 1024)
    saved_mb = estimate.estimated_saved_bytes / (1024 * 1024)
    return (
        f"OpenRTC: {agents} in 1 worker (baseline ~{baseline_mb:.0f} MB). "
        f"{agent_count} separate livekit-agents workers would cost "
        f"~{separate_mb:.0f} MB; sharing one worker saves ~{saved_mb:.0f} MB "
        "of idle baseline (assumes equal per-worker baselines)."
    )
