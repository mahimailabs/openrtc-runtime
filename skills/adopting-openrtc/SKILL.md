---
name: adopting-openrtc
description: 'Moves a livekit-agents project onto OpenRTC, or starts a new one on it: one AgentPool worker that routes each call to one of several standard Agent classes, with hot reload, a live `openrtc top`, tenant caps and drain deploys. Use when the user says "use OpenRTC", "add openrtc", "run several LiveKit agents in one worker", "route calls to different agents", "one worker for all my agents", "replace my entrypoint", "migrate to openrtc", or when a livekit-agents repo has more than one agent and hand-written dispatch. Covers finding the existing entrypoint and AgentSession wiring, registering agents with add() or discover(), choosing the routing signal and the isolation mode, deleting the old wiring, and checking the result with openrtc list, dev and top. For running it in production use operating-openrtc; for LiveKit APIs use reading-livekit-docs.'
license: MIT
metadata:
  author: mahimailabs
---

# Adopting OpenRTC

OpenRTC is a thin layer over livekit-agents. The user's agents stay standard
`livekit.agents.Agent` subclasses: OpenRTC has no base class and does not wrap
`@function_tool`, `RunContext`, `on_enter`, `on_exit` or the `*_node` hooks. What changes is the
worker around them: one `AgentPool` replaces the per-worker `entrypoint`, the `AgentSession(...)`
construction and `cli.run_app`.

This skill covers `openrtc` 0.20 and later, on livekit-agents `>=1.5,<1.9`.

## Facts come from the docs, not memory

Before writing OpenRTC code, read `https://docs.openrtc.tech/llms-full.txt` (all five docs pages
as Markdown), or one page as `https://docs.openrtc.tech/llms.mdx/<page>/content.md` with `<page>`
one of `how-it-works`, `cli`, `benchmark`. The supported API is `openrtc.__all__`. For LiveKit's
own APIs, load `reading-livekit-docs` (install with `npx skills add livekit/agent-skills`).

## First decide whether it fits

OpenRTC earns its place when the project has more than one agent, or needs the operating tools
(hot reload on live calls, `openrtc top`, tenant caps, drain deploys). Tell the user plainly when
it does not:

- **One agent, no need for the tooling.** Plain livekit-agents is simpler. Stop here.
- **More calls per machine.** OpenRTC does not raise the calls a machine can serve; CPU is the
  limit. Measured on livekit-agents 1.8.3: about 22 MB per call against about 65 MB for
  livekit's process per call, at about the same CPU. Don't promise density.

## 1. Find what the project does today

Search for the worker wiring. It usually looks like one of these:

- `server = AgentServer()` with `@server.rtc_session()` on an `async def entrypoint(ctx)`, then
  `cli.run_app(server)` (livekit-agents 1.x);
- `cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))` (older 1.x);
- inside the entrypoint: `AgentSession(stt=..., llm=..., tts=..., vad=...)`, `await ctx.connect()`,
  `await session.start(agent=SomeAgent(), room=ctx.room)`, maybe `generate_reply` as a greeting;
- dispatch the user wrote by hand: an `if` on the room name or on `ctx.job.metadata`.

Write down, per agent: the class, its STT, LLM and TTS, its greeting, any other `AgentSession`
options, and how a call is meant to reach it. Keep anything the entrypoint does beyond this
(custom logging, database setup); it moves to the agent's `on_enter` or to a session observer.

## 2. Register the agents

Pick one style and use it for the whole pool.

**One file per agent, discovered from a directory** (best when agents are many or edited often):

```python
# agents/booking.py
from livekit.agents import Agent

from openrtc import agent_config


@agent_config(name="booking", greeting="Welcome to reservations.")
class BookingAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="You help callers book a table.")
```

```bash
openrtc dev ./agents --default-stt openai/gpt-4o-mini-transcribe --default-llm openai/gpt-4.1-mini --default-tts openai/gpt-4o-mini-tts
```

