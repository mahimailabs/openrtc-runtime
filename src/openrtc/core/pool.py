from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import logging
import os
import pickle
import sys
import warnings
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import partial
from hashlib import sha1
from pathlib import Path
from types import ModuleType
from typing import Any, TypeVar, cast

from livekit.agents import Agent, AgentServer, AgentSession, JobContext, JobProcess, cli

from openrtc.resources import (
    MetricsStreamEvent,
    PoolRuntimeSnapshot,
    RuntimeMetricsStore,
)
from openrtc.types import ProviderValue

logger = logging.getLogger("openrtc")

_OPENAI_NOT_GIVEN_TYPE: type[Any] | None = None
try:
    from openai import NotGiven as _OpenAINotGiven
except ImportError:  # pragma: no cover - optional when openai is absent
    pass
else:
    _OPENAI_NOT_GIVEN_TYPE = _OpenAINotGiven

_AgentType = TypeVar("_AgentType", bound=type[Agent])
_AGENT_METADATA_ATTR = "__openrtc_agent_config__"
_METADATA_AGENT_KEYS = ("agent", "demo")
_DEPRECATED_TURN_HANDLING_KEYS = (
    "min_endpointing_delay",
    "max_endpointing_delay",
    "false_interruption_timeout",
    "turn_detection",
    "discard_audio_if_uninterruptible",
    "min_interruption_duration",
    "min_interruption_words",
    "allow_interruptions",
    "resume_false_interruption",
    "agent_false_interruption_timeout",
)


@dataclass(slots=True)
class _PoolRuntimeState:
    """Serializable runtime state shared with worker callbacks."""

    agents: dict[str, AgentConfig]
    metrics: RuntimeMetricsStore = field(default_factory=RuntimeMetricsStore)


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


def _prewarm_worker(
    runtime_state: _PoolRuntimeState,
    proc: JobProcess,
) -> None:
    """Load shared runtime assets into ``proc.userdata`` once per worker."""
    if not runtime_state.agents:
        raise RuntimeError("Register at least one agent before calling run().")
    silero_module, turn_detector_model = _load_shared_runtime_dependencies()
    proc.userdata["vad"] = silero_module.VAD.load()
    proc.userdata["turn_detection_factory"] = turn_detector_model


async def _run_universal_session(
    runtime_state: _PoolRuntimeState,
    ctx: JobContext,
) -> None:
    """Dispatch a session through the owning ``AgentPool``."""
    if not runtime_state.agents:
        raise RuntimeError("No agents are registered in the pool.")
    config = _resolve_agent_config(runtime_state.agents, ctx)
    session_kwargs = _build_session_kwargs(config.session_kwargs, ctx.proc)
    session: AgentSession = AgentSession(
        stt=config.stt,
        llm=config.llm,
        tts=config.tts,
        vad=ctx.proc.userdata["vad"],
        **session_kwargs,
    )
    try:
        runtime_state.metrics.record_session_started(config.name)
        await session.start(
            agent=config.agent_cls(),  # type: ignore[call-arg]
            room=ctx.room,
        )
        await ctx.connect()

        if config.greeting is not None:
            logger.debug("Generating greeting for agent '%s'.", config.name)
            await session.generate_reply(instructions=config.greeting)
    except Exception as exc:
        runtime_state.metrics.record_session_failure(config.name, exc)
        raise
    finally:
        runtime_state.metrics.record_session_finished(config.name)


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
        self._agent_ref = _build_agent_class_ref(self.agent_cls)
        _serialize_provider_value(self.stt)
        _serialize_provider_value(self.llm)
        _serialize_provider_value(self.tts)

    def __getstate__(self) -> dict[str, Any]:
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


