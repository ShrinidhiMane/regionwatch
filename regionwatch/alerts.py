"""Alerting: structured log line always, plus an optional Slack-style webhook."""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger("regionwatch.alerts")


class Alerter:
    def __init__(self, client: httpx.AsyncClient | None = None, webhook_url: str | None = None):
        self._client = client
        self._url = webhook_url
        self.sent: list[str] = []  # kept for tests and the /events API

    async def send(self, severity: str, message: str) -> None:
        text = f"[{severity}] {message}"
        self.sent.append(text)
        level = logging.ERROR if severity in ("CRITICAL", "PAGE") else logging.WARNING
        log.log(level, text)
        if self._client and self._url:
            try:
                await self._client.post(self._url, json={"text": text}, timeout=5)
            except httpx.HTTPError as exc:  # alerting must never crash the monitor
                log.error("alert webhook failed: %s", exc)
