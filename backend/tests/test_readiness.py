from app.engine.load import LoadMetrics
from app.engine.readiness import DayInputs, compute_readiness

HRV_HIST = [48, 52, 50, 49, 51, 53, 47, 50, 52, 48, 50, 51, 49, 50]
RHR_HIST = [52, 53, 51, 52, 54, 52, 51, 53, 52, 52, 51, 53, 52, 52]


def load(**kw):
    base = dict(acute=300, chronic=300, ratio=1.0, week_sum=2100, prev_week_sum=2100, ramp=0.0, avg4_week=2100,
                consecutive_hard=0, days_since_hard=2, today_load=0, today_hard=False)
    base.update(kw)
    return LoadMetrics(**base)


def good_day(**kw):
    base = dict(hrv=55, hrv_history=HRV_HIST, rhr=50, rhr_history=RHR_HIST, sleep_seconds=8 * 3600,
                sleep_score=88, body_battery=90, load=load())
    base.update(kw)
    return DayInputs(**base)


def test_good_recovery_and_normal_load_is_go_hard(cfg):
    r = compute_readiness(good_day(), cfg)
    assert r.score >= 80 and r.verdict == "Go hard"
    assert r.confidence == "High"
    assert r.reasons, "reasons must always be listed"


def test_poor_recovery_lowers_score(cfg):
    r = compute_readiness(good_day(hrv=38, rhr=59, sleep_seconds=5 * 3600, sleep_score=45, body_battery=35), cfg)
    assert r.score < 40 and r.verdict == "Rest"
    assert any("HRV" in x and "below" in x for x in r.reasons)
    assert any("Resting HR" in x and "above" in x for x in r.reasons)


def test_score_is_bounded(cfg):
    low = compute_readiness(good_day(hrv=5, rhr=90, sleep_seconds=3600, sleep_score=5, body_battery=5,
                                     load=load(ratio=2.5, consecutive_hard=4, today_load=900, today_hard=True),
                                     checkin={"soreness": 5, "energy": 1, "allergy": 1}), cfg)
    high = compute_readiness(good_day(hrv=90, rhr=40, sleep_seconds=10 * 3600, sleep_score=100, body_battery=100,
                                      checkin={"soreness": 1, "energy": 5}), cfg)
    assert 0 <= low.score <= 100 and 0 <= high.score <= 100


def test_illness_caps_verdict(cfg):
    r = compute_readiness(good_day(checkin={"soreness": 1, "energy": 5, "ill": 1}), cfg)
    assert r.score >= 80 and r.verdict == "Keep it easy"
    assert "ill" in r.reasons[0]


def test_pain_note_caps_verdict_and_is_named(cfg):
    r = compute_readiness(good_day(checkin={"pain_note": "left hamstring tight"}), cfg)
    assert r.verdict == "Keep it easy"
    assert any("left hamstring tight" in x for x in r.reasons)


def test_three_hard_days_caps_verdict(cfg):
    r = compute_readiness(good_day(hrv=60, load=load(consecutive_hard=3, days_since_hard=1)), cfg)
    assert r.verdict == "Keep it easy"


def test_high_ratio_caps_at_train_normally(cfg):
    r = compute_readiness(good_day(hrv=62, rhr=48, body_battery=100, sleep_score=100, load=load(ratio=1.6)), cfg)
    assert r.verdict in ("Train normally", "Keep it easy", "Rest")
    assert any("well above" in x for x in r.reasons)


def test_ratio_in_safe_range_costs_nothing(cfg):
    a = compute_readiness(good_day(load=load(ratio=0.9)), cfg)
    b = compute_readiness(good_day(load=load(ratio=1.25)), cfg)
    assert a.components["load"] == b.components["load"] == 85


def test_training_today_lowers_score(cfg):
    before = compute_readiness(good_day(), cfg)
    after = compute_readiness(good_day(load=load(today_load=630, today_hard=True, consecutive_hard=1, days_since_hard=0)), cfg)
    assert after.score < before.score
    assert any("already trained hard today" in x for x in after.reasons)


def test_skipped_checkin_moves_weight_to_recovery(cfg):
    # Recovery 100-ish, load 100: same total with or without a perfect check-in.
    without = compute_readiness(good_day(), cfg)
    assert without.components["checkin"] is None
    bad = compute_readiness(good_day(checkin={"soreness": 5, "energy": 1}), cfg)
    assert bad.score < without.score
    assert bad.score >= without.score - 10      # check-in is worth at most 10 points


def test_missing_overnight_data_lowers_confidence_but_still_scores(cfg):
    r = compute_readiness(DayInputs(load=load()), cfg)
    assert 0 <= r.score <= 100 and r.verdict
    assert r.confidence == "Low"
    assert any("watch not worn" in n for n in r.confidence_notes)


def test_partial_data_and_young_baseline(cfg):
    r = compute_readiness(good_day(hrv=None, sleep_seconds=None, sleep_score=None,
                                   hrv_history=HRV_HIST[:9], rhr_history=RHR_HIST[:9]), cfg)
    assert r.confidence_score == 100 - 20 - 15 - 15
    assert r.components["hrv"] is None and r.components["rhr"] is not None


def test_garmin_baseline_range_used_before_own_history(cfg):
    r = compute_readiness(good_day(hrv=40, hrv_history=[], rhr_history=[], hrv_baseline_low=45, hrv_baseline_high=60), cfg)
    assert r.components["hrv"] < 50
    assert any("building" in n or "being built" in n for n in r.confidence_notes)


def test_estimated_sessions_reduce_confidence(cfg):
    base = compute_readiness(good_day(), cfg)
    est = compute_readiness(good_day(estimated_sessions_28d=4, unrated_sessions_7d=1, data_stale=True), cfg)
    assert est.confidence_score == base.confidence_score - 25
    assert est.score == base.score


def test_an_average_day_is_train_normally(cfg):
    r = compute_readiness(DayInputs(hrv=50, hrv_history=HRV_HIST, rhr=52, rhr_history=RHR_HIST,
                                    sleep_seconds=7.2 * 3600, body_battery=70, load=load()), cfg)
    assert r.verdict == "Train normally" and 60 <= r.score < 80


def test_mediocre_night_is_keep_it_easy(cfg):
    r = compute_readiness(DayInputs(hrv=47, hrv_history=HRV_HIST, rhr=54, rhr_history=RHR_HIST,
                                    sleep_seconds=6 * 3600, sleep_score=60, body_battery=50,
                                    load=load(consecutive_hard=1, days_since_hard=1)), cfg)
    assert r.verdict == "Keep it easy"


def test_freshness_raises_load_score(cfg):
    tired = compute_readiness(good_day(load=load(consecutive_hard=1, days_since_hard=1)), cfg)
    fresh = compute_readiness(good_day(load=load(days_since_hard=4)), cfg)
    assert tired.components["load"] == 65 and fresh.components["load"] == 95
