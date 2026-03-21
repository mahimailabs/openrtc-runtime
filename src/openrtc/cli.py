from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from openrtc.pool import AgentConfig, AgentPool
from openrtc.resources import (
    agent_disk_footprints,
    file_size_bytes,
    format_byte_size,
    process_resident_set_bytes,
)

logger = logging.getLogger("openrtc")


def build_parser() -> argparse.ArgumentParser:
    """Create the OpenRTC command-line parser."""
    parser = argparse.ArgumentParser(
        prog="openrtc",
        description="Discover and run multiple LiveKit agents in one worker.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser(
        "list",
        help="List discovered agents and optional resource estimates.",
    )
    _add_pool_arguments(list_parser)
    list_parser.add_argument(
        "--resources",
        action="store_true",
        help=(
            "After listing agents, print on-disk source sizes and approximate "
            "process memory (RSS) for this CLI process after discovery."
        ),
    )

    for command_name in ("start", "dev"):
        command_parser = subparsers.add_parser(command_name)
        _add_pool_arguments(command_parser)

    return parser


def _add_pool_arguments(command_parser: argparse.ArgumentParser) -> None:
    command_parser.add_argument(
        "--agents-dir",
        type=Path,
        required=True,
        help="Directory containing discoverable agent modules.",
    )
    command_parser.add_argument(
        "--default-stt",
        help=(
            "Default STT provider used when a discovered agent does not "
            "override STT via @agent_config(...)."
        ),
    )
    command_parser.add_argument(
        "--default-llm",
        help=(
            "Default LLM provider used when a discovered agent does not "
            "override LLM via @agent_config(...)."
        ),
    )
    command_parser.add_argument(
        "--default-tts",
        help=(
            "Default TTS provider used when a discovered agent does not "
            "override TTS via @agent_config(...)."
        ),
    )
    command_parser.add_argument(
        "--default-greeting",
        help=(
            "Default greeting used when a discovered agent does not "
            "override greeting via @agent_config(...)."
        ),
    )


def main(argv: list[str] | None = None) -> int:
    """Run the OpenRTC CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    pool = AgentPool(**_pool_kwargs_from_args(args))
    discovered = pool.discover(args.agents_dir)
    if not discovered:
        logger.error("No agent modules were discovered in %s.", args.agents_dir)
        return 1

    if args.command == "list":
        show_resources = getattr(args, "resources", False)
        for config in discovered:
            line = (
                f"{config.name}: class={config.agent_cls.__name__}, "
                f"stt={config.stt!r}, llm={config.llm!r}, tts={config.tts!r}, "
                f"greeting={config.greeting!r}"
            )
            if show_resources and config.source_path is not None:
                sz = file_size_bytes(config.source_path)
                line += f", source_file={format_byte_size(sz)}"
            print(line)

        if show_resources:
            _print_resource_summary(discovered)
        return 0

    sys.argv = [sys.argv[0], args.command]
    pool.run()
    return 0


def _print_resource_summary(discovered: list[AgentConfig]) -> None:
    footprints = agent_disk_footprints(discovered)
    total_source = sum(f.size_bytes for f in footprints)
    print()
    print("Resource summary (local estimates for this `openrtc list` process):")
    print(
        f"  Agents: {len(discovered)}; "
        f"on-disk agent source total: {format_byte_size(total_source)}"
    )
    if len(footprints) < len(discovered):
        print(
            "  Note: per-agent source size is shown only for agents "
            "registered with a known file path (e.g. via discovery)."
        )

    rss = process_resident_set_bytes()
    if rss is not None:
        if sys.platform == "darwin":
            print(
                f"  Approximate resident memory (peak RSS on macOS): "
                f"{format_byte_size(rss)}"
            )
        else:
            print(f"  Approximate resident memory (RSS): {format_byte_size(rss)}")
    else:
        print("  Resident memory (RSS): not available on this platform.")

    print()
    print(
        "OpenRTC runs every agent in one shared LiveKit worker process, so you ship "
        "one container image and one runtime instead of duplicating a large base "
        "image per agent. Actual memory at runtime depends on models, concurrent "
        "sessions, and providers; use host metrics in production."
    )


def _pool_kwargs_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "default_stt": args.default_stt,
        "default_llm": args.default_llm,
        "default_tts": args.default_tts,
        "default_greeting": args.default_greeting,
    }
