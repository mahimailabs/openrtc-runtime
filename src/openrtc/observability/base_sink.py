"""The metrics-sink contract; JsonlMetricsSink is the built-in implementation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from openrtc.observability.snapshot import PoolRuntimeSnapshot

__all__ = ["MetricsSink"]


@runtime_checkable
class MetricsSink(Protocol):
    """Receive snapshot and event records from the runtime reporter."""

    def open(self) -> None: ...

    def write_snapshot(self, snapshot: PoolRuntimeSnapshot) -> None: ...

    def write_event(self, payload: Mapping[str, Any]) -> None: ...

    def close(self) -> None: ...
