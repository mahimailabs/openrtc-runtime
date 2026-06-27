# OpenRTC architecture: with vs without OpenRTC

How a livekit-agents voice agent runs **on its own** (stock process-per-job) versus
**with OpenRTC** added (coroutine / density mode): how connections are passed, how
work is parallelized, and the start-to-end lifecycle of one call.

> Diagrams are grounded in the actual source (livekit-agents 1.6.2 in `.venv` and
> `src/openrtc`) and were adversarially checked against it. Each is embedded as
> Mermaid (renders on GitHub / VS Code) with rendered `.svg` and `.png` alongside.

The cast of connections is the same in both worlds; only the *runtime unit* changes:

| Connection | Transport | Carries |
| --- | --- | --- |
| Worker to LiveKit server | WebSocket (protobuf) | registration, job availability/assignment, status |
| Worker to job runtime | Unix socketpair (vanilla) / in-process call (OpenRTC) | start/shutdown signals |
| Job to room | WebRTC (DTLS/SRTP) | audio media |
| Plugins to STT/LLM/TTS | HTTP (shared aiohttp session) | provider API calls |

The one provider that bites in density mode (Cartesia TTS) uses that last HTTP path,
which is why the per-job http context matters: see `03` below.

---

## 1. Without OpenRTC: process-per-job

Stock livekit-agents. The worker holds one WebSocket to the LiveKit server and, for
**each** job, hands off to a **dedicated OS subprocess** from a warm pool. Every
subprocess independently loads its own VAD + turn-detector weights, opens its own
WebRTC peer and its own aiohttp session, and runs the STT to LLM to TTS pipeline as
concurrent asyncio tasks inside that one process. N concurrent calls means N
subprocesses, each ~3 GB (per the audit), sharing nothing.

### Lifecycle of one call

```mermaid
sequenceDiagram
    participant LK as LiveKit SFU
    participant W as AgentServer<br>main process
    participant PP as ProcPool
    participant SUB as Job Subprocess<br>_JobProc
    participant ROOM as rtc.Room<br>WebRTC peer
    participant PROV as STT LLM TTS<br>provider APIs

    W->>LK: WorkerMessage register<br>WebSocket
    LK->>W: RegisterWorkerResponse worker_id<br>WebSocket
    W->>PP: ProcPool.start
    PP->>SUB: spawn warm subprocess<br>in-process
    SUB->>SUB: prewarm_fnc loads VAD<br>and turn detector

    LK->>W: ServerMessage availability<br>WebSocket
    W->>LK: WorkerMessage available True<br>WebSocket
    LK->>W: ServerMessage assignment room and token<br>WebSocket

    W->>PP: launch_job
    PP->>SUB: StartJobRequest<br>Unix socketpair
    SUB->>SUB: create rtc.Room<br>set JobContextVar<br>open http_context

    SUB->>ROOM: ctx.connect room URL and token
    ROOM->>LK: WebRTC DTLS SRTP join<br>WebRTC

    loop STT to LLM to TTS pipeline
        ROOM->>SUB: participant audio track<br>WebRTC
        SUB->>PROV: STT streaming audio<br>HTTP
        PROV->>SUB: transcript text<br>HTTP
        SUB->>PROV: LLM chat completion<br>HTTP
        PROV->>SUB: response tokens<br>HTTP
        SUB->>PROV: TTS synthesis<br>HTTP
        PROV->>SUB: audio frames<br>HTTP
        SUB->>ROOM: publish agent audio<br>WebRTC
        ROOM->>LK: outbound media<br>WebRTC
    end

    LK->>ROOM: room disconnect signal<br>WebRTC
    ROOM->>SUB: shutdown triggered
    SUB->>SUB: session.aclose 60s timeout
    SUB->>SUB: session_end_fnc
    SUB->>SUB: http_context close<br>JobContextVar reset
    SUB->>W: ShuttingDown then Exiting<br>Unix socketpair
    W->>LK: WorkerMessage update_job SUCCESS<br>WebSocket
    PP->>SUB: spawn fresh warm subprocess
```

### Parallelization / topology (3 concurrent calls)

