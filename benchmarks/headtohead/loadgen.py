"""Open N concurrent 'calls': dispatch the bench agent into a room, join as a caller,
and loop real speech into it. Reports agent join latency and whether the agent
actually spoke back (non-silent agent audio received), per room."""

import asyncio
import json
import os
import statistics
import sys
import time
import wave

import numpy as np
from livekit import api, rtc

N = int(sys.argv[1])
HOLD = float(sys.argv[2])
RUN = sys.argv[3]
SPREAD = float(os.environ.get("BENCH_SPREAD", "0.2"))  # seconds between call arrivals
URL = os.environ["LIVEKIT_URL"]

with wave.open(os.path.join(os.path.dirname(__file__), "change-sophie.wav")) as w:
    assert w.getframerate() == 48000
    assert w.getnchannels() == 1
    CLIP = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
FRAME = 480  # 10 ms at 48 kHz
SILENCE = np.zeros(FRAME, dtype=np.int16)


async def push(src: rtc.AudioSource, samples: np.ndarray) -> None:
    for off in range(0, len(samples) - FRAME, FRAME):
        chunk = samples[off : off + FRAME]
        await src.capture_frame(rtc.AudioFrame(chunk.tobytes(), 48000, 1, FRAME))


async def caller(i: int, lkapi: api.LiveKitAPI) -> dict:
    await asyncio.sleep(i * SPREAD)
    name = f"{RUN}-{i}"
    r = {"room": name, "join_s": None, "agent_audio_s": 0.0}
    t0 = time.perf_counter()
    await lkapi.agent_dispatch.create_dispatch(
        api.CreateAgentDispatchRequest(agent_name="bench", room=name)
    )
    token = (
        api.AccessToken()
        .with_identity(f"caller-{i}")
        .with_grants(api.VideoGrants(room_join=True, room=name))
        .to_jwt()
    )
    room = rtc.Room()
    tasks: list[asyncio.Task] = []

    def saw(p: rtc.RemoteParticipant) -> None:
        if p.kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT and r["join_s"] is None:
            r["join_s"] = round(time.perf_counter() - t0, 3)

    async def listen(track: rtc.Track) -> None:
        async for ev in rtc.AudioStream(track):
            f = ev.frame
            if np.abs(np.frombuffer(f.data, dtype=np.int16)).mean() > 200:
                r["agent_audio_s"] += f.samples_per_channel / f.sample_rate

    room.on("participant_connected", saw)
    room.on(
        "track_subscribed",
        lambda t, _pub, _p: (
            t.kind == rtc.TrackKind.KIND_AUDIO
            and tasks.append(asyncio.create_task(listen(t)))
        ),
    )
    await room.connect(URL, token)
    for p in room.remote_participants.values():
        saw(p)
    src = rtc.AudioSource(48000, 1)
    track = rtc.LocalAudioTrack.create_audio_track("mic", src)
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )
    end = time.perf_counter() + HOLD
    while time.perf_counter() < end:
        await push(src, CLIP)  # ~6 s of speech
        await push(
            src, np.zeros(48000 * 5, dtype=np.int16)
        )  # 5 s silence: agent replies
    for t in tasks:
        t.cancel()
    await room.disconnect()
    await lkapi.room.delete_room(api.DeleteRoomRequest(room=name))
    r["agent_audio_s"] = round(r["agent_audio_s"], 1)
    return r


async def main() -> None:
    lkapi = api.LiveKitAPI()
    results = await asyncio.gather(
        *(caller(i, lkapi) for i in range(N)), return_exceptions=True
    )
    await lkapi.aclose()
    ok = [r for r in results if isinstance(r, dict)]
    joins = sorted(r["join_s"] for r in ok if r["join_s"] is not None)
    spoke = [r for r in ok if r["agent_audio_s"] > 0]
    summary = {
        "calls": N,
        "errors": [repr(r) for r in results if not isinstance(r, dict)][:3],
        "agent_joined": len(joins),
        "join_p50_s": round(statistics.median(joins), 3) if joins else None,
        "join_max_s": joins[-1] if joins else None,
        "agent_spoke": len(spoke),
        "agent_audio_s_mean": round(statistics.mean(r["agent_audio_s"] for r in ok), 1)
        if ok
        else 0,
    }
    print(json.dumps(summary))


asyncio.run(main())
