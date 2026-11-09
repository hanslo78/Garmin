"""Hevy CSV import (requirements 3.2, R9, R10).

Self-contained module: if the account moves to Hevy Pro, an API client can
produce the same `parse` output and reuse `store`.

NOTE: the column names below follow Hevy's public export format but have not
yet been confirmed against a real export from this account. Column lookup is
tolerant (case, spaces, a few aliases) and unknown layouts fail with a clear
message naming the columns that were found.
"""
from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime
from statistics import mean

from .. import workouts as wk
from ..db import now_iso, update_sync_state

ALIASES = {
    "title": ["title", "workout_name", "workout_title", "name"],
    "start": ["start_time", "start", "date"],
    "end": ["end_time", "end"],
    "description": ["description", "workout_notes"],
    "exercise": ["exercise_title", "exercise_name", "exercise"],
    "exercise_notes": ["exercise_notes"],
    "set_type": ["set_type"],
    "weight_kg": ["weight_kg", "weight"],
    "weight_lbs": ["weight_lbs"],
    "reps": ["reps"],
    "distance_km": ["distance_km"],
    "duration_s": ["duration_seconds", "seconds"],
    "rpe": ["rpe"],
}
DATE_FORMATS = (
    "%d %b %Y, %H:%M", "%d %b %Y, %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%b %d, %Y, %I:%M %p",
)


class HevyFormatError(ValueError):
    pass


def _parse_time(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _num(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def parse(text: str) -> list[dict]:
    """Turn a Hevy export into a list of workouts with exercises and sets."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        raise HevyFormatError("The file is empty.")
    norm = {f.strip().lower().replace(" ", "_"): f for f in reader.fieldnames}
    col = {key: next((norm[a] for a in names if a in norm), None) for key, names in ALIASES.items()}
    if not col["start"] or not col["exercise"]:
        raise HevyFormatError(
            "This does not look like a Hevy workout export. Columns found: " + ", ".join(reader.fieldnames)
        )

    def get(row: dict, key: str) -> str | None:
        return row.get(col[key]) if col[key] else None

    grouped: dict[str, dict] = {}
    for row in reader:
        start = _parse_time(get(row, "start") or "")
        if start is None:
            continue
        key = start.isoformat()
        w = grouped.get(key)
        if w is None:
            end = _parse_time(get(row, "end") or "")
            duration = (end - start).total_seconds() / 60.0 if end and end > start else 60.0
            w = grouped[key] = {
                "external_id": key,
                "title": (get(row, "title") or "Gym").strip(),
                "start_time": key,
                "duration_min": round(duration, 1),
                "notes": (get(row, "description") or "").strip() or None,
                "exercises": [],
            }
        name = (get(row, "exercise") or "").strip()
        if not name:
            continue
        if not w["exercises"] or w["exercises"][-1]["name"] != name:
            w["exercises"].append({"name": name, "sets": []})
        weight = _num(get(row, "weight_kg"))
        if weight is None and (lbs := _num(get(row, "weight_lbs"))) is not None:
            weight = round(lbs * 0.45359237, 2)
        w["exercises"][-1]["sets"].append({
            "type": (get(row, "set_type") or "normal").strip() or "normal",
            "weight_kg": weight,
            "reps": _num(get(row, "reps")),
            "rpe": _num(get(row, "rpe")),
            "distance_km": _num(get(row, "distance_km")),
            "duration_s": _num(get(row, "duration_s")),
        })
    out = []
    for w in grouped.values():
        rpes = [s["rpe"] for e in w["exercises"] for s in e["sets"] if s["rpe"] and s["type"] != "warmup"]
        # R10: Hevy has no workout-level effort; estimate from set RPE where logged.
        w["effort"] = max(1, min(10, round(mean(rpes)))) if rpes else None
        out.append(w)
    return sorted(out, key=lambda w: w["start_time"])


def summarize_exercises(exercises: list[dict] | None, limit: int = 8) -> str:
    """Short text like 'Bench Press 3x8 @ 60 kg; Squat 4x5 @ 80 kg'."""
    parts = []
    for ex in (exercises or [])[:limit]:
        sets = [s for s in ex["sets"] if s.get("type") != "warmup"] or ex["sets"]
        if not sets:
            continue
        weights = [s["weight_kg"] for s in sets if s.get("weight_kg")]
        reps = [int(s["reps"]) for s in sets if s.get("reps")]
        text = f"{ex['name']} {len(sets)}x{max(reps)}" if reps else f"{ex['name']} {len(sets)} sets"
        if weights:
            text += f" @ {max(weights):g} kg"
        parts.append(text)
    extra = len(exercises or []) - limit
    return "; ".join(parts) + (f"; +{extra} more" if extra > 0 else "")


def import_csv(conn: sqlite3.Connection, text: str) -> dict:
    """Store an export. Re-importing the full history never creates duplicates."""
    try:
        parsed = parse(text)
    except HevyFormatError as exc:
        update_sync_state(conn, "hevy", last_attempt=now_iso(), last_error=str(exc))
        raise
    counts = {"added": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    for w in parsed:
        result = wk.upsert_external(conn, "hevy", w["external_id"], {
            "sport": "strength",
            "title": w["title"],
            "start_time": w["start_time"],
            "duration_min": w["duration_min"],
            "effort": w["effort"],
            "effort_estimated": w["effort"] is not None,
            "notes": w["notes"],
            "detail": w["exercises"],
        })
        counts[result] += 1
    counts["total"] = len(parsed)
    stamp = now_iso()
    update_sync_state(conn, "hevy", last_attempt=stamp, last_success=stamp, last_error=None, info=counts)
    return counts
