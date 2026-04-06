# Task: Implement `livekit-plugins-hf` — Local HuggingFace LLM Plugin

## Background

[OpenRTC](https://github.com/mahimairaja/openrtc-python) is a multi-agent voice
pipeline built on LiveKit Agents SDK. It pools multiple voice agents in a single
worker process, sharing expensive resources (VAD, turn detector) to reduce memory
overhead. Today, all LLM providers are cloud APIs (OpenAI, Groq, Anthropic).

We need a new LiveKit Agents SDK plugin — `livekit-plugins-hf` — that runs
HuggingFace transformer models **locally on GPU**, with optional
[TurboQuant-GPU](https://github.com/mahimairaja/turboquant-gpu) KV cache
compression for ~5x memory reduction per concurrent session.

### Why This Matters

- Eliminates per-token API costs for high-volume deployments
- Keeps data on-prem for privacy-sensitive use cases
- With TurboQuant-GPU: a 24GB GPU can serve ~31 concurrent 7B-model sessions
  instead of ~6 (5x KV cache compression via 2-3 bit Lloyd-Max quantization)

---

## Validated Interface Contract

We have already audited the LiveKit Agents SDK `LLM` base class. Here is the
interface your plugin must conform to:

### `LLM` Base Class

```python
from livekit.agents import llm

class LLM(llm.LLM):
    """Subclass this. It's stateless — one instance can serve concurrent chat() calls."""

    @abstractmethod
    def chat(
        self,
        *,
        chat_ctx: ChatContext,           # Conversation history
        tools: list[Tool] | None = None, # Available function tools
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[ToolChoice] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
    ) -> LLMStream:
        """Return an LLMStream. Each call creates an independent stream."""
        ...

    def prewarm(self) -> None:
        """Called once to pre-load resources. Load model weights here."""
        pass
```

### `LLMStream` Base Class

```python
class LLMStream(llm.LLMStream):
    """Subclass this. Implement _run() to generate tokens."""

    @abstractmethod
    async def _run(self) -> None:
        """
        Generate tokens and push them to self._event_ch.

        Push ChatChunk objects for each token:
            self._event_ch.send_nowait(ChatChunk(
                id="request-id",
                delta=ChoiceDelta(role="assistant", content="token_text"),
            ))

        Push tool calls when the model invokes a tool:
            self._event_ch.send_nowait(ChatChunk(
                id="request-id",
                delta=ChoiceDelta(tool_calls=[FunctionToolCall(
                    type="function",
                    name="tool_name",
                    arguments='{"arg": "value"}',
                    call_id="call_123",
                )]),
            ))

        Push usage stats in the final chunk:
            self._event_ch.send_nowait(ChatChunk(
                id="request-id",
                usage=CompletionUsage(
                    completion_tokens=50,
                    prompt_tokens=100,
                    total_tokens=150,
                ),
            ))
        """
        ...
```

### Key Data Types

```python
from livekit.agents.llm import (
    ChatChunk,
    ChoiceDelta,
    CompletionUsage,
    FunctionToolCall,
    ChatContext,    # Contains .items: list[ChatItem] — messages, tool calls, tool outputs
    ChatRole,      # "system" | "developer" | "user" | "assistant"
    Tool,          # Function tool definitions
)
```

---

## What You Need to Explore in This Repo

Before implementing, study these patterns in the LiveKit Agents codebase:

1. **Existing plugin structure** — Look at `livekit-plugins-openai/` for:
   - File layout: `livekit/plugins/{name}/__init__.py`, `llm.py`, etc.
   - How `__init__.py` exports the public API
   - How `pyproject.toml` declares dependencies and entry points

2. **ChatContext → model input conversion** — In the OpenAI plugin:
   - How `ChatContext.items` (ChatMessage, FunctionCall, FunctionCallOutput) are
     mapped to the provider's message format
   - How system/user/assistant roles are handled
   - How multi-turn conversation history is serialized

3. **Tool calling serialization** — How existing plugins:
   - Convert `tools: list[Tool]` to the model's function-calling schema
   - Parse the model's tool call responses back into `FunctionToolCall` objects
   - Handle `tool_choice` and `parallel_tool_calls`

4. **Event channel pattern** — Check whether plugins use:
   - `self._event_ch.send_nowait(chunk)` (non-blocking)
   - `await self._event_ch.send(chunk)` (blocking)
   - Any batching or buffering patterns

5. **Usage/metrics reporting** — How existing plugins:
   - Calculate and report `CompletionUsage`
   - Handle the `metrics_collected` event

---

## Implementation Guide

### Package Structure

```
livekit-plugins-hf/
├── pyproject.toml
├── README.md
└── livekit/
    └── plugins/
        └── hf/
            ├── __init__.py     # Public API exports
            ├── llm.py          # LLM and HFLLMStream classes
            └── _opts.py        # Options dataclass (for OpenRTC serialization compat)
```

### Core Classes

#### `_opts.py`

```python
@dataclass(frozen=True)
class HFLLMOptions:
    model: str                          # HuggingFace model ID
    device: str = "cuda"                # torch device
    dtype: str = "float16"              # torch dtype
    max_new_tokens: int = 512           # generation limit
    temperature: float = 0.7
    top_p: float = 0.9
    turboquant_enabled: bool = False    # optional TurboQuant-GPU
    turboquant_bits: int = 3            # 2 or 3 bit quantization
```

**Important**: The `_opts` attribute pattern is required for compatibility with
OpenRTC's provider serialization system. OpenRTC's `_serialize_provider_value()`
detects `livekit.plugins.*` classes with `_opts` and extracts constructor kwargs
from it for cross-process pickling.

#### `llm.py`

```python
class LLM(llm.LLM):
    def __init__(self, *, model: str, device: str = "cuda", turboquant: bool = False, **kwargs):
        super().__init__()
        self._opts = HFLLMOptions(model=model, device=device, turboquant_enabled=turboquant, **kwargs)
        self._model = None       # loaded lazily or in prewarm()
        self._tokenizer = None

    def prewarm(self) -> None:
        # Load model weights once — shared across all concurrent chat() calls
        self._tokenizer = AutoTokenizer.from_pretrained(self._opts.model)
        self._model = AutoModelForCausalLM.from_pretrained(
            self._opts.model,
            torch_dtype=getattr(torch, self._opts.dtype),
            device_map=self._opts.device,
        )
        if self._opts.turboquant_enabled:
            from turboquant_gpu import TurboQuantEngine
            self._tq_engine = TurboQuantEngine(
                head_dim=self._model.config.head_dim,
                total_bits=self._opts.turboquant_bits,
                device=self._opts.device,
            )
            self._tq_engine.auto_tune(seq_len=2048)

    def chat(self, *, chat_ctx, tools=None, **kwargs) -> "HFLLMStream":
        return HFLLMStream(
            llm=self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=kwargs.get("conn_options", DEFAULT_API_CONNECT_OPTIONS),
        )
```

#### `HFLLMStream._run()`

The generation loop — this is the core:

```python
async def _run(self) -> None:
    # 1. Convert ChatContext to token IDs
    messages = self._convert_chat_ctx(self._chat_ctx)
    input_ids = self._llm._tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt"
    ).to(self._llm._opts.device)

    # 2. Stream tokens using TextIteratorStreamer
    from transformers import TextIteratorStreamer
    streamer = TextIteratorStreamer(self._llm._tokenizer, skip_special_tokens=True)

    # 3. Run generation in a thread (model.generate() is blocking)
    import threading
    gen_kwargs = {
        "input_ids": input_ids,
        "max_new_tokens": self._llm._opts.max_new_tokens,
        "temperature": self._llm._opts.temperature,
        "top_p": self._llm._opts.top_p,
        "streamer": streamer,
    }

    # If TurboQuant is enabled, use step-by-step generation instead
    # to intercept past_key_values between steps
    thread = threading.Thread(target=self._llm._model.generate, kwargs=gen_kwargs)
    thread.start()

    # 4. Stream tokens as ChatChunk
    request_id = str(uuid.uuid4())
    prompt_tokens = input_ids.shape[1]
    completion_tokens = 0

    for text in streamer:
        if text:
            completion_tokens += 1  # approximate
            self._event_ch.send_nowait(ChatChunk(
                id=request_id,
                delta=ChoiceDelta(role="assistant", content=text),
            ))

    # 5. Send final usage chunk
    self._event_ch.send_nowait(ChatChunk(
        id=request_id,
        usage=CompletionUsage(
            completion_tokens=completion_tokens,
            prompt_tokens=prompt_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    ))

    thread.join()
```

### TurboQuant-GPU Integration Point

When `turboquant_enabled=True`, the generation loop changes to step-by-step
instead of using `TextIteratorStreamer`:

```python
# Step-by-step generation with KV cache compression
past_key_values = None
for step in range(max_new_tokens):
    output = model(input_ids, past_key_values=past_key_values, use_cache=True)

    # TurboQuant compresses the KV cache
    compressed = tq_engine.compress_kv_cache(output.past_key_values)
    past_key_values = tq_engine.build_cache(compressed)  # Returns DynamicCache

    # Get next token
    next_token = output.logits[:, -1, :].argmax(dim=-1)
    token_text = tokenizer.decode(next_token, skip_special_tokens=True)

    self._event_ch.send_nowait(ChatChunk(
        id=request_id,
        delta=ChoiceDelta(role="assistant", content=token_text),
    ))

    input_ids = next_token.unsqueeze(0)
    if next_token.item() == tokenizer.eos_token_id:
        break
```

### TurboQuant-GPU API Reference

```python
from turboquant_gpu import TurboQuantEngine

engine = TurboQuantEngine(head_dim=128, total_bits=3, device="cuda")
engine.auto_tune(seq_len=512)  # benchmarks 2-bit vs 3-bit, cuTile vs PyTorch

# Compress KV cache after model forward pass
compressed = engine.compress_kv_cache(model_output.past_key_values)

# Build standard DynamicCache from compressed data
cache = engine.build_cache(compressed)  # drop-in replacement

# Stats
stats = engine.compression_stats(model_output.past_key_values)
# Returns: {"fp16_bytes": ..., "tq_bytes": ..., "ratio": 5.02}
```

Key properties:
- Rotation matrices (Pi, S) are seeded/deterministic — initialized once, reused
- `build_cache()` returns `transformers.DynamicCache` — standard interface
- Falls back to PyTorch if cuTile GPU kernels unavailable
- Deps: `torch`, `scipy`, optional `cuda-tile`

---

## Key Constraints

1. **TurboQuant is optional** — The plugin must work as a pure HuggingFace
   inference plugin without TurboQuant installed. Gate all TurboQuant code
   behind `if self._opts.turboquant_enabled:` with a lazy import.

2. **Concurrent safety** — Multiple `chat()` calls share the same model weights.
   `model.generate()` with CUDA should handle this, but verify thread safety.
   Consider using `asyncio.to_thread()` for the blocking generation call.

3. **Incremental streaming** — Tokens must be pushed one at a time, not batched.
   The voice pipeline consumes them in real-time for TTS.

4. **`_opts` pattern** — The `LLM` class must expose an `_opts` attribute
   (dataclass with constructor kwargs) for OpenRTC's provider serialization.
   Look at how `livekit-plugins-openai` structures its options.

5. **Tool calling** — Many local models support tool calling via chat templates.
   Use `tokenizer.apply_chat_template(messages, tools=tools_schema)` when tools
   are provided. Parse tool call responses from the model's output format.

---

## Usage (End State)

```python
from livekit.plugins.hf import LLM

# Basic local inference
llm = LLM(model="meta-llama/Llama-3.1-8B-Instruct")

# With TurboQuant-GPU KV cache compression
llm = LLM(
    model="meta-llama/Llama-3.1-8B-Instruct",
    turboquant=True,
    turboquant_bits=3,
)

# In OpenRTC
pool = AgentPool(default_llm=llm)
```
