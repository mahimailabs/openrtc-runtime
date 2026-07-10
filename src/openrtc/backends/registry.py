"""Backend selection: framework name to a ``Backend`` builder (lazy import).

``AgentPool(backend=...)`` resolves the substrate here. Each entry is imported
lazily on selection, so ``import openrtc`` (and picking one backend) never pulls
another framework. Only the livekit backend ships today; ``pipecat`` is added
here when its backend lands, behind the ``openrtc[pipecat]`` extra.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from openrtc.core.backend import Backend
    from openrtc.runtime.registry import ServerParams

__all__ = ["resolve_backend_builder"]

# backend name -> (module path, builder attribute). Lazy import keeps each
# framework out of the others' (and the neutral core's) import graph.
_BACKENDS: dict[str, tuple[str, str]] = {
    "livekit": ("openrtc.backends.livekit", "build_backend"),
}


def resolve_backend_builder(name: str) -> Callable[[ServerParams, str], Backend]:
    """Return the ``Backend`` builder for a framework name (lazy import).

    Raises ``ValueError`` for an unknown name. When a backend's extra is not
    installed, importing its module raises the underlying ``ImportError`` with the
    missing dependency, which the pool surfaces as an install hint.
    """
    try:
        module_path, attr = _BACKENDS[name]
    except KeyError as exc:
        available = ", ".join(sorted(_BACKENDS))
        raise ValueError(
            f"Unknown backend {name!r}. Available backends: {available}."
        ) from exc
    module = importlib.import_module(module_path)
    builder: Callable[[ServerParams, str], Backend] = getattr(module, attr)
    return builder
