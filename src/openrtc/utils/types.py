"""Shared type aliases for voice pipeline provider slots (STT, LLM, TTS)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    from livekit.agents import JobRequest

# Values accepted for STT, LLM, and TTS configuration:
# - Provider ID strings (e.g. ``"openai/gpt-4o-mini-transcribe"``) used by LiveKit
#   routing and the OpenRTC CLI defaults.
# - Concrete LiveKit plugin instances (e.g. ``livekit.plugins.openai.STT(...)``).
# ``object`` allows any third-party plugin class without enumerating them here;
# use strings when you want the type checker to stay precise.
ProviderValue: TypeAlias = str | object

# A per-job accept/reject hook. LiveKit offers every room to every worker under
# automatic dispatch; a request filter lets a pool accept only the rooms it
# should handle by awaiting ``req.accept()`` or ``req.reject()``. Passed to
# ``AgentPool(request_fnc=...)``; ``None`` keeps LiveKit's accept-all default.
RequestFilter: TypeAlias = Callable[["JobRequest"], Awaitable[None]]

# A custom dispatch router: maps a job's parsed dispatch metadata to a registered
# agent name (or ``None`` to defer to the default routing chain). Passed to
# ``AgentPool(router=...)``; an unknown name or a raised exception rejects the
# session. In ``process`` isolation it must be picklable (a module-level function,
# not a lambda), since it rides on the spawned worker's runtime state; in the
# default ``coroutine`` mode any callable works.
AgentRouter: TypeAlias = Callable[[Mapping[str, Any] | None], "str | None"]
