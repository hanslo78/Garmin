import json

from app import service, workouts as wk
from app.sources import hevy

HEVY = '''"title","start_time","end_time","description","exercise_title","superset_id","exercise_notes","set_index","set_type","weight_kg","reps","distance_km","duration_seconds","rpe"
"Push Day","5 Nov 2026, 18:00","5 Nov 2026, 19:05","felt ok","Bench Press (Barbell)",,"",0,"warmup",40,10,,,
"Push Day","5 Nov 2026, 18:00","5 Nov 2026, 19:05","felt ok","Bench Press (Barbell)",,"",1,"normal",60,8,,,8
"Push Day","5 Nov 2026, 18:00","5 Nov 2026, 19:05","felt ok","Bench Press (Barbell)",,"",2,"normal",60,7,,,9
"Push Day","5 Nov 2026, 18:00","5 Nov 2026, 19:05","felt ok","Shoulder Press (Dumbbell)",,"",0,"normal",18,10,,,
"Legs","7 Nov 2026, 10:00","7 Nov 2026, 10:50","","Squat (Barbell)",,"",0,"normal",80,5,,,
'''


def garmin(conn, ext, start, minutes, sport="swimming", zones=None):
    return wk.upsert_external(conn, "garmin", ext, {
        "sport": sport, "start_time": start, "duration_min": minutes, "zone_seconds": zones})


def test_hevy_parse_groups_sets_and_estimates_effort():
    parsed = hevy.parse(HEVY)
    assert [w["title"] for w in parsed] == ["Push Day", "Legs"]
    push = parsed[0]
    assert push["duration_min"] == 65 and push["start_time"] == "2026-11-05T18:00:00"
    assert [e["name"] for e in push["exercises"]] == ["Bench Press (Barbell)", "Shoulder Press (Dumbbell)"]
    assert len(push["exercises"][0]["sets"]) == 3
    assert push["effort"] == 8          # mean of set RPE 8 and 9, warm-up ignored
    assert parsed[1]["effort"] is None
    assert hevy.summarize_exercises(push["exercises"]).startswith("Bench Press (Barbell) 2x8 @ 60 kg")


def test_hevy_reimport_creates_no_duplicates(conn, cfg):
    assert hevy.import_csv(conn, HEVY) == {"added": 2, "updated": 0, "unchanged": 0, "skipped": 0, "total": 2}
    again = hevy.import_csv(conn, HEVY)
    assert again["added"] == 0 and again["unchanged"] == 2
    changed = hevy.import_csv(conn, HEVY.replace('"normal",80,5', '"normal",85,5'))
    assert changed["updated"] == 1 and changed["unchanged"] == 1
    assert len(wk.list_workouts(conn, cfg)) == 2


def test_hevy_rejects_other_csv(conn):
    try:
        hevy.import_csv(conn, "a,b\n1,2\n")
        assert False
    except hevy.HevyFormatError as exc:
        assert "Columns found: a, b" in str(exc)


def test_unrated_hevy_workout_is_estimated_until_rated(conn, cfg):
    hevy.import_csv(conn, HEVY)
    legs, push = wk.list_workouts(conn, cfg)
    assert push["effort"] == 8 and push["effort_source"] == "estimated" and push["load_estimated"]
    assert legs["effort"] is None and legs["load"] == 50 * cfg["default_effort"] and legs["load_estimated"]
    wk.update_workout(conn, legs["id"], {"effort": 7})
    legs = wk.list_workouts(conn, cfg)[0]
    assert legs["load"] == 350 and not legs["load_estimated"] and legs["effort_source"] == "user"


def test_quick_gym_log_merges_with_hevy_import(conn, cfg):
    wk.insert_record(conn, source="manual", sport="strength", start_time="2026-11-05T21:30:00", duration_min=60, effort=7)
    hevy.import_csv(conn, HEVY)
    ws = wk.list_workouts(conn, cfg)
    assert len(ws) == 2
    push = ws[1]
    assert set(push["sources"]) == {"hevy", "manual"}
    assert push["duration_min"] == 65 and push["effort"] == 7 and push["load"] == 455   # counted once
    assert push["exercises"] and not push["load_estimated"]


