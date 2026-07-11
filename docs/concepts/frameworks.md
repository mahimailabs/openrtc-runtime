---
title: Frameworks
description: Run OpenRTC on livekit or pipecat through one backend seam, and how agents register on each.
icon: layer-group
---

# Frameworks

OpenRTC is a thin operational layer (registration, routing, shared prewarm,
observability, drain) over a voice runtime. That runtime is a **backend**, chosen
when you build the pool:

```python
from openrtc import AgentPool

pool = AgentPool()                    # livekit (the default)
pool = AgentPool(backend="pipecat")   # pipecat
```

`import openrtc` pulls **neither** framework. Each backend lives behind its own
extra and is imported only when you select it:

| Backend | Install | Agent shape |
|---|---|---|
| `livekit` (default) | `openrtc[livekit]` | `livekit.agents.Agent` subclass |
| `pipecat` | `openrtc[pipecat]` | pipeline builder callable |

Selecting a backend whose framework is not installed raises a clear error with
the `pip install openrtc[...]` hint. Serving the pipecat backend (`run()`) also
needs `openrtc[pipecat-serve]`, which adds pipecat's FastAPI runner.

## What every backend shares

Whichever runtime you pick, OpenRTC gives you the same operator control plane:

- **Registration and routing.** `pool.add(name, ...)` registers an agent; each
  call is routed to one by the same precedence (custom router, then job / room
  metadata, then room-name prefix, then first registered). See
  [Routing](/concepts/routing).
- **Shared prewarm.** The worker loads the VAD and turn model **once** and shares
  them across every session, instead of building them per call.
- **Observability.** Every session emits the same start / end signals to the
  observers you pass to the pool, so metrics and cost / quality lanes stay wired
  across frameworks.

The registration surface is the same on both: `add`, `get`, `remove`, and
`list_agents`.

## livekit backend (default)

Agents are standard `livekit.agents.Agent` subclasses, and the provider arguments
pass through to the session. This is the model in
[Getting Started](/getting-started) and
[Coming from livekit-agents](/coming-from-livekit-agents).

## pipecat backend

A pipecat agent registers as a **pipeline builder**: a callable that, given the
call's view, returns the pipecat processors for that call. The builder owns the
transport and the STT / LLM / TTS services (so the pool's provider arguments,
which are livekit-only, do not apply here). OpenRTC wraps routing, shared
prewarm, and observability around it.

The call view (`PipecatCallView`) carries the worker's shared prewarm, so the
builder attaches the shared VAD and turn analyzer instead of building its own:

```python
from openrtc import AgentPool
from openrtc.backends.pipecat import PipecatCallView


def support(view: PipecatCallView):
    # transport and services are yours (any pipecat transport / services);
    # the shared VAD and turn model come from the pool's prewarm.
    transport = make_transport(vad_analyzer=view.prewarmed.vad)
    return [
        transport.input(),
        stt,
        view.prewarmed.turn,
        llm,
        tts,
        transport.output(),
    ]


pool = AgentPool(backend="pipecat")
pool.add("support", support)
```

### Registration side by side

<Tabs>
  <Tab title="livekit">
    ```python
    from livekit.agents import Agent
    from livekit.plugins import openai
    from openrtc import AgentPool

    class Support(Agent):
        def __init__(self) -> None:
            super().__init__(instructions="Help callers.")

    pool = AgentPool()  # backend="livekit"
    pool.add(
        "support",
        Support,
        stt=openai.STT(),
        llm=openai.responses.LLM(),
        tts=openai.TTS(),
    )
    ```
  </Tab>
  <Tab title="pipecat">
    ```python
    from openrtc import AgentPool
    from openrtc.backends.pipecat import PipecatCallView

    def support(view: PipecatCallView):
        transport = make_transport(
            vad_analyzer=view.prewarmed.vad,
        )
        return [
            transport.input(),
            stt,
            view.prewarmed.turn,
            llm,
            tts,
            transport.output(),
        ]

    pool = AgentPool(backend="pipecat")
    pool.add("support", support)
    ```
  </Tab>
</Tabs>

### Serving

`pool.run()` serves calls over a transport via pipecat's runner (a FastAPI
server). Install the serving extra and call `run()`:

```bash
pip install "openrtc[pipecat-serve]"
```

```python
from openrtc import AgentPool
from openrtc.backends.pipecat import PipecatCallView


def support(view: PipecatCallView):
    transport = make_transport(vad_analyzer=view.prewarmed.vad)
    return [transport.input(), stt, view.prewarmed.turn, llm, tts, transport.output()]


pool = AgentPool(backend="pipecat")
pool.add("support", support)
pool.run()  # serves until it exits
```

Each connection hits the runner's `/start` endpoint; OpenRTC routes it
(`body["agent"]`), builds the observed session, and runs one pipeline per call
with the shared prewarm. Host and port come from pipecat's environment
(`RUNNER_HOST` / `RUNNER_PORT`). During a drain the worker declines new calls and
lets in-flight ones finish.

From a directory of `@agent_config`-marked builders, the CLI does the same:

```bash
openrtc serve ./agents
```

**Smoke test locally.** With a WebRTC transport builder, `openrtc serve ./agents`
starts pipecat's runner (default `http://localhost:7860`), which serves a browser
test client at that URL. Open it, start a call, and confirm the agent responds and
that OpenRTC emits a session start / end for the call. This live check is the one
step the automated suite cannot cover (the assembly is otherwise verified end to
end in process); everything up to accepting a real transport connection is tested.

## Status and boundaries

The pipecat backend's **per-call path** (registration, routing, shared prewarm,
dispatch, and observability) is complete and verified against real pipecat
pipelines. `AgentPool(backend="pipecat").run()` **serves** calls over a transport
via pipecat's runner (behind `openrtc[pipecat-serve]`): it registers a
per-connection bot that routes the call and runs the observed session, so one
worker serves many calls under OpenRTC's routing, prewarm, and observability. The
one remaining boundary is a genuinely live transport connection (WebRTC / Daily /
telephony), covered by a manual / integration smoke rather than the unit suite,
the same way the livekit backend does not re-test its live network front in
process. The livekit backend is complete and is the default.

Hot reload requires the livekit backend (requesting it on pipecat raises a clear
error). Session introspection is a livekit-backend feature as well; see
[Hot reload](/concepts/hot-reload) and
[Session introspection](/concepts/session-introspection).
