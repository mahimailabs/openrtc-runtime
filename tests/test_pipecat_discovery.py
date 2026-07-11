"""Pipecat builder discovery: find @agent_config-marked callables in a directory."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import Any

from openrtc import AgentPool, agent_config
from openrtc.backends.pipecat.backend import PipecatAgentConfig
from openrtc.core.discovery import _find_marked_builders


def test_agent_config_marks_a_builder_callable() -> None:
    @agent_config(name="support")
    def support(view: Any) -> list[Any]:
        return []

    # The decorator (typed for classes today) also stamps a plain builder.
    assert hasattr(support, "__openrtc_agent_config__")
    assert support.__openrtc_agent_config__.name == "support"  # type: ignore[attr-defined]


def test_find_marked_builders_scopes_to_local_marked_callables() -> None:
    module = ModuleType("mymod")

    @agent_config(name="local")
    def local(view: Any) -> list[Any]:
        return []

    local.__module__ = "mymod"  # defined in this module

    imported = agent_config(name="imported")(lambda view: [])
    imported.__module__ = "elsewhere"  # imported from another module

    def unmarked(view: Any) -> list[Any]:
        return []

    unmarked.__module__ = "mymod"

    module.local = local  # type: ignore[attr-defined]
    module.imported = imported  # type: ignore[attr-defined]
    module.unmarked = unmarked  # type: ignore[attr-defined]

    found = _find_marked_builders(module)
    assert [name for name, _ in found] == ["local"]  # only the local, marked one
    assert found[0][1] is local


def _write(directory: Path, name: str, body: str) -> None:
    (directory / name).write_text(body, encoding="utf-8")


def test_pipecat_discover_registers_marked_builders(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "sales.py",
        "from openrtc import agent_config\n"
        "@agent_config(name='sales')\n"
        "def build(view):\n"
        "    return []\n",
    )
    _write(
        tmp_path,
        "support.py",
        "from openrtc import agent_config\n"
        "@agent_config()\n"  # no explicit name -> falls back to the function name
        "def support(view):\n"
        "    return []\n"
        "def helper(view):\n"  # unmarked callable -> ignored
        "    return []\n",
    )
    _write(tmp_path, "__init__.py", "")  # skipped, must not raise

    pool = AgentPool(backend="pipecat")
    configs = pool.discover(tmp_path)

    assert all(isinstance(c, PipecatAgentConfig) for c in configs)
    assert sorted(c.name for c in configs) == ["sales", "support"]
    assert sorted(pool.list_agents()) == ["sales", "support"]


def test_pipecat_discover_finds_several_builders_in_one_file(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "agents.py",
        "from openrtc import agent_config\n"
        "@agent_config(name='a')\n"
        "def build_a(view):\n"
        "    return []\n"
        "@agent_config(name='b')\n"
        "def build_b(view):\n"
        "    return []\n",
    )
    pool = AgentPool(backend="pipecat")
    pool.discover(tmp_path)
    assert sorted(pool.list_agents()) == ["a", "b"]
