"""Glue between storage and the calculation engine: today's view, trends, weekly context."""
from __future__ import annotations

import sqlite3
from dataclasses import asdict
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any, Mapping

from . import workouts as wk
from .config import DEFAULT_PRESETS, DEFAULT_PROFILE, DEFAULT_THRESHOLDS, DISCLAIMER, get_env
from .db import get_setting, get_sync_state
from .engine.load import LoadMetrics, load_metrics
from .engine.readiness import DayInputs, compute_readiness


def get_cfg(conn: sqlite3.Connection) -> dict:
    cfg = dict(DEFAULT_THRESHOLDS)
    overrides = get_setting(conn, "thresholds", {}) or {}
    for key, value in overrides.items():
        if key not in cfg:
            continue
        if isinstance(cfg[key], dict) and isinstance(value, dict):
            cfg[key] = {**cfg[key], **{k: v for k, v in value.items() if k in cfg[key]}}
        else:
            cfg[key] = value
    return cfg


def validate_thresholds(overrides: Mapping[str, Any]) -> dict:
    """Keep only known keys with values of the right kind."""
    clean: dict = {}
    for key, value in overrides.items():
        default = DEFAULT_THRESHOLDS.get(key)
        if default is None:
            continue
        if isinstance(default, bool):
            clean[key] = bool(value)
        elif isinstance(default, (int, float)):
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                clean[key] = value
        elif isinstance(default, list):
            if isinstance(value, list) and len(value) == len(default) and all(isinstance(v, (int, float)) for v in value):
                clean[key] = value
        elif isinstance(default, dict):
            if isinstance(value, dict):
                clean[key] = {k: v for k, v in value.items() if k in default and isinstance(v, (int, float))}
    return clean


class Context:
    """Everything the engine needs, loaded once per request."""

    def __init__(self, conn: sqlite3.Connection, today: date | None = None):
        self.today = today or date.today()
        self.cfg = get_cfg(conn)
        self.workouts = wk.list_workouts(conn, self.cfg)
        self.daily_load: dict[date, float] = {}
        self.hard_days: set[date] = set()
        self.by_day: dict[date, list[dict]] = {}
        for w in self.workouts:
            d = date.fromisoformat(w["date"])
            self.daily_load[d] = self.daily_load.get(d, 0.0) + w["load"]
            self.by_day.setdefault(d, []).append(w)
            if w["hard"]:
                self.hard_days.add(d)
        for d, total in self.daily_load.items():
            if total >= self.cfg["hard_day_load"]:
                self.hard_days.add(d)
        self.metrics = {date.fromisoformat(r["date"]): dict(r) for r in conn.execute("SELECT * FROM daily_metrics")}
        self.checkins = {date.fromisoformat(r["date"]): dict(r) for r in conn.execute("SELECT * FROM checkins")}
        garmin = get_sync_state(conn, "garmin")
        last = garmin["last_success"]
        self.garmin_stale = not last or datetime.now() - datetime.fromisoformat(last) > timedelta(hours=36)

    def _history(self, day: date, column: str) -> list[float]:
        out = []
        for i in range(1, self.cfg["baseline_days"] + 1):
            value = (self.metrics.get(day - timedelta(days=i)) or {}).get(column)
            if value:
                out.append(value)
        return out

    def load(self, day: date, include_day: bool) -> LoadMetrics:
        return load_metrics(self.daily_load, self.hard_days, day, self.cfg, include_ref_day=include_day)

    def readiness(self, day: date) -> dict:
        """Readiness for `day`. Today includes sessions already done today (R17);
        past days show the morning view."""
        is_today = day == self.today
        m = self.metrics.get(day) or {}
        load = self.load(day, include_day=is_today)
        window = [w for d, ws in self.by_day.items() if 0 <= (day - d).days < 28 for w in ws]
        recent = [w for d, ws in self.by_day.items() if 0 <= (day - d).days < 7 for w in ws]
        inputs = DayInputs(
            hrv=m.get("hrv"),
            hrv_history=self._history(day, "hrv"),
            hrv_baseline_low=m.get("hrv_baseline_low"),
            hrv_baseline_high=m.get("hrv_baseline_high"),
            rhr=m.get("resting_hr"),
            rhr_history=self._history(day, "resting_hr"),
            sleep_seconds=m.get("sleep_seconds"),
            sleep_score=m.get("sleep_score"),
            body_battery=m.get("body_battery_high"),
            load=load,
            checkin=self.checkins.get(day),
            estimated_sessions_28d=sum(1 for w in window if w["estimated"]),
            unrated_sessions_7d=sum(1 for w in recent if w["load_estimated"] and not w["estimated"]),
            data_stale=is_today and self.garmin_stale,
        )
        result = asdict(compute_readiness(inputs, self.cfg))
        result["load_metrics"] = asdict(load)
        return result

    def weekly(self, day: date) -> dict:
        """R18: is there room to add a session, or is load rising too quickly?"""
        cfg = self.cfg
        load = self.load(day, include_day=True)
        last28 = [w["load"] for d, ws in self.by_day.items() if 0 <= (day - d).days < 28 for w in ws if w["load"] > 0]
        typical = round(median(last28)) if last28 else 0
        target = load.avg4_week * (1 + cfg["max_weekly_increase"])
        room = round(target - load.week_sum)
        sessions = sum(len(ws) for d, ws in self.by_day.items() if 0 <= (day - d).days < 7)
        if load.avg4_week < 7 * cfg["min_chronic_load"] / 2:
            status, message = "building", "Not enough training history yet to judge your weekly load."
        elif (load.ratio is not None and load.ratio > cfg["ratio_safe_high"]) or (load.ramp is not None and load.ramp > 0.3):
            status, message = "rising", "Load is rising quickly. Hold your volume steady before adding more."
        elif typical and room >= typical:
            status, message = "room", f"There is room to add a session this week (about {room} load points left)."
        elif room > 0:
            status, message = "on_track", f"You are on track. A short or easy session still fits (about {room} load points left)."
        else:
            status, message = "full", "The last 7 days already match a safe step up from your 4-week average. Hold steady."
        return {
            "status": status, "message": message, "sessions_7d": sessions,
            "load_7d": load.week_sum, "avg_4_weeks": load.avg4_week, "safe_target": round(target),
            "room": room, "typical_session_load": typical, "ramp": load.ramp, "ratio": load.ratio,
        }


