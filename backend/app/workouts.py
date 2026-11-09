"""Workout storage: records from each source, merging (R12) and the combined view."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Mapping

from .config import STRENGTH_SPORTS
from .db import now_iso
from .engine.load import calibrate_scale, is_hard_session, session_load, zone_weighted_minutes

RECORD_FIELDS = (
    "source", "external_id", "sport", "title", "start_time", "duration_min", "effort",
    "effort_estimated", "estimated", "notes", "avg_hr", "max_hr", "zone_seconds",
    "distance_m", "calories", "detail",
)
SOURCE_PRIORITY = {"garmin": 0, "hevy": 1, "manual": 2}


def sport_category(sport: str) -> str:
    return "strength" if sport in STRENGTH_SPORTS else sport


def _encode(fields: Mapping[str, Any]) -> dict:
    out = {k: fields.get(k) for k in RECORD_FIELDS if k in fields}
    for key in ("zone_seconds", "detail"):
        if key in out and out[key] is not None and not isinstance(out[key], str):
            out[key] = json.dumps(out[key])
    for key in ("effort_estimated", "estimated"):
        if key in out:
            out[key] = int(bool(out[key]))
    return out


def insert_record(conn: sqlite3.Connection, **fields: Any) -> int:
    """Insert a record as its own workout, then merge it if it overlaps another source."""
    data = _encode(fields)
    data["created_at"] = data["updated_at"] = now_iso()
    data["workout_id"] = conn.execute("INSERT INTO workouts DEFAULT VALUES").lastrowid
    cols = ", ".join(data)
    record_id = conn.execute(
        f"INSERT INTO records({cols}) VALUES({', '.join('?' for _ in data)})", list(data.values())
    ).lastrowid
    auto_merge(conn, record_id)
    return record_id


def upsert_external(conn: sqlite3.Connection, source: str, external_id: str, fields: Mapping[str, Any]) -> str:
    """Insert or update an imported record. Returns added | updated | unchanged | skipped."""
    data = _encode({**fields, "source": source, "external_id": external_id})
    row = conn.execute(
        "SELECT * FROM records WHERE source = ? AND external_id = ?", (source, external_id)
    ).fetchone()
    if row is None:
        insert_record(conn, **data)
        return "added"
    if row["deleted"]:
        return "skipped"
    changed = {k: v for k, v in data.items() if row[k] != v}
    if not changed:
        return "unchanged"
    changed["updated_at"] = now_iso()
    conn.execute(
        f"UPDATE records SET {', '.join(f'{k} = ?' for k in changed)} WHERE id = ?",
        [*changed.values(), row["id"]],
    )
    return "updated"


# ---------- merging ----------

def _interval(rec: Mapping) -> tuple[datetime, datetime]:
    start = datetime.fromisoformat(rec["start_time"])
    return start, start + timedelta(minutes=rec["duration_min"] or 0)


def _match_score(a: Mapping, b: Mapping) -> float:
    """> 0 when two records from different sources look like the same session."""
    (a0, a1), (b0, b1) = _interval(a), _interval(b)
    overlap = (min(a1, b1) - max(a0, b0)).total_seconds() / 60.0
    shorter = min(a["duration_min"] or 0, b["duration_min"] or 0)
    if shorter > 0 and overlap >= 0.5 * shorter:
        return 1000 + overlap
    # Manual logs have rough times: same day and same kind of sport is enough.
    if "manual" in (a["source"], b["source"]) and a0.date() == b0.date() \
            and sport_category(a["sport"]) == sport_category(b["sport"]):
        return 500 - abs((a0 - b0).total_seconds()) / 3600.0
    return 0.0


def auto_merge(conn: sqlite3.Connection, record_id: int) -> int | None:
    """Merge the record's workout into an overlapping workout from other sources."""
    rec = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
    if rec is None or rec["deleted"]:
        return None
    mine = conn.execute("SELECT * FROM records WHERE workout_id = ?", (rec["workout_id"],)).fetchall()
    my_sources = {r["source"] for r in mine}
    day = rec["start_time"][:10]
    lo = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    hi = (date.fromisoformat(day) + timedelta(days=2)).isoformat()
    candidates = conn.execute(
        "SELECT * FROM records WHERE deleted = 0 AND workout_id != ? AND start_time >= ? AND start_time < ?",
        (rec["workout_id"], lo, hi),
    ).fetchall()
    excluded = {
        tuple(sorted((r["record_a"], r["record_b"])))
        for r in conn.execute("SELECT * FROM merge_exclusions")
    }
    best, best_score = None, 0.0
    for cand in candidates:
        if cand["source"] == rec["source"]:
            continue
        their = conn.execute("SELECT id, source FROM records WHERE workout_id = ?", (cand["workout_id"],)).fetchall()
        if my_sources & {r["source"] for r in their}:
            continue  # at most one record per source in a workout
        if any(tuple(sorted((m["id"], t["id"]))) in excluded for m in mine for t in their):
            continue
        score = _match_score(rec, cand)
        if score > best_score:
            best, best_score = cand, score
    if best is None:
        return None
    target, old = best["workout_id"], rec["workout_id"]
    old_row = conn.execute("SELECT * FROM workouts WHERE id = ?", (old,)).fetchone()
    conn.execute(
        "UPDATE workouts SET user_effort = COALESCE(user_effort, ?), user_notes = COALESCE(user_notes, ?) WHERE id = ?",
        (old_row["user_effort"], old_row["user_notes"], target),
    )
    conn.execute("UPDATE records SET workout_id = ? WHERE workout_id = ?", (target, old))
    conn.execute("DELETE FROM workouts WHERE id = ?", (old,))
    return target


