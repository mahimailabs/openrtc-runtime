"""Unit tests for :mod:`openrtc.cli_params` bundles."""

from __future__ import annotations

from pathlib import Path

from openrtc.cli_params import SharedLiveKitWorkerOptions, agent_provider_kwargs


def test_agent_provider_kwargs_matches_agent_pool_constructor() -> None:
    d = agent_provider_kwargs("stt", "llm", "tts", "greet")
    assert d == {
        "default_stt": "stt",
        "default_llm": "llm",
        "default_tts": "tts",
        "default_greeting": "greet",
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
    assert opts.agent_pool_kwargs() == agent_provider_kwargs("a", None, None, "hi")

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
