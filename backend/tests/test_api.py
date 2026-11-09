from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from tests.test_workouts import HEVY


@pytest.fixture
def client(db_path, monkeypatch):
    from app.main import app
    app.state.run_scheduler = False
    with TestClient(app) as c:
        yield c


def test_today_works_on_an_empty_database(client):
    body = client.get("/api/today").json()
    assert body["readiness"]["verdict"] in {"Go hard", "Train normally", "Keep it easy", "Rest"}
    assert body["readiness"]["confidence"] == "Low"
    assert body["suggest_backfill"] and "not medical advice" in body["disclaimer"]
    assert any("GARMIN_API_KEY" in w for w in body["warnings"])


def test_log_edit_delete_workout(client):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    r = client.post("/api/workouts", json={"sport": "Volleyball", "duration_min": 90, "effort": 7,
                                           "start_time": f"{yesterday}T19:00:00", "notes": "league"})
    assert r.status_code == 201
    wid = r.json()["workout_id"]
    w = client.get("/api/workouts").json()[0]
    assert (w["sport"], w["load"], w["date"], w["notes"]) == ("volleyball", 630, yesterday, "league")
    assert client.patch(f"/api/workouts/{wid}", json={"effort": 5, "duration_min": 60}).status_code == 200
    assert client.get("/api/workouts").json()[0]["load"] == 300
    assert client.delete(f"/api/workouts/{wid}").status_code == 200
    assert client.get("/api/workouts").json() == []


def test_validation(client):
    assert client.post("/api/workouts", json={"sport": "x", "duration_min": 30, "effort": 11}).status_code == 422
    assert client.post("/api/workouts", json={"sport": "x", "effort": 5}).status_code == 422
    assert client.get("/api/export?start=2026-11-09&end=2026-11-01").status_code == 422


def test_backfill_marks_sessions_estimated_and_is_idempotent(client):
    body = {"sport": "volleyball", "weekday": 1, "time": "19:00", "duration_min": 90, "effort": 7}
    assert client.post("/api/backfill", json=body).json() == {"created": 4}
    assert client.post("/api/backfill", json=body).json() == {"created": 0}
    ws = client.get("/api/workouts").json()
    assert len(ws) == 4 and all(w["estimated"] and date.fromisoformat(w["date"]).weekday() == 1 for w in ws)
    today = client.get("/api/today").json()
    assert not today["suggest_backfill"]
    assert any("estimated" in n for n in today["readiness"]["confidence_notes"])


def test_checkin_changes_verdict(client):
    today = date.today().isoformat()
    assert client.get(f"/api/checkin/{today}").json() is None
    client.put(f"/api/checkin/{today}", json={"soreness": 2, "energy": 4, "ill": True})
    body = client.get("/api/today").json()
    assert body["checkin"]["ill"] == 1
    assert body["readiness"]["verdict"] in {"Keep it easy", "Rest"}
    assert "ill" in body["readiness"]["reasons"][0]


def test_hevy_import_and_rating_prompt(client):
    csv = HEVY.replace("5 Nov 2026", date.today().strftime("%-d %b %Y")).replace("7 Nov 2026", "1 Jan 2020")
    r = client.post("/api/hevy/import", content=csv.encode(), headers={"Content-Type": "text/csv"})
    assert r.json()["added"] == 2
    body = client.get("/api/today").json()
    assert [w["title"] for w in body["needs_effort"]] == ["Push Day"]      # only recent ones are asked about
    assert body["sync"]["hevy"]["info"]["added"] == 2
    assert client.post("/api/hevy/import", content=b"x,y\n1,2\n").status_code == 400
    assert "Hevy" in client.get("/api/sync/status").json()["hevy"]["last_error"]


def test_settings_roundtrip_and_key_expiry_warning(client):
    soon = (date.today() + timedelta(days=5)).isoformat()
    body = client.put("/api/settings", json={
        "thresholds": {"sleep_target_hours": 7.5, "unknown": 1, "verdict_go_hard": "x"},
        "presets": [{"name": "Padel", "sport": "padel", "duration_min": 60, "effort": 6}],
        "garmin_key_expires": soon,
    }).json()
    assert body["thresholds"]["sleep_target_hours"] == 7.5 and body["thresholds"]["verdict_go_hard"] == 80
    assert "unknown" not in body["thresholds"] and body["presets"][0]["name"] == "Padel"
    assert any("expires in 5 day" in w for w in client.get("/api/today").json()["warnings"])


def test_trends_and_export(client):
    today = date.today()
    client.post("/api/workouts", json={"sport": "volleyball", "duration_min": 90, "effort": 7,
                                       "start_time": f"{today - timedelta(days=2)}T19:00:00"})
    client.put(f"/api/checkin/{today - timedelta(days=1)}", json={"soreness": 3, "energy": 3, "pain_note": "sore calf"})
    rows = client.get("/api/trends?days=14").json()
    assert len(rows) == 14 and rows[-3]["load"] == 630 and rows[0]["readiness"] is None
    start, end = (today - timedelta(days=6)).isoformat(), today.isoformat()
    md = client.get(f"/api/export?start={start}&end={end}").text
    for expected in ("## Profile", "## How the numbers are defined", "## Daily overview", "## Workouts",
                     "volleyball", "load 630", "sore calf", "previous 4 weeks", "## Missing or uncertain data",
                     "No HRV on 7 of 7 days", "not medical advice"):
        assert expected in md, expected


def test_sync_run_needs_key(client):
    assert client.post("/api/sync/run").status_code == 400
