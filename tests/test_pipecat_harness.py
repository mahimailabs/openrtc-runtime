"""The pipecat test harness: verify OpenRTC's pipecat work against a real pipeline.

Pipecat backends cannot be checked against mocks alone (a wrong read of the
pipecat API would pass its own mocks while failing on a live pipeline). Pipecat
ships ``pipecat.tests.utils.run_test``, which runs a real ``PipelineRunner`` over
a processor, pushes frames, and validates the frames that flow out, all
in-process with no transport, audio, network, or provider keys.

This module proves that vehicle runs green in the suite. The pipecat backend and
its tests (added next) build on the same ``run_test`` harness, so their frame-flow
assertions exercise genuine pipecat behavior, not our own mocks.
"""

from __future__ import annotations

import pytest
from pipecat.frames.frames import Frame, TextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.tests.utils import run_test


class _Passthrough(FrameProcessor):
    """The smallest real processor: forward every frame unchanged."""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)


@pytest.mark.asyncio
async def test_pipecat_run_test_harness_runs_a_real_pipeline() -> None:
    received_down, _received_up = await run_test(
        _Passthrough(),
        frames_to_send=[TextFrame("hello")],
        expected_down_frames=[TextFrame],
    )
    assert any(
        isinstance(frame, TextFrame) and frame.text == "hello"
        for frame in received_down
    )
