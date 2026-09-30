"""The monitor loop: probe every target concurrently, update state, alert, remediate."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

import httpx

from .alerts import Alerter
from .checker import probe
from .config import Settings, TargetConfig
from .health import HealthTracker
from .metrics import STATE_VALUE, Metrics
from .models import Health, ProbeResult
from .remediation import RemediationAction, RemediationPolicy
from .store import Store

log = logging.getLogger("regionwatch.monitor")


class Monitor:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        client: httpx.AsyncClient,
        alerter: Alerter,
        actions: dict[str, RemediationAction],
        metrics: Metrics | None = None,
        clock: Callable[[], float] = time.time,
        sleep=asyncio.sleep,
    ) -> None:
        self.settings = settings
        self.store = store
        self.client = client
        self.alerter = alerter
        self.actions = actions
        self.metrics = metrics or Metrics()
        self.clock = clock
        self._sleep = sleep
        self.policy = RemediationPolicy()
        self.trackers = {
            t.id: HealthTracker(t.id, settings.failure_threshold, settings.recovery_threshold,
                                settings.latency_slo_ms)
            for t in settings.targets
        }
        self.cycles = 0

    # ---- one target -----------------------------------------------------------------
    async def check_target(self, target: TargetConfig) -> ProbeResult:
        result = await probe(self.client, target, retries=self.settings.retries,
                             sleep=self._sleep, clock=self.clock)
        self.store.record_probe(result)
        self._record_metrics(target, result)

        tracker = self.trackers[target.id]
        transition = tracker.observe(result)
        if transition:
            detail = f"{transition.old.value} -> {transition.new.value}"
            if result.error:
                detail += f" ({result.error})"
            self.store.record_event(target.id, "transition", detail, self.clock())
            self.metrics.transitions.labels(target.id, target.region, transition.new.value).inc()
            await self._alert_transition(target, transition.old, transition.new, result)
            if transition.new == Health.HEALTHY and transition.old == Health.DOWN:
                self.policy.reset(target.id)

        if tracker.state == Health.DOWN:
            await self._maybe_remediate(target)
        return result

    async def _alert_transition(self, target, old: Health, new: Health, result) -> None:
        where = f"{target.id} ({target.region})"
        if new == Health.DOWN:
            await self.alerter.send("CRITICAL", f"{where} is DOWN: {result.error}")
        elif new == Health.HEALTHY and old in (Health.DOWN, Health.DEGRADED):
            await self.alerter.send("RESOLVED", f"{where} recovered")
        elif new == Health.DEGRADED:
            reason = result.error or f"latency {result.latency_ms} ms > SLO"
            await self.alerter.send("WARNING", f"{where} is DEGRADED: {reason}")

    async def _maybe_remediate(self, target: TargetConfig) -> None:
        now = self.clock()
        decision = self.policy.decide(target, now)
        if decision == "cooldown" or decision == "exhausted":
            return
        if decision == "escalate":
            msg = (f"{target.id} still DOWN after {target.remediation.max_attempts} "
                   f"remediation attempts; paging on-call")
            self.store.record_event(target.id, "escalation", msg, now)
            await self.alerter.send("PAGE", msg)
            return

        action = self.actions.get(target.remediation.action)
        if action is None or target.remediation.action == "none":
            return
        self.policy.record_attempt(target.id, now)
        attempt = self.policy.attempts(target.id)
        try:
            outcome = await action.run(target)
            self.store.record_event(target.id, "remediation",
                                    f"attempt {attempt}: {outcome}", now)
            self.metrics.remediations.labels(target.id, target.region, "ok").inc()
            log.info("remediated %s: %s", target.id, outcome)
        except Exception as exc:  # noqa: BLE001 - any failure here must not stop monitoring
            self.store.record_event(target.id, "remediation",
                                    f"attempt {attempt} failed: {exc}", now)
            self.metrics.remediations.labels(target.id, target.region, "error").inc()
            log.warning("remediation failed for %s: %s", target.id, exc)

    def _record_metrics(self, target: TargetConfig, result: ProbeResult) -> None:
        labels = (target.id, target.region)
        self.metrics.up.labels(*labels).set(1 if result.ok else 0)
        self.metrics.probes.labels(*labels, "ok" if result.ok else "fail").inc()
        if result.latency_ms is not None:
            self.metrics.latency.labels(*labels).observe(result.latency_ms / 1000)

    # ---- all targets ----------------------------------------------------------------
    async def run_once(self) -> list[ProbeResult]:
        results = await asyncio.gather(*(self.check_target(t) for t in self.settings.targets))
        for t in self.settings.targets:
            self.metrics.state.labels(t.id, t.region).set(
                STATE_VALUE[self.trackers[t.id].state.value])
        self.cycles += 1
        return list(results)

    async def run_forever(self, stop: asyncio.Event) -> None:
        log.info("monitoring %d targets every %ss", len(self.settings.targets),
                 self.settings.interval_seconds)
        while not stop.is_set():
            started = time.monotonic()
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001 - keep the loop alive no matter what
                log.exception("monitor cycle failed")
            elapsed = time.monotonic() - started
            try:
                await asyncio.wait_for(stop.wait(),
                                       timeout=max(0.0, self.settings.interval_seconds - elapsed))
            except TimeoutError:
                pass

    # ---- read model for the API ----------------------------------------------------
    def snapshot(self) -> list[dict]:
        hour_ago = self.clock() - 3600
        out = []
        for t in self.settings.targets:
            tr = self.trackers[t.id]
            last = tr.last_result
            out.append({
                "id": t.id,
                "region": t.region,
                "state": tr.state.value,
                "last_latency_ms": last.latency_ms if last else None,
                "last_error": last.error if last else None,
                "consecutive_failures": tr.consecutive_failures,
                "remediation_attempts": self.policy.attempts(t.id),
                "availability_1h": self.store.availability(t.id, hour_ago),
                "p95_latency_ms_1h": self.store.p95_latency(t.id, hour_ago),
            })
        return out
