"""The same agent on plain livekit-agents. BENCH_EXECUTOR=process (default) or thread."""

import os

from fakes import FakeLLM, FakeSTT, FakeTTS
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobExecutorType,
    JobProcess,
    cli,
)
from livekit.plugins import silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel


class BenchAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="You are a restaurant booking assistant.")


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server = AgentServer(
    setup_fnc=prewarm,
    job_executor_type=JobExecutorType(os.environ.get("BENCH_EXECUTOR", "process")),
    load_threshold=0.99,
    # same admission policy as OpenRTC (active / max) so only the execution model differs
    load_fnc=lambda srv: len(srv.active_jobs) / 200,
)


@server.rtc_session(agent_name="bench")
async def entrypoint(ctx: JobContext) -> None:
    session = AgentSession(
        stt=FakeSTT(),
        llm=FakeLLM(),
        tts=FakeTTS(),
        vad=ctx.proc.userdata["vad"],
        turn_handling={
            "interruption": {"mode": "vad"},
            "turn_detection": MultilingualModel(),
        },
    )
    await ctx.connect()
    await session.start(agent=BenchAgent(), room=ctx.room)


if __name__ == "__main__":
    cli.run_app(server)