Without `@agent_config`, an agent's name is its file name.

**Explicit registration in Python** (best when agents need provider objects or options):

```python
from livekit.plugins import openai

from openrtc import AgentPool
from agents.booking import BookingAgent
from agents.support import SupportAgent

pool = AgentPool(
    default_stt=openai.STT(model="gpt-4o-mini-transcribe"),
    default_llm=openai.responses.LLM(model="gpt-4.1-mini"),
    default_tts=openai.TTS(model="gpt-4o-mini-tts"),
)
pool.add("booking", BookingAgent, greeting="Welcome to reservations.")
pool.add("support", SupportAgent, llm=openai.responses.LLM(model="gpt-4.1"))

if __name__ == "__main__":
    pool.run()
```

Then `python main.py dev` and `python main.py start` work as they did for the livekit worker.

Rules that avoid the common failures:

- Providers set on most agents go on the pool as `default_stt`, `default_llm`, `default_tts`;
  the odd one out goes on `add(...)` or `@agent_config(...)`. A provider is a plugin object or a
  provider string, passed to `AgentSession` unchanged.
- Other `AgentSession` options go on `add(..., **options)` or `session_kwargs=`. Turn handling
  defaults to the multilingual turn detector with VAD interruption; override it there.
- Do not create Silero VAD or the turn detector per call. OpenRTC loads them once per worker.
  Delete the old `prewarm` that did this.
- Define agent classes at module scope. In `process` isolation the registration is pickled into
  each job process, so no classes inside functions and no lambdas in provider settings.

## 3. Route calls to agents

OpenRTC picks the agent for each call in this order:

1. `ctx.job.metadata` with `{"agent": "booking"}` (dispatch metadata)
2. the room's metadata with the same key
3. the room name prefix: a room named `booking-call-7` goes to `booking`
4. the first registered agent

Map the old hand-written dispatch onto one of these and delete it. A metadata value that names an
agent the pool does not have raises `ValueError` and the call is rejected; it never falls back
silently. If the worker shares a LiveKit project with other workers, scope it so it only accepts
its own rooms:

```python
from openrtc import AgentPool

pool = AgentPool(accept_only_registered_rooms=True)
```

For rules the chain cannot express, pass `router=` (a function from job metadata to an agent name,
module-level so it pickles), or your own `request_fnc=` accept/reject hook.

## 4. Choose the isolation mode

| | `coroutine` (default) | `process` |
| --- | --- | --- |
| A call runs as | an `asyncio.Task` in the worker | its own process (livekit's model) |
| Memory per call | about 22 MB | about 65 MB |
| CPU | one Python process, about one core | every core |
| Hot reload, `slow` in `openrtc top`, tenant breaker | yes | no |

Keep the default unless the agents do heavy CPU work in Python, or the user needs a crash in one
call never to touch another. For several cores in coroutine mode, run one worker per core (see
`operating-openrtc`).

## 5. Delete the old wiring

Remove the old `entrypoint`, the `AgentSession(...)` construction, the `prewarm` function and the
`cli.run_app(...)` call. Keep the agent classes exactly as they were. Add the dependency:

```bash
pip install "openrtc[livekit,cli]"
```

## 6. Check it

```bash
openrtc list ./agents --plain
openrtc dev ./agents
openrtc top
```

1. `openrtc list` loads the directory and prints what would register, with no LiveKit connection.
   Every agent should appear with the providers you expect.
2. `openrtc dev` runs a worker with hot reload. Join a room whose name starts with an agent's
   name (or dispatch with `{"agent": "<name>"}` metadata) and check the right agent answers.
3. `openrtc top`, in a second terminal, lists the live call with its agent and tenant.
4. Run the project's tests. Agents unchanged means their tests should pass unchanged.

To probe an agent's behavior turn by turn, `debugging-livekit-agents` works on OpenRTC agents
too: they are ordinary LiveKit agents.
