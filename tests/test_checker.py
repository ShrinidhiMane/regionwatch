from regionwatch.checker import probe
from regionwatch.config import TargetConfig

T = TargetConfig(id="t", region="r", url="http://svc/health")


class SleepRecorder:
    def __init__(self):
        self.calls = []

    async def __call__(self, seconds):
        self.calls.append(seconds)


async def test_healthy_probe(client, backend):
    r = await probe(client, T, retries=2)
    assert r.ok and r.status_code == 200 and r.attempts == 1
    assert r.latency_ms is not None


async def test_5xx_retries_with_exponential_backoff(client, backend):
    backend.modes["http://svc/health"] = "fail"
    sleep = SleepRecorder()
    r = await probe(client, T, retries=2, base_backoff=0.2, sleep=sleep)
    assert not r.ok
    assert r.error == "HTTP 503" and r.status_code == 503
    assert r.attempts == 3
    assert sleep.calls == [0.2, 0.4]
    assert len(backend.calls) == 3


async def test_timeout_is_reported(client, backend):
    backend.modes["http://svc/health"] = "timeout"
    r = await probe(client, T, retries=1, sleep=SleepRecorder())
    assert not r.ok and r.error == "timeout" and r.status_code is None


async def test_connection_refused_is_reported(client, backend):
    backend.modes["http://svc/health"] = "refused"
    r = await probe(client, T, retries=0, sleep=SleepRecorder())
    assert not r.ok and r.error == "ConnectError"


async def test_4xx_is_not_retried(client, backend):
    backend.modes["http://svc/health"] = "notfound"
    sleep = SleepRecorder()
    r = await probe(client, T, retries=3, sleep=sleep)
    assert not r.ok and r.status_code == 404
    assert r.attempts == 1 and sleep.calls == []
