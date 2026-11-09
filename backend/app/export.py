"""Self-contained Markdown export of a date range (R27-R29).

Built only when the user asks for it. Nothing is sent anywhere by the app.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from statistics import mean

from .config import DEFAULT_PROFILE, DISCLAIMER
from .db import get_setting
from .service import Context, day_row
from .sources.hevy import summarize_exercises


def _fmt(value, digits: int = 0, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}{suffix}"


def _avg(rows: list[dict], key: str) -> float | None:
    values = [r[key] for r in rows if r.get(key) is not None]
    return mean(values) if values else None


def build_export(conn: sqlite3.Connection, start: date, end: date) -> str:
    ctx = Context(conn)
    cfg = ctx.cfg
    profile = get_setting(conn, "profile", DEFAULT_PROFILE)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    rows = [day_row(ctx, d) for d in days]
    prev_days = [start - timedelta(days=i) for i in range(1, 29)]
    prev = [day_row(ctx, d) for d in prev_days]
    n = len(days)
    out: list[str] = []
    add = out.append

    add(f"# Training data {start.isoformat()} to {end.isoformat()}")
    add("")
    add("## Profile")
    for label, key in (("Goal", "goal"), ("Current training", "training"), ("Health notes", "health_notes"), ("Watch", "watch")):
        if profile.get(key):
            add(f"- **{label}:** {profile[key]}")
    add("- **Units:** metric")
    add("")
    add("## How the numbers are defined")
    add(
        f"Readiness is a rule-based score from 0 to 100 (no AI): {cfg['weight_recovery'] * 100:.0f}% recovery "
        f"(overnight HRV, resting HR, sleep and Body Battery, each compared with my own {cfg['baseline_days']}-day baseline), "
        f"{cfg['weight_load'] * 100:.0f}% training load and {cfg['weight_checkin'] * 100:.0f}% morning check-in "
        f"(soreness and energy; this weight moves to recovery when I skip it). Verdicts: Go hard from {cfg['verdict_go_hard']}, "
        f"Train normally from {cfg['verdict_normal']}, Keep it easy from {cfg['verdict_easy']}, otherwise Rest; illness, a pain note "
        f"or three hard days in a row limit the verdict to Keep it easy. Load is on one scale for every session: duration in minutes "
        f"x effort (1-10), or for watch sessions with heart rate, zone-weighted minutes (zones 1-5 weighted {cfg['zone_weights']}) "
        f"scaled to match. Gym sessions always use effort. The load ratio is the {cfg['acute_days']}-day exponentially weighted "
        f"average load divided by the {cfg['chronic_days']}-day one; above {cfg['ratio_safe_high']} load is rising faster than I am "
        f"used to. HRV is Garmin's overnight average in ms, resting HR is in bpm, Body Battery is the day's peak (0-100), stress is "
        f"Garmin's daily average (0-100). For past days readiness is the morning value, before that day's training."
    )
    add("")
    add("## Daily overview")
    add("| Date | Readiness | Verdict | HRV (ms) | Resting HR | Sleep (h) | Body Battery | Stress | Load | Load ratio |")
    add("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        weekday = date.fromisoformat(r["date"]).strftime("%a")
        add(
            f"| {weekday} {r['date']} | {_fmt(r['readiness'])} | {r['verdict'] or 'n/a'} | {_fmt(r['hrv'])} | "
            f"{_fmt(r['resting_hr'])} | {_fmt(r['sleep_hours'], 1)} | {_fmt(r['body_battery'])} | {_fmt(r['stress'])} | "
            f"{r['load']} | {_fmt(r['ratio'], 2)} |"
        )
    add("")
    add("## Workouts")
    in_range = sorted(
        (w for w in ctx.workouts if start.isoformat() <= w["date"] <= end.isoformat()), key=lambda w: w["start_time"]
    )
    if not in_range:
        add("No workouts recorded in this period.")
    for w in in_range:
        effort = "not rated" if w["effort"] is None else f"{w['effort']}/10" + (" (estimated)" if w["effort_source"] != "user" else "")
        flags = []
        if w["estimated"]:
            flags.append("backfilled estimate")
        if w["load_estimated"]:
            flags.append("load estimated")
        method = "heart-rate zones" if w["load_method"] == "heart_rate" else "duration x effort"
        add(
            f"- **{w['start_time'][:16].replace('T', ' ')} - {w['title']}** ({w['sport']}): source {' + '.join(w['sources'])}, "
            f"{w['duration_min']:.0f} min, effort {effort}, load {w['load']:.0f} ({method})"
            + (f", avg HR {w['avg_hr']:.0f}" if w["avg_hr"] else "")
            + (f" [{', '.join(flags)}]" if flags else "")
        )
        if w["exercises"]:
            add(f"  - Exercises: {summarize_exercises(w['exercises'])}")
        if w["notes"]:
            add(f"  - Notes: {w['notes']}")
    add("")
    add("## Check-ins")
    checkins = [(d, ctx.checkins[d]) for d in days if d in ctx.checkins]
    if not checkins:
        add("No check-ins in this period.")
    for d, c in checkins:
        parts = []
        if c.get("soreness"):
            parts.append(f"soreness {c['soreness']}/5")
        if c.get("energy"):
            parts.append(f"energy {c['energy']}/5")
        if c.get("ill"):
            parts.append("feeling ill")
        if c.get("allergy"):
            parts.append("allergy flare-up")
        if c.get("pain_note"):
            parts.append(f"pain/injury: {c['pain_note']}")
        if c.get("notes"):
            parts.append(f"note: {c['notes']}")
        add(f"- {d.isoformat()}: {', '.join(parts) or 'no details'}")
    add("")
    add("## This period compared with the previous 4 weeks")
    load_now = sum(r["load"] for r in rows) / n * 7
    load_prev = sum(r["load"] for r in prev) / 4
    sessions_now = len(in_range) / n * 7
    sessions_prev = sum(1 for w in ctx.workouts if prev_days[-1].isoformat() <= w["date"] <= prev_days[0].isoformat()) / 4
    add("| Measure | This period | Previous 4-week average |")
    add("|---|---|---|")
    add(f"| Load per week | {load_now:.0f} | {load_prev:.0f} |")
    add(f"| Sessions per week | {sessions_now:.1f} | {sessions_prev:.1f} |")
    for label, key, digits in (("Readiness", "readiness", 0), ("HRV (ms)", "hrv", 0), ("Resting HR (bpm)", "resting_hr", 0),
                               ("Sleep (h)", "sleep_hours", 1), ("Body Battery peak", "body_battery", 0), ("Stress", "stress", 0)):
        add(f"| {label} (daily average) | {_fmt(_avg(rows, key), digits)} | {_fmt(_avg(prev, key), digits)} |")
    add("")
    add("## Missing or uncertain data")
    flags: list[str] = []
    for label, key in (("HRV", "hrv"), ("sleep", "sleep_hours"), ("resting HR", "resting_hr"), ("Body Battery", "body_battery")):
        missing = [r["date"] for r in rows if r[key] is None]
        if missing:
            flags.append(f"No {label} on {len(missing)} of {n} days: {', '.join(missing)}")
    no_checkin = n - len(checkins)
    if no_checkin:
        flags.append(f"No check-in on {no_checkin} of {n} days")
    for w in in_range:
        if w["estimated"]:
            flags.append(f"{w['date']} {w['title']}: backfilled session, duration and effort are estimates")
        elif w["load_estimated"]:
            flags.append(f"{w['date']} {w['title']}: no effort rating, load is estimated")
    if ctx.garmin_stale:
        flags.append("Garmin data had not synced in the 36 hours before this export")
    for f in flags or ["Nothing flagged."]:
        add(f"- {f}")
    add("")
    add(f"_{DISCLAIMER}_")
    return "\n".join(out) + "\n"
