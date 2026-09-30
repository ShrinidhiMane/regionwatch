"""Load and validate the YAML configuration that describes what to monitor."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

VALID_ACTIONS = {"none", "docker_restart", "webhook"}


class ConfigError(ValueError):
    """Raised when the config file is missing fields or has bad values."""


@dataclass(frozen=True)
class RemediationConfig:
    action: str = "none"  # none | docker_restart | webhook
    container: str | None = None  # for docker_restart
    url: str | None = None  # for webhook
    cooldown_seconds: float = 30.0  # minimum wait between two attempts
    max_attempts: int = 3  # then stop and escalate to a human


@dataclass(frozen=True)
class TargetConfig:
    id: str
    region: str
    url: str
    timeout_seconds: float = 2.0
    remediation: RemediationConfig = field(default_factory=RemediationConfig)


@dataclass(frozen=True)
class Settings:
    interval_seconds: float = 5.0
    failure_threshold: int = 3  # consecutive failures before a target is DOWN
    recovery_threshold: int = 2  # consecutive successes before DOWN -> HEALTHY
    latency_slo_ms: float = 500.0  # slower than this = DEGRADED
    retries: int = 2  # retries per probe, with exponential backoff
    db_path: str = "regionwatch.db"
    alert_webhook: str | None = None  # Slack-compatible incoming webhook
    targets: tuple[TargetConfig, ...] = ()


def _require(d: dict, key: str, where: str):
    if key not in d or d[key] in (None, ""):
        raise ConfigError(f"{where}: missing required field '{key}'")
    return d[key]


def parse_settings(raw: dict) -> Settings:
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")

    targets: list[TargetConfig] = []
    seen: set[str] = set()
    for i, t in enumerate(raw.get("targets") or []):
        where = f"targets[{i}]"
        tid = _require(t, "id", where)
        if tid in seen:
            raise ConfigError(f"{where}: duplicate target id '{tid}'")
        seen.add(tid)

        rem_raw = t.get("remediation") or {}
        action = rem_raw.get("action", "none")
        if action not in VALID_ACTIONS:
            raise ConfigError(f"{where}: unknown remediation action '{action}'")
        if action == "docker_restart" and not rem_raw.get("container"):
            raise ConfigError(f"{where}: docker_restart needs 'container'")
        if action == "webhook" and not rem_raw.get("url"):
            raise ConfigError(f"{where}: webhook remediation needs 'url'")

        targets.append(
            TargetConfig(
                id=tid,
                region=_require(t, "region", where),
                url=_require(t, "url", where),
                timeout_seconds=float(t.get("timeout_seconds", 2.0)),
                remediation=RemediationConfig(
                    action=action,
                    container=rem_raw.get("container"),
                    url=rem_raw.get("url"),
                    cooldown_seconds=float(rem_raw.get("cooldown_seconds", 30.0)),
                    max_attempts=int(rem_raw.get("max_attempts", 3)),
                ),
            )
        )

    if not targets:
        raise ConfigError("config must define at least one target")

    settings = Settings(
        interval_seconds=float(raw.get("interval_seconds", 5.0)),
        failure_threshold=int(raw.get("failure_threshold", 3)),
        recovery_threshold=int(raw.get("recovery_threshold", 2)),
        latency_slo_ms=float(raw.get("latency_slo_ms", 500.0)),
        retries=int(raw.get("retries", 2)),
        db_path=str(raw.get("db_path", "regionwatch.db")),
        alert_webhook=raw.get("alert_webhook"),
        targets=tuple(targets),
    )
    if settings.failure_threshold < 1 or settings.recovery_threshold < 1:
        raise ConfigError("thresholds must be >= 1")
    if settings.interval_seconds <= 0:
        raise ConfigError("interval_seconds must be > 0")
    return settings


def load_settings(path: str | Path) -> Settings:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {p}")
    return parse_settings(yaml.safe_load(p.read_text()) or {})