def unmerge(conn: sqlite3.Connection, workout_id: int, record_id: int) -> int:
    """Split one record out of a merged workout and remember not to merge it again."""
    records = conn.execute("SELECT id FROM records WHERE workout_id = ?", (workout_id,)).fetchall()
    ids = [r["id"] for r in records]
    if record_id not in ids or len(ids) < 2:
        raise ValueError("Record is not part of a merged workout")
    for other in ids:
        if other != record_id:
            a, b = sorted((record_id, other))
            conn.execute("INSERT OR IGNORE INTO merge_exclusions(record_a, record_b) VALUES(?, ?)", (a, b))
    new_id = conn.execute("INSERT INTO workouts DEFAULT VALUES").lastrowid
    conn.execute("UPDATE records SET workout_id = ? WHERE id = ?", (new_id, record_id))
    return new_id


# ---------- editing ----------

def update_workout(conn: sqlite3.Connection, workout_id: int, changes: Mapping[str, Any]) -> None:
    if conn.execute("SELECT 1 FROM workouts WHERE id = ?", (workout_id,)).fetchone() is None:
        raise KeyError(workout_id)
    manual = conn.execute(
        "SELECT * FROM records WHERE workout_id = ? AND source = 'manual'", (workout_id,)
    ).fetchone()
    if "effort" in changes:
        conn.execute("UPDATE workouts SET user_effort = ? WHERE id = ?", (changes["effort"], workout_id))
        if manual is not None and changes["effort"] is not None:
            conn.execute("UPDATE records SET effort = ? WHERE id = ?", (changes["effort"], manual["id"]))
    if "notes" in changes:
        conn.execute("UPDATE workouts SET user_notes = ? WHERE id = ?", (changes["notes"], workout_id))
    if manual is not None:
        fields = {k: changes[k] for k in ("sport", "start_time", "duration_min") if changes.get(k) is not None}
        if fields:
            fields["updated_at"] = now_iso()
            conn.execute(
                f"UPDATE records SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                [*fields.values(), manual["id"]],
            )


def delete_workout(conn: sqlite3.Connection, workout_id: int) -> None:
    """Manual records are removed; imported ones are tombstoned so a sync does not bring them back."""
    conn.execute("DELETE FROM records WHERE workout_id = ? AND source = 'manual'", (workout_id,))
    conn.execute("UPDATE records SET deleted = 1, workout_id = NULL WHERE workout_id = ?", (workout_id,))
    conn.execute("DELETE FROM workouts WHERE id = ?", (workout_id,))


# ---------- combined view ----------

def _zones(rec: Mapping) -> list[float] | None:
    if not rec["zone_seconds"]:
        return None
    zones = json.loads(rec["zone_seconds"])
    return zones if any(zones) else None


