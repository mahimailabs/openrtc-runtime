from __future__ import annotations

import builtins
import importlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console
from typer.testing import CliRunner

from openrtc.cli import app, main
from openrtc.provider_types import ProviderValue
from openrtc.resources import (
    MetricsStreamEvent,
    PoolRuntimeSnapshot,
    ProcessResidentSetInfo,
    SavingsEstimate,
)

# Rich/Click may inject ANSI and soft-wrap error text; normalize before substring checks.
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _normalize_cli_output_for_assert(text: str) -> str:
    plain = _ANSI_ESCAPE_RE.sub("", text)
    return plain.replace("\n", "").replace("\r", "")


@dataclass
class StubConfig:
    name: str
    agent_cls: type[Any]
    stt: ProviderValue | None = None
    llm: ProviderValue | None = None
    tts: ProviderValue | None = None
    greeting: str | None = None


class StubAgent:
    __name__ = "StubAgent"


class StubPool:
    def __init__(
        self,
        *,
        default_stt: ProviderValue | None = None,
        default_llm: ProviderValue | None = None,
        default_tts: ProviderValue | None = None,
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
        self.runtime_snapshot_calls = 0

    def discover(self, agents_dir: Path) -> list[StubConfig]:
        self.discover_calls.append(agents_dir)
        return self._discovered

    def run(self) -> None:
        self.run_called = True

    def drain_metrics_stream_events(self) -> list[MetricsStreamEvent]:
        return []

    def runtime_snapshot(self) -> PoolRuntimeSnapshot:
        self.runtime_snapshot_calls += 1
        return PoolRuntimeSnapshot(
            timestamp=1.0,
            uptime_seconds=2.5,
            registered_agents=len(self._discovered),
            active_sessions=1,
            total_sessions_started=3,
            total_session_failures=0,
            last_routed_agent=self._discovered[0].name if self._discovered else None,
            last_error=None,
            sessions_by_agent=(
                {self._discovered[0].name: 1} if self._discovered else {}
            ),
            resident_set=ProcessResidentSetInfo(
                bytes_value=256 * 1024 * 1024,
                metric="linux_vm_rss",
                description="Current resident set from VmRSS.",
            ),
            savings_estimate=SavingsEstimate(
                agent_count=len(self._discovered),
                shared_worker_bytes=256 * 1024 * 1024,
                estimated_separate_workers_bytes=(
                    256 * 1024 * 1024 * max(len(self._discovered), 1)
                ),
                estimated_saved_bytes=(
                    256 * 1024 * 1024 * max(len(self._discovered) - 1, 0)
                ),
                assumptions=("assumption",),
            ),
        )


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


@pytest.mark.parametrize(
    ("command", "extra_args"),
    [
        ("start", ["--agents-dir", "./agents"]),
        ("dev", ["--agents-dir", "./agents"]),
        ("console", ["--agents-dir", "./agents"]),
        ("download-files", ["--agents-dir", "./agents"]),
        ("connect", ["--agents-dir", "./agents", "--room", "demo-room"]),
    ],
)
def test_run_commands_inject_livekit_mode_and_run_pool(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    extra_args: list[str],
    original_argv: list[str],
) -> None:
    stub_pool = StubPool(
        discovered=[StubConfig(name="restaurant", agent_cls=StubAgent)]
    )
    monkeypatch.setattr("openrtc.cli_livekit.AgentPool", lambda **kwargs: stub_pool)
    monkeypatch.setattr(sys, "argv", original_argv.copy())

    exit_code = main([command, *extra_args])

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


def test_download_files_has_minimal_options_no_provider_defaults(
    tmp_path: Path,
) -> None:
    """download-files only needs agents dir + connection; no --default-* flags."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "download-files",
            "--agents-dir",
            str(tmp_path),
            "--default-stt",
            "deepgram/x",
        ],
    )
    assert result.exit_code == 2
    out = (result.stdout or "") + (result.stderr or "")
    normalized = _normalize_cli_output_for_assert(out)
    assert re.search(r"default[-_]stt", normalized), normalized[:800]


def test_list_exits_cleanly_when_agents_dir_does_not_exist(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    missing = tmp_path / "nonexistent_agents"
    runner = CliRunner()
    with caplog.at_level(logging.ERROR, logger="openrtc"):
        result = runner.invoke(app, ["list", "--agents-dir", str(missing)])
    assert result.exit_code == 1
    assert "does not exist" in caplog.text


def test_strip_openrtc_only_flags_for_livekit_removes_openrtc_options() -> None:
    """LiveKit ``run_app`` must not see OpenRTC-only flags (see ``_livekit_sys_argv``)."""
    from openrtc.cli_app import _strip_openrtc_only_flags_for_livekit

    tail = [
        "--agents-dir",
        "./agents",
        "--dashboard",
        "--dashboard-refresh",
        "2.0",
        "--metrics-json-file",
        "/tmp/m.json",
        "--default-stt",
        "x",
        "--default-llm",
        "y",
        "--default-tts",
        "z",
        "--default-greeting",
        "hi",
        "--metrics-jsonl",
        "/tmp/x.jsonl",
        "--metrics-jsonl-interval",
        "0.5",
        "--reload",
        "--log-level",
        "DEBUG",
    ]
    assert _strip_openrtc_only_flags_for_livekit(tail) == [
        "--reload",
        "--log-level",
        "DEBUG",
    ]
    assert _strip_openrtc_only_flags_for_livekit(["--agents-dir=./a", "--reload"]) == [
        "--reload"
    ]
    assert _strip_openrtc_only_flags_for_livekit([]) == []
    assert _strip_openrtc_only_flags_for_livekit(
        ["--metrics-json-file", "--not-a-flag", "--reload"],
    ) == ["--reload"]


def test_dev_passes_reload_through_argv_strip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import openrtc.cli_livekit as cli_livekit_mod

    agents = tmp_path / "agents"
    agents.mkdir()
    stub_pool = StubPool(discovered=[StubConfig(name="a", agent_cls=StubAgent)])
    monkeypatch.setattr(cli_livekit_mod, "AgentPool", lambda **kwargs: stub_pool)

    def _run_pool_stub(pool: StubPool, **kwargs: Any) -> None:
        pool.run()

    monkeypatch.setattr(cli_livekit_mod, "_run_pool_with_reporting", _run_pool_stub)
    real_strip = cli_livekit_mod._strip_openrtc_only_flags_for_livekit
    recorded: list[tuple[list[str], list[str]]] = []

    def recording_strip(tail: list[str]) -> list[str]:
        out = real_strip(tail)
        recorded.append((list(tail), list(out)))
        return out

    monkeypatch.setattr(
        cli_livekit_mod,
        "_strip_openrtc_only_flags_for_livekit",
        recording_strip,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["openrtc", "dev", "--agents-dir", str(agents), "--reload"],
    )
    exit_code = main(["dev", "--agents-dir", str(agents), "--reload"])
    assert exit_code == 0
    assert stub_pool.run_called
    assert recorded
    assert recorded[0][1] == ["--reload"]


def test_livekit_env_restored_after_delegate_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import openrtc.cli_livekit as cli_livekit_mod

    stub_pool = StubPool(discovered=[StubConfig(name="a", agent_cls=StubAgent)])
    monkeypatch.setattr(cli_livekit_mod, "AgentPool", lambda **kwargs: stub_pool)
    monkeypatch.setattr(
        cli_livekit_mod, "_run_pool_with_reporting", lambda *a, **k: None
    )
    monkeypatch.setenv("LIVEKIT_URL", "ws://persist")
    exit_code = main(
        ["start", "--agents-dir", "./agents", "--url", "ws://temporary-override"],
    )
    assert exit_code == 0
    assert os.environ.get("LIVEKIT_URL") == "ws://persist"


def test_cli_entrypoint_documents_optional_extra() -> None:
    from openrtc.cli import CLI_EXTRA_INSTALL_HINT

    assert "openrtc[cli]" in CLI_EXTRA_INSTALL_HINT


def test_main_returns_one_when_typer_not_installed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    real_import_module = importlib.import_module

    def import_module_without_typer(name: str, package: str | None = None) -> Any:
        if name == "typer":
            raise ModuleNotFoundError("No module named 'typer'", name="typer")
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", import_module_without_typer)

    exit_code = main(["list", "--agents-dir", "./agents"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "openrtc[cli]" in err


def test_main_propagates_module_not_found_for_non_optional_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing modules other than typer/rich must not be masked as the [cli] hint."""
    real_import_module = importlib.import_module

    def import_module_missing_click(name: str, package: str | None = None) -> Any:
        if name == "typer":
            raise ModuleNotFoundError("No module named 'click'", name="click")
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", import_module_missing_click)

    with pytest.raises(ModuleNotFoundError, match="click"):
        main(["list", "--agents-dir", "./agents"])


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
    assert "savings_estimate" in data["resource_summary"]


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


def test_build_runtime_dashboard_renders_key_metrics() -> None:
    from openrtc.cli_app import build_runtime_dashboard

    snapshot = PoolRuntimeSnapshot(
        timestamp=1.0,
        uptime_seconds=5.0,
        registered_agents=2,
        active_sessions=1,
        total_sessions_started=4,
        total_session_failures=1,
        last_routed_agent="restaurant",
        last_error="RuntimeError: boom",
        sessions_by_agent={"restaurant": 1},
        resident_set=ProcessResidentSetInfo(
            bytes_value=512 * 1024 * 1024,
            metric="linux_vm_rss",
            description="Current resident set from VmRSS.",
        ),
        savings_estimate=SavingsEstimate(
            agent_count=2,
            shared_worker_bytes=512 * 1024 * 1024,
            estimated_separate_workers_bytes=1024 * 1024 * 1024,
            estimated_saved_bytes=512 * 1024 * 1024,
            assumptions=("Estimated separate-worker memory multiplies the baseline.",),
        ),
    )

    console = Console(record=True, width=120)
    console.print(build_runtime_dashboard(snapshot))
    rendered = console.export_text()

    assert "OpenRTC runtime dashboard" in rendered
    assert "Worker RSS" in rendered
    assert "Estimated saved" in rendered
    assert "restaurant" in rendered


def test_start_command_can_write_runtime_metrics_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stub_pool = StubPool(
        discovered=[StubConfig(name="restaurant", agent_cls=StubAgent)]
    )
    monkeypatch.setattr("openrtc.cli_livekit.AgentPool", lambda **kwargs: stub_pool)

    metrics_path = tmp_path / "runtime.json"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "start",
            "--agents-dir",
            "./agents",
            "--metrics-json-file",
            str(metrics_path),
        ],
    )

    assert result.exit_code == 0
    assert stub_pool.run_called is True
    data = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert data["active_sessions"] == 1
    assert data["registered_agents"] == 1
    assert data["sessions_by_agent"]["restaurant"] == 1


