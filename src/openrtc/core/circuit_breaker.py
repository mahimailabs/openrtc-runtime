"""Per-tenant circuit breaker for blast-radius isolation (MAH-104).

One tenant's failing code must not degrade the pool for the others. This breaker
tracks each tenant's recent session outcomes in a rolling time window; when a
tenant's failure ratio crosses a threshold (with a minimum sample count so a
single failure never trips it), the breaker **opens** and the request filter
rejects that tenant's new sessions for a cooldown. After the cooldown it recovers
automatically. Failures are counted per tenant, so a healthy tenant never
inherits a noisy neighbor's breaker.

State changes are logged (open on entry, recovery on exit). Per-tenant cost /
telemetry export stays with voicegateway; this is a runtime safety valve only.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable

logger = logging.getLogger("openrtc")

__all__ = ["TenantCircuitBreaker"]

OnStateChange = Callable[[str, str], None]


class TenantCircuitBreaker:
    """Open a per-tenant breaker when its recent failure ratio crosses a threshold."""

    def __init__(
        self,
        *,
        failure_ratio: float = 0.5,
        min_samples: int = 5,
        window_seconds: float = 60.0,
        cooldown_seconds: float = 30.0,
        on_state_change: OnStateChange | None = None,
        time_source: Callable[[], float] = time.monotonic,
    ) -> None:
        self._failure_ratio = failure_ratio
        self._min_samples = min_samples
        self._window = window_seconds
        self._cooldown = cooldown_seconds
        self._on_state_change = on_state_change
        self._time = time_source
        # tenant -> recent (timestamp, success) outcomes within the window.
        self._outcomes: dict[str, deque[tuple[float, bool]]] = {}
        # tenant -> monotonic time the breaker reopens/closes at (only while open).
        self._open_until: dict[str, float] = {}

    def record_outcome(self, tenant: str, *, success: bool) -> None:
        """Record one session outcome; open the breaker if the failure ratio trips."""
        now = self._time()
        outcomes = self._outcomes.setdefault(tenant, deque())
        outcomes.append((now, success))
        self._prune(outcomes, now)
        if tenant in self._open_until:
            return  # already open; recovery is time-based, not outcome-based
        total = len(outcomes)
        if total < self._min_samples:
            return
        failures = sum(1 for _, ok in outcomes if not ok)
        if failures / total > self._failure_ratio:
            self._open_until[tenant] = now + self._cooldown
            outcomes.clear()  # fresh window after recovery
            logger.warning(
                "[circuit-breaker] tenant '%s' opened after %d/%d failures; "
                "rejecting its new sessions for %.0fs",
                tenant,
                failures,
                total,
                self._cooldown,
            )
            self._notify(tenant, "open")

    def should_reject(self, tenant: str) -> bool:
        """Return True while the tenant's breaker is open; auto-recover after cooldown."""
        until = self._open_until.get(tenant)
        if until is None:
            return False
        if self._time() >= until:
            del self._open_until[tenant]
            logger.info("[circuit-breaker] tenant '%s' recovered", tenant)
            self._notify(tenant, "closed")
            return False
        return True

    def _prune(self, outcomes: deque[tuple[float, bool]], now: float) -> None:
        cutoff = now - self._window
        while outcomes and outcomes[0][0] < cutoff:
            outcomes.popleft()

    def _notify(self, tenant: str, state: str) -> None:
        if self._on_state_change is not None:
            self._on_state_change(tenant, state)
