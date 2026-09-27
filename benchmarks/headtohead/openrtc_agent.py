"""The bench agent on OpenRTC. Coroutine isolation and uvloop are the defaults.

BENCH_ISOLATION=process switches isolation, BENCH_INTROSPECTION=0 turns the
openrtc top stack off, and OPENRTC_UVLOOP=0 keeps the asyncio loop.
"""

import os

from fakes import FakeLLM, FakeSTT, FakeTTS
from livekit.agents import Agent

from openrtc import AgentPool


class BenchAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="You are a restaurant booking assistant.")


pool = AgentPool(
    agent_name="bench",
    default_stt=FakeSTT(),
    default_llm=FakeLLM(),
    default_tts=FakeTTS(),
    isolation=os.environ.get("BENCH_ISOLATION", "coroutine"),  # type: ignore[arg-type]
    max_concurrent_sessions=200,
    enable_introspection=os.environ.get("BENCH_INTROSPECTION", "1") == "1",
)
pool.add("bench", BenchAgent)

if __name__ == "__main__":
    pool.run()
