from __future__ import annotations

from pathlib import Path

import pytest
from livekit.agents import Agent

from openrtc import AgentPool

_AGENT_TEMPLATE = """from __future__ import annotations

from livekit.agents import Agent

{config_block}

class {class_name}(Agent):
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
) -> None:
    directory.joinpath(filename).write_text(
        _AGENT_TEMPLATE.format(
            class_name=class_name,
            instructions=instructions,
            config_block=config_block,
        ),
        encoding="utf-8",
    )


def test_discover_finds_agents_and_reads_module_config(tmp_path: Path) -> None:
    _write_agent_module(
        tmp_path,
        "restaurant.py",
        config_block=(
            'AGENT_NAME = "restaurant"\n'
            'AGENT_STT = "deepgram/nova-3:multi"\n'
            'AGENT_LLM = "openai/gpt-4.1-mini"\n'
            'AGENT_TTS = "cartesia/sonic-3"\n'
            'AGENT_GREETING = "Welcome to reservations."\n'
        ),
    )
    _write_agent_module(tmp_path, "dental.py", class_name="DentalAgent")

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
    assert restaurant.stt == "deepgram/nova-3:multi"
    assert restaurant.llm == "openai/gpt-4.1-mini"
    assert restaurant.tts == "cartesia/sonic-3"
    assert restaurant.greeting == "Welcome to reservations."
    assert pool.list_agents() == ["dental", "restaurant"]


def test_discover_skips_private_modules(tmp_path: Path) -> None:
    _write_agent_module(tmp_path, "_hidden.py")
    _write_agent_module(tmp_path, "visible.py")

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


class ImportedBaseAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="base")


def test_discover_ignores_imported_agent_subclasses(tmp_path: Path) -> None:
    module_path = tmp_path / "imported.py"
    module_path.write_text(
        "from __future__ import annotations\n\n"
        "from tests.test_discovery import ImportedBaseAgent\n\n"
        "AGENT_NAME = 'local'\n\n"
        "class LocalAgent(ImportedBaseAgent):\n"
        "    def __init__(self) -> None:\n"
        "        super().__init__()\n",
        encoding="utf-8",
    )

    pool = AgentPool()
    discovered = pool.discover(tmp_path)

    assert [config.name for config in discovered] == ["local"]
    assert discovered[0].agent_cls.__name__ == "LocalAgent"
