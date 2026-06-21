"""Worker-option validation helpers."""

from __future__ import annotations

import pytest

from openrtc.utils.validation import require_positive_int, validate_isolation


def test_require_positive_int_returns_value() -> None:
    assert require_positive_int("max_concurrent_sessions", 50) == 50


@pytest.mark.parametrize("bad", [True, False, 1.0, "1", None])
def test_require_positive_int_rejects_non_int(bad: object) -> None:
    with pytest.raises(TypeError, match=r"widget must be an int, got "):
        require_positive_int("widget", bad)


def test_require_positive_int_rejects_below_one() -> None:
    with pytest.raises(ValueError, match=r"widget must be >= 1, got 0\."):
        require_positive_int("widget", 0)


def test_validate_isolation_accepts_known_modes() -> None:
    assert validate_isolation("coroutine") == "coroutine"
    assert validate_isolation("process") == "process"


def test_validate_isolation_rejects_unknown() -> None:
    with pytest.raises(ValueError, match=r"isolation must be 'coroutine' or 'process'"):
        validate_isolation("threads")
