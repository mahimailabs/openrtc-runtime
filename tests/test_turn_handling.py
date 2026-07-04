"""Unit tests for ``openrtc.core.turn_handling`` translation helpers.

The module turns the v0.0.x flat top-level kwargs (``min_endpointing_delay``,
``allow_interruptions``, ...) into the modern nested ``turn_handling`` dict
that ``AgentSession`` expects. Each deprecated key has a fixed mapping; this
suite locks down the per-key translations and the env-var / explicit-object
edge cases that the higher-level ``test_pool.py`` integration tests don't
exercise individually.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from openrtc.core.turn_handling import (
    _build_session_kwargs,
    _default_turn_detection,
    _deprecated_turn_options_to_turn_handling,
    _supports_multilingual_turn_detection,
)


def _proc() -> Any:
    # A real livekit ``JobProcess`` has no ``inference_executor`` attribute; the
    # executor lives on the ``JobContext`` and is passed separately. This fake
    # deliberately omits it so tests cannot accidentally read it from the proc.
    return SimpleNamespace(
        userdata={"vad": object(), "turn_detection_factory": lambda: "td"},
    )


class _NoopExecutor:
    """Mirrors ``_NoOpInferenceExecutor``'s unusable marker without importing it."""

    _openrtc_noop = True


def test_min_endpointing_delay_maps_to_endpointing_min_delay() -> None:
    result = _deprecated_turn_options_to_turn_handling({"min_endpointing_delay": 0.3})

    assert result == {"endpointing": {"min_delay": 0.3}}


def test_max_endpointing_delay_maps_to_endpointing_max_delay() -> None:
    result = _deprecated_turn_options_to_turn_handling({"max_endpointing_delay": 1.2})

    assert result == {"endpointing": {"max_delay": 1.2}}


def test_endpointing_keys_combine_into_one_endpointing_block() -> None:
    result = _deprecated_turn_options_to_turn_handling(
        {"min_endpointing_delay": 0.3, "max_endpointing_delay": 1.2}
    )

    assert result == {"endpointing": {"min_delay": 0.3, "max_delay": 1.2}}


def test_allow_interruptions_false_disables_interruption() -> None:
    result = _deprecated_turn_options_to_turn_handling({"allow_interruptions": False})

    assert result == {"interruption": {"enabled": False}}


def test_allow_interruptions_true_does_not_emit_enabled_key() -> None:
    result = _deprecated_turn_options_to_turn_handling({"allow_interruptions": True})

    assert result == {}


def test_discard_audio_if_uninterruptible_propagates() -> None:
    result = _deprecated_turn_options_to_turn_handling(
        {"discard_audio_if_uninterruptible": True}
    )

    assert result == {"interruption": {"discard_audio_if_uninterruptible": True}}


def test_min_interruption_duration_maps_to_min_duration() -> None:
    result = _deprecated_turn_options_to_turn_handling(
        {"min_interruption_duration": 0.4}
    )

    assert result == {"interruption": {"min_duration": 0.4}}


def test_min_interruption_words_maps_to_min_words() -> None:
    result = _deprecated_turn_options_to_turn_handling({"min_interruption_words": 2})

    assert result == {"interruption": {"min_words": 2}}


def test_false_interruption_timeout_maps_to_interruption_block() -> None:
    result = _deprecated_turn_options_to_turn_handling(
        {"false_interruption_timeout": 1.5}
    )

    assert result == {"interruption": {"false_interruption_timeout": 1.5}}


def test_agent_false_interruption_timeout_aliases_false_interruption_timeout() -> None:
    result = _deprecated_turn_options_to_turn_handling(
        {"agent_false_interruption_timeout": 2.5}
    )

    assert result == {"interruption": {"false_interruption_timeout": 2.5}}


def test_resume_false_interruption_propagates() -> None:
    result = _deprecated_turn_options_to_turn_handling(
        {"resume_false_interruption": False}
    )

    assert result == {"interruption": {"resume_false_interruption": False}}


def test_turn_detection_propagates_through_translation() -> None:
    result = _deprecated_turn_options_to_turn_handling({"turn_detection": "vad"})

    assert result == {"turn_detection": "vad"}


def test_supports_multilingual_when_remote_eot_url_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVEKIT_REMOTE_EOT_URL", "https://eot.example/predict")

    # No local executor needed when a remote EOT endpoint is configured.
    assert _supports_multilingual_turn_detection(None) is True


def test_supports_multilingual_when_usable_inference_executor_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LIVEKIT_REMOTE_EOT_URL", raising=False)

    assert _supports_multilingual_turn_detection("exec") is True


def test_supports_multilingual_returns_false_with_no_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LIVEKIT_REMOTE_EOT_URL", raising=False)

    assert _supports_multilingual_turn_detection(None) is False


def test_supports_multilingual_rejects_noop_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The coroutine no-op stub is not a usable executor: gate must return False."""
    monkeypatch.delenv("LIVEKIT_REMOTE_EOT_URL", raising=False)

    assert _supports_multilingual_turn_detection(_NoopExecutor()) is False


def test_default_turn_detection_uses_detector_for_usable_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression (MAH-159): a usable executor on the context selects the
    prewarmed multilingual detector, not the VAD fallback. The proc has no
    ``inference_executor`` attribute, proving the gate reads the passed executor.
    """
    monkeypatch.delenv("LIVEKIT_REMOTE_EOT_URL", raising=False)

    result = _default_turn_detection(_proc(), inference_executor="real-exec")

    assert result == "td"  # the prewarmed factory's product, not "vad"


def test_default_turn_detection_falls_back_to_vad_for_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LIVEKIT_REMOTE_EOT_URL", raising=False)

    assert _default_turn_detection(_proc(), inference_executor=_NoopExecutor()) == "vad"


def test_default_turn_detection_falls_back_to_vad_without_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LIVEKIT_REMOTE_EOT_URL", raising=False)

    assert _default_turn_detection(_proc(), inference_executor=None) == "vad"


def test_build_session_kwargs_threads_inference_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end: a usable executor propagates into the turn_handling dict."""
    monkeypatch.delenv("LIVEKIT_REMOTE_EOT_URL", raising=False)

    result = _build_session_kwargs({}, _proc(), "real-exec")

    assert result["turn_handling"]["turn_detection"] == "td"


def test_explicit_turn_handling_non_mapping_is_passed_through() -> None:
    sentinel = object()

    result = _build_session_kwargs({"turn_handling": sentinel}, _proc())

    assert result["turn_handling"] is sentinel


def test_default_turn_handling_omits_turn_detection_key_when_factory_returns_none() -> (
    None
):
    """Branch: a factory that returns None means no ``turn_detection`` key in the dict."""
    from openrtc.core.turn_handling import _default_turn_handling

    proc = SimpleNamespace(
        userdata={"vad": object(), "turn_detection_factory": lambda: None},
    )

    result = _default_turn_handling(proc, inference_executor="present")

    assert "turn_detection" not in result
    assert result == {"interruption": {"mode": "vad"}}