```mermaid
flowchart TB
    LK["LiveKit SFU"]
    PROV["STT LLM TTS provider APIs<br>OpenAI Deepgram etc"]
    W["AgentServer main process<br>single WebSocket to LK"]

    LK -- "WebSocket signaling" --> W

    subgraph SHARED ["SHARED main process only"]
        W
        PP["ProcPool<br>idle subprocess queue"]
        W --> PP
    end

    subgraph SUB1 ["Subprocess 1 approx 3 GB RAM"]
        direction TB
        VAD1["Silero VAD model<br>DUPLICATED"]
        TD1["Turn detector weights<br>DUPLICATED"]
        HEAP1["Python interpreter and SDK<br>DUPLICATED"]
        HTTP1["aiohttp ClientSession<br>DUPLICATED"]
        LOOP1["asyncio event loop<br>DUPLICATED"]
        JOB1["Job 1<br>rtc.Room and AgentSession<br>STT LLM TTS tasks"]
        VAD1 --- JOB1
        TD1 --- JOB1
        HEAP1 --- JOB1
        HTTP1 --- JOB1
        LOOP1 --- JOB1
    end

    subgraph SUB2 ["Subprocess 2 approx 3 GB RAM"]
        direction TB
        VAD2["Silero VAD model<br>DUPLICATED"]
        TD2["Turn detector weights<br>DUPLICATED"]
        HEAP2["Python interpreter and SDK<br>DUPLICATED"]
        HTTP2["aiohttp ClientSession<br>DUPLICATED"]
        LOOP2["asyncio event loop<br>DUPLICATED"]
        JOB2["Job 2<br>rtc.Room and AgentSession<br>STT LLM TTS tasks"]
        VAD2 --- JOB2
        TD2 --- JOB2
        HEAP2 --- JOB2
        HTTP2 --- JOB2
        LOOP2 --- JOB2
    end

    subgraph SUB3 ["Subprocess 3 approx 3 GB RAM"]
        direction TB
        VAD3["Silero VAD model<br>DUPLICATED"]
        TD3["Turn detector weights<br>DUPLICATED"]
        HEAP3["Python interpreter and SDK<br>DUPLICATED"]
        HTTP3["aiohttp ClientSession<br>DUPLICATED"]
        LOOP3["asyncio event loop<br>DUPLICATED"]
        JOB3["Job 3<br>rtc.Room and AgentSession<br>STT LLM TTS tasks"]
        VAD3 --- JOB3
        TD3 --- JOB3
        HEAP3 --- JOB3
        HTTP3 --- JOB3
        LOOP3 --- JOB3
    end

    PP -- "StartJobRequest<br>Unix socketpair" --> SUB1
    PP -- "StartJobRequest<br>Unix socketpair" --> SUB2
    PP -- "StartJobRequest<br>Unix socketpair" --> SUB3

    JOB1 -- "WebRTC media" --> LK
    JOB2 -- "WebRTC media" --> LK
    JOB3 -- "WebRTC media" --> LK
    JOB1 -- "HTTP" --> PROV
    JOB2 -- "HTTP" --> PROV
    JOB3 -- "HTTP" --> PROV

    NOTE["N calls equals N subprocesses<br>Each approx 3 GB RAM<br>Total approx N times 3 GB<br>Nothing shared across subprocesses"]
    style NOTE fill:#fef3c7,stroke:#d97706,color:#000
```

Note the HTTP edges go to the **external provider APIs** (OpenAI, Deepgram, Cartesia),
not to the LiveKit SFU; only WebRTC media goes to LiveKit.

---

## 2. With OpenRTC: coroutine / density mode

OpenRTC monkey-patches livekit's private `ipc.proc_pool.ProcPool` with a
`CoroutinePool`. There is now **one** long-lived worker process. Each incoming job
becomes an **asyncio task** in the shared event loop (a `CoroutineJobExecutor`) instead
of a subprocess. The VAD and turn detector are prewarmed **once** into the singleton
`JobProcess.userdata` and shared by every session. Each task still sets its own
`JobContextVar`, opens its **own per-job http context** (the in-flight fix), runs the
routing chain to pick the user's `Agent` subclass, and builds an `AgentSession` that
pulls the shared prewarmed VAD. Per-session cost drops to ~50-65 MB, so a single worker
targets 50+ sessions instead of ~1.

### Lifecycle of one call

