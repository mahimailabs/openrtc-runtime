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
    _deprecated_turn_options_to_turn_handling,
    _supports_multilingual_turn_detection,
)


def _proc(*, inference_executor: Any = None) -> Any:
    return SimpleNamespace(
        userdata={"vad": object(), "turn_detection_factory": lambda: "td"},
        inference_executor=inference_executor,
    )


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

    assert _supports_multilingual_turn_detection(_proc()) is True


def test_supports_multilingual_when_inference_executor_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LIVEKIT_REMOTE_EOT_URL", raising=False)

    assert (
        _supports_multilingual_turn_detection(_proc(inference_executor="exec")) is True
    )


def test_supports_multilingual_returns_false_with_no_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LIVEKIT_REMOTE_EOT_URL", raising=False)

    assert _supports_multilingual_turn_detection(_proc()) is False


def test_explicit_turn_handling_non_mapping_is_passed_through() -> None:
    sentinel = object()

    result = _build_session_kwargs({"turn_handling": sentinel}, _proc())

    assert result["turn_handling"] is sentinel
