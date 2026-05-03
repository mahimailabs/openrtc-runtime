"""Structured CLI parameter bundles for LiveKit worker handoff (internal)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openrtc.types import ProviderValue


def agent_provider_kwargs(
    default_stt: ProviderValue | None,
    default_llm: ProviderValue | None,
    default_tts: ProviderValue | None,
    default_greeting: str | None,
) -> dict[str, Any]:
    """Keyword arguments for :class:`openrtc.core.pool.AgentPool` provider defaults."""
    return {
        "default_stt": default_stt,
        "default_llm": default_llm,
        "default_tts": default_tts,
        "default_greeting": default_greeting,
    }


@dataclass(frozen=True)
class SharedLiveKitWorkerOptions:
    """Options shared by ``start`` / ``dev`` / ``console`` / ``connect`` handoff paths.

    Typer still lists each flag on every command so ``--help`` stays accurate; this
    dataclass deduplicates the handoff to :mod:`openrtc.cli_livekit`.
    """

    agents_dir: Path
    default_stt: ProviderValue | None
    default_llm: ProviderValue | None
    default_tts: ProviderValue | None
    default_greeting: str | None
    url: str | None
    api_key: str | None
    api_secret: str | None
    log_level: str | None
    dashboard: bool
    dashboard_refresh: float
    metrics_json_file: Path | None
    metrics_jsonl: Path | None
    metrics_jsonl_interval: float | None

    def agent_pool_kwargs(self) -> dict[str, Any]:
        return agent_provider_kwargs(
            self.default_stt,
            self.default_llm,
            self.default_tts,
            self.default_greeting,
        )

    @classmethod
    def from_cli(
        cls,
        agents_dir: Path,
        *,
        default_stt: ProviderValue | None = None,
        default_llm: ProviderValue | None = None,
        default_tts: ProviderValue | None = None,
        default_greeting: str | None = None,
        url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        log_level: str | None = None,
        dashboard: bool = False,
        dashboard_refresh: float = 1.0,
        metrics_json_file: Path | None = None,
        metrics_jsonl: Path | None = None,
        metrics_jsonl_interval: float | None = None,
    ) -> SharedLiveKitWorkerOptions:
        return cls(
            agents_dir=agents_dir,
            default_stt=default_stt,
            default_llm=default_llm,
            default_tts=default_tts,
            default_greeting=default_greeting,
            url=url,
            api_key=api_key,
            api_secret=api_secret,
            log_level=log_level,
            dashboard=dashboard,
            dashboard_refresh=dashboard_refresh,
            metrics_json_file=metrics_json_file,
            metrics_jsonl=metrics_jsonl,
            metrics_jsonl_interval=metrics_jsonl_interval,
        )

    @classmethod
    def for_download_files(
        cls,
        agents_dir: Path,
        *,
        url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        log_level: str | None = None,
    ) -> SharedLiveKitWorkerOptions:
        return cls(
            agents_dir=agents_dir,
            default_stt=None,
            default_llm=None,
            default_tts=None,
            default_greeting=None,
            url=url,
            api_key=api_key,
            api_secret=api_secret,
            log_level=log_level,
            dashboard=False,
            dashboard_refresh=1.0,
            metrics_json_file=None,
            metrics_jsonl=None,
            metrics_jsonl_interval=None,
        )
