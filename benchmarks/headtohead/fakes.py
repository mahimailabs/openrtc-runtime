"""Local stand-ins for STT/LLM/TTS so the full voice pipeline runs without API keys.

Each fake sleeps to mimic provider network latency and emits real data: STT a
transcript, LLM streamed tokens, TTS 24 kHz PCM audio that gets published to the room.
"""

from __future__ import annotations

import asyncio
import math
import struct
import uuid

from livekit.agents import llm, stt, tts
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

_REPLY = "Sure, I can help you with that. Let me check the details for you right now."
_SR = 24000
# one 440 Hz tone second, int16 mono
_TONE = b"".join(
    struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / _SR)))
    for i in range(_SR)
)


class FakeSTT(stt.STT):
    def __init__(self) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=False, interim_results=False)
        )

    async def _recognize_impl(
        self, buffer, *, language=None, conn_options
    ) -> stt.SpeechEvent:  # type: ignore[override]
        await asyncio.sleep(0.15)
        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[
                stt.SpeechData(
                    language="en", text="hello, can you help me book a table"
                )
            ],
        )


class _FakeLLMStream(llm.LLMStream):
    async def _run(self) -> None:
        await asyncio.sleep(0.3)
        rid = uuid.uuid4().hex
        for word in _REPLY.split():
            self._event_ch.send_nowait(
                llm.ChatChunk(
                    id=rid, delta=llm.ChoiceDelta(role="assistant", content=word + " ")
                )
            )
            await asyncio.sleep(0.01)


class FakeLLM(llm.LLM):
    def chat(
        self,
        *,
        chat_ctx,
        tools=None,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
        **_: object,
    ):  # type: ignore[override]
        return _FakeLLMStream(
            self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options
        )


class _FakeChunked(tts.ChunkedStream):
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(
            request_id=uuid.uuid4().hex,
            sample_rate=_SR,
            num_channels=1,
            mime_type="audio/pcm",
        )
        await asyncio.sleep(0.1)
        seconds = max(1, len(self._input_text) // 15)
        for _ in range(seconds):
            output_emitter.push(_TONE)
            await asyncio.sleep(0)
        output_emitter.flush()


class FakeTTS(tts.TTS):
    def __init__(self) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=_SR,
            num_channels=1,
        )

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ):  # type: ignore[override]
        return _FakeChunked(tts=self, input_text=text, conn_options=conn_options)
