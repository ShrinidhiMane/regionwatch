from regionwatch.health import HealthTracker
from regionwatch.models import Health, ProbeResult


def ok(latency=50.0):
    return ProbeResult("t", True, 0.0, 200, latency)


def fail():
    return ProbeResult("t", False, 0.0, 503, None, "HTTP 503")


def tracker():
    return HealthTracker("t", failure_threshold=3, recovery_threshold=2, latency_slo_ms=500)


def test_first_success_is_healthy():
    t = tracker()
    tr = t.observe(ok())
    assert t.state == Health.HEALTHY
    assert (tr.old, tr.new) == (Health.UNKNOWN, Health.HEALTHY)


def test_single_failure_is_only_degraded():
    t = tracker()
    t.observe(ok())
    t.observe(fail())
    assert t.state == Health.DEGRADED


def test_down_after_threshold_consecutive_failures():
    t = tracker()
    t.observe(ok())
    for _ in range(2):
        t.observe(fail())
    assert t.state == Health.DEGRADED
    tr = t.observe(fail())
    assert t.state == Health.DOWN
    assert tr.new == Health.DOWN


def test_a_success_resets_the_failure_streak():
    t = tracker()
    t.observe(fail())
    t.observe(fail())
    t.observe(ok())
    t.observe(fail())
    assert t.state == Health.DEGRADED
    assert t.consecutive_failures == 1


def test_recovery_needs_a_streak_of_successes():
    t = tracker()
    for _ in range(3):
        t.observe(fail())
    assert t.state == Health.DOWN
    assert t.observe(ok()) is None  # one success is not trusted yet
    assert t.state == Health.DOWN
    tr = t.observe(ok())
    assert t.state == Health.HEALTHY
    assert (tr.old, tr.new) == (Health.DOWN, Health.HEALTHY)


def test_slow_response_is_degraded():
    t = tracker()
    t.observe(ok(latency=900))
    assert t.state == Health.DEGRADED
    t.observe(ok(latency=40))
    assert t.state == Health.HEALTHY


def test_no_transition_when_state_is_unchanged():
    t = tracker()
    t.observe(ok())
    assert t.observe(ok()) is None
