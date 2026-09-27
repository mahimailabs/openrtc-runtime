"""Drift guard for the agent skills in ``skills/``.

Adopters install them with ``npx skills add mahimailabs/openrtc-runtime``, so a skill that names a
flag or keyword OpenRTC no longer has teaches every coding agent the wrong thing. These tests check
each ``SKILL.md`` against the real ``AgentPool``, ``agent_config`` and CLI signatures.
"""

from __future__ import annotations

import ast
import inspect
import re
import shlex
from pathlib import Path

import click
import pytest
import typer

from openrtc import AgentPool, agent_config
from openrtc.cli.main_cli import app

_SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"
_SKILL_FILES = sorted(_SKILLS_DIR.glob("*/SKILL.md"))
_FENCE = re.compile(r"```(\w+)\n(.*?)```", re.DOTALL)
_KWARGS = {
    "AgentPool": set(inspect.signature(AgentPool).parameters),
    "add": set(inspect.signature(AgentPool.add).parameters),
    "agent_config": set(inspect.signature(agent_config).parameters),
}


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "SKILL.md must start with YAML frontmatter"
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith(" "):
            fields[key.strip()] = value.strip().strip("'\"")
    return fields


def _blocks(text: str, lang: str) -> list[str]:
    return [body for fence, body in _FENCE.findall(text) if fence == lang]


def _cli_options() -> dict[str, set[str]]:
    group = typer.main.get_command(app)
    assert isinstance(group, click.Group)
    return {
        name: {opt for param in cmd.params for opt in param.opts} | {"--help"}
        for name, cmd in group.commands.items()
    }


def _bad_kwargs(source: str) -> list[str]:
    bad = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        allowed = _KWARGS.get(name)
        if allowed is None or "session_options" in allowed:
            continue  # not ours, or add(**session_options), which AgentSession checks
        bad += [f"{name}({kw.arg}=)" for kw in node.keywords if kw.arg not in allowed]
    return bad


def _bad_flags(script: str, options: dict[str, set[str]]) -> list[str]:
    bad = []
    for line in script.splitlines():
        words = shlex.split(line, comments=True)
        while words and "=" in words[0]:  # leading VAR=value assignments
            words.pop(0)
        if len(words) < 2 or words[0] != "openrtc":
            continue
        command = words[1]
        if command not in options:
            bad.append(f"openrtc {command}")
            continue
        bad += [
            f"openrtc {command} {word}"
            for word in words[2:]
            if word.startswith("--") and word.split("=")[0] not in options[command]
        ]
    return bad


def test_skills_exist() -> None:
    assert [p.parent.name for p in _SKILL_FILES] == [
        "adopting-openrtc",
        "operating-openrtc",
    ]


@pytest.mark.parametrize("path", _SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_frontmatter_and_style(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    fields = _frontmatter(text)
    assert fields.get("name") == path.parent.name
    assert len(fields.get("description", "")) > 50
    assert "—" not in text, "no em dashes"


@pytest.mark.parametrize("path", _SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_python_uses_real_keywords(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    bad = [kw for block in _blocks(text, "python") for kw in _bad_kwargs(block)]
    assert bad == []


@pytest.mark.parametrize("path", _SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_commands_use_real_flags(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    options = _cli_options()
    inline = "\n".join(re.findall(r"`(openrtc [^`]+)`", text))
    bad = [
        flag
        for block in [*_blocks(text, "bash"), inline]
        for flag in _bad_flags(block, options)
    ]
    assert bad == []


def test_checks_catch_drift() -> None:
    options = _cli_options()
    assert _bad_flags("openrtc start ./agents --no-such-flag 1", options) == [
        "openrtc start --no-such-flag"
    ]
    assert _bad_flags("OPENRTC_PORT=1 openrtc frobnicate", options) == [
        "openrtc frobnicate"
    ]
    assert _bad_kwargs("AgentPool(no_such_kwarg=1)") == ["AgentPool(no_such_kwarg=)"]
    assert _bad_kwargs("agent_config(nme='x')") == ["agent_config(nme=)"]
    assert _bad_kwargs("pool.add('a', A, anything=1)") == []