class AgentPool:
    """Manage multiple LiveKit agents inside a single worker process.

    ``AgentPool`` keeps user-defined agents as standard LiveKit ``Agent``
    subclasses while centralizing the shared worker concerns OpenRTC adds:
    prewarm, routing, and per-agent session construction.
    """

    def __init__(
        self,
        *,
        default_stt: ProviderValue | None = None,
        default_llm: ProviderValue | None = None,
        default_tts: ProviderValue | None = None,
        default_greeting: str | None = None,
    ) -> None:
        """Create a pool with shared defaults, prewarm, and a universal entrypoint.

        Args:
            default_stt: Default STT provider used when an agent does not override
                it during ``add()`` or ``discover()``.
            default_llm: Default LLM provider used when an agent does not override
                it during ``add()`` or ``discover()``.
            default_tts: Default TTS provider used when an agent does not override
                it during ``add()`` or ``discover()``.
            default_greeting: Default greeting used when an agent does not override
                it during ``add()`` or ``discover()``.
        """
        self._server = AgentServer()
        self._agents: dict[str, AgentConfig] = {}
        self._runtime_state = _PoolRuntimeState(agents=self._agents)
        self._default_stt = default_stt
        self._default_llm = default_llm
        self._default_tts = default_tts
        self._default_greeting = default_greeting
        self._server.setup_fnc = partial(_prewarm_worker, self._runtime_state)
        self._server.rtc_session()(partial(_run_universal_session, self._runtime_state))

    @property
    def server(self) -> AgentServer:
        """Return the underlying LiveKit ``AgentServer`` instance."""
        return self._server

    def runtime_snapshot(self) -> PoolRuntimeSnapshot:
        """Return a live snapshot of worker metrics for dashboards and automation."""
        return self._runtime_state.metrics.snapshot(registered_agents=len(self._agents))

    def drain_metrics_stream_events(self) -> list[MetricsStreamEvent]:
        """Drain pending session lifecycle events for JSONL sidecar export."""
        return self._runtime_state.metrics.drain_stream_events()

    def add(
        self,
        name: str,
        agent_cls: type[Agent],
        *,
        stt: ProviderValue | None = None,
        llm: ProviderValue | None = None,
        tts: ProviderValue | None = None,
        greeting: str | None = None,
        session_kwargs: Mapping[str, Any] | None = None,
        source_path: Path | str | None = None,
        **session_options: Any,
    ) -> AgentConfig:
        """Register an agent in the pool.

        Args:
            name: Unique name used for dispatch.
            agent_cls: Agent subclass to instantiate per session.
            stt: STT provider string or instance.
            llm: LLM provider string or instance.
            tts: TTS provider string or instance.
            greeting: Optional greeting played after the room connection completes.
            session_kwargs: Extra keyword arguments forwarded to ``AgentSession``.
                Common examples include ``preemptive_generation``,
                ``allow_interruptions``, ``min_endpointing_delay``,
                ``max_endpointing_delay``, and ``max_tool_steps``.
            **session_options: Additional ``AgentSession`` options passed
                directly to ``add()``. When the same option appears in both
                ``session_kwargs`` and direct keyword arguments, the direct
                keyword argument takes precedence.
            source_path: Optional path to the agent's Python module on disk
                (used for discovery metadata and footprint reporting).

        Returns:
            The created agent configuration.

        Raises:
            TypeError: If ``agent_cls`` is not a LiveKit ``Agent`` subclass.
            ValueError: If ``name`` is empty or already registered.
        """
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Agent name must be a non-empty string.")
        if normalized_name in self._agents:
            raise ValueError(f"Agent '{normalized_name}' is already registered.")
        if not isinstance(agent_cls, type) or not issubclass(agent_cls, Agent):
            raise TypeError("agent_cls must be a subclass of livekit.agents.Agent.")

        resolved_source: Path | None
        if source_path is None:
            resolved_source = None
        else:
            resolved_source = Path(source_path).expanduser().resolve()

        config = AgentConfig(
            name=normalized_name,
            agent_cls=agent_cls,
            stt=self._resolve_provider(stt, self._default_stt),
            llm=self._resolve_provider(llm, self._default_llm),
            tts=self._resolve_provider(tts, self._default_tts),
            greeting=self._resolve_greeting(greeting),
            session_kwargs=self._merge_session_kwargs(
                session_kwargs=session_kwargs,
                direct_session_kwargs=session_options,
            ),
            source_path=resolved_source,
        )
        self._agents[normalized_name] = config
        logger.debug("Registered agent '%s'.", normalized_name)
        return config

    def discover(self, agents_dir: str | Path) -> list[AgentConfig]:
        """Discover agent modules from a directory and register them.

        Args:
            agents_dir: Directory containing Python files that define agent modules.
                Each discovered module must define a local LiveKit ``Agent``
                subclass. Optional OpenRTC overrides are read from the
                ``@agent_config(...)`` decorator attached to that class. When a
                field is omitted, ``AgentPool`` falls back to the module filename
                for the agent name and to pool defaults for providers and greeting.

        Returns:
            The list of agent configurations registered from the directory.

        Raises:
            FileNotFoundError: If ``agents_dir`` does not exist.
            NotADirectoryError: If ``agents_dir`` is not a directory.
            RuntimeError: If a module cannot be loaded or contains no local
                ``Agent`` subclass.
        """
        directory = Path(agents_dir).expanduser().resolve()
        if not directory.exists():
            raise FileNotFoundError(f"Agents directory does not exist: {directory}")
        if not directory.is_dir():
            raise NotADirectoryError(f"Agents path is not a directory: {directory}")

        discovered_configs: list[AgentConfig] = []
        for module_path in sorted(directory.glob("*.py")):
            if module_path.name == "__init__.py" or module_path.stem.startswith("_"):
                logger.debug("Skipping agent module '%s'.", module_path.name)
                continue

            module = self._load_agent_module(module_path)
            agent_cls = self._find_local_agent_subclass(module)
            metadata = self._resolve_discovery_metadata(module, agent_cls)
            agent_name = metadata.name or module_path.stem
            config = self.add(
                agent_name,
                agent_cls,
                stt=metadata.stt,
                llm=metadata.llm,
                tts=metadata.tts,
                greeting=metadata.greeting,
                source_path=module_path,
            )
            logger.info(
                "Discovered agent '%s' from %s using class %s.",
                config.name,
                module_path,
                agent_cls.__name__,
            )
            discovered_configs.append(config)

        return discovered_configs

    def list_agents(self) -> list[str]:
        """Return registered agent names in registration order."""
        return list(self._agents)

    def get(self, name: str) -> AgentConfig:
        """Return a registered agent configuration by name.

        Args:
            name: The registered agent name.

        Returns:
            The registered configuration.

        Raises:
            KeyError: If the agent name is unknown.
        """
        try:
            return self._agents[name]
        except KeyError as exc:
            raise KeyError(f"Unknown agent '{name}'.") from exc

    def remove(self, name: str) -> AgentConfig:
        """Remove and return a registered agent configuration.

        Args:
            name: The registered agent name.

        Returns:
            The removed configuration.

        Raises:
            KeyError: If the agent name is unknown.
        """
        try:
            removed = self._agents.pop(name)
        except KeyError as exc:
            raise KeyError(f"Unknown agent '{name}'.") from exc
        logger.debug("Removed agent '%s'.", name)
        return removed

    def run(self) -> None:
        """Run the LiveKit worker for the registered agents.

        Raises:
            RuntimeError: If no agents were registered before startup.
        """
        if not self._agents:
            raise RuntimeError("Register at least one agent before calling run().")
        cli.run_app(self._server)

    def _resolve_provider(
        self,
        value: ProviderValue | None,
        default_value: ProviderValue | None,
    ) -> ProviderValue | None:
        return default_value if value is None else value

    def _resolve_greeting(self, greeting: str | None) -> str | None:
        return self._default_greeting if greeting is None else greeting

    def _merge_session_kwargs(
        self,
        session_kwargs: Mapping[str, Any] | None,
        direct_session_kwargs: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        merged_kwargs: dict[str, Any] = {}
        if session_kwargs is not None:
            merged_kwargs.update(session_kwargs)
        if direct_session_kwargs is not None:
            merged_kwargs.update(direct_session_kwargs)
        return merged_kwargs

    def _resolve_discovery_metadata(
        self,
        module: ModuleType,
        agent_cls: type[Agent],
    ) -> AgentDiscoveryConfig:
        metadata = getattr(agent_cls, _AGENT_METADATA_ATTR, None)
        if metadata is not None:
            return cast(AgentDiscoveryConfig, metadata)

        return AgentDiscoveryConfig()

    def _load_agent_module(self, module_path: Path) -> ModuleType:
        module_name = _discovered_module_name(module_path)
        try:
            return _load_module_from_path(module_name, module_path)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to import agent module '{module_path.name}': {exc}"
            ) from exc

    def _find_local_agent_subclass(self, module: ModuleType) -> type[Agent]:
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, Agent)
                and value is not Agent
                and value.__module__ == module.__name__
            ):
                return value

        raise RuntimeError(
            f"Module '{module.__name__}' does not define a local Agent subclass."
        )


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


