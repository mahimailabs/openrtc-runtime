"""PrewarmResources stores and reads the shared assets via one typed surface."""

from __future__ import annotations

from types import SimpleNamespace

from openrtc.runtime.resources import PrewarmResources


def test_store_then_read_round_trips() -> None:
    proc = SimpleNamespace(userdata={})
    factory = object()
    PrewarmResources(vad="VAD", turn_detection_factory=factory).store(proc)
    assert proc.userdata["vad"] == "VAD"
    assert proc.userdata["turn_detection_factory"] is factory
    assert PrewarmResources.vad_from(proc) == "VAD"
    assert PrewarmResources.turn_detection_factory_from(proc) is factory
