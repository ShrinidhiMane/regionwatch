"""Automatic remediation ("runbook as code") with guardrails.

Guardrails matter more than the action itself: an auto-remediator that restarts
a service in a tight loop can turn a small incident into a big one. So every
target gets a cooldown between attempts and a cap on attempts, after which the
monitor stops and escalates to a human (on-call).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from .config import TargetConfig

log = logging.getLogger("regionwatch.remediation")


class RemediationAction(Protocol):
    name: str

    async def run(self, target: TargetConfig) -> str:
        """Perform the action. Return a short description, raise on failure."""
        ...


class NoopAction:
    name = "none"

    async def run(self, target: TargetConfig) -> str:
        return "no remediation configured"


class DockerRestartAction:
    """Restart the container behind a target through the Docker Engine API."""

    name = "docker_restart"

    def __init__(self, client=None) -> None:
        self._client = client  # created lazily so tests and non-Docker runs don't need Docker

    def _docker(self):
        if self._client is None:
            import docker  # imported here on purpose: optional dependency at runtime

            self._client = docker.from_env()
        return self._client

    async def run(self, target: TargetConfig) -> str:
        name = target.remediation.container
        container = await asyncio.to_thread(self._docker().containers.get, name)
        await asyncio.to_thread(container.restart, timeout=5)
        return f"restarted container {name}"


class WebhookAction:
    """POST to an external automation endpoint (e.g. a Lambda or runbook service)."""

    name = "webhook"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def run(self, target: TargetConfig) -> str:
        resp = await self._client.post(
            target.remediation.url,
            json={"target": target.id, "region": target.region, "action": "remediate"},
            timeout=5,
        )
        resp.raise_for_status()
        return f"webhook returned HTTP {resp.status_code}"


@dataclass
class _Attempts:
    count: int = 0
    last_ts: float | None = None
    escalated: bool = False


class RemediationPolicy:
    """Decides whether a remediation attempt is allowed right now."""

    def __init__(self) -> None:
        self._state: dict[str, _Attempts] = {}

    def _get(self, target_id: str) -> _Attempts:
        return self._state.setdefault(target_id, _Attempts())

    def decide(self, target: TargetConfig, now: float) -> str:
        """Returns 'attempt', 'cooldown', 'escalate' (first time over the cap) or 'exhausted'."""
        s = self._get(target.id)
        cfg = target.remediation
        if s.count >= cfg.max_attempts:
            if not s.escalated:
                s.escalated = True
                return "escalate"
            return "exhausted"
        if s.last_ts is not None and now - s.last_ts < cfg.cooldown_seconds:
            return "cooldown"
        return "attempt"

    def record_attempt(self, target_id: str, now: float) -> None:
        s = self._get(target_id)
        s.count += 1
        s.last_ts = now

    def attempts(self, target_id: str) -> int:
        return self._get(target_id).count

    def reset(self, target_id: str) -> None:
        self._state.pop(target_id, None)
