"""A tiny service that stands in for a real regional service.

It has a /health endpoint and "chaos" endpoints so you can inject failures and
watch RegionWatch detect and fix them:

    POST /chaos/slow     -> /health responds in ~1.2 s (breaks the latency SLO)
    POST /chaos/failing  -> /health returns 503
    POST /chaos/crash    -> the process exits (container stops)
    POST /chaos/healthy  -> back to normal
"""

from __future__ import annotations

import asyncio
import os
import threading

from fastapi import FastAPI, HTTPException, Response

SERVICE = os.getenv("SERVICE_NAME", "demo-service")
REGION = os.getenv("REGION", "local")
MODES = {"healthy", "slow", "failing", "crash"}

app = FastAPI(title=f"{SERVICE} ({REGION})")
state = {"mode": "healthy"}


@app.get("/health")
async def health(response: Response) -> dict:
    mode = state["mode"]
    if mode == "slow":
        await asyncio.sleep(1.2)
    if mode == "failing":
        response.status_code = 503
        return {"service": SERVICE, "region": REGION, "status": "failing"}
    return {"service": SERVICE, "region": REGION, "status": "ok"}


@app.post("/chaos/{mode}")
def chaos(mode: str) -> dict:
    if mode not in MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {sorted(MODES)}")
    if mode == "crash":
        # exit shortly after replying so the caller gets a response
        threading.Timer(0.2, lambda: os._exit(1)).start()
    state["mode"] = mode
    return {"service": SERVICE, "mode": mode}


@app.get("/")
def root() -> dict:
    return {"service": SERVICE, "region": REGION, "mode": state["mode"]}
