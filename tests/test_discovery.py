from __future__ import annotations

import pickle
import sys
from pathlib import Path

import pytest

from openrtc import AgentPool

_AGENT_TEMPLATE = """from __future__ import annotations

from livekit.agents import Agent
from openrtc import agent_config

{config_block}

{decorator}class {class_name}(Agent):
    def __init__(self) -> None:
        super().__init__(instructions={instructions!r})
"""


def _write_agent_module(
    directory: Path,
    filename: str,
    *,
    class_name: str = "DiscoveredAgent",
    instructions: str = "A discovered agent.",
    config_block: str = "",
    decorator: str = "",
) -> None:
    directory.joinpath(filename).write_text(
        _AGENT_TEMPLATE.format(
            class_name=class_name,
            instructions=instructions,
            config_block=config_block,
            decorator=decorator,
        ),
        encoding="utf-8",
    )


def test_discover_prefers_decorator_metadata_and_uses_pool_defaults(
    tmp_path: Path,
) -> None:
    _write_agent_module(
        tmp_path,
        "restaurant.py",
        decorator=(
            "@agent_config(\n"
            '    name="restaurant",\n'
            '    stt="openai/gpt-4o-mini-transcribe",\n'
            '    llm="openai/gpt-4.1-mini",\n'
            '    greeting="Welcome to reservations.",\n'
            ")\n"
        ),
    )
    _write_agent_module(
        tmp_path,
        "dental.py",
        class_name="DentalAgent",
        decorator='@agent_config(name="dental")\n',
    )

    pool = AgentPool(
        default_stt="fallback-stt",
        default_llm="fallback-llm",
        default_tts="fallback-tts",
        default_greeting="fallback greeting",
    )
    discovered = pool.discover(tmp_path)

    assert [config.name for config in discovered] == ["dental", "restaurant"]
    dental = next(config for config in discovered if config.name == "dental")
    assert dental.stt == "fallback-stt"
    assert dental.llm == "fallback-llm"
    assert dental.tts == "fallback-tts"
    assert dental.greeting == "fallback greeting"

    restaurant = next(config for config in discovered if config.name == "restaurant")
    assert restaurant.stt == "openai/gpt-4o-mini-transcribe"
    assert restaurant.llm == "openai/gpt-4.1-mini"
    assert restaurant.tts == "fallback-tts"
    assert restaurant.greeting == "Welcome to reservations."
    assert pool.list_agents() == ["dental", "restaurant"]


def test_discover_uses_filename_and_pool_defaults_without_decorator(
    tmp_path: Path,
) -> None:
    _write_agent_module(
        tmp_path,
        "fallback_agent.py",
        class_name="FallbackAgent",
    )

    pool = AgentPool(
        default_stt="openai/gpt-4o-mini-transcribe",
        default_llm="openai/gpt-4.1-mini",
        default_tts="openai/gpt-4o-mini-tts",
        default_greeting="Hello from pool defaults.",
    )
    discovered = pool.discover(tmp_path)

    assert [config.name for config in discovered] == ["fallback_agent"]
    assert discovered[0].stt == "openai/gpt-4o-mini-transcribe"
    assert discovered[0].llm == "openai/gpt-4.1-mini"
    assert discovered[0].tts == "openai/gpt-4o-mini-tts"
    assert discovered[0].greeting == "Hello from pool defaults."


def test_discover_skips_private_modules(tmp_path: Path) -> None:
    _write_agent_module(tmp_path, "_hidden.py")
    _write_agent_module(
        tmp_path, "visible.py", decorator='@agent_config(name="visible")\n'
    )

    pool = AgentPool()
    discovered = pool.discover(tmp_path)

    assert [config.name for config in discovered] == ["visible"]


def test_discover_raises_for_import_errors(tmp_path: Path) -> None:
    tmp_path.joinpath("broken.py").write_text("raise RuntimeError('boom')\n")

    pool = AgentPool()

    with pytest.raises(RuntimeError, match="Failed to import agent module 'broken.py'"):
        pool.discover(tmp_path)


def test_discover_raises_when_no_local_agent_subclass_exists(tmp_path: Path) -> None:
    tmp_path.joinpath("helper.py").write_text(
        "from livekit.agents import Agent\nAlias = Agent\n",
        encoding="utf-8",
    )

    pool = AgentPool()

    with pytest.raises(RuntimeError, match="does not define a local Agent subclass"):
        pool.discover(tmp_path)


def test_discover_ignores_imported_agent_subclasses(tmp_path: Path) -> None:
    module_path = tmp_path / "imported.py"
    module_path.write_text(
        "from __future__ import annotations\n\n"
        "from livekit.agents import Agent as ImportedBaseAgent\n"
        "from openrtc import agent_config\n\n"
        "@agent_config(name='local')\n"
        "class LocalAgent(ImportedBaseAgent):\n"
        "    def __init__(self) -> None:\n"
        "        super().__init__(instructions='local')\n",
        encoding="utf-8",
    )

    pool = AgentPool()
    discovered = pool.discover(tmp_path)

    assert [config.name for config in discovered] == ["local"]
    assert discovered[0].agent_cls.__name__ == "LocalAgent"


def test_discovered_agent_config_is_pickleable_across_module_reload(
    tmp_path: Path,
) -> None:
    _write_agent_module(
        tmp_path,
        "dental.py",
        class_name="DentalAgent",
        decorator='@agent_config(name="dental")\n',
    )

    pool = AgentPool()
    discovered = pool.discover(tmp_path)

    config = discovered[0]
    module_name = config.agent_cls.__module__
    sys.modules.pop(module_name, None)

    restored = pickle.loads(pickle.dumps(config))

    assert restored.name == "dental"
    assert restored.agent_cls.__name__ == "DentalAgent"
    assert restored.agent_cls.__module__ == module_name
    assert restored.source_path == (tmp_path / "dental.py").resolve()


def test_discover_records_source_path_next_to_agent_module(tmp_path: Path) -> None:
    _write_agent_module(
        tmp_path,
        "zoo.py",
        class_name="ZooAgent",
    )
    pool = AgentPool()
    discovered = pool.discover(tmp_path)
    assert len(discovered) == 1
    assert discovered[0].source_path == (tmp_path / "zoo.py").resolve()


def test_load_module_from_path_raises_when_spec_cannot_be_built(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A None-spec from spec_from_file_location surfaces as a clear RuntimeError."""
    import importlib.util

    from openrtc.core import discovery as discovery_module

    target = tmp_path / "agent.py"
    target.write_text("# minimal\n", encoding="utf-8")

    monkeypatch.setattr(
        importlib.util, "spec_from_file_location", lambda _name, _path: None
    )

    with pytest.raises(RuntimeError, match="Could not create import spec"):
        discovery_module._load_module_from_path("openrtc_test_no_spec", target)
