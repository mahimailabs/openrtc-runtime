from __future__ import annotations

from examples.agents.dental import DentalAgent
from examples.agents.restaurant import RestaurantAgent
from openrtc import AgentPool


def main() -> None:
    pool = AgentPool()
    pool.add(
        "restaurant",
        RestaurantAgent,
        stt="deepgram/nova-3:multi",
        llm="openai/gpt-5-mini",
        tts="cartesia/sonic-3",
        greeting="Welcome to OpenRTC restaurant reservations.",
    )
    pool.add(
        "dental",
        DentalAgent,
        stt="deepgram/nova-3:multi",
        llm="openai/gpt-5-mini",
        tts="cartesia/sonic-3",
        greeting="Welcome to OpenRTC dental scheduling.",
    )
    pool.run()


if __name__ == "__main__":
    main()
