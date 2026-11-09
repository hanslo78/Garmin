import json
from datetime import date, timedelta

import httpx

from app import service, workouts as wk
from app.db import connect, get_sync_state
from app.sources import garmin

TODAY = date(2026, 11, 9)
KEY = "secret-key-123"
TOKEN = "tok-abc"


class FakeGarmin:
    """Minimal stand-in for the Personal API, shaped like the documented endpoints."""

    def __init__(self, fail_paths=(), reject_key=False, fail_after=None):
        self.calls, self.token_calls = [], 0
        self.fail_paths, self.reject_key, self.fail_after = fail_paths, reject_key, fail_after
        self.activities = [
            {"activityId": 1000 + i, "activityName": "Vienna Pool Swim", "ownerFullName": "Jane Doe",
             "startLatitude": 48.2, "startLongitude": 16.3, "endLatitude": 48.2, "endLongitude": 16.3,
             "startTimeLocal": f"{TODAY - timedelta(days=i * 3)} 07:00:00", "duration": 2700.0,
             "activityType": {"typeKey": "lap_swimming"}, "averageHR": 128.0, "maxHR": 150.0,
             "hrTimeInZone_1": 300.0, "hrTimeInZone_2": 900.0, "hrTimeInZone_3": 1200.0,
             "hrTimeInZone_4": 300.0, "hrTimeInZone_5": 0.0, "activityTrainingLoad": None}
            for i in range(130)
        ]

    def _days(self, start, end):
        d = date.fromisoformat(start)
        while d <= date.fromisoformat(end):
            yield d.isoformat()
            d += timedelta(days=1)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == garmin.TOKEN_PATH:
            self.token_calls += 1
            assert request.headers["authorization"] == f"ApiKey {KEY}"
            assert "application/json" not in request.headers.get("accept", "")
            return httpx.Response(401) if self.reject_key else httpx.Response(200, text=TOKEN)
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        self.calls.append(path)
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            return httpx.Response(500)
        if any(p in path for p in self.fail_paths):
            return httpx.Response(500)
        q = dict(request.url.params)
        if "/hrv-service/" in path:
            s, e = path.split("/")[-2:]
            return httpx.Response(200, json={"hrvSummaries": [
                {"calendarDate": d, "lastNightAvg": 50, "weeklyAvg": 49, "status": "BALANCED",
                 "baseline": {"balancedLow": 44, "balancedUpper": 58}} for d in self._days(s, e)]})
        if "/stats/stress/" in path:
            s, e = path.split("/")[-2:]
            return httpx.Response(200, json=[{"calendarDate": d, "values": {"overallStressLevel": 31}} for d in self._days(s, e)])
        if "/stats/steps/" in path:
            s, e = path.split("/")[-2:]
            return httpx.Response(200, json=[{"calendarDate": d, "totalSteps": 8000} for d in self._days(s, e)])
        if "bodyBattery" in path:
            return httpx.Response(200, json=[
                {"date": d, "charged": 60, "bodyBatteryValuesArray": [[1, "MEASURED", 22, 1.0], [2, "MEASURED", 91, 1.0]]}
                for d in self._days(q["startDate"], q["endDate"])])
        if "dailySleepSummariesByDate" in path:
            out = []
            for d in self._days(q["startDate"], q["endDate"]):
                empty = d == TODAY.isoformat()        # a night without the watch comes back empty
                out.append({"dailySleepDTO": {"calendarDate": d, "sleepTimeSeconds": None if empty else 27000,
                                              "sleepScores": None if empty else {"overall": {"value": 82}}}})
            return httpx.Response(200, json=out)
        if "dailysummaries" in path:
            return httpx.Response(200, json=[{"calendarDate": d, "restingHeartRate": 52, "userFullName": "Jane Doe"}
                                             for d in self._days(q["startDate"], q["endDate"])])
        if "dailyHeartRate" in path:
            return httpx.Response(200, json={"calendarDate": q["date"], "restingHeartRate": 53})
        if "activities/search" in path:
            start, limit = int(q["start"]), int(q["limit"])
            return httpx.Response(200, json=self.activities[start:start + limit])
        return httpx.Response(404)


def run(fake, db_path, days=60):
    client = garmin.GarminClient(KEY, transport=httpx.MockTransport(fake), pause=0)
    return garmin.sync(client=client, db_path=db_path, history_days=days, today=TODAY)


