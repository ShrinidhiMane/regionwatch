"""HTTP API: status, history, events, Prometheus metrics, and a small dashboard."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .alerts import Alerter
from .config import Settings
from .monitor import Monitor
from .remediation import DockerRestartAction, NoopAction, WebhookAction
from .store import Store

log = logging.getLogger("regionwatch.api")
DASHBOARD = Path(__file__).with_name("dashboard.html")


def build_monitor(settings: Settings, client: httpx.AsyncClient) -> Monitor:
    actions = {
        "none": NoopAction(),
        "docker_restart": DockerRestartAction(),
        "webhook": WebhookAction(client),
    }
    return Monitor(settings, Store(settings.db_path), client,
                   Alerter(client, settings.alert_webhook), actions)


def create_app(settings: Settings, monitor: Monitor | None = None,
               start_background: bool = True) -> FastAPI:
    state: dict = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = None
        mon = monitor
        if mon is None:
            client = httpx.AsyncClient()
            mon = build_monitor(settings, client)
        state["monitor"] = mon
        stop = asyncio.Event()
        task = asyncio.create_task(mon.run_forever(stop)) if start_background else None
        try:
            yield
        finally:
            stop.set()
            if task:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if client:
                await client.aclose()

    app = FastAPI(title="RegionWatch", version="1.0.0", lifespan=lifespan)

    def mon() -> Monitor:
        return state["monitor"]

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def dashboard() -> str:
        return DASHBOARD.read_text()

    @app.get("/healthz")
    def healthz() -> dict:
        """Liveness of the monitor itself."""
        return {"status": "ok", "cycles": mon().cycles}

    @app.get("/status")
    def status() -> dict:
        targets = mon().snapshot()
        down = [t["id"] for t in targets if t["state"] == "DOWN"]
        return {"overall": "DOWN" if down else "OK", "down": down, "targets": targets}

    @app.get("/targets/{target_id}/history")
    def history(target_id: str, limit: int = Query(50, ge=1, le=1000)) -> dict:
        if target_id not in mon().trackers:
            raise HTTPException(status_code=404, detail=f"unknown target '{target_id}'")
        return {"target": target_id, "probes": mon().store.history(target_id, limit)}

    @app.get("/events")
    def events(limit: int = Query(100, ge=1, le=1000), target: str | None = None) -> dict:
        return {"events": mon().store.events(limit, target)}

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(mon().metrics.registry), media_type=CONTENT_TYPE_LATEST)

    return app
