# AGENTS.md

## Purpose
This repository is a Python open-source package built on LiveKit for voice AI applications. The package should be production-minded, easy to understand, well-typed, testable, and friendly for contributors.

When making changes, prioritize:
1. Correctness and reliability in real-time voice flows
2. Clear public APIs
3. Backward compatibility for open-source users
4. Strong typing and test coverage
5. Minimal, maintainable abstractions

---

## Product and Architecture Principles

### Core goals
- Build reusable Python components for voice AI on LiveKit
- Keep framework-specific details isolated where possible
- Make real-time behavior predictable and observable
- Prefer explicit APIs over magic or hidden behavior
- Optimize for contributor readability, not cleverness

### Architectural rules
- Keep business logic separate from transport/runtime glue
- Keep LiveKit integration code isolated from domain logic
- Avoid tightly coupling high-level package APIs to internal implementation details
- Prefer composition over inheritance
- Keep modules focused and small
- Do not introduce global mutable state unless absolutely necessary
- Avoid singleton-heavy designs

### Layering
Use this mental model when organizing code:
- `api/` or public package surface: stable interfaces intended for users
- `core/`: domain logic, orchestration, state handling
- `integrations/` or `livekit/`: LiveKit-specific adapters and runtime hooks
- `models/` or `types/`: typed shared schemas, events, config objects
- `utils/`: narrow helper functions only, no hidden business logic

Business logic must not live inside:
- CLI entrypoints
- example scripts
- callbacks that should delegate into core logic
- transport adapters

---

## Code Style

### General Python style
- Target modern Python syntax supported by the project version
- Use type hints everywhere
- Prefer explicit return types on public functions and methods
- Prefer small pure functions where practical
- Prefer `dataclass` or clear typed classes over loose dictionaries for structured data
- Prefer `Enum` for constrained option sets
- Avoid boolean flag arguments when an enum or separate function would be clearer
- Avoid overly terse variable names
- Avoid surprising side effects

### Readability
- Write code for maintainers and contributors unfamiliar with the internals
- Favor straightforward control flow over clever compact code
- Add comments only when the why is not obvious from the code
- Do not add noisy comments that restate the code
- Keep functions focused on one responsibility
- If a function needs extensive explanation, split it into smaller helpers

### Naming
- Use `snake_case` for variables, functions, and modules
- Use `PascalCase` for classes
- Use `UPPER_SNAKE_CASE` for constants
- Name functions after what they do, not how they do it
- Use domain-specific names such as `session`, `turn`, `utterance`, `participant`, `track`, `transcript`, `agent`, `pipeline`, `vad`, `stt`, `tts` when appropriate

### Imports
- Prefer absolute imports within the package
- Keep imports grouped and sorted
- Avoid circular imports by improving module boundaries rather than using late imports unless necessary
- Do not introduce heavy dependencies in core modules unless justified

---

## Public API Guidelines

### Stability
- Treat public APIs as stable unless the task explicitly allows a breaking change
- Avoid renaming or reshaping public interfaces without strong justification
- If a breaking change is necessary, update docs, changelog notes, and tests

### API design
- Public APIs should be easy to discover and hard to misuse
- Prefer explicit configuration objects over long argument lists
- Prefer sensible defaults
- Validate user input early with clear error messages
- Raise precise exceptions with actionable messages
- Avoid leaking internal implementation details through public return values

### Async design
- Use async only where it is justified by I/O or runtime integration
- Keep async boundaries clean and intentional
- Do not mix sync and async styles inconsistently in the same API surface
- Avoid blocking operations in async code
- Use cancellation-safe patterns where relevant

---

## LiveKit-Specific Guidance

### Real-time constraints
- Real-time audio paths should avoid unnecessary allocations, blocking calls, and hidden latency
- Be careful with backpressure, task buildup, and event storms
- Time-sensitive paths should be simple and observable
- Do not add logging noise in hot loops

### Event-driven behavior
- Make event handling explicit
- Prefer well-defined event payload types over loosely shaped dicts
- Guard against race conditions in session lifecycle logic
- Be careful around connect/disconnect, participant joins/leaves, track subscription changes, and stream interruptions

### Voice pipeline concerns
- Preserve clear boundaries between:
  - audio input handling
  - VAD / turn detection
  - STT
  - LLM or agent reasoning
  - TTS
  - playback/output
- Avoid coupling one stage tightly to another unless necessary
- Keep pipeline stages mockable for tests
- Make retries, fallbacks, and timeout behavior explicit

### Error handling
- Network/runtime failures should degrade gracefully where possible
- Never swallow exceptions silently
- Include contextual information in exceptions and logs
- Distinguish between expected runtime conditions and true failures

---

## Typing Rules

- All new public functions, methods, and classes must be typed
- Internal functions should also be typed unless truly trivial
- Prefer concrete types over `Any`
- Use `Protocol` for interface-like behavior where useful
- Use `TypedDict` only when interop with dict-shaped payloads is necessary
- Prefer dataclasses or typed models for internal structured data
- Keep generics understandable; avoid type complexity that hurts maintainability

Example expectations:
- Good: `def create_session(config: SessionConfig) -> AgentSession:`
- Good: `async def synthesize(request: TTSRequest) -> AsyncIterator[AudioFrame]:`
- Avoid: `def run(config):`
- Avoid: `def process(data: dict[str, Any]) -> Any:`

---

## Documentation Expectations

- Public classes and functions should have concise docstrings
- Docstrings should explain behavior, important parameters, return values, and edge cases
- Keep docstrings practical and contributor-friendly
- Update README or package docs when changing public behavior
- Examples should reflect real package usage patterns and be runnable with minimal setup

