"""Per-target health state machine.

Why thresholds? A single failed check is often noise (a network blip, a GC
pause). Requiring several failures in a row before declaring DOWN, and several
successes before declaring recovery, prevents "flapping" alerts and stops the
remediator from restarting a service that was only briefly slow.

    UNKNOWN --ok--> HEALTHY <--ok x recovery_threshold-- DOWN
       |               |  ^                                ^
       |             fail ok                                |
       +--fail--> DEGRADED ------fail x failure_threshold---+
"""

from __future__ import annotations

from .models import Health, ProbeResult, Transition


class HealthTracker:
    def __init__(self, target_id: str, failure_threshold: int, recovery_threshold: int,
                 latency_slo_ms: float) -> None:
        self.target_id = target_id
        self.failure_threshold = failure_threshold
        self.recovery_threshold = recovery_threshold
        self.latency_slo_ms = latency_slo_ms
        self.state = Health.UNKNOWN
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.last_result: ProbeResult | None = None

    def observe(self, result: ProbeResult) -> Transition | None:
        """Feed one probe result in; returns a Transition if the state changed."""
        self.last_result = result
        old = self.state

        if not result.ok:
            self.consecutive_failures += 1
            self.consecutive_successes = 0
            if self.consecutive_failures >= self.failure_threshold:
                new = Health.DOWN
            elif old == Health.DOWN:
                new = Health.DOWN
            else:
                new = Health.DEGRADED
        else:
            self.consecutive_successes += 1
            self.consecutive_failures = 0
            slow = result.latency_ms is not None and result.latency_ms > self.latency_slo_ms
            if old == Health.DOWN and self.consecutive_successes < self.recovery_threshold:
                new = Health.DOWN  # not trusted yet: wait for a streak of successes
            else:
                new = Health.DEGRADED if slow else Health.HEALTHY

        self.state = new
        return Transition(self.target_id, old, new) if new != old else None
