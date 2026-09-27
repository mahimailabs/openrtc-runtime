"""The bench agent on OpenRTC. Coroutine isolation and uvloop are the defaults.

BENCH_ISOLATION=process switches isolation, BENCH_INTROSPECTION=0 turns the
openrtc top stack off, OPENRTC_UVLOOP=0 keeps the asyncio loop, and
BENCH_PORT gives the worker's HTTP server a port of its own (multi.sh).
BENCH_FFI_ROUTE=1 installs the FfiQueue routing prototype (ffiroute.py).
"""

import os

import ffiroute
import ffistats
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
if "BENCH_PORT" in os.environ:
    pool.server._port = int(os.environ["BENCH_PORT"])

if os.environ.get("BENCH_FFI_ROUTE") == "1":
    ffiroute.install()
if os.environ.get("BENCH_FFI_STATS") == "1":
    ffistats.install()

if __name__ == "__main__":
    pool.run()