```mermaid
sequenceDiagram
    participant LK as LiveKit Cloud
    participant WS as AgentServer WS loop
    participant CP as CoroutinePool
    participant EX as CoroutineJobExecutor
    participant RS as run_session
    participant Room as rtc.Room WebRTC
    participant Prov as STT LLM TTS

    Note over WS: Worker registers via WebSocket
    WS->>LK: WorkerMessage register
    LK-->>WS: ServerMessage job available
    WS->>LK: WorkerMessage accept
    LK-->>WS: ServerMessage job assigned

    WS->>CP: launch_job info in-process
    CP->>EX: create CoroutineJobExecutor in-process
    CP->>EX: launch_job info in-process
    EX->>EX: loop create_task run_entrypoint

    Note over EX: asyncio Task starts
    EX->>EX: JobContextVar set ctx
    EX->>EX: open per-job http_context (the fix)
    EX->>RS: await entrypoint_fnc ctx in-process

    RS->>RS: routing chain resolves AgentConfig
    RS->>RS: read shared VAD from proc userdata
    RS->>RS: build AgentSession stt llm tts vad
    RS->>Room: session start agent room WebRTC
    RS->>Room: ctx connect WebRTC
    Room-->>RS: room connected WebRTC

    Note over RS,Prov: Live voice loop
    Room->>RS: user audio frames WebRTC
    RS->>Prov: STT transcribe HTTP WebSocket
    Prov-->>RS: transcript HTTP WebSocket
    RS->>Prov: LLM completion HTTP WebSocket
    Prov-->>RS: reply text HTTP WebSocket
    RS->>Prov: TTS synthesize HTTP WebSocket
    Prov-->>RS: audio bytes HTTP WebSocket
    RS->>Room: synthesized audio frames WebRTC

    Note over EX: User disconnects
    Room->>EX: room disconnected event in-process
    EX->>EX: shutdown_fut resolved in-process
    EX->>RS: await teardown in-process
    RS->>RS: primary aclose max 60s in-process
    RS->>RS: on_session_end callbacks in-process
    EX->>EX: close per-job http_context
    EX->>EX: JobContextVar reset in-process
    EX->>CP: done callback on_executor_done
    CP->>CP: remove executor emit process_closed
    WS->>LK: WorkerMessage status update
```

The `open per-job http_context` step is the fix we are implementing: coroutine mode
mirrors livekit's `_JobContextVar` set/reset but currently skips the http context that
plugins like Cartesia TTS resolve lazily, which is the `Attempted to use an http session
outside of a job context` error.

### Parallelization / topology (3 concurrent calls)

```mermaid
flowchart TB
    LK["LiveKit Cloud"]

    subgraph worker["ONE OS Process one event loop one heap"]
        direction TB

        subgraph shared["SHARED across all sessions"]
            direction LR
            WS_LOOP["AgentServer<br>Worker WS loop"]
            CP["CoroutinePool<br>ProcPool replacement"]
            PROC["Singleton JobProcess<br>shared_proc"]
            VAD["Silero VAD<br>loaded once"]
            TURN["MultilingualModel<br>turn detector once"]
            METRICS["RuntimeMetricsStore<br>shared"]
            PROC --> VAD
            PROC --> TURN
        end

        subgraph task1["asyncio Task Session 1 ~50-65 MB"]
            direction TB
            EX1["CoroutineJobExecutor 1"]
            CTX1["JobContext 1"]
            SESS1["AgentSession 1<br>STT LLM TTS state"]
            ROOM1["rtc.Room 1<br>WebRTC peer"]
            EX1 --> CTX1 --> SESS1 --> ROOM1
        end

        subgraph task2["asyncio Task Session 2 ~50-65 MB"]
            direction TB
            EX2["CoroutineJobExecutor 2"]
            CTX2["JobContext 2"]
            SESS2["AgentSession 2<br>STT LLM TTS state"]
            ROOM2["rtc.Room 2<br>WebRTC peer"]
            EX2 --> CTX2 --> SESS2 --> ROOM2
        end

        subgraph task3["asyncio Task Session 3 ~50-65 MB"]
            direction TB
            EX3["CoroutineJobExecutor 3"]
            CTX3["JobContext 3"]
            SESS3["AgentSession 3<br>STT LLM TTS state"]
            ROOM3["rtc.Room 3<br>WebRTC peer"]
            EX3 --> CTX3 --> SESS3 --> ROOM3
        end

        WS_LOOP -->|"launch_job in-process"| CP
        CP -->|"create executor in-process"| EX1
        CP -->|"create executor in-process"| EX2
        CP -->|"create executor in-process"| EX3

        PROC -.->|"vad shared in-process"| CTX1
        PROC -.->|"vad shared in-process"| CTX2
        PROC -.->|"vad shared in-process"| CTX3
        PROC -.->|"turn detector shared"| CTX1
    end

    LK -->|"job dispatch WebSocket"| WS_LOOP
    WS_LOOP -->|"heartbeat WebSocket"| LK

    PROV["STT LLM TTS<br>provider APIs"]
    ROOM1 -->|"WebRTC"| LK
    ROOM2 -->|"WebRTC"| LK
    ROOM3 -->|"WebRTC"| LK
    SESS1 -->|"HTTP WebSocket"| PROV
    SESS2 -->|"HTTP WebSocket"| PROV
    SESS3 -->|"HTTP WebSocket"| PROV

    NOTE["Models paid ONCE per worker<br>vs once per process in vanilla<br>Target 50 sessions per worker<br>Vanilla 1 session at ~3 GB each"]
    style NOTE fill:#fffbcc,stroke:#ccc,color:#333
```

