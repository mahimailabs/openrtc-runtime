"""Unit tests for the spawn-safe provider serialization helpers.

The serialization layer captures plugin instances as ``_ProviderRef`` records
and rebuilds them in spawned workers. The ``_extract_provider_kwargs`` and
``_filter_provider_kwargs`` helpers are the bridge between a plugin's
``_opts`` dataclass and the kwargs we serialize. These tests pin the
edge cases (no ``_opts``, OpenAI ``NotGiven`` sentinel filtering) that
the higher-level pool tests don't exercise directly.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from openrtc.core.serialization import (
    _extract_provider_kwargs,
    _filter_provider_kwargs,
)


def test_extract_provider_kwargs_returns_empty_when_opts_is_none() -> None:
    plugin = SimpleNamespace(_opts=None)

    assert _extract_provider_kwargs(plugin) == {}


def test_extract_provider_kwargs_returns_empty_when_opts_attr_is_missing() -> None:
    class _Bare:
        pass

    assert _extract_provider_kwargs(_Bare()) == {}


def test_extract_provider_kwargs_extracts_set_options() -> None:
    plugin = SimpleNamespace(_opts=SimpleNamespace(model="gpt-4o", temperature=0.2))

    assert _extract_provider_kwargs(plugin) == {"model": "gpt-4o", "temperature": 0.2}


def test_filter_provider_kwargs_drops_openai_not_given_sentinel() -> None:
    pytest.importorskip("openai")
    from openai import NOT_GIVEN

    options = {"model": "gpt-4o", "language": NOT_GIVEN, "temperature": 0.2}

    assert _filter_provider_kwargs(options) == {
        "model": "gpt-4o",
        "temperature": 0.2,
    }


def test_filter_provider_kwargs_passes_through_explicit_none() -> None:
    options = {"model": "gpt-4o", "language": None}

    assert _filter_provider_kwargs(options) == {"model": "gpt-4o", "language": None}
