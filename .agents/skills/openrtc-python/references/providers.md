# Provider string reference

OpenRTC passes provider strings through to `livekit-agents`. Use the format
`provider/model` or `provider/model:variant`.

## STT (Speech-to-Text)

| String | Provider |
|---|---|
| `deepgram/nova-3` | Deepgram Nova 3 |
| `deepgram/nova-3:multi` | Deepgram Nova 3 multilingual |
| `assemblyai/...` | AssemblyAI |
| `google/...` | Google Cloud STT |

## LLM (Large Language Model)

| String | Provider |
|---|---|
| `openai/gpt-4.1-mini` | OpenAI GPT-4.1 Mini |
| `openai/gpt-4.1` | OpenAI GPT-4.1 |
| `groq/llama-4-scout` | Groq Llama 4 Scout |
| `anthropic/claude-sonnet-4-20250514` | Anthropic Claude Sonnet 4 |

## TTS (Text-to-Speech)

| String | Provider |
|---|---|
| `cartesia/sonic-3` | Cartesia Sonic 3 |
| `elevenlabs/...` | ElevenLabs |
| `openai/tts-1` | OpenAI TTS-1 |

## Using provider objects

For advanced configuration (custom parameters, non-default endpoints), pass
provider instances instead of strings:

```python
from livekit.plugins import openai

stt = openai.STT(model="gpt-4o-mini-transcribe")
llm = openai.responses.LLM(model="gpt-4.1-mini")
tts = openai.TTS(model="gpt-4o-mini-tts")
```

Provider objects must be pickleable. OpenRTC has built-in serialization support
for `livekit.plugins.openai` STT, TTS, and LLM types. Other provider objects
must be natively pickleable or you should use string identifiers instead.

## Environment variables

Each provider requires its own API key:

| Provider | Environment variable |
|---|---|
| Deepgram | `DEEPGRAM_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Cartesia | `CARTESIA_API_KEY` |
| Groq | `GROQ_API_KEY` |
| ElevenLabs | `ELEVENLABS_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| AssemblyAI | `ASSEMBLYAI_API_KEY` |

Only set the keys for providers your agents actually use.
