"""SQLite storage. Plain sqlite3, one connection per request/operation."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .config import get_env

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
    source TEXT PRIMARY KEY,
    last_attempt TEXT,
    last_success TEXT,
    last_error TEXT,
    info TEXT
);

-- One row per calendar day of Garmin wellness data.
CREATE TABLE IF NOT EXISTS daily_metrics (
    date TEXT PRIMARY KEY,
    resting_hr REAL,
    hrv REAL,
    hrv_baseline_low REAL,
    hrv_baseline_high REAL,
    hrv_status TEXT,
    sleep_seconds REAL,
    sleep_score REAL,
    body_battery_high REAL,
    body_battery_low REAL,
    stress_avg REAL,
    steps REAL,
    updated_at TEXT
);

-- A workout is what the user did; it groups one record per source (R12).
CREATE TABLE IF NOT EXISTS workouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_effort INTEGER,
    user_notes TEXT
);

CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id INTEGER REFERENCES workouts(id),
    source TEXT NOT NULL,              -- garmin | hevy | manual
    external_id TEXT,
    sport TEXT NOT NULL,
    title TEXT,
    start_time TEXT NOT NULL,          -- local time, ISO 'YYYY-MM-DDTHH:MM:SS'
    duration_min REAL NOT NULL,
    effort INTEGER,                    -- manual: user effort; hevy: estimate from set RPE
    effort_estimated INTEGER NOT NULL DEFAULT 0,
    estimated INTEGER NOT NULL DEFAULT 0,   -- backfilled session (R12a)
    notes TEXT,
    avg_hr REAL,
    max_hr REAL,
    zone_seconds TEXT,                 -- JSON [z1..z5] seconds
    distance_m REAL,
    calories REAL,
    detail TEXT,                       -- JSON (Hevy exercises)
    deleted INTEGER NOT NULL DEFAULT 0,     -- tombstone so imports do not resurrect it
    created_at TEXT,
    updated_at TEXT,
    UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_records_start ON records(start_time);
CREATE INDEX IF NOT EXISTS idx_records_workout ON records(workout_id);

-- Pairs the user un-merged; never auto-merge them again.
CREATE TABLE IF NOT EXISTS merge_exclusions (
    record_a INTEGER NOT NULL,
    record_b INTEGER NOT NULL,
    PRIMARY KEY (record_a, record_b)
);

CREATE TABLE IF NOT EXISTS checkins (
    date TEXT PRIMARY KEY,
    soreness INTEGER,                  -- 1 none .. 5 very sore
    energy INTEGER,                    -- 1 drained .. 5 great
    ill INTEGER NOT NULL DEFAULT 0,
    allergy INTEGER NOT NULL DEFAULT 0,
    pain_note TEXT,
    notes TEXT,
    updated_at TEXT
);
"""


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(path) if path else get_env().database_path
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False)  # one connection per request
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def session(path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_setting(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )


def get_sync_state(conn: sqlite3.Connection, source: str) -> dict:
    row = conn.execute("SELECT * FROM sync_state WHERE source = ?", (source,)).fetchone()
    if not row:
        return {"source": source, "last_attempt": None, "last_success": None, "last_error": None, "info": {}}
    d = dict(row)
    d["info"] = json.loads(d["info"]) if d["info"] else {}
    return d


def update_sync_state(conn: sqlite3.Connection, source: str, **fields: Any) -> None:
    state = get_sync_state(conn, source)
    state.update(fields)
    conn.execute(
        "INSERT INTO sync_state(source, last_attempt, last_success, last_error, info) VALUES(?,?,?,?,?) "
        "ON CONFLICT(source) DO UPDATE SET last_attempt=excluded.last_attempt, "
        "last_success=excluded.last_success, last_error=excluded.last_error, info=excluded.info",
        (source, state["last_attempt"], state["last_success"], state["last_error"], json.dumps(state["info"])),
    )
