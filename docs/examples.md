---
title: Examples
description: Multi-agent example showing how to register, route, and run two agents in one OpenRTC worker.
icon: play
---

# Examples

The `examples/` directory contains a multi-agent setup that runs two specialized
agents in a single `AgentPool`. Both share the same worker process and prewarmed
runtime resources (VAD, turn detector).

## Multi-agent worker

`examples/main.py` registers two agents (`restaurant` and `dental`) with per-agent
instructions and tools:

```python
from livekit.agents import Agent, function_tool
from livekit.plugins import openai
from openrtc import AgentPool


class RestaurantAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are a helpful restaurant reservation assistant. "
                "Use the tools to check availability, make reservations, and describe the menu."
            )
        )

    @function_tool
    async def check_availability(self, date: str, party_size: int) -> str:
        """Check table availability for a given date and party size."""
        return f"Tables are available for {party_size} on {date}."

    @function_tool
    async def make_reservation(self, name: str, date: str, party_size: int) -> str:
        """Make a reservation."""
        return f"Reservation confirmed for {name}, party of {party_size} on {date}."


class DentalAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are a helpful dental office assistant. "
                "Use the tools to schedule appointments and share pre-visit information."
            )
        )

    @function_tool
    async def schedule_cleaning(self, name: str, date: str) -> str:
        """Schedule a dental cleaning appointment."""
        return f"Cleaning appointment confirmed for {name} on {date}."

    @function_tool
    async def pre_visit_instructions(self) -> str:
        """Provide pre-visit instructions."""
        return "Brush and floss before your appointment. Arrive 10 minutes early."


pool = AgentPool(
    default_stt=openai.STT(model="gpt-4o-mini-transcribe"),
    default_llm=openai.responses.LLM(model="gpt-4.1-mini"),
    default_tts=openai.TTS(model="gpt-4o-mini-tts"),
)
pool.add("restaurant", RestaurantAgent, greeting="Welcome to our restaurant. How can I help?")
pool.add("dental", DentalAgent)

pool.run()
```

## Routing between agents

With both agents registered, OpenRTC routes each call by room or job metadata.

Route by job metadata (pass as JSON string when dispatching):

```json
{"agent": "restaurant"}
```

Route by room name prefix (no metadata needed):

```
dental-call-123   ->  DentalAgent
restaurant-room-1 ->  RestaurantAgent
```

See [Routing](/concepts/routing) for the full priority chain.

## Running the example

```bash
# Install with CLI extra for openrtc dev
uv add "openrtc[cli]"

# Set LiveKit credentials
export LIVEKIT_URL=ws://localhost:7880
export LIVEKIT_API_KEY=devkey
export LIVEKIT_API_SECRET=secret

# Run the worker
openrtc dev examples/main.py
```

Or run in discovery mode if each agent lives in its own file under `examples/agents/`:

```bash
openrtc dev ./examples/agents \
  --default-stt openai/gpt-4o-mini-transcribe \
  --default-llm openai/gpt-4.1-mini \
  --default-tts openai/gpt-4o-mini-tts
```

## What the example demonstrates

- Two `livekit.agents.Agent` subclasses registered in one `AgentPool`: no OpenRTC base class required.
- Shared prewarm: VAD and turn detector load once for both agents.
- Routing by room prefix (`restaurant-*`, `dental-*`) or metadata key (`{"agent": "dental"}`).
- Per-agent greeting: only `RestaurantAgent` sends a greeting on connect.
- Tool calls: each agent exposes function tools relevant to its domain.
