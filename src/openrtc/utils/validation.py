"""Validation helpers for worker option values, shared by the pool and executors."""

from __future__ import annotations

import re

__all__ = [
    "require_agent_name",
    "require_non_negative_number",
    "require_positive_int",
    "validate_isolation",
]

_ISOLATION_MODES = ("coroutine", "process")

# Agent names double as routing signals (the ``<agent>-`` room-name prefix) and
# as metadata / log / socket tokens, so they are restricted to a safe charset.
# Underscores are allowed alongside letters/digits/dashes because discovery
# derives names from Python module filenames, which conventionally use them
# (``fallback_agent.py``); rejecting them would break existing pools.
_AGENT_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")
_AGENT_NAME_MAX = 64


def require_positive_int(name: str, value: object) -> int:
    """Return ``value`` if it is a non-bool int that is at least 1, else raise."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}.")
    if value < 1:
        raise ValueError(f"{name} must be >= 1, got {value}.")
    return value


def require_non_negative_number(name: str, value: object) -> float:
    """Return ``value`` as a float if it is a non-bool number >= 0, else raise.

    Used for memory watermarks where ``0`` means "disabled" (livekit's own
    convention for ``memory_limit_mb``).
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name} must be a number, got {type(value).__name__}.")
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}.")
    return float(value)


def validate_isolation(value: str) -> str:
    """Return ``value`` if it names a known isolation mode, else raise ValueError."""
    if value not in _ISOLATION_MODES:
        raise ValueError(f"isolation must be 'coroutine' or 'process', got {value!r}.")
    return value


def require_agent_name(value: str) -> str:
    """Return the stripped agent name if valid, else raise ValueError.

    Valid names are 1-64 characters of ASCII letters, digits, dashes, and
    underscores. This is the single registration chokepoint (``AgentPool.add``
    and the multi-agent constructor both route through it), so every registered
    name is a safe routing / metadata / log token.
    """
    normalized = value.strip()
    if not normalized:
        raise ValueError("Agent name must be a non-empty string.")
    if len(normalized) > _AGENT_NAME_MAX or not _AGENT_NAME_RE.fullmatch(normalized):
        raise ValueError(
            "Agent name must be 1-64 characters of ASCII letters, digits, "
            f"dashes, or underscores, got {value!r}."
        )
    return normalized
