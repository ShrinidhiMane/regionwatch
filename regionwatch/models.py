"""Small shared data types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Health(StrEnum):
    UNKNOWN = "UNKNOWN"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"  # answering, but slow or occasionally failing
    DOWN = "DOWN"  # failed `failure_threshold` checks in a row


@dataclass(frozen=True)
class ProbeResult:
    target_id: str
    ok: bool
    timestamp: float
    status_code: int | None = None
    latency_ms: float | None = None
    error: str | None = None
    attempts: int = 1


@dataclass(frozen=True)
class Transition:
    target_id: str
    old: Health
    new: Health
