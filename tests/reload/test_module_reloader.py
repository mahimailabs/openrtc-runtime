"""MAH-81: rollback-safe re-import of a changed agent module."""

from __future__ import annotations

from pathlib import Path

from openrtc.core.discovery import _find_local_agent_subclass, _load_agent_module
from openrtc.reload.base_reload import ReloadResult
from openrtc.reload.module_reloader import reload_agent_module

_AGENT_SOURCE = """\
from livekit.agents import Agent


class ReloadableAgent(Agent):
    version = "{marker}"

    def __init__(self) -> None:
        super().__init__(instructions="marker {marker}")
"""


def _write_agent(path: Path, marker: str) -> None:
    path.write_text(_AGENT_SOURCE.format(marker=marker))


def _load(path: Path) -> type:
    """Load the agent module fresh and return its local Agent subclass."""
    return _find_local_agent_subclass(_load_agent_module(path))


def test_clean_reload_swaps_the_class(tmp_path: Path) -> None:
    agent_file = tmp_path / "agent_clean.py"
    _write_agent(agent_file, "v1")
    current = _load(agent_file)
    assert current.version == "v1"

    _write_agent(agent_file, "v2")
    result = reload_agent_module(agent_file, current)

    assert result.status == "swapped"
    assert result.agent_cls is not None
    assert result.agent_cls is not current
    assert result.agent_cls.version == "v2"
    assert result.error is None


def test_syntax_error_keeps_prior_version(tmp_path: Path) -> None:
    agent_file = tmp_path / "agent_syntax.py"
    _write_agent(agent_file, "v1")
    current = _load(agent_file)

    # A missing colon: a SyntaxError on save must not poison the running pool.
    agent_file.write_text(
        "from livekit.agents import Agent\n\n\n"
        "class ReloadableAgent(Agent)\n"
        "    version = 'v2'\n"
    )
    result = reload_agent_module(agent_file, current)

    assert result.status == "failed"
    assert result.agent_cls is None
    assert result.error is not None
    assert "agent_syntax.py" in result.error
    # The old class is untouched and still resolvable.
    assert _load(agent_file).version == "v1"


def test_import_error_keeps_prior_version(tmp_path: Path) -> None:
    agent_file = tmp_path / "agent_import.py"
    _write_agent(agent_file, "v1")
    current = _load(agent_file)

    agent_file.write_text(
        "import openrtc_definitely_missing_module_xyz  # noqa\n"
        "from livekit.agents import Agent\n\n\n"
        "class ReloadableAgent(Agent):\n"
        "    version = 'v2'\n"
        "    def __init__(self) -> None:\n"
        "        super().__init__(instructions='v2')\n"
    )
    result = reload_agent_module(agent_file, current)

    assert result.status == "failed"
    assert result.agent_cls is None
    assert result.error is not None
    assert _load(agent_file).version == "v1"


def test_rename_uses_structural_fallback(tmp_path: Path) -> None:
    agent_file = tmp_path / "agent_rename.py"
    _write_agent(agent_file, "v1")
    current = _load(agent_file)

    # The class is renamed, so lookup by the old name misses and the reloader
    # must fall back to structural discovery.
    agent_file.write_text(
        "from livekit.agents import Agent\n\n\n"
        "class RenamedAgent(Agent):\n"
        "    version = 'v2'\n"
        "    def __init__(self) -> None:\n"
        "        super().__init__(instructions='v2')\n"
    )
    result = reload_agent_module(agent_file, current)

    assert result.status == "swapped"
    assert result.agent_cls is not None
    assert result.agent_cls.__name__ == "RenamedAgent"
    assert result.agent_cls.version == "v2"


def test_no_agent_subclass_fails_and_rolls_back(tmp_path: Path) -> None:
    agent_file = tmp_path / "agent_noclass.py"
    _write_agent(agent_file, "v1")
    current = _load(agent_file)

    # A save that removes the Agent subclass entirely must not swap.
    agent_file.write_text("VALUE = 1\n")
    result = reload_agent_module(agent_file, current)

    assert result.status == "failed"
    assert result.agent_cls is None
    assert _load(agent_file).version == "v1"


def test_missing_source_file_fails_safely(tmp_path: Path) -> None:
    agent_file = tmp_path / "agent_present.py"
    _write_agent(agent_file, "v1")
    current = _load(agent_file)

    missing = tmp_path / "gone.py"
    result = reload_agent_module(missing, current)

    assert result.status == "failed"
    assert result.agent_cls is None
    assert result.error is not None
    assert "gone.py" in result.error


def test_unsupported_extension_fails(tmp_path: Path) -> None:
    agent_file = tmp_path / "agent_ext.py"
    _write_agent(agent_file, "v1")
    current = _load(agent_file)

    # Valid Python that compiles, but a suffix importlib cannot build a spec for.
    weird = tmp_path / "agent.notpy"
    weird.write_text("X = 1\n")
    result = reload_agent_module(weird, current)

    assert result.status == "failed"
    assert result.error is not None
    assert "import spec" in result.error


def test_rollback_when_module_absent(tmp_path: Path) -> None:
    import sys

    from openrtc.core.discovery import _discovered_module_name

    agent_file = tmp_path / "agent_absent.py"
    _write_agent(agent_file, "v1")
    current = _load(agent_file)

    # Drop the module so the failed reload hits the "no prior module" rollback path.
    sys.modules.pop(_discovered_module_name(agent_file), None)
    agent_file.write_text(
        "import openrtc_definitely_missing_module_xyz  # noqa\n"
        "from livekit.agents import Agent\n"
    )
    result = reload_agent_module(agent_file, current)

    assert result.status == "failed"
    assert _discovered_module_name(agent_file) not in sys.modules


def test_reload_result_is_immutable() -> None:
    result = ReloadResult(status="failed", agent_cls=None, error="boom")
    try:
        result.status = "swapped"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("ReloadResult should be frozen")
