"""The `openrtc serve` command: discover pipecat builders and serve them."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer

from openrtc.cli.main_cli import serve_command
from openrtc.cli.pipecat_cli import serve_pipecat_agents
from openrtc.core.pool import AgentPool

_MARKED_BUILDER = (
    "from openrtc import agent_config\n"
    "@agent_config(name='sales')\n"
    "def build(view):\n"
    "    return []\n"
)


def test_serve_command_discovers_and_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "sales.py").write_text(_MARKED_BUILDER, encoding="utf-8")
    ran: list[AgentPool] = []
    monkeypatch.setattr(AgentPool, "run", lambda self: ran.append(self))

    serve_command(tmp_path)

    assert len(ran) == 1  # run() was invoked
    pool = ran[0]
    assert pool.list_agents() == ["sales"]  # discovered before serving
    assert pool._backend_name == "pipecat"  # on the pipecat backend


def test_serve_exits_when_no_agents_are_discovered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran: list[AgentPool] = []
    monkeypatch.setattr(AgentPool, "run", lambda self: ran.append(self))
    with pytest.raises(typer.Exit):
        serve_pipecat_agents(tmp_path)  # empty dir
    assert ran == []  # never reaches run()


def test_serve_exits_when_directory_is_missing(tmp_path: Path) -> None:
    with pytest.raises(typer.Exit):
        serve_pipecat_agents(tmp_path / "does-not-exist")


def test_serve_exits_when_path_is_not_a_directory(tmp_path: Path) -> None:
    plain_file = tmp_path / "plain.py"
    plain_file.write_text("", encoding="utf-8")
    with pytest.raises(typer.Exit):
        serve_pipecat_agents(plain_file)
