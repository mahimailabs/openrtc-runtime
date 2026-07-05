"""Signed-version pool membership (MAH-111).

During a rollout, a leftover worker from the previous version must not keep
grabbing new traffic (a silent regression: bugs you fixed reappear). Each worker
signs its membership with an HMAC over its ``(version, worker_id, timestamp)``
using a shared secret; a coordinator verifies the signature and that the version
matches the active deployment manifest before letting the worker take traffic.

This module provides the crypto primitives (sign + verify) with conservative
defaults: HMAC-SHA256, constant-time comparison, a JSON-canonical message (so a
delimiter inside ``worker_id`` cannot forge a different tuple), a freshness window
(replay protection), and secret rotation (accept any of several valid secrets
during a rotation window). Attaching the signature to LiveKit registration, and
auto-exiting a rejected worker with a non-zero code, is the coordinator/platform
integration on top of these primitives (see the deployment guide).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable, Sequence

__all__ = ["MembershipError", "MembershipVerifier", "sign_membership"]

_DEFAULT_MAX_AGE_SECONDS = 300.0


class MembershipError(ValueError):
    """Raised when a worker's signed membership is rejected."""


def _canonical(version: str, worker_id: str, timestamp: float) -> bytes:
    """Return an unambiguous message for the HMAC.

    JSON-encoding the fields as a list means a newline or delimiter inside any
    field is escaped, so no two distinct tuples can ever produce the same message.
    """
    return json.dumps(
        [version, worker_id, repr(float(timestamp))], separators=(",", ":")
    ).encode("utf-8")


def sign_membership(
    *, version: str, worker_id: str, timestamp: float, secret: str
) -> str:
    """Return the HMAC-SHA256 hex signature of this worker's membership tuple."""
    return hmac.new(
        secret.encode("utf-8"),
        _canonical(version, worker_id, timestamp),
        hashlib.sha256,
    ).hexdigest()


class MembershipVerifier:
    """Verify a worker's signed membership against the active deployment manifest."""

    def __init__(
        self,
        *,
        secrets: Sequence[str],
        expected_version: str | None = None,
        max_age_seconds: float = _DEFAULT_MAX_AGE_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not secrets:
            raise ValueError("MembershipVerifier requires at least one secret.")
        self._secrets = list(secrets)
        self._expected_version = expected_version
        self._max_age = max_age_seconds
        self._clock = clock

    def verify(
        self, *, token: str, version: str, worker_id: str, timestamp: float
    ) -> None:
        """Raise :class:`MembershipError` unless the membership is valid and current.

        Checks, in order: the version matches the manifest (if set), the timestamp
        is within the freshness window (no replay of a stale or future signature),
        and the signature is valid under any current secret (constant-time compare).
        """
        if self._expected_version is not None and version != self._expected_version:
            raise MembershipError(
                f"version '{version}' does not match the active deployment "
                f"'{self._expected_version}'"
            )
        age = self._clock() - timestamp
        if age > self._max_age:
            raise MembershipError("membership timestamp is stale (expired)")
        if age < -self._max_age:
            raise MembershipError("membership timestamp is in the future")
        expected = [
            sign_membership(
                version=version, worker_id=worker_id, timestamp=timestamp, secret=s
            )
            for s in self._secrets
        ]
        if not any(hmac.compare_digest(token, candidate) for candidate in expected):
            raise MembershipError("invalid membership signature")

    def is_valid(
        self, *, token: str, version: str, worker_id: str, timestamp: float
    ) -> bool:
        """Return whether the membership verifies, without raising."""
        try:
            self.verify(
                token=token, version=version, worker_id=worker_id, timestamp=timestamp
            )
        except MembershipError:
            return False
        return True
