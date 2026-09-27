"""Per-framework worker substrates for :class:`openrtc.core.backend.Backend`.

The ``livekit`` subpackage adapts livekit-agents to OpenRTC's ``Backend`` seam.
Subpackages import their framework, so this
package deliberately imports nothing at the top level: ``import openrtc.backends``
pulls no framework.
"""

from __future__ import annotations

__all__: list[str] = []
