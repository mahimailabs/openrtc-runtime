# OpenRTC Frontend Example

Simple React Router demo for the two example agents hosted by the same OpenRTC
worker:

- `/dentist` starts the `dental` agent
- `/restaurant` starts the `restaurant` agent

## Environment

Set the same LiveKit connection values used by the Python worker:

```bash
export LIVEKIT_URL=ws://localhost:7880
export LIVEKIT_API_KEY=devkey
export LIVEKIT_API_SECRET=secret
```

The frontend server uses these values to:

1. create a room with room metadata such as `{"agent":"dental"}`
2. issue a participant token for the browser

## Run the demo

Start the OpenRTC worker from the repository root:

```bash
cd examples
../.venv/bin/python main.py dev
```

Then start the frontend:

```bash
cd examples/frontend
npm install
npm run dev
```

Open `http://localhost:5173` and choose either the dentist or restaurant demo.

## Dispatch behavior

The frontend token route creates a unique room for each call and sets room
metadata to the selected agent name. The Python `AgentPool` reads that metadata
and dispatches the correct agent inside the shared worker.
