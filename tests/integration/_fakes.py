"""Hermetic fake STT/LLM/TTS provider stubs for integration tests.

These satisfy the livekit ``AgentSession`` provider interfaces without any
network calls or API keys, so a provider-agnostic integration test can run on
every PR (including fork PRs where no secrets are exposed).

The agents that use these never speak and receive no audio, so the generation
methods are never invoked. They raise if called, so a future test that does
rely on them fails loudly rather than silently producing nothing.
"""

from __future__ import annotations

from typing import Any

from livekit.agents import llm, stt, tts


class FakeSTT(stt.STT):
    """Non-streaming STT that never transcribes (the test sends no audio)."""

    def __init__(self) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=False, interim_results=False)
        )

    async def _recognize_impl(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(
            "FakeSTT does not transcribe; the integration test sends no audio."
        )


class FakeLLM(llm.LLM):
    """LLM that never generates (the test agents do not speak)."""

    def chat(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(
            "FakeLLM does not generate; the integration test agents do not speak."
        )


class FakeTTS(tts.TTS):
    """Non-streaming TTS that never synthesizes (the test agents do not speak)."""

    def __init__(self) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=24000,
            num_channels=1,
        )

    def synthesize(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(
            "FakeTTS does not synthesize; the integration test agents do not speak."
        )
