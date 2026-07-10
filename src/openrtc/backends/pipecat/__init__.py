"""The pipecat worker substrate: OpenRTC's operational layer over pipecat.

Importing this package (or its modules) pulls pipecat, so it is imported only for
the pipecat backend, never at ``import openrtc`` top level. Built up piece by
piece against pipecat's frame-driven test harness
(``pipecat.tests.utils.run_test``): the lifecycle observer today, the pipeline
builder and dispatch front next.
"""

from __future__ import annotations

__all__: list[str] = []
