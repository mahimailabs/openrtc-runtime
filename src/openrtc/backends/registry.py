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

# backend name -> (module path, builder attribute, pip extra / framework root).
# Lazy import keeps each framework out of the others' (and the neutral core's)
# import graph; the extra name (== the framework's top-level module) drives the
# install hint when it is not installed.
_BACKENDS: dict[str, tuple[str, str, str]] = {
    "livekit": ("openrtc.backends.livekit", "build_backend", "livekit"),
}


def resolve_backend_builder(name: str) -> Callable[[ServerParams, str], Backend]:
    """Return the ``Backend`` builder for a framework name (lazy import).

    Raises ``ValueError`` for an unknown name. When the backend's framework is not
    installed, raises ``ImportError`` with an install hint (``pip install
    openrtc[<extra>]``); any other import failure propagates unchanged.
    """
    try:
        module_path, attr, extra = _BACKENDS[name]
    except KeyError as exc:
        available = ", ".join(sorted(_BACKENDS))
        raise ValueError(
            f"Unknown backend {name!r}. Available backends: {available}."
        ) from exc
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] == extra:
            raise ImportError(
                f"The {name!r} backend needs the {extra!r} framework, which is not "
                f"installed. Install it with: pip install openrtc[{extra}]"
            ) from exc
        raise
    builder: Callable[[ServerParams, str], Backend] = getattr(module, attr)
    return builder
