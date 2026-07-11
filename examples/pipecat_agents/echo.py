"""Minimal pipecat agent: echo your audio back (no API keys).

The simplest way to confirm the OpenRTC pipecat serving path works end to end.
OpenRTC discovers this builder, routes a WebRTC call to it, and runs the pipeline,
so you hear yourself echoed. It needs only the WebRTC transport (aiortc); no
STT / LLM / TTS and no API keys.

Run::

    pip install "openrtc[pipecat-serve]" "pipecat-ai[webrtc]"
    openrtc serve ./examples/pipecat_agents

Then open the runner's test client (default http://localhost:7860) and talk. See
../README.md for the full walkthrough.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pipecat.transports.base_transport import TransportParams

from openrtc import agent_config

try:  # the transport module path shifted across pipecat releases
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
except ImportError:
    from pipecat.transports.network.small_webrtc import SmallWebRTCTransport

if TYPE_CHECKING:
    from pipecat.processors.frame_processor import FrameProcessor

    from openrtc.backends.pipecat import PipecatCallView


@agent_config(name="echo")
def echo(view: PipecatCallView) -> list[FrameProcessor]:
    """Loop the caller's audio straight back to them."""
    transport = SmallWebRTCTransport(
        webrtc_connection=view.connection.webrtc_connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    )
    return [transport.input(), transport.output()]
