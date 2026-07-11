"""A pipecat voice assistant (OpenAI STT / LLM / TTS + OpenRTC shared prewarm).

The realistic pipecat example. The builder owns the transport and the services;
OpenRTC supplies routing, observability, and the shared VAD (``view.prewarmed.vad``,
loaded once per worker and reused across every call, the density win). The caller
speaks first and the assistant replies.

Run::

    pip install "openrtc[pipecat-serve]" "pipecat-ai[webrtc,openai,silero]"
    export OPENAI_API_KEY=...
    openrtc serve ./examples/pipecat_agents

Then open the runner's test client (default http://localhost:7860) and talk. See
../README.md for the full walkthrough.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.transports.base_transport import TransportParams

from openrtc import agent_config

try:  # the transport module path shifted across pipecat releases
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
except ImportError:
    from pipecat.transports.network.small_webrtc import SmallWebRTCTransport

if TYPE_CHECKING:
    from pipecat.processors.frame_processor import FrameProcessor

    from openrtc.backends.pipecat import PipecatCallView

_SYSTEM_PROMPT = (
    "You are a friendly voice assistant. Keep replies short and conversational, "
    "and avoid special characters since your reply is spoken aloud."
)


@agent_config(name="assistant")
def assistant(view: PipecatCallView) -> list[FrameProcessor]:
    """Build a spoken assistant: transport in, STT, LLM, TTS, transport out."""
    transport = SmallWebRTCTransport(
        webrtc_connection=view.connection.webrtc_connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    )
    # Services read OPENAI_API_KEY from the environment.
    stt = OpenAISTTService(model="gpt-4o-mini-transcribe")
    llm = OpenAILLMService(model="gpt-4.1-mini")
    tts = OpenAITTSService(model="gpt-4o-mini-tts", voice="alloy")

    # The shared VAD comes from OpenRTC's prewarm (loaded once, reused per call).
    context = LLMContext(messages=[{"role": "system", "content": _SYSTEM_PROMPT}])
    aggregators = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=view.prewarmed.vad),
    )
    return [
        transport.input(),
        stt,
        aggregators.user(),
        llm,
        tts,
        transport.output(),
        aggregators.assistant(),
    ]
