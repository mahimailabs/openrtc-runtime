"""Shared type aliases for voice pipeline provider slots (STT, LLM, TTS)."""

from __future__ import annotations

from typing import TypeAlias

# Values accepted for STT, LLM, and TTS configuration:
# - Provider ID strings (e.g. ``"openai/gpt-4o-mini-transcribe"``) used by LiveKit
#   routing and the OpenRTC CLI defaults.
# - Concrete LiveKit plugin instances (e.g. ``livekit.plugins.openai.STT(...)``).
# ``object`` allows any third-party plugin class without enumerating them here;
# use strings when you want the type checker to stay precise.
ProviderValue: TypeAlias = str | object
