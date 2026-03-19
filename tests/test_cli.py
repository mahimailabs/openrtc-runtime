from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from openrtc.cli import main


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


def test_list_command_prints_discovered_agents(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stub_pool = StubPool(
        discovered=[
            StubConfig(
                name="restaurant",
                agent_cls=StubAgent,
                stt="deepgram/nova-3",
                llm="openai/gpt-4.1-mini",
                tts="cartesia/sonic-3",
                greeting="hello",
            )
        ]
    )
    monkeypatch.setattr("openrtc.cli.AgentPool", lambda **kwargs: stub_pool)

    exit_code = main(["list", "--agents-dir", "./agents"])

    assert exit_code == 0
    assert stub_pool.discover_calls == [Path("./agents")]
    assert "restaurant: class=StubAgent" in capsys.readouterr().out


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

    monkeypatch.setattr("openrtc.cli.AgentPool", build_pool)

    exit_code = main(
        [
            "list",
            "--agents-dir",
            "./agents",
            "--default-stt",
            "deepgram/nova-3:multi",
            "--default-llm",
            "openai/gpt-4.1-mini",
            "--default-tts",
            "cartesia/sonic-3",
            "--default-greeting",
            "Hello from OpenRTC.",
        ]
    )

    assert exit_code == 0
    assert len(created_pools) == 1
    assert created_pools[0].default_stt == "deepgram/nova-3:multi"
    assert created_pools[0].default_llm == "openai/gpt-4.1-mini"
    assert created_pools[0].default_tts == "cartesia/sonic-3"
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
    monkeypatch.setattr("openrtc.cli.AgentPool", lambda **kwargs: stub_pool)
    monkeypatch.setattr(sys, "argv", original_argv.copy())

    exit_code = main([command, "--agents-dir", "./agents"])

    assert exit_code == 0
    assert stub_pool.run_called is True
    assert sys.argv == [original_argv[0], command]


def test_cli_returns_non_zero_when_no_agents_are_discovered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_pool = StubPool(discovered=[])
    monkeypatch.setattr("openrtc.cli.AgentPool", lambda **kwargs: stub_pool)

    exit_code = main(["list", "--agents-dir", "./agents"])

    assert exit_code == 1
