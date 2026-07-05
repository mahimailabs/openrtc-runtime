"""Signed-version pool membership (MAH-111)."""

from __future__ import annotations

import pytest

from openrtc.core.membership import (
    MembershipError,
    MembershipVerifier,
    sign_membership,
)


class _Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _token(secret: str = "s1", *, version: str = "v2", ts: float = 1000.0) -> str:
    return sign_membership(
        version=version, worker_id="w-1", timestamp=ts, secret=secret
    )


def _verifier(**kw: object) -> MembershipVerifier:
    params: dict[str, object] = {
        "secrets": ["s1"],
        "expected_version": "v2",
        "max_age_seconds": 300.0,
        "clock": _Clock(1000.0),
    }
    params.update(kw)
    return MembershipVerifier(**params)  # type: ignore[arg-type]


def test_sign_is_deterministic() -> None:
    a = sign_membership(version="v2", worker_id="w-1", timestamp=1000.0, secret="s1")
    b = sign_membership(version="v2", worker_id="w-1", timestamp=1000.0, secret="s1")
    assert a == b


def test_sign_differs_by_field() -> None:
    base = _token()
    assert base != _token(version="v3")
    assert base != sign_membership(
        version="v2", worker_id="w-2", timestamp=1000.0, secret="s1"
    )
    assert base != _token(ts=1001.0)
    assert base != _token(secret="other")


def test_valid_signature_accepted() -> None:
    v = _verifier()
    v.verify(
        token=_token(), version="v2", worker_id="w-1", timestamp=1000.0
    )  # no raise


def test_invalid_signature_rejected() -> None:
    v = _verifier()
    with pytest.raises(MembershipError, match="signature"):
        v.verify(token="deadbeef", version="v2", worker_id="w-1", timestamp=1000.0)


def test_wrong_version_rejected() -> None:
    v = _verifier(expected_version="v2")
    # A validly-signed token for v1 is rejected because the manifest expects v2:
    # this is the leftover-old-worker case the signing scheme guards against.
    token = _token(version="v1")
    with pytest.raises(MembershipError, match="version"):
        v.verify(token=token, version="v1", worker_id="w-1", timestamp=1000.0)


def test_stale_timestamp_rejected() -> None:
    v = _verifier(clock=_Clock(2000.0))  # 1000s in the future -> stale
    with pytest.raises(MembershipError, match="stale|expired|timestamp"):
        v.verify(token=_token(), version="v2", worker_id="w-1", timestamp=1000.0)


def test_future_timestamp_rejected() -> None:
    v = _verifier(clock=_Clock(500.0))  # token from 500s in the future
    with pytest.raises(MembershipError, match="timestamp|future"):
        v.verify(token=_token(), version="v2", worker_id="w-1", timestamp=1000.0)


def test_secret_rotation_accepts_either_secret() -> None:
    v = _verifier(secrets=["new", "old"])  # rotation window: two valid secrets
    v.verify(token=_token("new"), version="v2", worker_id="w-1", timestamp=1000.0)
    v.verify(token=_token("old"), version="v2", worker_id="w-1", timestamp=1000.0)
    with pytest.raises(MembershipError):
        v.verify(
            token=_token("unknown"), version="v2", worker_id="w-1", timestamp=1000.0
        )


def test_no_expected_version_skips_version_check() -> None:
    v = _verifier(expected_version=None)
    # Any validly-signed version is accepted when no manifest version is set.
    v.verify(
        token=_token(version="v9"), version="v9", worker_id="w-1", timestamp=1000.0
    )


def test_is_valid_returns_bool() -> None:
    v = _verifier()
    assert v.is_valid(token=_token(), version="v2", worker_id="w-1", timestamp=1000.0)
    assert not v.is_valid(token="bad", version="v2", worker_id="w-1", timestamp=1000.0)


def test_verifier_requires_at_least_one_secret() -> None:
    with pytest.raises(ValueError, match="at least one secret"):
        MembershipVerifier(secrets=[])