def _load_groups(conn: sqlite3.Connection, start: str | None, end: str | None) -> list[tuple[sqlite3.Row, list[sqlite3.Row]]]:
    sql = "SELECT * FROM records WHERE deleted = 0 AND workout_id IS NOT NULL"
    workouts = {r["id"]: r for r in conn.execute("SELECT * FROM workouts")}
    groups: dict[int, list[sqlite3.Row]] = {}
    for rec in conn.execute(sql):
        groups.setdefault(rec["workout_id"], []).append(rec)
    out = []
    for wid, recs in groups.items():
        recs.sort(key=lambda r: SOURCE_PRIORITY.get(r["source"], 9))
        day = recs[0]["start_time"][:10]
        if (start and day < start) or (end and day > end):
            continue
        out.append((workouts[wid], recs))
    return out


def _base(workout: sqlite3.Row, recs: list[sqlite3.Row]) -> dict:
    by = {r["source"]: r for r in recs}
    garmin, hevy, manual = by.get("garmin"), by.get("hevy"), by.get("manual")
    primary = recs[0]
    sport = manual["sport"] if manual else ("strength" if hevy else primary["sport"])
    if workout["user_effort"] is not None:
        effort, effort_source = workout["user_effort"], "user"
    elif manual is not None and manual["effort"] is not None:
        effort, effort_source = manual["effort"], "user"
    elif hevy is not None and hevy["effort"] is not None:
        effort, effort_source = hevy["effort"], "estimated"
    else:
        effort, effort_source = None, "none"
    return {
        "id": workout["id"],
        "date": primary["start_time"][:10],
        "start_time": primary["start_time"],
        "duration_min": round(primary["duration_min"], 1),
        "sport": sport,
        "title": (hevy or garmin or manual)["title"] or sport.replace("_", " ").title(),
        "effort": effort,
        "effort_source": effort_source,
        "is_strength": sport in STRENGTH_SPORTS or hevy is not None,
        "zone_seconds": _zones(garmin) if garmin else None,
        "avg_hr": garmin["avg_hr"] if garmin else None,
        "max_hr": garmin["max_hr"] if garmin else None,
        "distance_m": garmin["distance_m"] if garmin else None,
        "estimated": any(r["estimated"] for r in recs),
        "notes": workout["user_notes"] or (manual["notes"] if manual else None),
        "sources": [r["source"] for r in recs],
        "exercises": json.loads(hevy["detail"]) if hevy is not None and hevy["detail"] else None,
        "records": [
            {"id": r["id"], "source": r["source"], "sport": r["sport"], "title": r["title"],
             "start_time": r["start_time"], "duration_min": round(r["duration_min"], 1)}
            for r in recs
        ],
    }


def hr_scale(conn: sqlite3.Connection, cfg: Mapping) -> float:
    """Calibration factor from sessions that have both heart rate and a user effort (5.1)."""
    pairs = []
    for workout, recs in _load_groups(conn, None, None):
        w = _base(workout, recs)
        if w["zone_seconds"] and not w["is_strength"] and w["effort_source"] == "user":
            pairs.append((zone_weighted_minutes(w["zone_seconds"], cfg["zone_weights"]), w["duration_min"] * w["effort"]))
    return calibrate_scale(pairs, cfg)


def list_workouts(conn: sqlite3.Connection, cfg: Mapping, start: str | None = None, end: str | None = None) -> list[dict]:
    """All workouts (newest first) with their load on the common scale."""
    scale = hr_scale(conn, cfg)
    out = []
    for workout, recs in _load_groups(conn, start, end):
        w = _base(workout, recs)
        load, method = session_load(w["duration_min"], w["effort"], w["zone_seconds"], w["is_strength"], cfg, scale)
        w["load"], w["load_method"] = load, method
        w["load_estimated"] = method == "effort" and w["effort_source"] != "user"
        effective = w["effort"] if w["effort"] is not None else (
            load / w["duration_min"] if method == "heart_rate" and w["duration_min"] > 0 else None)
        w["hard"] = is_hard_session(w["duration_min"], effective, load, cfg)
        out.append(w)
    out.sort(key=lambda w: w["start_time"], reverse=True)
    return out
