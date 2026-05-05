"""Worker prewarm hook.

The function in this module is registered as ``AgentServer.setup_fnc`` and runs
once per worker process before any session starts. It loads the shared runtime
assets (Silero VAD, LiveKit turn-detector model) into ``proc.userdata`` so they
are not re-loaded per session.

Adding a new shared resource means adding it to ``_prewarm_worker``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from livekit.agents import JobProcess

if TYPE_CHECKING:
    from openrtc.core.pool import _PoolRuntimeState


def _prewarm_worker(
    runtime_state: _PoolRuntimeState,
    proc: JobProcess,
) -> None:
    """Load shared runtime assets into ``proc.userdata`` once per worker."""
    if not runtime_state.agents:
        raise RuntimeError("Register at least one agent before calling run().")
    silero_module, turn_detector_model = _load_shared_runtime_dependencies()
    proc.userdata["vad"] = silero_module.VAD.load()
    proc.userdata["turn_detection_factory"] = turn_detector_model


def _load_shared_runtime_dependencies() -> tuple[Any, type[Any]]:
    """Load the optional LiveKit runtime dependencies used during prewarm."""
    try:
        from livekit.plugins import silero
        from livekit.plugins.turn_detector.multilingual import MultilingualModel
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "OpenRTC requires the LiveKit Silero and turn-detector plugins. "
            "Reinstall openrtc, or install livekit-agents[silero,turn-detector]."
        ) from exc

    return silero, MultilingualModel
