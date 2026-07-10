"""The livekit worker substrate: OpenRTC's ``Backend`` over ``livekit-agents``.

Importing this package (or :mod:`openrtc.backends.livekit.backend`) pulls
livekit, so the pool imports it only for the livekit backend, never at
``import openrtc`` top level.
"""

from __future__ import annotations

from openrtc.backends.livekit.backend import LiveKitBackend, build_backend

__all__ = ["LiveKitBackend", "build_backend"]
