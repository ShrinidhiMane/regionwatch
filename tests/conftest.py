"""Shared test helpers: a fake HTTP backend and a controllable clock."""

from __future__ import annotations

import httpx
import pytest

from regionwatch.config import parse_settings


class FakeBackend:
    """Maps URL -> behaviour. Behaviour is 'ok', 'fail' (503), 'timeout', 'notfound'."""

    def __init__(self) -> None:
        self.modes: dict[str, str] = {}
        self.calls: list[str] = []
        self.posts: list[tuple[str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST":
            import json

            self.posts.append((url, json.loads(request.content or b"{}")))
            return httpx.Response(200, json={"ok": True})
        self.calls.append(url)
        mode = self.modes.get(url, "ok")
        if mode == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if mode == "refused":
            raise httpx.ConnectError("refused", request=request)
        if mode == "fail":
            return httpx.Response(503, json={"status": "failing"})
        if mode == "notfound":
            return httpx.Response(404)
        return httpx.Response(200, json={"status": "ok"})


class Clock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def no_sleep(_seconds: float) -> None:
    return None


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
async def client(backend: FakeBackend):
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend.handler)) as c:
        yield c


@pytest.fixture
def clock() -> Clock:
    return Clock()


def make_raw(**overrides) -> dict:
    """A valid raw config dict. api-east auto-remediates through a webhook."""
    raw = {
        "interval_seconds": 1,
        "failure_threshold": 3,
        "recovery_threshold": 2,
        "latency_slo_ms": 500,
        "retries": 1,
        "db_path": ":memory:",
        "targets": [
            {"id": "api-east", "region": "east", "url": "http://east/health",
             "remediation": {"action": "webhook", "url": "http://automation/remediate",
                             "cooldown_seconds": 10, "max_attempts": 2}},
            {"id": "api-west", "region": "west", "url": "http://west/health"},
        ],
    }
    raw.update(overrides)
    return raw


def make_settings(**overrides):
    return parse_settings(make_raw(**overrides))
