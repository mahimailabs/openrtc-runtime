"""Drive a full pipecat call lifecycle in-process, to verify the pipecat backend.

A pipecat "call" is a pipeline run: a ``StartFrame`` opens it, user frames flow,
an ``EndFrame`` closes it. Pipecat's ``PipelineWorker`` + ``WorkerRunner`` run
exactly that over a set of processors, with no transport, audio, or network.
``simulate_call`` packages it so an OpenRTC pipecat session (a builder's
processors plus OpenRTC's observability) can be verified end-to-end against real
pipecat, the way ``pipecat.tests.utils.run_test`` verifies a single processor.

This is a testing utility (importable by OpenRTC's suite and by users testing
their own pipecat agents); it is not on any runtime path.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pipecat.frames.frames import EndFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.workers.runner import WorkerRunner

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pipecat.frames.frames import Frame
    from pipecat.observers.base_observer import BaseObserver

__all__ = ["simulate_call"]


class _CaptureSink(FrameProcessor):
    """Record every frame reaching the end of the pipeline, then forward it."""

    def __init__(self, captured: list[Frame]) -> None:
        super().__init__()
        self._captured = captured

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        self._captured.append(frame)
        await self.push_frame(frame, direction)


async def simulate_call(
    processors: Sequence[FrameProcessor],
    *,
    user_frames: Sequence[Frame],
    observers: Sequence[BaseObserver] = (),
    timeout: float = 5.0,
) -> list[Frame]:
    """Run a scripted call through ``processors`` on a real pipecat worker.

    Drives ``StartFrame`` (connect) then each of ``user_frames`` then ``EndFrame``
    (disconnect) through a genuine ``PipelineWorker`` / ``WorkerRunner``, with
    ``observers`` (e.g. OpenRTC's ``PipecatLifecycleObserver``) attached, and
    returns the frames captured at the end of the pipeline. Bounded by ``timeout``
    so a stalled pipeline fails fast instead of hanging.
    """
    captured: list[Frame] = []
    pipeline = Pipeline([*processors, _CaptureSink(captured)])
    worker = PipelineWorker(
        pipeline, cancel_on_idle_timeout=False, observers=list(observers)
    )

    async def _drive() -> None:
        await asyncio.sleep(0.01)  # let the runner start the worker
        for frame in user_frames:
            await worker.queue_frame(frame, FrameDirection.DOWNSTREAM)
        await worker.queue_frame(EndFrame())

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await asyncio.wait_for(asyncio.gather(runner.run(), _drive()), timeout=timeout)
    return captured