def _serialize_provider_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    provider_ref = _try_build_provider_ref(value)
    if provider_ref is not None:
        return provider_ref

    try:
        pickle.dumps(value)
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


def _build_session_kwargs(
    configured_kwargs: Mapping[str, Any],
    proc: JobProcess,
) -> dict[str, Any]:
    session_kwargs = dict(configured_kwargs)
    explicit_turn_handling = session_kwargs.pop("turn_handling", None)
    deprecated_turn_options = _extract_deprecated_turn_options(session_kwargs)

    if isinstance(explicit_turn_handling, Mapping):
        turn_handling = _merge_turn_handling(
            _default_turn_handling(proc),
            explicit_turn_handling,
        )
    else:
        turn_handling = _default_turn_handling(proc)
        if deprecated_turn_options:
            turn_handling = _merge_turn_handling(
                turn_handling,
                _deprecated_turn_options_to_turn_handling(deprecated_turn_options),
            )

    if explicit_turn_handling is not None and not isinstance(
        explicit_turn_handling, Mapping
    ):
        session_kwargs["turn_handling"] = explicit_turn_handling
    else:
        session_kwargs["turn_handling"] = turn_handling

    return session_kwargs


def _default_turn_handling(proc: JobProcess) -> dict[str, Any]:
    turn_detection = _default_turn_detection(proc)
    turn_handling: dict[str, Any] = {"interruption": {"mode": "vad"}}
    if turn_detection is not None:
        turn_handling["turn_detection"] = turn_detection
    return turn_handling


