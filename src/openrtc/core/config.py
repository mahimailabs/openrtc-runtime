"""Public agent configuration types and the ``@agent_config`` decorator."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from livekit.agents import Agent

from openrtc.types import ProviderValue

if TYPE_CHECKING:
    from openrtc.core.pool import _AgentClassRef

_AgentType = TypeVar("_AgentType", bound=type[Agent])
_AGENT_METADATA_ATTR = "__openrtc_agent_config__"


def _normalize_optional_name(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(
            f"OpenRTC metadata field {field_name!r} must be a string, got "
            f"{type(value).__name__}."
        )
    normalized_value = value.strip()
    if not normalized_value:
        raise RuntimeError(f"OpenRTC metadata field {field_name!r} cannot be empty.")
    return normalized_value


@dataclass(slots=True)
class AgentConfig:
    """Configuration for a registered LiveKit agent.

    Args:
        name: Unique name used to identify and route to the agent.
        agent_cls: A ``livekit.agents.Agent`` subclass.
        stt: Speech-to-text provider string or provider instance.
        llm: Large language model provider string or provider instance.
        tts: Text-to-speech provider string or provider instance.
        greeting: Optional initial greeting played after the session connects.
        session_kwargs: Additional keyword arguments forwarded to ``AgentSession``.
        source_path: When known (e.g. after discovery), filesystem path to the agent
            module ``.py`` file; ``None`` when unknown (e.g. programmatic ``add()`` without path).
    """

    name: str
    agent_cls: type[Agent]
    stt: ProviderValue | None = None
    llm: ProviderValue | None = None
    tts: ProviderValue | None = None
    greeting: str | None = None
    session_kwargs: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None
    _agent_ref: _AgentClassRef = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Late imports avoid a circular dependency with core.pool until the
        # serialization helpers move to core/serialization.py (next refactor task).
        from openrtc.core.pool import (
            _build_agent_class_ref,
            _serialize_provider_value,
        )

        self._agent_ref = _build_agent_class_ref(self.agent_cls)
        _serialize_provider_value(self.stt)
        _serialize_provider_value(self.llm)
        _serialize_provider_value(self.tts)

    def __getstate__(self) -> dict[str, Any]:
        from openrtc.core.pool import _serialize_provider_value

        return {
            "name": self.name,
            "stt": _serialize_provider_value(self.stt),
            "llm": _serialize_provider_value(self.llm),
            "tts": _serialize_provider_value(self.tts),
            "greeting": self.greeting,
            "session_kwargs": dict(self.session_kwargs),
            "agent_ref": self._agent_ref,
            "source_path": (
                None if self.source_path is None else str(self.source_path.resolve())
            ),
        }

    def __setstate__(self, state: Mapping[str, Any]) -> None:
        from openrtc.core.pool import (
            _deserialize_provider_value,
            _resolve_agent_class,
        )

        self.name = state["name"]
        self.stt = _deserialize_provider_value(state["stt"])
        self.llm = _deserialize_provider_value(state["llm"])
        self.tts = _deserialize_provider_value(state["tts"])
        self.greeting = state["greeting"]
        self.session_kwargs = dict(state["session_kwargs"])
        self._agent_ref = state["agent_ref"]
        raw_source = state.get("source_path")
        self.source_path = None if raw_source is None else Path(str(raw_source))
        self.agent_cls = _resolve_agent_class(self._agent_ref)


@dataclass(slots=True)
class AgentDiscoveryConfig:
    """Optional metadata attached to an ``Agent`` class for discovery.

    Args:
        name: Optional explicit agent name. Falls back to the module filename when
            omitted.
        stt: Optional STT provider override.
        llm: Optional LLM provider override.
        tts: Optional TTS provider override.
        greeting: Optional greeting override.
    """

    name: str | None = None
    stt: ProviderValue | None = None
    llm: ProviderValue | None = None
    tts: ProviderValue | None = None
    greeting: str | None = None


def agent_config(
    *,
    name: str | None = None,
    stt: ProviderValue | None = None,
    llm: ProviderValue | None = None,
    tts: ProviderValue | None = None,
    greeting: str | None = None,
) -> Callable[[_AgentType], _AgentType]:
    """Attach OpenRTC discovery metadata to a standard LiveKit ``Agent`` class.

    Args:
        name: Optional explicit agent name used during discovery.
        stt: Optional STT provider override.
        llm: Optional LLM provider override.
        tts: Optional TTS provider override.
        greeting: Optional greeting override.

    Returns:
        A decorator that stores OpenRTC discovery metadata on the class.
    """

    metadata = AgentDiscoveryConfig(
        name=_normalize_optional_name(name, field_name="name"),
        stt=stt,
        llm=llm,
        tts=tts,
        greeting=_normalize_optional_name(greeting, field_name="greeting"),
    )

    def decorator(agent_cls: _AgentType) -> _AgentType:
        setattr(agent_cls, _AGENT_METADATA_ATTR, metadata)
        return agent_cls

    return decorator
