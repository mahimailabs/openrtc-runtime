"""MAH-85: dev --watch / --no-watch / --watch-path flag plumbing."""

from __future__ import annotations

from pathlib import Path

from openrtc.cli.base_cli import SharedLiveKitWorkerOptions, resolve_hot_reload
from openrtc.cli.livekit_cli import _strip_openrtc_only_flags_for_livekit


def test_resolve_hot_reload_only_for_dev_in_coroutine_mode() -> None:
    assert resolve_hot_reload("dev", no_watch=False, isolation="coroutine") is True
    assert resolve_hot_reload("dev", no_watch=True, isolation="coroutine") is False
    assert resolve_hot_reload("dev", no_watch=False, isolation="process") is False
    assert resolve_hot_reload("start", no_watch=False, isolation="coroutine") is False
    assert resolve_hot_reload("console", no_watch=False, isolation="coroutine") is False


def test_agent_pool_kwargs_carry_hot_reload() -> None:
    opts = SharedLiveKitWorkerOptions.from_cli(
        Path("./agents"),
        enable_hot_reload=True,
        watch_paths=(Path("/a"), Path("/b")),
    )
    kwargs = opts.agent_pool_kwargs()
    assert kwargs["enable_hot_reload"] is True
    assert kwargs["watch_paths"] == [Path("/a"), Path("/b")]


def test_agent_pool_kwargs_default_to_no_reload() -> None:
    kwargs = SharedLiveKitWorkerOptions.from_cli(Path("./agents")).agent_pool_kwargs()
    assert kwargs["enable_hot_reload"] is False
    assert kwargs["watch_paths"] is None


def test_strip_removes_watch_flags_before_livekit_handoff() -> None:
    argv = [
        "--agents-dir",
        "./agents",
        "--no-watch",
        "--watch-path",
        "/x",
        "--url",
        "ws://h",
    ]
    out = _strip_openrtc_only_flags_for_livekit(argv)
    assert "--no-watch" not in out
    assert "--watch-path" not in out
    assert "/x" not in out
    # LiveKit's own flags survive the strip.
    assert out == ["--url", "ws://h"]


def test_strip_removes_equals_forms() -> None:
    out = _strip_openrtc_only_flags_for_livekit(["--watch-path=/x", "--no-watch"])
    assert out == []
