"""Per-framework worker substrates for :class:`openrtc.core.backend.Backend`.

Each subpackage adapts one voice framework to OpenRTC's neutral ``Backend`` seam
(``livekit`` today, ``pipecat`` next). Subpackages import their framework, so this
package deliberately imports nothing at the top level: ``import openrtc.backends``
pulls no framework.
"""

from __future__ import annotations

__all__: list[str] = []
