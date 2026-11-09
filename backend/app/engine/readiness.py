"""Daily readiness score and verdict (requirements 5.2 - 5.4).

Rules only (R20). Pure functions: everything needed is passed in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Mapping, Sequence

from .load import LoadMetrics

VERDICTS = ["Rest", "Keep it easy", "Train normally", "Go hard"]


@dataclass
class DayInputs:
    hrv: float | None = None
    hrv_history: Sequence[float] = ()          # previous days, most recent baseline window
    hrv_baseline_low: float | None = None      # Garmin's own balanced range
    hrv_baseline_high: float | None = None
    rhr: float | None = None
    rhr_history: Sequence[float] = ()
    sleep_seconds: float | None = None
    sleep_score: float | None = None
    body_battery: float | None = None          # morning peak
    load: LoadMetrics | None = None
    checkin: Mapping | None = None             # soreness, energy, ill, allergy, pain_note
    estimated_sessions_28d: int = 0            # backfilled sessions still in the 28-day window
    unrated_sessions_7d: int = 0               # recent sessions whose effort is a guess
    data_stale: bool = False                   # Garmin has not synced recently


@dataclass
class Readiness:
    score: int
    verdict: str
    reasons: list[str]
    confidence: str
    confidence_score: int
    confidence_notes: list[str]
    components: dict = field(default_factory=dict)
    caps: list[str] = field(default_factory=list)


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _z(value: float, history: Sequence[float], min_sd: float) -> float:
    sd = max(pstdev(history), min_sd)
    return (value - mean(history)) / sd


def score_hrv(inp: DayInputs, cfg: Mapping) -> tuple[float | None, str | None]:
    if inp.hrv is None:
        return None, None
    if len(inp.hrv_history) >= cfg["baseline_min_days"]:
        base = mean(inp.hrv_history)
        z = _z(inp.hrv, inp.hrv_history, 0.05 * base)
    elif inp.hrv_baseline_low and inp.hrv_baseline_high and inp.hrv_baseline_high > inp.hrv_baseline_low:
        base = (inp.hrv_baseline_low + inp.hrv_baseline_high) / 2
        z = (inp.hrv - base) / ((inp.hrv_baseline_high - inp.hrv_baseline_low) / 2)
    else:
        return 65.0, f"HRV was {inp.hrv:.0f} ms, but there is no baseline yet to compare it with"
    score = _clamp(70 + 20 * z)
    if z <= -1:
        reason = f"Overnight HRV ({inp.hrv:.0f} ms) is clearly below your baseline (about {base:.0f} ms)"
    elif z < -0.4:
        reason = f"Overnight HRV ({inp.hrv:.0f} ms) is a little below your baseline (about {base:.0f} ms)"
    elif z >= 0.5:
        reason = f"Overnight HRV ({inp.hrv:.0f} ms) is above your baseline (about {base:.0f} ms)"
    else:
        reason = f"Overnight HRV ({inp.hrv:.0f} ms) is in your normal range"
    return score, reason


def score_rhr(inp: DayInputs, cfg: Mapping) -> tuple[float | None, str | None]:
    if inp.rhr is None:
        return None, None
    if len(inp.rhr_history) < cfg["baseline_min_days"]:
        return 65.0, f"Resting HR was {inp.rhr:.0f} bpm, but there is no baseline yet to compare it with"
    base = mean(inp.rhr_history)
    z = _z(inp.rhr, inp.rhr_history, 1.5)
    score = _clamp(70 - 20 * z)
    diff = inp.rhr - base
    if z >= 1:
        reason = f"Resting HR ({inp.rhr:.0f} bpm) is {diff:.0f} bpm above your usual {base:.0f}"
    elif z <= -0.5:
        reason = f"Resting HR ({inp.rhr:.0f} bpm) is at or below your usual {base:.0f}"
    else:
        reason = f"Resting HR ({inp.rhr:.0f} bpm) is normal for you"
    return score, reason


def score_sleep(inp: DayInputs, cfg: Mapping) -> tuple[float | None, str | None]:
    if not inp.sleep_seconds:
        return None, None
    hours = inp.sleep_seconds / 3600.0
    duration_score = _clamp(100 - (cfg["sleep_target_hours"] - hours) * 25)
    score = duration_score if inp.sleep_score is None else 0.5 * duration_score + 0.5 * _clamp(inp.sleep_score)
    h, m = int(hours), int(round((hours - int(hours)) * 60))
    text = f"{h} h {m:02d} min"
    if score >= 80:
        reason = f"You slept well ({text})"
    elif score >= 60:
        reason = f"Sleep was acceptable ({text})"
    else:
        reason = f"Sleep was short or poor ({text})"
    return score, reason


def score_body_battery(inp: DayInputs) -> tuple[float | None, str | None]:
    if inp.body_battery is None:
        return None, None
    bb = _clamp(inp.body_battery)
    if bb >= 75:
        reason = f"Body Battery recharged to {bb:.0f}"
    elif bb >= 50:
        reason = f"Body Battery only recharged to {bb:.0f}"
    else:
        reason = f"Body Battery is low (peaked at {bb:.0f})"
    return bb, reason


def score_load(load: LoadMetrics | None, cfg: Mapping) -> tuple[float, list[str]]:
    """Neutral load scores 75; being fresh adds up to 20, strain subtracts."""
    if load is None:
        return 75.0, []
    score, reasons = 75.0, []
    if load.ratio is not None:
        if load.ratio > cfg["ratio_cap"]:
            score -= min(60.0, 30 + (load.ratio - cfg["ratio_cap"]) / 0.5 * 30)
            reasons.append(f"Recent load is well above what you are used to (ratio {load.ratio:.2f})")
        elif load.ratio > cfg["ratio_safe_high"]:
            span = cfg["ratio_cap"] - cfg["ratio_safe_high"]
            score -= (load.ratio - cfg["ratio_safe_high"]) / span * 30
            reasons.append(f"Recent load is somewhat above what you are used to (ratio {load.ratio:.2f})")
        elif load.ratio < 0.8:
            reasons.append(f"Recent load is lighter than usual (ratio {load.ratio:.2f})")
        else:
            reasons.append(f"Recent load matches what you are used to (ratio {load.ratio:.2f})")
    if load.ramp is not None and load.ramp > cfg["ramp_warn"]:
        frac = min(1.0, (load.ramp - cfg["ramp_warn"]) / (cfg["ramp_high"] - cfg["ramp_warn"]))
        score -= 20 * frac
        reasons.append(f"Weekly load is up {load.ramp * 100:.0f}% on the week before")
    if load.consecutive_hard >= 3:
        score -= 40
        reasons.append(f"{load.consecutive_hard} hard days in a row")
    elif load.consecutive_hard == 2:
        score -= 25
        reasons.append("Two hard days in a row")
    elif load.consecutive_hard == 1 and not load.today_hard:
        score -= 10
        reasons.append("Yesterday was a hard day")
    if load.today_load > 0:
        score -= 30 * min(1.5, load.today_load / cfg["hard_day_load"])
        if load.today_hard:
            reasons.append("You have already trained hard today")
        else:
            reasons.append("You have already trained today")
    elif load.days_since_hard is None or load.days_since_hard >= 3:
        score += 20
        if load.days_since_hard is not None:
            reasons.append(f"{load.days_since_hard} days since your last hard session")
    elif load.days_since_hard == 2:
        score += 10
    return _clamp(score), reasons


def score_checkin(checkin: Mapping | None) -> tuple[float | None, list[str]]:
    if not checkin:
        return None, []
    parts, reasons = [], []
    soreness, energy = checkin.get("soreness"), checkin.get("energy")
    if soreness:
        parts.append(100 - (soreness - 1) * 25)
        if soreness >= 4:
            reasons.append("You reported strong muscle soreness")
        elif soreness == 3:
            reasons.append("You reported some muscle soreness")
    if energy:
        parts.append((energy - 1) * 25)
        if energy <= 2:
            reasons.append("You reported low energy")
        elif energy >= 4:
            reasons.append("You reported good energy")
    if not parts and not checkin.get("allergy"):
        return None, reasons
    score = mean(parts) if parts else 70.0
    if checkin.get("allergy"):
        score -= 25
        reasons.append("You reported an allergy flare-up")
    return _clamp(score), reasons


def compute_readiness(inp: DayInputs, cfg: Mapping) -> Readiness:
    reasons: list[str] = []
    conf, conf_notes = 100, []

    # --- Recovery group ---
    parts = {
        "hrv": score_hrv(inp, cfg),
        "rhr": score_rhr(inp, cfg),
        "sleep": score_sleep(inp, cfg),
        "body_battery": score_body_battery(inp),
    }
    weights = cfg["recovery_weights"]
    present = {k: v for k, v in parts.items() if v[0] is not None}
    recovery = None
    if present:
        total_w = sum(weights[k] for k in present)
        recovery = sum(v[0] * weights[k] for k, v in present.items()) / total_w
        reasons += [v[1] for v in present.values() if v[1]]
    missing_cost = {"hrv": 20, "sleep": 15, "rhr": 10, "body_battery": 5}
    labels = {"hrv": "overnight HRV", "sleep": "sleep", "rhr": "resting HR", "body_battery": "Body Battery"}
    missing = [k for k in parts if k not in present]
    if missing:
        conf -= sum(missing_cost[k] for k in missing)
        conf_notes.append("No " + ", ".join(labels[k] for k in missing) + " for last night (watch not worn or not synced?)")
    n_base = min(len(inp.hrv_history), len(inp.rhr_history)) if (inp.hrv_history or inp.rhr_history) else 0
    if n_base < cfg["baseline_min_days"]:
        conf -= 25
        conf_notes.append("Personal baseline is still being built (under a week of data)")
    elif n_base < 14:
        conf -= 15
        conf_notes.append("Personal baseline is still young (under two weeks of data)")

    # --- Load group ---
    load_score, load_reasons = score_load(inp.load, cfg)
    reasons += load_reasons
    if inp.load is not None and inp.load.ratio is None:
        conf -= 10
        conf_notes.append("Not enough training history yet for a reliable load ratio")
    if inp.estimated_sessions_28d:
        conf -= 5
        conf_notes.append(f"{inp.estimated_sessions_28d} estimated (backfilled) session(s) in the last 28 days")
    if inp.unrated_sessions_7d:
        conf -= 5
        conf_notes.append(f"{inp.unrated_sessions_7d} recent session(s) have no effort rating, so their load is a guess")
    if inp.data_stale:
        conf -= 15
        conf_notes.append("Garmin data has not synced recently")

    # --- Check-in group ---
    checkin_score, checkin_reasons = score_checkin(inp.checkin)
    reasons += checkin_reasons

    w_rec, w_load, w_chk = cfg["weight_recovery"], cfg["weight_load"], cfg["weight_checkin"]
    if checkin_score is None:
        w_rec, w_chk = w_rec + w_chk, 0.0          # weight moves to Recovery if skipped
    if recovery is None:
        w_load, w_rec = w_load + w_rec, 0.0        # nothing overnight: lean on load, low confidence
    total_w = w_rec + w_load + w_chk
    score = ((recovery or 0) * w_rec + load_score * w_load + (checkin_score or 0) * w_chk) / total_w
    score_int = int(round(_clamp(score)))

    if score_int >= cfg["verdict_go_hard"]:
        level = 3
    elif score_int >= cfg["verdict_normal"]:
        level = 2
    elif score_int >= cfg["verdict_easy"]:
        level = 1
    else:
        level = 0

    # --- Hard limits (5.3) ---
    caps: list[str] = []

    def cap(max_level: int, why: str) -> None:
        nonlocal level
        caps.append(why)
        level = min(level, max_level)

    c = inp.checkin or {}
    if c.get("ill"):
        cap(1, "You reported feeling ill, so the verdict is limited to Keep it easy")
    if (c.get("pain_note") or "").strip():
        cap(1, f"You noted pain or an injury (\"{c['pain_note'].strip()}\"), so the verdict is limited to Keep it easy")
    if inp.load is not None:
        if inp.load.consecutive_hard >= 3:
            cap(1, f"{inp.load.consecutive_hard} hard days in a row, so the verdict is limited to Keep it easy")
        if inp.load.ratio is not None and inp.load.ratio > cfg["ratio_cap"]:
            cap(2, "Load ratio is well above the safe range, so the verdict is limited to Train normally")

    conf = int(_clamp(conf))
    confidence = "High" if conf >= 75 else "Medium" if conf >= 50 else "Low"
    return Readiness(
        score=score_int,
        verdict=VERDICTS[level],
        reasons=caps + reasons,
        confidence=confidence,
        confidence_score=conf,
        confidence_notes=conf_notes,
        components={
            "recovery": None if recovery is None else round(recovery),
            "load": round(load_score),
            "checkin": None if checkin_score is None else round(checkin_score),
            "hrv": None if parts["hrv"][0] is None else round(parts["hrv"][0]),
            "rhr": None if parts["rhr"][0] is None else round(parts["rhr"][0]),
            "sleep": None if parts["sleep"][0] is None else round(parts["sleep"][0]),
            "body_battery": None if parts["body_battery"][0] is None else round(parts["body_battery"][0]),
        },
        caps=caps,
    )
