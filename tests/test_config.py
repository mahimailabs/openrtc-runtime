"""Validation tests for the ``@agent_config`` decorator.

The decorator calls ``_normalize_optional_name`` on its ``name`` and
``greeting`` arguments. The discovery integration tests exercise the happy
path; this module locks down the input-validation branches that surface as
``RuntimeError`` to catch typos / wrong types before they reach the runtime.
"""

from __future__ import annotations

import pytest

from openrtc import agent_config


def test_agent_config_rejects_non_string_name() -> None:
    with pytest.raises(RuntimeError, match="'name' must be a string, got int"):
        agent_config(name=42)  # type: ignore[arg-type]


def test_agent_config_rejects_blank_name() -> None:
    with pytest.raises(RuntimeError, match="'name' cannot be empty"):
        agent_config(name="   ")


def test_agent_config_rejects_non_string_greeting() -> None:
    with pytest.raises(RuntimeError, match="'greeting' must be a string, got list"):
        agent_config(greeting=["hello"])  # type: ignore[arg-type]


def test_agent_config_rejects_blank_greeting() -> None:
    with pytest.raises(RuntimeError, match="'greeting' cannot be empty"):
        agent_config(greeting="\t\n ")


def test_agent_config_strips_whitespace_around_name_and_greeting() -> None:
    decorator = agent_config(name="  dental  ", greeting="  Hello.  ")

    class _Marker:
        pass

    decorator(_Marker)  # type: ignore[arg-type]

    metadata = _Marker.__openrtc_agent_config__  # type: ignore[attr-defined]
    assert metadata.name == "dental"
    assert metadata.greeting == "Hello."


def test_agent_config_allows_none_name_and_greeting() -> None:
    decorator = agent_config(name=None, greeting=None)

    class _Marker:
        pass

    decorator(_Marker)  # type: ignore[arg-type]

    metadata = _Marker.__openrtc_agent_config__  # type: ignore[attr-defined]
    assert metadata.name is None
    assert metadata.greeting is None
