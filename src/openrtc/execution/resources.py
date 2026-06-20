"""Typed access to the shared assets prewarm stores on the worker process."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from livekit.agents import JobProcess

__all__ = ["PrewarmResources"]

_VAD_KEY = "vad"
_TURN_DETECTION_FACTORY_KEY = "turn_detection_factory"


@dataclass(frozen=True, slots=True)
class PrewarmResources:
    """Shared runtime assets loaded once per worker in prewarm."""

    vad: Any
    turn_detection_factory: Any

    def store(self, proc: JobProcess) -> None:
        """Write the resources into ``proc.userdata`` under their canonical keys."""
        proc.userdata[_VAD_KEY] = self.vad
        proc.userdata[_TURN_DETECTION_FACTORY_KEY] = self.turn_detection_factory

    @staticmethod
    def vad_from(proc: JobProcess) -> Any:
        """Return the prewarmed VAD stored on ``proc``."""
        return proc.userdata[_VAD_KEY]

    @staticmethod
    def turn_detection_factory_from(proc: JobProcess) -> Any:
        """Return the prewarmed turn-detection factory stored on ``proc``."""
        return proc.userdata[_TURN_DETECTION_FACTORY_KEY]