`CoroutinePool` (the `ProcPool` drop-in) owns `max_concurrent_sessions` backpressure and
the consecutive-failure supervisor; it allocates one executor per job. The prewarmed VAD
and MultilingualModel turn detector are read in-process from `shared_proc` by every
session.

---

## 3. Side by side

### What is duplicated vs shared

```mermaid
flowchart LR
  subgraph vanilla["Without OpenRTC"]
    direction TB
    W1["Worker Process<br>WebSocket to LiveKit"]
    subgraph proc1["OS Process - Call 1"]
      direction TB
      I1["Python interpreter"]
      VAD1["Silero VAD weights"]
      TD1["Turn detector weights"]
      SDK1["livekit-agents SDK"]
      R1["rtc.Room WebRTC peer"]
      S1["AgentSession state"]
    end
    subgraph proc2["OS Process - Call 2"]
      direction TB
      I2["Python interpreter"]
      VAD2["Silero VAD weights"]
      TD2["Turn detector weights"]
      SDK2["livekit-agents SDK"]
      R2["rtc.Room WebRTC peer"]
      S2["AgentSession state"]
    end
    subgraph procN["OS Process - Call N"]
      direction TB
      IN["Python interpreter"]
      VADN["Silero VAD weights"]
      TDN["Turn detector weights"]
      SDKN["livekit-agents SDK"]
      RN["rtc.Room WebRTC peer"]
      SN["AgentSession state"]
    end
    W1 -->|"spawn"| proc1
    W1 -->|"spawn"| proc2
    W1 -->|"spawn"| procN
    proc1 -->|"WebRTC"| LiveKit1(["LiveKit Cloud"])
    proc2 -->|"WebRTC"| LiveKit1
    procN -->|"WebRTC"| LiveKit1
  end

  subgraph openrtc["With OpenRTC"]
    direction TB
    W2["Worker Process<br>WebSocket to LiveKit"]
    subgraph singleproc["Single OS Process - shared heap"]
      direction TB
      SVAD["Silero VAD loaded once"]
      STD["Turn detector loaded once"]
      subgraph task1["asyncio.Task - Call 1"]
        R21["rtc.Room WebRTC peer"]
        AS1["AgentSession state"]
      end
      subgraph task2["asyncio.Task - Call 2"]
        R22["rtc.Room WebRTC peer"]
        AS2["AgentSession state"]
      end
      subgraph taskN["asyncio.Task - Call 50"]
        R2N["rtc.Room WebRTC peer"]
        ASN["AgentSession state"]
      end
    end
    W2 -->|"in-process"| singleproc
    task1 -->|"WebRTC"| LiveKit2(["LiveKit Cloud"])
    task2 -->|"WebRTC"| LiveKit2
    taskN -->|"WebRTC"| LiveKit2
  end
```

### Memory / scaling at N concurrent calls

```mermaid
flowchart TB
  subgraph legend["Memory at N concurrent calls"]
    direction TB
    subgraph baseline_proc["Vanilla livekit-agents"]
      direction TB
      F1["N x ~3 GB per OS process"]
      F2["Models duplicated N times"]
      F3["10 calls ~30 GB RAM"]
      F4["50 calls ~150 GB RAM"]
      F1 --> F2 --> F3 --> F4
    end
    subgraph baseline_rtc["OpenRTC coroutine mode"]
      direction TB
      G1["Shared base once per worker"]
      G2["VAD plus turn detector paid once"]
      G3["Per session 50-65 MB total"]
      G4["50 calls target 60 MB each"]
      G5["50 calls roughly 3 GB worker"]
      G1 --> G2 --> G3 --> G4 --> G5
    end
  end
  baseline_proc -->|"30-50x more RAM"| baseline_rtc
```

---

## The change in one breath

- **Runtime unit:** OS subprocess per job  ->  asyncio task per job (one process).
- **Models:** loaded once per process  ->  prewarmed once per worker, shared.
- **Memory:** ~3 GB x N  ->  shared baseline + ~50-65 MB x N.
- **Density:** ~1 session per process  ->  50+ sessions per worker.
- **Unchanged:** the connection cast (WebSocket signaling, WebRTC media, HTTP to
  providers) and the user's `Agent` subclass. OpenRTC swaps the *executor*, not the API.