def _default_turn_detection(proc: JobProcess) -> Any:
    if _supports_multilingual_turn_detection(proc):
        return proc.userdata["turn_detection_factory"]()

    logger.info(
        "Falling back to VAD turn detection because no inference executor or "
        "LIVEKIT_REMOTE_EOT_URL is available."
    )
    return "vad"


def _supports_multilingual_turn_detection(proc: JobProcess) -> bool:
    if os.getenv("LIVEKIT_REMOTE_EOT_URL"):
        return True

    inference_executor = getattr(proc, "inference_executor", None)
    return inference_executor is not None


def _extract_deprecated_turn_options(session_kwargs: dict[str, Any]) -> dict[str, Any]:
    deprecated_options: dict[str, Any] = {}
    for key in _DEPRECATED_TURN_HANDLING_KEYS:
        if key in session_kwargs:
            deprecated_options[key] = session_kwargs.pop(key)
    if deprecated_options:
        found = ", ".join(f"'{k}'" for k in deprecated_options)
        warnings.warn(
            f"Passing {found} as top-level session_kwargs keys is deprecated and will "
            "be removed in a future release. Use the turn_handling dict instead: "
            "session_kwargs={'turn_handling': {'endpointing': {...}, 'interruption': {...}}}. "
            "See the AgentPool.add() docstring for the supported turn_handling structure.",
            DeprecationWarning,
            stacklevel=3,
        )
    return deprecated_options


def _deprecated_turn_options_to_turn_handling(
    options: Mapping[str, Any],
) -> dict[str, Any]:
    turn_handling: dict[str, Any] = {}
    endpointing: dict[str, Any] = {}
    interruption: dict[str, Any] = {}

    if "min_endpointing_delay" in options:
        endpointing["min_delay"] = options["min_endpointing_delay"]
    if "max_endpointing_delay" in options:
        endpointing["max_delay"] = options["max_endpointing_delay"]
    if endpointing:
        turn_handling["endpointing"] = endpointing

    if options.get("allow_interruptions") is False:
        interruption["enabled"] = False
    if "discard_audio_if_uninterruptible" in options:
        interruption["discard_audio_if_uninterruptible"] = options[
            "discard_audio_if_uninterruptible"
        ]
    if "min_interruption_duration" in options:
        interruption["min_duration"] = options["min_interruption_duration"]
    if "min_interruption_words" in options:
        interruption["min_words"] = options["min_interruption_words"]
    if "false_interruption_timeout" in options:
        interruption["false_interruption_timeout"] = options[
            "false_interruption_timeout"
        ]
    if "agent_false_interruption_timeout" in options:
        interruption["false_interruption_timeout"] = options[
            "agent_false_interruption_timeout"
        ]
    if "resume_false_interruption" in options:
        interruption["resume_false_interruption"] = options["resume_false_interruption"]
    if interruption:
        turn_handling["interruption"] = interruption

    if "turn_detection" in options:
        turn_handling["turn_detection"] = options["turn_detection"]

    return turn_handling


