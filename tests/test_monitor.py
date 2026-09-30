"""End-to-end behaviour of the monitor loop against a fake HTTP backend."""

import pytest

from regionwatch.alerts import Alerter
from regionwatch.models import Health
from regionwatch.monitor import Monitor
from regionwatch.remediation import NoopAction, WebhookAction
from regionwatch.store import Store

from .conftest import make_settings, no_sleep

EAST = "http://east/health"
HOOK = "http://automation/remediate"


@pytest.fixture
def monitor(client, clock):
    settings = make_settings()
    return Monitor(settings, Store(":memory:"), client, Alerter(),
                   {"none": NoopAction(), "webhook": WebhookAction(client)},
                   clock=clock, sleep=no_sleep)


def remediation_posts(backend):
    return [p for p in backend.posts if p[0] == HOOK]


async def test_all_healthy(monitor):
    await monitor.run_once()
    assert {t["state"] for t in monitor.snapshot()} == {"HEALTHY"}
    assert monitor.alerter.sent == []


async def test_outage_goes_down_alerts_and_remediates(monitor, backend):
    await monitor.run_once()
    backend.modes[EAST] = "fail"
    for _ in range(3):
        await monitor.run_once()

    assert monitor.trackers["api-east"].state == Health.DOWN
    assert monitor.trackers["api-west"].state == Health.HEALTHY  # other region unaffected
    assert any("CRITICAL" in a and "api-east" in a for a in monitor.alerter.sent)
    posts = remediation_posts(backend)
    assert len(posts) == 1
    assert posts[0][1] == {"target": "api-east", "region": "east", "action": "remediate"}


async def test_cooldown_prevents_restart_loops(monitor, backend, clock):
    backend.modes[EAST] = "fail"
    for _ in range(6):  # DOWN at cycle 3, then keeps failing, but no time passes
        await monitor.run_once()
    assert len(remediation_posts(backend)) == 1

    clock.advance(11)  # past the 10 s cooldown
    await monitor.run_once()
    assert len(remediation_posts(backend)) == 2


async def test_escalates_to_on_call_after_max_attempts(monitor, backend, clock):
    backend.modes[EAST] = "fail"
    for _ in range(3):
        await monitor.run_once()
    clock.advance(11)
    await monitor.run_once()  # attempt 2 (max_attempts = 2)
    clock.advance(11)
    await monitor.run_once()  # over the cap -> page
    clock.advance(11)
    await monitor.run_once()  # already paged: stay quiet

    assert len(remediation_posts(backend)) == 2
    pages = [a for a in monitor.alerter.sent if a.startswith("[PAGE]")]
    assert len(pages) == 1
    kinds = [e["kind"] for e in monitor.store.events(target_id="api-east")]
    assert "escalation" in kinds


async def test_recovery_resolves_and_resets_attempts(monitor, backend):
    backend.modes[EAST] = "fail"
    for _ in range(3):
        await monitor.run_once()
    assert monitor.policy.attempts("api-east") == 1

    backend.modes[EAST] = "ok"
    await monitor.run_once()
    assert monitor.trackers["api-east"].state == Health.DOWN  # needs 2 successes
    await monitor.run_once()
    assert monitor.trackers["api-east"].state == Health.HEALTHY
    assert monitor.policy.attempts("api-east") == 0
    assert any(a.startswith("[RESOLVED]") for a in monitor.alerter.sent)


async def test_failed_remediation_does_not_crash_monitor(client, clock, backend):
    class Broken:
        name = "webhook"

        async def run(self, target):
            raise RuntimeError("automation endpoint unavailable")

    mon = Monitor(make_settings(), Store(":memory:"), client, Alerter(),
                  {"webhook": Broken()}, clock=clock, sleep=no_sleep)
    backend.modes[EAST] = "fail"
    for _ in range(3):
        await mon.run_once()
    details = [e["detail"] for e in mon.store.events(target_id="api-east")]
    assert any("failed: automation endpoint unavailable" in d for d in details)


async def test_snapshot_reports_availability(monitor, backend):
    await monitor.run_once()
    backend.modes[EAST] = "fail"
    await monitor.run_once()
    east = next(t for t in monitor.snapshot() if t["id"] == "api-east")
    assert east["availability_1h"] == 0.5
    assert east["last_error"] == "HTTP 503"


async def test_docker_restart_action_restarts_the_right_container(client, clock, backend):
    from regionwatch.config import parse_settings
    from regionwatch.remediation import DockerRestartAction

    from .conftest import make_raw

    class FakeContainer:
        def __init__(self):
            self.restarts = 0

        def restart(self, timeout):
            self.restarts += 1

    class FakeContainers:
        def __init__(self):
            self.by_name = {"rw-api-east": FakeContainer()}

        def get(self, name):
            return self.by_name[name]

    class FakeDocker:
        containers = FakeContainers()

    fake = FakeDocker()
    raw = make_raw()
    raw["targets"][0]["remediation"] = {"action": "docker_restart", "container": "rw-api-east",
                                        "cooldown_seconds": 10, "max_attempts": 3}
    mon = Monitor(parse_settings(raw), Store(":memory:"), client, Alerter(),
                  {"docker_restart": DockerRestartAction(client=fake)},
                  clock=clock, sleep=no_sleep)
    backend.modes[EAST] = "fail"
    for _ in range(3):
        await mon.run_once()
    assert fake.containers.by_name["rw-api-east"].restarts == 1
    details = [e["detail"] for e in mon.store.events(target_id="api-east")]
    assert "attempt 1: restarted container rw-api-east" in details
