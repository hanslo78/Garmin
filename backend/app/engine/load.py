"""Training load on one scale across all sources (requirements 5.1).

Pure functions only: no database, no network. The unit is session-RPE load:
duration in minutes x effort (1-10). Heart-rate sessions are converted onto
that scale with a calibration factor.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median
from typing import Iterable, Mapping, Sequence


def zone_weighted_minutes(zone_seconds: Sequence[float] | None, weights: Sequence[float]) -> float:
    """Minutes in each HR zone multiplied by the zone weight (Edwards-style)."""
    if not zone_seconds:
        return 0.0
    return sum((s or 0) / 60.0 * w for s, w in zip(zone_seconds, weights))


def calibrate_scale(pairs: Iterable[tuple[float, float]], cfg: Mapping) -> float:
    """Learn how zone-weighted minutes map to effort load for this user.

    `pairs` are (zone_weighted_minutes, duration x effort) for sessions that have
    both heart rate and a user-given effort. Falls back to the configured default
    until there are enough sessions. The result is clamped to a sane range.
    """
    default = float(cfg["hr_to_effort_scale"])
    if not cfg.get("calibrate_hr_scale", True):
        return default
    ratios = [srpe / zwm for zwm, srpe in pairs if zwm > 5 and srpe > 0]
    if len(ratios) < int(cfg["calibration_min_sessions"]):
        return default
    return round(min(4.0, max(1.0, median(ratios))), 3)


def session_load(
    duration_min: float,
    effort: float | None,
    zone_seconds: Sequence[float] | None,
    is_strength: bool,
    cfg: Mapping,
    hr_scale: float | None = None,
) -> tuple[float, str]:
    """Return (load, method). Method is 'heart_rate' or 'effort'.

    Strength work always uses effort because heart rate underestimates it.
    Other sessions use heart-rate zones when the watch recorded them.
    """
    zwm = zone_weighted_minutes(zone_seconds, cfg["zone_weights"])
    if zwm > 0 and not is_strength:
        scale = hr_scale if hr_scale is not None else float(cfg["hr_to_effort_scale"])
        return round(zwm * scale, 1), "heart_rate"
    e = effort if effort is not None else cfg["default_effort"]
    return round(max(0.0, duration_min) * e, 1), "effort"


def is_hard_session(duration_min: float, effort: float | None, load: float, cfg: Mapping) -> bool:
    if effort is not None and effort >= cfg["hard_effort_min"] and duration_min >= cfg["hard_min_duration"]:
        return True
    return load >= cfg["hard_day_load"]


@dataclass
class LoadMetrics:
    acute: float                 # 7-day exponentially weighted average daily load
    chronic: float               # 28-day exponentially weighted average daily load
    ratio: float | None          # acute / chronic, None when chronic is too small to trust
    week_sum: float              # last 7 days including the reference day
    prev_week_sum: float         # the 7 days before that
    ramp: float | None           # week-over-week change, e.g. 0.2 = +20%
    avg4_week: float             # average weekly load over the 4 weeks before the last 7 days
    consecutive_hard: int        # hard days in a row, ending today (if hard) or yesterday
    days_since_hard: int | None
    today_load: float
    today_hard: bool


def ewma_series(daily: Mapping[date, float], start: date, end: date, n_days: int) -> dict[date, float]:
    """Exponentially weighted moving average of daily load, alpha = 2 / (N + 1).

    Seeded with the mean of the first N days so the average does not start at zero.
    """
    alpha = 2.0 / (n_days + 1)
    days = (end - start).days + 1
    seed_days = [daily.get(start + timedelta(days=i), 0.0) for i in range(min(days, n_days))]
    value = sum(seed_days) / len(seed_days) if seed_days else 0.0
    out: dict[date, float] = {}
    for i in range(days):
        d = start + timedelta(days=i)
        value = alpha * daily.get(d, 0.0) + (1 - alpha) * value
        out[d] = value
    return out


def load_metrics(
    daily: Mapping[date, float],
    hard_days: set[date],
    ref: date,
    cfg: Mapping,
    include_ref_day: bool = True,
) -> LoadMetrics:
    """Load picture on `ref`. With include_ref_day=False it is the morning view:
    sessions on `ref` itself are ignored."""
    if not include_ref_day:
        daily = {d: v for d, v in daily.items() if d < ref}
        hard_days = {d for d in hard_days if d < ref}
    else:
        daily = {d: v for d, v in daily.items() if d <= ref}
        hard_days = {d for d in hard_days if d <= ref}

    first = min(daily) if daily else ref
    start = min(first, ref - timedelta(days=cfg["chronic_days"]))
    # Until something is logged today, today is "not trained yet", not a rest day:
    # the averages then run through yesterday so the morning ratio is not dragged down.
    last = ref if daily.get(ref, 0.0) > 0 else ref - timedelta(days=1)
    start = min(start, last)
    acute = ewma_series(daily, start, last, cfg["acute_days"])[last]
    chronic = ewma_series(daily, start, last, cfg["chronic_days"])[last]
    ratio = round(acute / chronic, 2) if chronic >= cfg["min_chronic_load"] else None

    def window(offset: int, length: int = 7) -> float:
        return sum(daily.get(ref - timedelta(days=offset + i), 0.0) for i in range(length))

    week_sum, prev_week_sum = window(0), window(7)
    ramp = round((week_sum - prev_week_sum) / prev_week_sum, 2) if prev_week_sum >= 7 * cfg["min_chronic_load"] / 2 else None
    avg4_week = window(7, 28) / 4.0

    cursor = ref if ref in hard_days else ref - timedelta(days=1)
    consecutive = 0
    while cursor in hard_days:
        consecutive += 1
        cursor -= timedelta(days=1)

    past_hard = [d for d in hard_days if d <= ref]
    days_since = (ref - max(past_hard)).days if past_hard else None

    return LoadMetrics(
        acute=round(acute, 1),
        chronic=round(chronic, 1),
        ratio=ratio,
        week_sum=round(week_sum, 1),
        prev_week_sum=round(prev_week_sum, 1),
        ramp=ramp,
        avg4_week=round(avg4_week, 1),
        consecutive_hard=consecutive,
        days_since_hard=days_since,
        today_load=round(daily.get(ref, 0.0), 1),
        today_hard=ref in hard_days,
    )