def _merge_turn_handling(
    base: Mapping[str, Any],
    override: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _resolve_agent_config(
    agents: Mapping[str, AgentConfig],
    ctx: JobContext,
) -> AgentConfig:
    """Resolve the agent for a session from metadata or fallback order."""
    if not agents:
        raise RuntimeError("No agents are registered in the pool.")

    selected_name = _agent_name_from_metadata(getattr(ctx.job, "metadata", None))
    if selected_name is not None:
        return _get_registered_agent(agents, selected_name, source="job metadata")

    selected_name = _agent_name_from_metadata(getattr(ctx.room, "metadata", None))
    if selected_name is not None:
        return _get_registered_agent(agents, selected_name, source="room metadata")

    room_name = getattr(ctx.room, "name", None)
    if isinstance(room_name, str):
        for agent_name, config in agents.items():
            if room_name.startswith(f"{agent_name}-"):
                logger.info(
                    "Resolved agent '%s' via room name prefix from room '%s'.",
                    agent_name,
                    room_name,
                )
                return config

    default_agent = next(iter(agents.values()))
    logger.info("Resolved agent '%s' via default fallback.", default_agent.name)
    return default_agent


def _agent_name_from_metadata(metadata: Any) -> str | None:
    if metadata is None:
        return None
    if isinstance(metadata, Mapping):
        return _agent_name_from_mapping(metadata)
    if isinstance(metadata, str):
        stripped = metadata.strip()
        if not stripped:
            return None
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            logger.debug("Ignoring non-JSON metadata: %s", stripped)
            return None
        if isinstance(decoded, Mapping):
            return _agent_name_from_mapping(decoded)
    return None


def _agent_name_from_mapping(metadata: Mapping[str, Any]) -> str | None:
    for key in _METADATA_AGENT_KEYS:
        value = metadata.get(key)
        if isinstance(value, str):
            normalized_value = value.strip()
            if normalized_value:
                return normalized_value
    return None


def _get_registered_agent(
    agents: Mapping[str, AgentConfig],
    name: str,
    *,
    source: str,
) -> AgentConfig:
    try:
        config = agents[name]
    except KeyError as exc:
        raise ValueError(f"Unknown agent '{name}' requested via {source}.") from exc
    logger.info("Resolved agent '%s' via %s.", name, source)
    return config


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


def _try_get_module_path(agent_cls: type[Agent]) -> Path | None:
    try:
        source_path = inspect.getsourcefile(agent_cls)
    except (OSError, TypeError):
        source_path = None
    if source_path is None:
        return None
    return Path(source_path).resolve()


def _discovered_module_name(module_path: Path) -> str:
    resolved_path = module_path.resolve()
    digest = sha1(str(resolved_path).encode("utf-8")).hexdigest()[:12]
    return f"openrtc_discovered_{resolved_path.stem}_{digest}"


def _load_module_from_path(module_name: str, module_path: Path) -> ModuleType:
    resolved_path = module_path.resolve()
    existing_module = sys.modules.get(module_name)
    if existing_module is not None:
        existing_file = getattr(existing_module, "__file__", None)
        if existing_file is not None and Path(existing_file).resolve() == resolved_path:
            return existing_module

    spec = importlib.util.spec_from_file_location(module_name, resolved_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not create import spec for {resolved_path}.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _load_shared_runtime_dependencies() -> tuple[Any, type[Any]]:
    """Load the optional LiveKit runtime dependencies used during prewarm."""
    try:
        from livekit.plugins import silero
        from livekit.plugins.turn_detector.multilingual import MultilingualModel
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "OpenRTC requires the LiveKit Silero and turn-detector plugins. "
            "Reinstall openrtc, or install livekit-agents[silero,turn-detector]."
        ) from exc

    return silero, MultilingualModel
