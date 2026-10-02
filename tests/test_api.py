import pytest
from fastapi.testclient import TestClient

from regionwatch.alerts import Alerter
from regionwatch.api import create_app
from regionwatch.monitor import Monitor
from regionwatch.remediation import NoopAction
from regionwatch.store import Store

from .conftest import make_settings, no_sleep


@pytest.fixture
async def app_and_monitor(client, clock):
    settings = make_settings()
    mon = Monitor(settings, Store(":memory:"), client, Alerter(), {"none": NoopAction()},
                  clock=clock, sleep=no_sleep)
    await mon.run_once()
    return create_app(settings, monitor=mon, start_background=False), mon


def test_status_and_history(app_and_monitor):
    app, _ = app_and_monitor
    with TestClient(app) as http:
        s = http.get("/status").json()
        assert s["overall"] == "OK"
        assert {t["id"] for t in s["targets"]} == {"api-east", "api-west"}

        h = http.get("/targets/api-east/history").json()
        assert len(h["probes"]) == 1 and h["probes"][0]["ok"] is True

        assert http.get("/targets/nope/history").status_code == 404
        assert http.get("/healthz").json()["cycles"] == 1


def test_metrics_endpoint(app_and_monitor):
    app, _ = app_and_monitor
    with TestClient(app) as http:
        body = http.get("/metrics").text
        assert 'regionwatch_target_up{region="east",target="api-east"} 1.0' in body
        assert "regionwatch_probe_latency_seconds_bucket" in body


def test_dashboard_served(app_and_monitor):
    app, _ = app_and_monitor
    with TestClient(app) as http:
        r = http.get("/")
        assert r.status_code == 200 and "RegionWatch" in r.text


async def _app(client, clock, **overrides):
    settings = make_settings(**overrides)
    mon = Monitor(settings, Store(":memory:"), client, Alerter(), {"none": NoopAction()},
                  clock=clock, sleep=no_sleep)
    return create_app(settings, monitor=mon, start_background=False)


async def test_demo_endpoints_absent_by_default(client, clock):
    app = await _app(client, clock)
    with TestClient(app) as http:
        assert http.get("/demo").status_code == 404
        assert http.post("/demo/chaos/api-east/failing").status_code == 404


async def test_demo_chaos_forwards_fault_to_the_target(client, clock, backend):
    app = await _app(client, clock, demo_mode=True)
    with TestClient(app) as http:
        assert http.get("/demo").json() == {"enabled": True, "faults": ["slow", "failing"]}
        r = http.post("/demo/chaos/api-east/failing")
        assert r.status_code == 200
    assert backend.posts[-1][0] == "http://east/chaos/failing"


async def test_demo_chaos_rejects_unknown_target_and_crash(client, clock):
    app = await _app(client, clock, demo_mode=True)
    with TestClient(app) as http:
        assert http.post("/demo/chaos/nope/failing").status_code == 404
        assert http.post("/demo/chaos/api-east/crash").status_code == 400
