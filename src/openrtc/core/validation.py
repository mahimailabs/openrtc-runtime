"""Validation helpers for worker option values, shared by the pool and executors."""

from __future__ import annotations

__all__ = ["require_positive_int", "validate_isolation"]

_ISOLATION_MODES = ("coroutine", "process")


def require_positive_int(name: str, value: object) -> int:
    """Return ``value`` if it is a non-bool int that is at least 1, else raise."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}.")
    if value < 1:
        raise ValueError(f"{name} must be >= 1, got {value}.")
    return value


def validate_isolation(value: str) -> str:
    """Return ``value`` if it names a known isolation mode, else raise ValueError."""
    if value not in _ISOLATION_MODES:
        raise ValueError(f"isolation must be 'coroutine' or 'process', got {value!r}.")
    return value
