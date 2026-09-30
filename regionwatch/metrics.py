"""Prometheus metrics, exposed at GET /metrics."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

STATE_VALUE = {"UNKNOWN": -1, "DOWN": 0, "DEGRADED": 1, "HEALTHY": 2}


class Metrics:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        labels = ["target", "region"]
        self.up = Gauge("regionwatch_target_up", "1 if the last probe succeeded", labels,
                        registry=self.registry)
        self.state = Gauge("regionwatch_target_state",
                           "-1 unknown, 0 down, 1 degraded, 2 healthy", labels,
                           registry=self.registry)
        self.latency = Histogram("regionwatch_probe_latency_seconds", "Probe latency", labels,
                                 buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
                                 registry=self.registry)
        self.probes = Counter("regionwatch_probes_total", "Probes by outcome",
                              [*labels, "outcome"], registry=self.registry)
        self.transitions = Counter("regionwatch_transitions_total", "State transitions",
                                   [*labels, "to"], registry=self.registry)
        self.remediations = Counter("regionwatch_remediations_total", "Remediation attempts",
                                    [*labels, "result"], registry=self.registry)
