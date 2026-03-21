from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from openrtc.cli import app, main


@dataclass
class StubConfig:
    name: str
    agent_cls: type[Any]
    stt: Any = None
    llm: Any = None
    tts: Any = None
    greeting: str | None = None


class StubAgent:
    __name__ = "StubAgent"


class StubPool:
    def __init__(
        self,
        *,
        default_stt: Any = None,
        default_llm: Any = None,
        default_tts: Any = None,
        default_greeting: str | None = None,
        discovered: list[StubConfig],
    ) -> None:
        self.default_stt = default_stt
        self.default_llm = default_llm
        self.default_tts = default_tts
        self.default_greeting = default_greeting
        self._discovered = discovered
        self.discover_calls: list[Path] = []
        self.run_called = False

    def discover(self, agents_dir: Path) -> list[StubConfig]:
        self.discover_calls.append(agents_dir)
        return self._discovered

    def run(self) -> None:
        self.run_called = True


@pytest.fixture
def original_argv() -> list[str]:
    return sys.argv.copy()


def test_list_with_resources_shows_footprint_and_summary(tmp_path: Path) -> None:
    agent_path = tmp_path / "one.py"
    agent_path.write_text(
        "from __future__ import annotations\n"
        "from livekit.agents import Agent\n"
        "class One(Agent):\n"
        "    def __init__(self) -> None:\n"
        "        super().__init__(instructions='x')\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["list", "--agents-dir", str(tmp_path), "--resources"])

    assert result.exit_code == 0
    out = result.stdout
    assert "one" in out
    assert "One" in out
    assert "Resource summary" in out
    assert "OpenRTC runs every agent" in out


def test_list_command_prints_discovered_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_pool = StubPool(
        discovered=[
            StubConfig(
                name="restaurant",
                agent_cls=StubAgent,
                stt="openai/gpt-4o-mini-transcribe",
                llm="openai/gpt-4.1-mini",
                tts="openai/gpt-4o-mini-tts",
                greeting="hello",
            )
        ]
    )
    monkeypatch.setattr("openrtc.cli_app.AgentPool", lambda **kwargs: stub_pool)

    runner = CliRunner()
    result = runner.invoke(app, ["list", "--agents-dir", "./agents"])

    assert result.exit_code == 0
    assert stub_pool.discover_calls == [Path("./agents").resolve()]
    out = result.stdout
    assert "restaurant" in out
    assert "StubAgent" in out


def test_cli_passes_pool_defaults_into_agent_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_pools: list[StubPool] = []

    def build_pool(**kwargs: Any) -> StubPool:
        pool = StubPool(
            discovered=[StubConfig(name="restaurant", agent_cls=StubAgent)], **kwargs
        )
        created_pools.append(pool)
        return pool

    monkeypatch.setattr("openrtc.cli_app.AgentPool", build_pool)

    exit_code = main(
        [
            "list",
            "--agents-dir",
            "./agents",
            "--default-stt",
            "openai/gpt-4o-mini-transcribe",
            "--default-llm",
            "openai/gpt-4.1-mini",
            "--default-tts",
            "openai/gpt-4o-mini-tts",
            "--default-greeting",
            "Hello from OpenRTC.",
        ]
    )

    assert exit_code == 0
    assert len(created_pools) == 1
    assert created_pools[0].default_stt == "openai/gpt-4o-mini-transcribe"
    assert created_pools[0].default_llm == "openai/gpt-4.1-mini"
    assert created_pools[0].default_tts == "openai/gpt-4o-mini-tts"
    assert created_pools[0].default_greeting == "Hello from OpenRTC."


@pytest.mark.parametrize("command", ["start", "dev"])
def test_run_commands_inject_livekit_mode_and_run_pool(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    original_argv: list[str],
) -> None:
    stub_pool = StubPool(
        discovered=[StubConfig(name="restaurant", agent_cls=StubAgent)]
    )
    monkeypatch.setattr("openrtc.cli_app.AgentPool", lambda **kwargs: stub_pool)
    monkeypatch.setattr(sys, "argv", original_argv.copy())

    exit_code = main([command, "--agents-dir", "./agents"])

    assert exit_code == 0
    assert stub_pool.run_called is True
    # Programmatic `main([...])` restores sys.argv after the Typer app finishes.
    assert sys.argv == original_argv


def test_cli_returns_non_zero_when_no_agents_are_discovered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_pool = StubPool(discovered=[])
    monkeypatch.setattr("openrtc.cli_app.AgentPool", lambda **kwargs: stub_pool)

    exit_code = main(["list", "--agents-dir", "./agents"])

    assert exit_code == 1


def test_cli_entrypoint_documents_optional_extra() -> None:
    from openrtc.cli import CLI_EXTRA_INSTALL_HINT

    assert "openrtc[cli]" in CLI_EXTRA_INSTALL_HINT


def test_main_returns_one_when_typer_not_installed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    real_find = importlib.util.find_spec

    def find_spec_without_typer(name: str) -> Any:
        if name == "typer":
            return None
        return real_find(name)

    monkeypatch.setattr(importlib.util, "find_spec", find_spec_without_typer)

    exit_code = main(["list", "--agents-dir", "./agents"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "openrtc[cli]" in err


def test_list_json_output_is_valid_json(tmp_path: Path) -> None:
    agent_path = tmp_path / "one.py"
    agent_path.write_text(
        "from __future__ import annotations\n"
        "from livekit.agents import Agent\n"
        "class One(Agent):\n"
        "    def __init__(self) -> None:\n"
        "        super().__init__(instructions='x')\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app, ["list", "--agents-dir", str(tmp_path), "--json", "--resources"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["schema_version"] == 1
    assert data["command"] == "list"
    assert len(data["agents"]) == 1
    assert data["agents"][0]["name"] == "one"
    assert "resource_summary" in data
    assert data["resource_summary"]["resident_set"]["metric"] in (
        "linux_vm_rss",
        "darwin_ru_max_rss",
        "unavailable",
    )


def test_list_plain_matches_line_oriented_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_pool = StubPool(
        discovered=[
            StubConfig(
                name="restaurant",
                agent_cls=StubAgent,
                stt="openai/gpt-4o-mini-transcribe",
                llm="openai/gpt-4.1-mini",
                tts="openai/gpt-4o-mini-tts",
                greeting="hello",
            )
        ]
    )
    monkeypatch.setattr("openrtc.cli_app.AgentPool", lambda **kwargs: stub_pool)

    runner = CliRunner()
    result = runner.invoke(app, ["list", "--agents-dir", "./agents", "--plain"])

    assert result.exit_code == 0
    assert (
        "restaurant: class=StubAgent, stt='openai/gpt-4o-mini-transcribe', "
        "llm='openai/gpt-4.1-mini', tts='openai/gpt-4o-mini-tts', greeting='hello'"
        in result.stdout
    )


def test_list_plain_and_json_conflict() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app, ["list", "--agents-dir", "./agents", "--plain", "--json"]
    )

    assert result.exit_code != 0
