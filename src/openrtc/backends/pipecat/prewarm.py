"""Shared prewarm for the pipecat backend.

Pipecat instantiates the Silero VAD analyzer and the SmartTurn ONNX model per
bot (``run_bot`` builds them inline). OpenRTC loads each once per worker and
hands the same instance to every call's pipeline builder, the same memory/CPU
win the livekit backend gets from ``proc.userdata`` prewarm. ONNX ``Run()`` is
thread-safe, so one analyzer safely serves concurrent sessions.

The heavy pipecat imports live inside the default factories, which run on first
access, so importing this module pulls neither pipecat nor onnxruntime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["SharedPrewarm"]

# A distinct "not loaded yet" marker so a factory may legitimately return None.
_UNSET: Any = object()


def _default_vad_factory() -> Any:
    """Build pipecat's Silero VAD analyzer (loaded lazily, behind the extra)."""
    try:
        from pipecat.audio.vad.silero import SileroVADAnalyzer
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "The pipecat backend needs the Silero VAD analyzer. "
            "Install it with: pip install openrtc[pipecat]"
        ) from exc
    return SileroVADAnalyzer()


def _default_turn_factory() -> Any:
    """Build pipecat's local SmartTurn v3 analyzer (bundled ONNX, no download)."""
    try:
        from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import (
            LocalSmartTurnAnalyzerV3,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "The pipecat backend needs the SmartTurn analyzer. "
            "Install it with: pip install openrtc[pipecat]"
        ) from exc
    return LocalSmartTurnAnalyzerV3()


class SharedPrewarm:
    """Load the pipecat VAD and turn analyzers once; share them across calls.

    Each analyzer is built on first access by its factory, then cached. The pool
    holds one ``SharedPrewarm`` and hands it to every call's builder (through the
    call view), so N concurrent sessions share one VAD and one turn model instead
    of each building its own. The factories are injectable so tests exercise the
    sharing without loading the real ONNX models.
    """

    __slots__ = ("_turn", "_turn_factory", "_vad", "_vad_factory")

    def __init__(
        self,
        *,
        vad_factory: Callable[[], Any] = _default_vad_factory,
        turn_factory: Callable[[], Any] = _default_turn_factory,
    ) -> None:
        self._vad_factory = vad_factory
        self._turn_factory = turn_factory
        self._vad: Any = _UNSET
        self._turn: Any = _UNSET

    @property
    def vad(self) -> Any:
        """The shared VAD analyzer, built once on first access."""
        if self._vad is _UNSET:
            self._vad = self._vad_factory()
        return self._vad

    @property
    def turn(self) -> Any:
        """The shared turn analyzer, built once on first access."""
        if self._turn is _UNSET:
            self._turn = self._turn_factory()
        return self._turn