def test_garmin_and_hevy_overlap_merge_and_use_effort_load(conn, cfg):
    hevy.import_csv(conn, HEVY)
    garmin(conn, "g1", "2026-11-05T18:02:00", 60, sport="strength", zones=[600, 1200, 600, 0, 0])
    ws = wk.list_workouts(conn, cfg)
    assert len(ws) == 2
    push = ws[1]
    assert push["sources"] == ["garmin", "hevy"]
    assert push["load_method"] == "effort" and push["zone_seconds"]     # HR kept as supporting data


def test_non_overlapping_sessions_stay_separate(conn, cfg):
    garmin(conn, "g1", "2026-11-05T07:00:00", 40)                      # morning swim
    hevy.import_csv(conn, HEVY)                                        # evening gym
    wk.insert_record(conn, source="manual", sport="volleyball", start_time="2026-11-05T20:00:00", duration_min=90, effort=7)
    assert len(wk.list_workouts(conn, cfg, "2026-11-05", "2026-11-05")) == 3


def test_unmerge_is_remembered(conn, cfg):
    hevy.import_csv(conn, HEVY)
    garmin(conn, "g1", "2026-11-05T18:02:00", 60, sport="strength")
    push = wk.list_workouts(conn, cfg, "2026-11-05", "2026-11-05")[0]
    garmin_rec = next(r for r in push["records"] if r["source"] == "garmin")
    wk.unmerge(conn, push["id"], garmin_rec["id"])
    assert len(wk.list_workouts(conn, cfg, "2026-11-05", "2026-11-05")) == 2
    wk.auto_merge(conn, garmin_rec["id"])                               # e.g. on the next sync
    assert len(wk.list_workouts(conn, cfg, "2026-11-05", "2026-11-05")) == 2


def test_deleted_imports_do_not_come_back(conn, cfg):
    garmin(conn, "g1", "2026-11-05T07:00:00", 40)
    wk.delete_workout(conn, wk.list_workouts(conn, cfg)[0]["id"])
    assert garmin(conn, "g1", "2026-11-05T07:00:00", 40) == "skipped"
    assert wk.list_workouts(conn, cfg) == []


def test_heart_rate_scale_is_calibrated_from_rated_sessions(conn, cfg):
    for i in range(5):
        garmin(conn, f"g{i}", f"2026-11-0{i + 1}T07:00:00", 40, zones=[0, 0, 2400, 0, 0])   # 120 zone-minutes
    assert wk.hr_scale(conn, cfg) == 2.0
    for w in wk.list_workouts(conn, cfg):
        wk.update_workout(conn, w["id"], {"effort": 9})                 # 360 effort load each
    assert wk.hr_scale(conn, cfg) == 3.0
    assert wk.list_workouts(conn, cfg)[0]["load"] == 360


def test_context_and_weekly(conn):
    from datetime import date, timedelta
    today = date.today()
    for i in range(1, 36):
        if i % 2:
            d = today - timedelta(days=i)
            wk.insert_record(conn, source="manual", sport="volleyball", start_time=f"{d}T18:00:00", duration_min=60, effort=5)
    ctx = service.Context(conn)
    weekly = ctx.weekly(today)
    assert weekly["status"] in {"room", "on_track", "full"} and weekly["avg_4_weeks"] > 0
    r = ctx.readiness(today)
    assert r["confidence"] == "Low" and 0 <= r["score"] <= 100       # no watch data at all
    wk.insert_record(conn, source="manual", sport="volleyball", start_time=f"{today}T08:00:00", duration_min=90, effort=8)
    assert service.Context(conn).readiness(today)["score"] < r["score"]   # R17