def day_row(ctx: Context, day: date) -> dict:
    """One row for trends and the export."""
    m = ctx.metrics.get(day) or {}
    r = ctx.readiness(day)
    has_data = bool(m) or day in ctx.daily_load or day in ctx.checkins
    return {
        "date": day.isoformat(),
        "readiness": r["score"] if has_data else None,
        "verdict": r["verdict"] if has_data else None,
        "confidence": r["confidence"] if has_data else None,
        "hrv": m.get("hrv"),
        "resting_hr": m.get("resting_hr"),
        "sleep_hours": round(m["sleep_seconds"] / 3600, 2) if m.get("sleep_seconds") else None,
        "sleep_score": m.get("sleep_score"),
        "body_battery": m.get("body_battery_high"),
        "stress": m.get("stress_avg"),
        "steps": m.get("steps"),
        "load": round(ctx.daily_load.get(day, 0.0)),
        "acute": r["load_metrics"]["acute"],
        "chronic": r["load_metrics"]["chronic"],
        "ratio": r["load_metrics"]["ratio"],
    }


def series(conn: sqlite3.Connection, start: date, end: date) -> list[dict]:
    ctx = Context(conn)
    return [day_row(ctx, start + timedelta(days=i)) for i in range((end - start).days + 1)]


def key_expiry(conn: sqlite3.Connection) -> str | None:
    return get_setting(conn, "garmin_key_expires") or get_env().garmin_key_expires or None


def warnings(conn: sqlite3.Connection, cfg: Mapping, today: date) -> list[str]:
    out = []
    if not get_env().garmin_api_key:
        out.append("No Garmin API key configured. Add GARMIN_API_KEY to .env to sync watch data.")
    expires = key_expiry(conn)
    if expires:
        try:
            left = (date.fromisoformat(expires) - today).days
            if left < 0:
                out.append(f"Your Garmin API key expired on {expires}. Create a new key and update .env.")
            elif left <= cfg["key_expiry_warning_days"]:
                out.append(f"Your Garmin API key expires in {left} day(s) ({expires}). Create a new key soon.")
        except ValueError:
            pass
    return out


def sync_status(conn: sqlite3.Connection) -> dict:
    garmin, hevy = get_sync_state(conn, "garmin"), get_sync_state(conn, "hevy")
    info = garmin["info"]
    garmin["history_complete"] = bool(info.get("metrics_complete") and info.get("activities_complete"))
    garmin["history_from"] = info.get("metrics_done_through")
    garmin["configured"] = bool(get_env().garmin_api_key)
    return {"garmin": garmin, "hevy": hevy}


def today_payload(conn: sqlite3.Connection) -> dict:
    ctx = Context(conn)
    day = ctx.today
    m = ctx.metrics.get(day) or {}
    recent_cut = (day - timedelta(days=7)).isoformat()
    return {
        "date": day.isoformat(),
        "readiness": ctx.readiness(day),
        "weekly": ctx.weekly(day),
        "metrics": {
            "hrv": m.get("hrv"), "resting_hr": m.get("resting_hr"),
            "sleep_hours": round(m["sleep_seconds"] / 3600, 2) if m.get("sleep_seconds") else None,
            "sleep_score": m.get("sleep_score"), "body_battery": m.get("body_battery_high"),
            "stress": m.get("stress_avg"),
        },
        "workouts_today": ctx.by_day.get(day, []),
        "needs_effort": [w for w in ctx.workouts if w["load_estimated"] and not w["estimated"] and w["date"] >= recent_cut],
        "checkin": ctx.checkins.get(day),
        "sync": sync_status(conn),
        "warnings": warnings(conn, ctx.cfg, day),
        "suggest_backfill": not get_setting(conn, "backfill_done", False),
        "presets": get_setting(conn, "presets", DEFAULT_PRESETS),
        "disclaimer": DISCLAIMER,
    }


def settings_payload(conn: sqlite3.Connection) -> dict:
    return {
        "thresholds": get_cfg(conn),
        "defaults": DEFAULT_THRESHOLDS,
        "presets": get_setting(conn, "presets", DEFAULT_PRESETS),
        "profile": get_setting(conn, "profile", DEFAULT_PROFILE),
        "garmin_key_expires": key_expiry(conn),
        "hr_scale_in_use": wk.hr_scale(conn, get_cfg(conn)),
        "sync": sync_status(conn),
        "sync_interval_minutes": get_env().sync_interval_minutes,
    }
