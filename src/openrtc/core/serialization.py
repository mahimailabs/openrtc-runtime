"""Spawn-safe serialization helpers for ``AgentConfig`` provider values.

OpenRTC supports forking the worker process. Provider instances such as
``livekit.plugins.openai.STT(...)`` cannot always survive serialization
unchanged, so we capture them as :class:`_ProviderRef` records when possible
and rebuild them in the spawned worker. The same machinery handles the
``Agent`` class reference (:class:`_AgentClassRef`).
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from livekit.agents import Agent

from openrtc.core.discovery import _load_module_from_path, _try_get_module_path

_SPAWN_PROBE = importlib.import_module("pickle")

_OPENAI_NOT_GIVEN_TYPE: type[Any] | None = None
try:
    from openai import NotGiven as _OpenAINotGiven
except ImportError:  # pragma: no cover - optional when openai is absent
    pass
else:
    _OPENAI_NOT_GIVEN_TYPE = _OpenAINotGiven


@dataclass(frozen=True, slots=True)
class _AgentClassRef:
    """Serializable reference to an agent class."""

    module_name: str
    qualname: str
    module_path: str | None = None


@dataclass(frozen=True, slots=True)
class _ProviderRef:
    """Serializable reference to a supported provider object."""

    module_name: str
    qualname: str
    kwargs: dict[str, Any]


# ``(module, qualname)`` pairs for plugin classes known to expose ``_opts``
# and rehydrate via ``ProviderClass(**kwargs)``.  The generic path in
# ``_try_build_provider_ref`` now handles any ``livekit.plugins.*`` class with
# ``_opts``, so this set is a fast-path / documentation of tested providers.
_PROVIDER_REF_KEYS: frozenset[tuple[str, str]] = frozenset(
    {
        ("livekit.plugins.openai.stt", "STT"),
        ("livekit.plugins.openai.tts", "TTS"),
        ("livekit.plugins.openai.responses.llm", "LLM"),
    }
)


def _serialize_provider_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    provider_ref = _try_build_provider_ref(value)
    if provider_ref is not None:
        return provider_ref

    try:
        _SPAWN_PROBE.dumps(value)
    except Exception as exc:
        raise ValueError(
            f"Provider object of type {value.__class__.__module__}."
            f"{value.__class__.__qualname__} is not spawn-safe. "
            "Pass a pickleable value or use a provider type supported by OpenRTC."
        ) from exc

    return value


def _deserialize_provider_value(value: Any) -> Any:
    if not isinstance(value, _ProviderRef):
        return value

    module = importlib.import_module(value.module_name)
    provider_cls = _resolve_qualname(module, value.qualname)
    return provider_cls(**dict(value.kwargs))


def _try_build_provider_ref(value: Any) -> _ProviderRef | None:
    cls = type(value)
    key = (cls.__module__, cls.__qualname__)
    # Fast path: known providers
    if key in _PROVIDER_REF_KEYS:
        return _ProviderRef(
            module_name=key[0],
            qualname=key[1],
            kwargs=_extract_provider_kwargs(value),
        )
    # Generic path: any livekit plugin with _opts
    if cls.__module__.startswith("livekit.plugins.") and hasattr(value, "_opts"):
        return _ProviderRef(
            module_name=cls.__module__,
            qualname=cls.__qualname__,
            kwargs=_extract_provider_kwargs(value),
        )
    return None


def _extract_provider_kwargs(value: Any) -> dict[str, Any]:
    options = getattr(value, "_opts", None)
    if options is None:
        return {}
    return _filter_provider_kwargs(vars(options))


def _filter_provider_kwargs(options: Mapping[str, Any]) -> dict[str, Any]:
    filtered: dict[str, Any] = {}
    for key, option_value in options.items():
        if _is_not_given(option_value):
            continue
        filtered[key] = option_value
    return filtered


def _is_not_given(value: Any) -> bool:
    """True if ``value`` is OpenAI's ``NotGiven`` (unset optional on plugin ``_opts``)."""
    if _OPENAI_NOT_GIVEN_TYPE is not None and isinstance(value, _OPENAI_NOT_GIVEN_TYPE):
        return True
    cls = type(value)
    if cls.__name__ != "NotGiven":
        return False
    module = getattr(cls, "__module__", "")
    return module == "openai._types" or module.startswith("openai.")


def _build_agent_class_ref(agent_cls: type[Agent]) -> _AgentClassRef:
    module_name = agent_cls.__module__
    qualname = agent_cls.__qualname__
    if "<locals>" in qualname:
        raise ValueError(
            "agent_cls must be defined at module scope so spawned workers can "
            "reload it safely."
        )

    module_path = _try_get_module_path(agent_cls)
    if module_name == "__main__" and module_path is None:
        raise ValueError(
            "agent_cls defined in __main__ must come from a real Python file so "
            "spawned workers can reload it."
        )

    return _AgentClassRef(
        module_name=module_name,
        qualname=qualname,
        module_path=None if module_path is None else str(module_path),
    )


def _resolve_agent_class(agent_ref: _AgentClassRef) -> type[Agent]:
    module: ModuleType | None = None
    module_path = (
        None if agent_ref.module_path is None else Path(agent_ref.module_path).resolve()
    )

    if module_path is not None and agent_ref.module_name.startswith(
        "openrtc_discovered_"
    ):
        module = _load_module_from_path(agent_ref.module_name, module_path)
    else:
        try:
            module = importlib.import_module(agent_ref.module_name)
        except ModuleNotFoundError:
            if module_path is None:
                raise
            module = _load_module_from_path(agent_ref.module_name, module_path)

    agent_cls = _resolve_qualname(module, agent_ref.qualname)
    if not isinstance(agent_cls, type) or not issubclass(agent_cls, Agent):
        raise TypeError(
            f"{agent_ref.qualname!r} in module {module.__name__!r} is not a "
            "livekit.agents.Agent subclass."
        )
    return agent_cls


def _resolve_qualname(module: ModuleType, qualname: str) -> Any:
    value: Any = module
    for part in qualname.split("."):
        value = getattr(value, part)
    return value
