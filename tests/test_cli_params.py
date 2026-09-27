"""Unit tests for :mod:`openrtc.cli.base_cli` parameter bundles."""

from __future__ import annotations

from pathlib import Path

from openrtc.cli.base_cli import (
    SharedLiveKitWorkerOptions,
    agent_pool_runtime_kwargs,
    agent_provider_kwargs,
)


def test_agent_provider_kwargs_matches_agent_pool_constructor() -> None:
    d = agent_provider_kwargs("stt", "llm", "tts", "greet")
    assert d == {
        "default_stt": "stt",
        "default_llm": "llm",
        "default_tts": "tts",
        "default_greeting": "greet",
    }


def test_agent_pool_runtime_kwargs_defaults() -> None:
    assert agent_pool_runtime_kwargs() == {
        "isolation": "coroutine",
        "max_concurrent_sessions": 50,
        "port": None,
    }


def test_agent_pool_runtime_kwargs_overrides() -> None:
    assert agent_pool_runtime_kwargs(
        isolation="process",
        max_concurrent_sessions=10,
        port=8082,
    ) == {
        "isolation": "process",
        "max_concurrent_sessions": 10,
        "port": 8082,
    }


def test_shared_livekit_worker_options_from_cli_and_for_download_files() -> None:
    agents = Path("/tmp/agents")
    opts = SharedLiveKitWorkerOptions.from_cli(
        agents,
        default_stt="a",
        default_greeting="hi",
        dashboard=True,
    )
    assert opts.agents_dir == agents
    assert opts.isolation == "coroutine"
    assert opts.max_concurrent_sessions == 50
    assert opts.agent_pool_kwargs() == {
        **agent_provider_kwargs("a", None, None, "hi"),
        **agent_pool_runtime_kwargs(),
        "enable_hot_reload": False,
        "watch_paths": None,
    }

    dl = SharedLiveKitWorkerOptions.for_download_files(
        agents,
        url="ws://example",
        log_level="INFO",
    )
    assert dl.default_stt is None
    assert dl.dashboard is False
    assert dl.metrics_jsonl is None
    assert dl.url == "ws://example"
    assert dl.log_level == "INFO"
    # Defaults flow through the for_download_files factory too.
    assert dl.isolation == "coroutine"
    assert dl.max_concurrent_sessions == 50


def test_shared_livekit_worker_options_isolation_and_max_propagate() -> None:
    """`--isolation` + `--max-concurrent-sessions` reach AgentPool kwargs."""
    agents = Path("/tmp/agents")
    opts = SharedLiveKitWorkerOptions.from_cli(
        agents,
        isolation="process",
        max_concurrent_sessions=12,
        port=8082,
    )
    kwargs = opts.agent_pool_kwargs()
    assert kwargs["isolation"] == "process"
    assert kwargs["max_concurrent_sessions"] == 12
    assert kwargs["port"] == 8082


def test_isolation_arg_reads_openrtc_isolation_envvar() -> None:
    """``--isolation`` falls back to ``OPENRTC_ISOLATION`` env var."""
    import typing

    from openrtc.cli.base_cli import IsolationArg

    _annotation, option_info = typing.get_args(IsolationArg)
    assert option_info.envvar == "OPENRTC_ISOLATION"


def test_max_concurrent_sessions_arg_reads_envvar() -> None:
    """``--max-concurrent-sessions`` falls back to ``OPENRTC_MAX_CONCURRENT_SESSIONS``."""
    import typing

    from openrtc.cli.base_cli import MaxConcurrentSessionsArg

    _annotation, option_info = typing.get_args(MaxConcurrentSessionsArg)
    assert option_info.envvar == "OPENRTC_MAX_CONCURRENT_SESSIONS"


def test_port_arg_reads_envvar_and_bounds() -> None:
    """``--port`` falls back to ``OPENRTC_PORT`` and only takes 0..65535."""
    import typing

    from openrtc.cli.base_cli import PortArg

    _annotation, option_info = typing.get_args(PortArg)
    assert option_info.envvar == "OPENRTC_PORT"
    assert (option_info.min, option_info.max) == (0, 65535)
