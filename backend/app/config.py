"""Environment settings and the single place where all scoring thresholds live.

Everything in DEFAULT_THRESHOLDS can be overridden from the Settings screen;
overrides are stored in the database and merged on top of these defaults.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Env:
    garmin_api_key: str
    garmin_key_expires: str
    database_path: Path
    host: str
    port: int
    sync_interval_minutes: int
    garmin_history_days: int


def get_env() -> Env:
    db = Path(os.getenv("DATABASE_PATH", "data/readiness.db"))
    if not db.is_absolute():
        db = ROOT / db
    return Env(
        garmin_api_key=os.getenv("GARMIN_API_KEY", "").strip(),
        garmin_key_expires=os.getenv("GARMIN_API_KEY_EXPIRES", "").strip(),
        database_path=db,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        sync_interval_minutes=max(15, int(os.getenv("SYNC_INTERVAL_MINUTES", "60"))),
        garmin_history_days=int(os.getenv("GARMIN_HISTORY_DAYS", "365")),
    )


# --- Calculation model (requirements section 5). Starting values, to be tuned. ---
DEFAULT_THRESHOLDS: dict = {
    # 5.1 Load
    "zone_weights": [1, 2, 3, 4, 5],     # minutes in HR zone 1..5 are multiplied by these
    "hr_to_effort_scale": 2.0,           # zone-weighted minutes x this = effort-scale load
    "calibrate_hr_scale": True,          # learn the scale from sessions that have both HR and effort
    "calibration_min_sessions": 5,
    "default_effort": 5,                 # used (and marked estimated) when no effort is known
    "acute_days": 7,
    "chronic_days": 28,
    "hard_effort_min": 7,                # a session with effort >= this ...
    "hard_min_duration": 30,             # ... lasting at least this many minutes is "hard"
    "hard_day_load": 420,                # or any day whose total load reaches this
    # 5.2 Weights
    "weight_recovery": 0.60,
    "weight_load": 0.30,
    "weight_checkin": 0.10,
    "recovery_weights": {"hrv": 0.35, "rhr": 0.20, "sleep": 0.30, "body_battery": 0.15},
    "baseline_days": 28,
    "baseline_min_days": 7,
    "sleep_target_hours": 8.0,
    # Load penalties
    "ratio_safe_high": 1.3,              # load ratio above this starts to cost points
    "ratio_cap": 1.5,                    # "well above the safe range": verdict capped (5.3)
    "ramp_warn": 0.15,                   # week-over-week increase that starts to cost points
    "ramp_high": 0.50,
    "min_chronic_load": 40,              # below this the ratio is too noisy to use
    "max_weekly_increase": 0.10,         # weekly room = 4-week average x (1 + this)
    # Verdict bands
    "verdict_go_hard": 80,
    "verdict_normal": 60,
    "verdict_easy": 40,
    # Misc
    "key_expiry_warning_days": 14,
}

DEFAULT_PRESETS: list[dict] = [
    {"name": "Volleyball", "sport": "volleyball", "duration_min": 90, "effort": 7},
    {"name": "Gym", "sport": "strength", "duration_min": 60, "effort": 6},
    {"name": "Swim", "sport": "swimming", "duration_min": 45, "effort": 5},
    {"name": "Walk", "sport": "walking", "duration_min": 45, "effort": 2},
]

DEFAULT_PROFILE: dict = {
    "goal": "General fitness and staying healthy; wants to increase training volume safely.",
    "training": "About 5 sessions a week: volleyball (no watch), gym (logged in Hevy), swimming (Garmin).",
    "health_notes": "Allergy medication. Hamstring strain earlier this year, expected healed. No training restrictions.",
    "watch": "Garmin Vivoactive 5, worn during sleep.",
}

# Sports whose load always uses effort (heart rate underestimates them).
STRENGTH_SPORTS = {"strength", "strength_training", "gym", "weightlifting", "indoor_climbing", "bouldering"}

DISCLAIMER = (
    "This app is a personal training aid based on simple rules. It is not medical advice. "
    "If you feel unwell or are in pain, talk to a doctor or physiotherapist."
)