### Docstring style
Use a consistent style across the repo. Prefer concise Google-style or simple imperative prose.

Example:
```python
def start(self) -> None:
    """Start the agent session and begin processing events."""
```

---

## Testing Standards

### General

- All non-trivial changes should include tests
- Prefer `pytest`
- Test public behavior, not private implementation details
- Keep tests deterministic and readable
- Avoid brittle timing-based tests unless unavoidable

### What to test

Cover these when relevant:

- Session lifecycle
- Event ordering
- Reconnection / interruption paths
- Config validation
- Error propagation
- Async cancellation behavior
- Fallback logic
- Serialization and deserialization
- Public API behavior

### Test design

- Prefer fixtures over repetitive setup
- Mock LiveKit/network boundaries cleanly
- Do not over-mock pure logic
- Add regression tests for bug fixes
- For async code, ensure tasks are awaited and cleaned up properly

### Performance-sensitive areas

- Add focused tests for buffering, queue growth, timeout handling, and cleanup when relevant
- Be cautious with sleeps in tests; prefer synchronization primitives or explicit hooks

---

## Logging and Observability

- Use structured, meaningful logging
- Logs should help debug real-time failures without flooding output
- Avoid excessive debug logs in hot paths
- Include identifiers like session ID, participant ID, track ID, or request ID when helpful
- Never log secrets, tokens, or sensitive user content unless explicitly intended and documented

### Error messages

Error messages should state what failed and what the user can do next.

**Prefer:**
> "TTS provider timed out after 10s for session {session_id}"

**Avoid:**
> "Something went wrong"

---

## Configuration

- Prefer explicit config objects for non-trivial components
- Validate config at boundaries
- Keep defaults safe and unsurprising
- Avoid hidden behavior controlled by many environment variables
- Document all supported environment variables and config fields

---

## Dependency Policy

- Keep dependencies minimal
- Prefer standard library where practical
- New dependencies must have clear value
- Avoid pulling large frameworks into core paths unless justified
- Favor libraries with good maintenance and permissive licenses
- Do not introduce dependencies just for small helper functionality

---

## Performance and Concurrency

- Be careful with task spawning; every background task should have a clear lifecycle
- Clean up tasks, streams, and resources explicitly
- Avoid unbounded queues and silent buffering
- Prefer bounded concurrency when processing streams/events
- Watch for memory leaks in long-lived sessions
- Avoid blocking file or network I/O in the event loop

When changing concurrency code:
- Reason about cancellation
- Reason about shutdown behavior
- Reason about partial failure
- Reason about ordering guarantees

---

## Backward Compatibility

This is an open-source package. Preserve compatibility unless the change explicitly calls for a breaking release.

Before making a breaking change:
- Confirm it is necessary
- Minimize blast radius
- Update docs and migration guidance
- Update tests to reflect the new contract

If unsure, prefer additive changes over breaking changes.

---

## Contributor Experience

- Keep the repo approachable for new contributors
- Prefer obvious file placement and predictable naming
- Add or update examples for meaningful new capabilities
- Avoid hidden conventions
- Leave code cleaner than you found it

When adding a new module:
- Ensure the name is discoverable
- Ensure its responsibility is narrow
- Add tests
- Expose it publicly only if needed

---

## Preferred Patterns

- Typed dataclasses for configuration and event payloads
- Small adapter classes around provider-specific integrations
- Explicit state transitions for session/agent lifecycle
- Dependency injection for providers like STT, TTS, VAD, and LLM backends
- Narrow interfaces for pluggable components
- Helper functions for repeated validation and normalization

## Patterns to Avoid

- Giant manager classes with many responsibilities
- Hidden global registries
- Untyped dicts passed across layers
- Broad `except Exception` without re-raising or translating meaningfully
- Adding retries without timeout and observability
- Mixing demo/example code into core package modules
- Adding synchronous blocking calls inside async execution paths

---

## Pull Request Expectations

When making changes:
- Keep diffs focused
- Update tests
- Update docs if public behavior changes
- Preserve compatibility unless explicitly told otherwise
- Add clear notes in code comments only where they improve maintainability

## Preferred Repository Conventions

Assume these conventions unless the existing repo clearly uses something else:

- Formatting with Black-compatible style
- Linting with Ruff
- Tests with Pytest
- Package metadata in `pyproject.toml`
- Type checking with mypy or pyright
- Examples in `examples/`
- Docs in `docs/`

If the repo already has established tooling, follow the repo instead of inventing a parallel standard.

---

## Instructions for Code Changes

When implementing a feature or fix:
- First understand the existing public API and architecture
- Make the smallest clean change that solves the problem
- Reuse existing abstractions before adding new ones
- Add or update tests near the changed behavior
- Avoid speculative refactors unless they are necessary to complete the task safely

When editing code:
- Preserve existing style and patterns where they are already good
- Improve weak areas incrementally, not by rewriting unrelated modules
- Do not introduce unrelated renames or formatting-only churn

## Instructions for Documentation and Examples

- Examples should demonstrate realistic voice AI workflows
- Favor examples that are minimal but idiomatic
- Use names that reflect voice-agent concepts
- Ensure examples match the current public API
- Avoid pseudo-code in user-facing docs when real code is practical

---

## Decision Rules

If there is a conflict, follow this priority order:

1. Correctness and safety in real-time behavior
2. Public API stability
3. Consistency with existing repository patterns
4. Simplicity and readability
5. Performance optimization

When in doubt:
- Choose the simpler design
- Choose the more explicit API
- Choose the more testable implementation
- Choose the option that is friendlier to open-source contributors
