from datetime import date, timedelta

import pytest

from app.engine.load import (calibrate_scale, ewma_series, is_hard_session, load_metrics,
                             session_load, zone_weighted_minutes)

D = date(2026, 11, 9)


def test_zone_weighted_minutes(cfg):
    # 10 min in each zone: 10*(1+2+3+4+5)
    assert zone_weighted_minutes([600] * 5, cfg["zone_weights"]) == 150
    assert zone_weighted_minutes(None, cfg["zone_weights"]) == 0


def test_manual_load_is_duration_times_effort(cfg):
    assert session_load(90, 7, None, False, cfg) == (630, "effort")


def test_heart_rate_load_uses_zones_and_scale(cfg):
    zones = [0, 0, 1800, 0, 0]  # 30 min in zone 3 -> 90 zone-minutes
    assert session_load(30, None, zones, False, cfg) == (180, "heart_rate")
    assert session_load(30, None, zones, False, cfg, hr_scale=1.5) == (135, "heart_rate")


def test_strength_ignores_heart_rate(cfg):
    zones = [0, 1800, 0, 0, 0]
    assert session_load(60, 6, zones, True, cfg) == (360, "effort")


def test_missing_effort_falls_back_to_default(cfg):
    assert session_load(40, None, None, False, cfg) == (40 * cfg["default_effort"], "effort")


def test_calibration_needs_enough_sessions(cfg):
    assert calibrate_scale([(100, 300)] * 4, cfg) == cfg["hr_to_effort_scale"]
    assert calibrate_scale([(100, 300)] * 5, cfg) == 3.0
    assert calibrate_scale([(100, 9000)] * 5, cfg) == 4.0  # clamped


def test_hard_session(cfg):
    assert is_hard_session(60, 7, 420, cfg)
    assert not is_hard_session(20, 9, 180, cfg)      # too short
    assert not is_hard_session(60, 5, 300, cfg)
    assert is_hard_session(120, 4, 480, cfg)         # sheer volume


def test_ewma_of_constant_load_is_constant():
    daily = {D - timedelta(days=i): 100.0 for i in range(60)}
    series = ewma_series(daily, D - timedelta(days=59), D, 7)
    assert series[D] == pytest.approx(100.0)


def test_ratio_is_one_for_steady_training(cfg):
    daily = {D - timedelta(days=i): 300.0 for i in range(60)}
    m = load_metrics(daily, set(), D, cfg)
    assert m.ratio == pytest.approx(1.0)
    assert m.ramp == pytest.approx(0.0)
    assert m.week_sum == 2100 and m.avg4_week == 2100


def test_ratio_rises_after_a_big_week(cfg):
    daily = {D - timedelta(days=i): (700.0 if i < 7 else 200.0) for i in range(60)}
    m = load_metrics(daily, set(), D, cfg)
    assert m.ratio > 1.5
    assert m.ramp == pytest.approx(2.5)


def test_ratio_unavailable_with_little_history(cfg):
    m = load_metrics({D: 100.0}, set(), D, cfg)
    assert m.ratio is None and m.ramp is None


def test_consecutive_hard_days_and_days_since(cfg):
    hard = {D - timedelta(days=1), D - timedelta(days=2), D - timedelta(days=3), D - timedelta(days=6)}
    m = load_metrics({d: 500.0 for d in hard}, hard, D, cfg)
    assert m.consecutive_hard == 3
    assert m.days_since_hard == 1
    assert not m.today_hard


def test_morning_view_excludes_today(cfg):
    daily = {D: 600.0, D - timedelta(days=3): 300.0}
    evening = load_metrics(daily, {D}, D, cfg, include_ref_day=True)
    morning = load_metrics(daily, {D}, D, cfg, include_ref_day=False)
    assert evening.today_load == 600 and evening.today_hard and evening.consecutive_hard == 1
    assert morning.today_load == 0 and not morning.today_hard and morning.consecutive_hard == 0
    assert evening.acute > morning.acute
