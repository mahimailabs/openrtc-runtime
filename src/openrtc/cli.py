from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from openrtc.pool import AgentPool

logger = logging.getLogger("openrtc")


def build_parser() -> argparse.ArgumentParser:
    """Create the OpenRTC command-line parser."""
    parser = argparse.ArgumentParser(
        prog="openrtc",
        description="Discover and run multiple LiveKit agents in one worker.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command_name in ("start", "dev", "list"):
        command_parser = subparsers.add_parser(command_name)
        command_parser.add_argument(
            "--agents-dir",
            type=Path,
            required=True,
            help="Directory containing discoverable agent modules.",
        )
        command_parser.add_argument(
            "--default-stt",
            help="Default STT provider used when an agent module omits AGENT_STT.",
        )
        command_parser.add_argument(
            "--default-llm",
            help="Default LLM provider used when an agent module omits AGENT_LLM.",
        )
        command_parser.add_argument(
            "--default-tts",
            help="Default TTS provider used when an agent module omits AGENT_TTS.",
        )
        command_parser.add_argument(
            "--default-greeting",
            help=("Default greeting used when an agent module omits AGENT_GREETING."),
        )

    return parser


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
        for config in discovered:
            print(
                f"{config.name}: class={config.agent_cls.__name__}, "
                f"stt={config.stt!r}, llm={config.llm!r}, tts={config.tts!r}, "
                f"greeting={config.greeting!r}"
            )
        return 0

    sys.argv = [sys.argv[0], args.command]
    pool.run()
    return 0


def _pool_kwargs_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "default_stt": args.default_stt,
        "default_llm": args.default_llm,
        "default_tts": args.default_tts,
        "default_greeting": args.default_greeting,
    }
