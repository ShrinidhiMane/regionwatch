"""HTTP health probe with timeouts and retries with exponential backoff."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx

from .config import TargetConfig
from .models import ProbeResult

Sleep = Callable[[float], Awaitable[None]]


async def probe(
    client: httpx.AsyncClient,
    target: TargetConfig,
    retries: int = 2,
    base_backoff: float = 0.2,
    sleep: Sleep = asyncio.sleep,
    clock: Callable[[], float] = time.time,
) -> ProbeResult:
    """GET the target's health URL.

    - 2xx            -> healthy, return immediately
    - 5xx / timeout  -> transient, retry after 0.2s, 0.4s, 0.8s ...
    - 4xx            -> a config problem (wrong path?), retrying won't help
    """
    last_error: str | None = None
    last_status: int | None = None
    attempts = 0

    for attempt in range(retries + 1):
        attempts = attempt + 1
        start = time.perf_counter()
        try:
            resp = await client.get(target.url, timeout=target.timeout_seconds)
            latency_ms = (time.perf_counter() - start) * 1000
            last_status = resp.status_code
            if 200 <= resp.status_code < 300:
                return ProbeResult(target.id, True, clock(), resp.status_code,
                                   round(latency_ms, 2), None, attempts)
            last_error = f"HTTP {resp.status_code}"
            if resp.status_code < 500:
                break
        except httpx.TimeoutException:
            last_error, last_status = "timeout", None
        except httpx.HTTPError as exc:
            last_error, last_status = f"{type(exc).__name__}", None

        if attempt < retries:
            await sleep(base_backoff * (2**attempt))

    return ProbeResult(target.id, False, clock(), last_status, None, last_error, attempts)
