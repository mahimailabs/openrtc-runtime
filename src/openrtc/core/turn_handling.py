"""Build ``AgentSession.turn_handling`` from raw kwargs and deprecated options.

OpenRTC accepts both the modern ``turn_handling`` dict and a flatter set of
top-level kwargs (``min_endpointing_delay``, ``allow_interruptions``, ...) that
match the older ``livekit-agents`` shape. This module owns that translation
plus the default turn-handling block we apply when nothing is configured.
"""

from __future__ import annotations

import logging
import os
import warnings
from collections.abc import Mapping
from typing import Any

from livekit.agents import JobProcess

from openrtc.runtime.resources import PrewarmResources

logger = logging.getLogger("openrtc")

_DEPRECATED_TURN_HANDLING_KEYS = (
    "min_endpointing_delay",
    "max_endpointing_delay",
    "false_interruption_timeout",
    "turn_detection",
    "discard_audio_if_uninterruptible",
    "min_interruption_duration",
    "min_interruption_words",
    "allow_interruptions",
    "resume_false_interruption",
    "agent_false_interruption_timeout",
)


def _build_session_kwargs(
    configured_kwargs: Mapping[str, Any],
    proc: JobProcess,
    inference_executor: Any = None,
) -> dict[str, Any]:
    session_kwargs = dict(configured_kwargs)
    explicit_turn_handling = session_kwargs.pop("turn_handling", None)
    deprecated_turn_options = _extract_deprecated_turn_options(session_kwargs)

    if isinstance(explicit_turn_handling, Mapping):
        turn_handling = _merge_turn_handling(
            _default_turn_handling(proc, inference_executor),
            explicit_turn_handling,
        )
    else:
        turn_handling = _default_turn_handling(proc, inference_executor)
        if deprecated_turn_options:
            turn_handling = _merge_turn_handling(
                turn_handling,
                _deprecated_turn_options_to_turn_handling(deprecated_turn_options),
            )

    if explicit_turn_handling is not None and not isinstance(
        explicit_turn_handling, Mapping
    ):
        session_kwargs["turn_handling"] = explicit_turn_handling
    else:
        session_kwargs["turn_handling"] = turn_handling

    return session_kwargs


def _default_turn_handling(
    proc: JobProcess, inference_executor: Any = None
) -> dict[str, Any]:
    turn_detection = _default_turn_detection(proc, inference_executor)
    turn_handling: dict[str, Any] = {"interruption": {"mode": "vad"}}
    if turn_detection is not None:
        turn_handling["turn_detection"] = turn_detection
    return turn_handling


def _default_turn_detection(proc: JobProcess, inference_executor: Any = None) -> Any:
    if _supports_multilingual_turn_detection(inference_executor):
        return PrewarmResources.turn_detection_factory_from(proc)()

    logger.info(
        "Falling back to VAD turn detection because no usable inference executor "
        "or LIVEKIT_REMOTE_EOT_URL is available."
    )
    return "vad"


def _supports_multilingual_turn_detection(inference_executor: Any) -> bool:
    """Whether the prewarmed multilingual turn detector can run for this job.

    The inference executor lives on the ``JobContext`` (``ctx.inference_executor``),
    not on the ``JobProcess``: a real ``JobProcess`` has no such attribute, so the
    previous ``proc``-based check always failed and silently fell back to VAD.
    A remote EOT endpoint removes the need for a local executor entirely.
    """
    if os.getenv("LIVEKIT_REMOTE_EOT_URL"):
        return True

    return _is_usable_inference_executor(inference_executor)


def _is_usable_inference_executor(inference_executor: Any) -> bool:
    """An inference executor is usable unless absent or the coroutine no-op stub.

    ``_openrtc_noop`` is set on ``runtime.coroutine_runtime._NoOpInferenceExecutor``;
    selecting the detector against that stub would raise on the first inference.
    """
    if inference_executor is None:
        return False
    return not getattr(inference_executor, "_openrtc_noop", False)


def _extract_deprecated_turn_options(session_kwargs: dict[str, Any]) -> dict[str, Any]:
    deprecated_options: dict[str, Any] = {}
    for key in _DEPRECATED_TURN_HANDLING_KEYS:
        if key in session_kwargs:
            deprecated_options[key] = session_kwargs.pop(key)
    if deprecated_options:
        found = ", ".join(f"'{k}'" for k in deprecated_options)
        warnings.warn(
            f"Passing {found} as top-level session_kwargs keys is deprecated and will "
            "be removed in a future release. Use the turn_handling dict instead: "
            "session_kwargs={'turn_handling': {'endpointing': {...}, 'interruption': {...}}}. "
            "See the AgentPool.add() docstring for the supported turn_handling structure.",
            DeprecationWarning,
            stacklevel=3,
        )
    return deprecated_options


def _deprecated_turn_options_to_turn_handling(
    options: Mapping[str, Any],
) -> dict[str, Any]:
    turn_handling: dict[str, Any] = {}
    endpointing: dict[str, Any] = {}
    interruption: dict[str, Any] = {}

    if "min_endpointing_delay" in options:
        endpointing["min_delay"] = options["min_endpointing_delay"]
    if "max_endpointing_delay" in options:
        endpointing["max_delay"] = options["max_endpointing_delay"]
    if endpointing:
        turn_handling["endpointing"] = endpointing

    if options.get("allow_interruptions") is False:
        interruption["enabled"] = False
    if "discard_audio_if_uninterruptible" in options:
        interruption["discard_audio_if_uninterruptible"] = options[
            "discard_audio_if_uninterruptible"
        ]
    if "min_interruption_duration" in options:
        interruption["min_duration"] = options["min_interruption_duration"]
    if "min_interruption_words" in options:
        interruption["min_words"] = options["min_interruption_words"]
    if "false_interruption_timeout" in options:
        interruption["false_interruption_timeout"] = options[
            "false_interruption_timeout"
        ]
    if "agent_false_interruption_timeout" in options:
        interruption["false_interruption_timeout"] = options[
            "agent_false_interruption_timeout"
        ]
    if "resume_false_interruption" in options:
        interruption["resume_false_interruption"] = options["resume_false_interruption"]
    if interruption:
        turn_handling["interruption"] = interruption

    if "turn_detection" in options:
        turn_handling["turn_detection"] = options["turn_detection"]

    return turn_handling


def _merge_turn_handling(
    base: Mapping[str, Any],
    override: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged
