"""JsonlMetricsSink conforms to the MetricsSink protocol."""

from __future__ import annotations

from pathlib import Path

from openrtc.observability.base_sink import MetricsSink
from openrtc.observability.jsonl_sink import JsonlMetricsSink


def test_jsonl_sink_conforms(tmp_path: Path) -> None:
    assert isinstance(JsonlMetricsSink(tmp_path / "m.jsonl"), MetricsSink)