def test_start_command_metrics_jsonl_writes_snapshot_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``--metrics-jsonl`` produces JSON Lines the sidecar TUI can tail."""
    jsonl = tmp_path / "sidecar.jsonl"
    stub_pool = StubPool(
        discovered=[StubConfig(name="restaurant", agent_cls=StubAgent)]
    )
    monkeypatch.setattr("openrtc.cli_livekit.AgentPool", lambda **kwargs: stub_pool)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "start",
            "--agents-dir",
            "./agents",
            "--metrics-jsonl",
            str(jsonl),
            "--metrics-jsonl-interval",
            "0.3",
        ],
    )

    assert result.exit_code == 0
    assert stub_pool.run_called is True
    lines = [ln for ln in jsonl.read_text(encoding="utf-8").split("\n") if ln.strip()]
    assert len(lines) >= 1
    first = json.loads(lines[0])
    assert first["schema_version"] == 1
    assert first["kind"] == "snapshot"
    assert "payload" in first
    assert first["payload"]["registered_agents"] == 1


def test_tui_command_exits_when_textual_is_not_importable(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``openrtc tui`` fails fast with a clear message if the TUI extra is absent."""
    real_import = builtins.__import__

    def guard(name: str, *args: object, **kwargs: object) -> object:
        if name == "openrtc.tui_app":
            raise ImportError("simulated missing textual")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    runner = CliRunner()
    with caplog.at_level(logging.ERROR, logger="openrtc"):
        result = runner.invoke(
            app,
            ["tui", "--watch", "./metrics.jsonl"],
            catch_exceptions=False,
        )
    assert result.exit_code == 1
    assert "Textual" in caplog.text
    assert "openrtc[tui]" in caplog.text
