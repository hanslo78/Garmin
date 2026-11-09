"""Fill a database with made-up data to try the app without a Garmin key.

Usage (never point this at your real database):
    DATABASE_PATH=data/demo.db python scripts/seed_demo.py
"""
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

if "demo" not in os.environ.get("DATABASE_PATH", ""):
    sys.exit("Set DATABASE_PATH to a file with 'demo' in its name, e.g. DATABASE_PATH=data/demo.db")

from app import workouts as wk  # noqa: E402
from app.db import now_iso, session, update_sync_state  # noqa: E402
from app.sources.garmin import store_metrics  # noqa: E402

random.seed(7)
today = date.today()
with session() as conn:
    for i in range(75, -1, -1):
        d = today - timedelta(days=i)
        worn = random.random() > 0.15 or i == 0
        store_metrics(conn, d.isoformat(), {
            "resting_hr": round(random.gauss(52, 1.8)),
            "hrv": round(random.gauss(50, 5)) if worn else None,
            "hrv_baseline_low": 44, "hrv_baseline_high": 58,
            "sleep_seconds": round(random.gauss(7.3, 0.8) * 3600) if worn else None,
            "sleep_score": round(min(98, random.gauss(78, 9))) if worn else None,
            "body_battery_high": round(min(100, random.gauss(80, 12))),
            "body_battery_low": round(random.gauss(22, 6)),
            "stress_avg": round(random.gauss(32, 6)),
            "steps": round(random.gauss(8500, 2500)),
        })
        if i == 0:
            continue
        wd = d.weekday()
        if wd == 1:  # volleyball, no watch
            wk.insert_record(conn, source="manual", sport="volleyball", start_time=f"{d}T19:00:00",
                             duration_min=90, effort=7, estimated=i > 14, notes="Backfilled estimate" if i > 14 else None)
        if wd in (0, 3):  # gym via Hevy; recent ones unrated
            wk.upsert_external(conn, "hevy", f"{d}T18:00:00", {
                "sport": "strength", "title": "Push Day" if wd == 0 else "Legs", "start_time": f"{d}T18:00:00",
                "duration_min": 62, "effort": None if i < 5 else 7, "effort_estimated": i >= 5,
                "detail": [{"name": "Bench Press (Barbell)", "sets": [{"type": "normal", "weight_kg": 60, "reps": 8, "rpe": 8}] * 3},
                           {"name": "Squat (Barbell)", "sets": [{"type": "normal", "weight_kg": 80, "reps": 5, "rpe": None}] * 4}]})
        if wd in (2, 5):  # swim on the watch
            mins = random.choice([35, 40, 45])
            wk.upsert_external(conn, "garmin", f"demo-{i}", {
                "sport": "swimming", "start_time": f"{d}T07:10:00", "duration_min": mins, "avg_hr": 128, "max_hr": 152,
                "zone_seconds": [mins * 8, mins * 18, mins * 22, mins * 8, 0]})
    conn.execute("INSERT OR REPLACE INTO checkins(date, soreness, energy, ill, allergy, updated_at) VALUES(?,2,4,0,0,?)",
                 (today.isoformat(), now_iso()))
    update_sync_state(conn, "garmin", last_attempt=now_iso(), last_success=now_iso(),
                      info={"metrics_complete": True, "activities_complete": True})
print("Demo data written to", os.environ["DATABASE_PATH"])