def test_full_sync_imports_history_in_chunks(db_path):
    fake = FakeGarmin()
    assert run(fake, db_path)["status"] == "ok"
    conn = connect(db_path)
    rows = conn.execute("SELECT * FROM daily_metrics ORDER BY date").fetchall()
    assert len(rows) == 61 and rows[0]["date"] == (TODAY - timedelta(days=60)).isoformat()
    day = dict(rows[10])
    assert (day["hrv"], day["hrv_baseline_low"], day["hrv_baseline_high"]) == (50, 44, 58)
    assert (day["resting_hr"], day["sleep_seconds"], day["sleep_score"]) == (52, 27000, 82)
    assert (day["body_battery_high"], day["body_battery_low"], day["stress_avg"], day["steps"]) == (91, 22, 31, 8000)
    assert dict(rows[-1])["sleep_seconds"] is None                    # empty night stays missing
    assert conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 130
    state = get_sync_state(conn, "garmin")
    assert state["last_success"] and state["last_error"] is None
    assert state["info"]["metrics_complete"] and state["info"]["activities_complete"]
    assert fake.token_calls == 1
    # No request asked for more than 28 days.
    hrv_ranges = [p.split("/")[-2:] for p in fake.calls if "/hrv-service/" in p]
    assert all((date.fromisoformat(e) - date.fromisoformat(s)).days < 28 for s, e in hrv_ranges)


def test_no_personal_fields_are_stored(db_path):
    run(FakeGarmin(), db_path)
    dump = "\n".join(connect(db_path).iterdump())
    for forbidden in ("Jane", "Vienna", "48.2", "16.3", KEY, TOKEN):
        assert forbidden not in dump


def test_activity_load_comes_from_heart_rate_zones(db_path, cfg):
    run(FakeGarmin(), db_path)
    w = wk.list_workouts(connect(db_path), cfg)[0]
    # zone minutes 5,15,20,5,0 -> 5 + 30 + 60 + 20 = 115, x scale 2.0
    assert w["sport"] == "swimming" and w["load_method"] == "heart_rate" and w["load"] == 230
    assert w["title"] == "Swimming"


def test_second_sync_is_light_and_adds_nothing(db_path):
    fake = FakeGarmin()
    run(fake, db_path)
    first = len(fake.calls)
    run(fake, db_path)
    assert len(fake.calls) - first == len(garmin.ENDPOINTS) + 1          # recent metrics + one activity page
    assert connect(db_path).execute("SELECT COUNT(*) FROM records").fetchone()[0] == 130


def test_interrupted_backfill_resumes(db_path):
    broken = FakeGarmin(fail_after=14)       # dies in the middle of the history
    assert run(broken, db_path)["status"] == "error"
    conn = connect(db_path)
    info = get_sync_state(conn, "garmin")["info"]
    assert info.get("metrics_done_through") and not info.get("metrics_complete")
    assert get_sync_state(conn, "garmin")["last_error"]
    conn.close()
    fake = FakeGarmin()
    assert run(fake, db_path)["status"] == "ok"
    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM daily_metrics WHERE hrv IS NOT NULL").fetchone()[0] == 61
    first_chunk_end = (TODAY - timedelta(days=4)).isoformat()
    assert not any(p.endswith(first_chunk_end) for p in fake.calls if "/hrv-service/" in p)   # not fetched twice


def test_one_failing_endpoint_gives_partial_sync_with_clear_error(db_path):
    assert run(FakeGarmin(fail_paths=("dailySleepSummariesByDate",)), db_path)["status"] == "partial"
    conn = connect(db_path)
    state = get_sync_state(conn, "garmin")
    assert "sleep: HTTP 500" in state["last_error"] and state["last_success"]
    assert conn.execute("SELECT COUNT(*) FROM daily_metrics WHERE hrv IS NOT NULL").fetchone()[0] == 61


def test_resting_hr_falls_back_to_daily_heart_rate(db_path):
    run(FakeGarmin(fail_paths=("dailysummaries",)), db_path)
    row = connect(db_path).execute("SELECT resting_hr FROM daily_metrics WHERE date = ?", (TODAY.isoformat(),)).fetchone()
    assert row["resting_hr"] == 53


def test_rejected_key_is_reported_without_leaking_it(db_path):
    result = run(FakeGarmin(reject_key=True), db_path)
    assert result["status"] == "error" and "rejected the API key" in result["error"]
    state = get_sync_state(connect(db_path), "garmin")
    assert KEY not in json.dumps(state) and state["last_success"] is None


def test_stored_data_still_works_when_garmin_is_down(db_path):
    run(FakeGarmin(), db_path, days=40)
    assert run(FakeGarmin(fail_after=0), db_path)["status"] == "error"
    ctx = service.Context(connect(db_path), today=TODAY)
    r = ctx.readiness(TODAY)
    assert 0 <= r["score"] <= 100 and r["components"]["hrv"] is not None       # R5
