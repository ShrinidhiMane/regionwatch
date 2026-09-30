"""SQLite storage for probe history and incident events."""

from __future__ import annotations

import sqlite3
import threading
import time

from .models import ProbeResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS probes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id TEXT NOT NULL,
    ts REAL NOT NULL,
    ok INTEGER NOT NULL,
    status_code INTEGER,
    latency_ms REAL,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_probes_target_ts ON probes(target_id, ts);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id TEXT NOT NULL,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,      -- transition | remediation | escalation
    detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def record_probe(self, r: ProbeResult) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO probes(target_id, ts, ok, status_code, latency_ms, error, attempts)"
                " VALUES (?,?,?,?,?,?,?)",
                (r.target_id, r.timestamp, int(r.ok), r.status_code, r.latency_ms, r.error,
                 r.attempts),
            )
            self._conn.commit()

    def record_event(self, target_id: str, kind: str, detail: str, ts: float | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events(target_id, ts, kind, detail) VALUES (?,?,?,?)",
                (target_id, ts if ts is not None else time.time(), kind, detail),
            )
            self._conn.commit()

    def history(self, target_id: str, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, ok, status_code, latency_ms, error, attempts FROM probes"
                " WHERE target_id=? ORDER BY ts DESC, id DESC LIMIT ?",
                (target_id, limit),
            ).fetchall()
        return [dict(r) | {"ok": bool(r["ok"])} for r in rows]

    def events(self, limit: int = 100, target_id: str | None = None) -> list[dict]:
        q = "SELECT target_id, ts, kind, detail FROM events"
        args: tuple = ()
        if target_id:
            q += " WHERE target_id=?"
            args = (target_id,)
        q += " ORDER BY ts DESC, id DESC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(q, (*args, limit)).fetchall()
        return [dict(r) for r in rows]

    def availability(self, target_id: str, since_ts: float) -> float | None:
        """Share of successful probes since `since_ts`, e.g. 0.998. None if no data."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n, SUM(ok) AS good FROM probes WHERE target_id=? AND ts>=?",
                (target_id, since_ts),
            ).fetchone()
        if not row["n"]:
            return None
        return round(row["good"] / row["n"], 4)

    def p95_latency(self, target_id: str, since_ts: float) -> float | None:
        with self._lock:
            rows = self._conn.execute(
                "SELECT latency_ms FROM probes WHERE target_id=? AND ts>=? AND ok=1"
                " AND latency_ms IS NOT NULL ORDER BY latency_ms",
                (target_id, since_ts),
            ).fetchall()
        if not rows:
            return None
        idx = max(0, int(round(0.95 * len(rows))) - 1)
        return rows[idx]["latency_ms"]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
