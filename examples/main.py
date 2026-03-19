from __future__ import annotations

from pathlib import Path

from openrtc import AgentPool


def main() -> None:
    pool = AgentPool(
        default_stt="deepgram/nova-3:multi",
        default_llm="openai/gpt-4.1-mini",
        default_tts="cartesia/sonic-3",
    )
    pool.discover(Path(__file__).with_name("agents"))
    pool.run()


if __name__ == "__main__":
    main()
