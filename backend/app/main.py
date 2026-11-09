"""FastAPI app: JSON API under /api, built frontend served from frontend/dist."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Iterator, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import service, workouts as wk
from .config import ROOT, get_env
from .db import connect, get_setting, now_iso, set_setting
from .export import build_export
from .sources import garmin, hevy

log = logging.getLogger("readiness")
DIST = ROOT / "frontend" / "dist"


async def _scheduler() -> None:
    """R2: sync on a schedule. Errors are recorded in sync_state, never raised."""
    interval = get_env().sync_interval_minutes * 60
    while True:
        if get_env().garmin_api_key:
            result = await asyncio.to_thread(garmin.sync)
            log.info("Garmin sync: %s", result.get("status"))
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    connect().close()  # create the schema
    task = asyncio.create_task(_scheduler()) if app.state.run_scheduler else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="Training Readiness", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
app.state.run_scheduler = True


def db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, f"Invalid date: {value}") from None


# ---------- models ----------

class WorkoutIn(BaseModel):
    sport: str = Field(min_length=1, max_length=40)
    start_time: Optional[datetime] = None      # defaults to now; may be in the past (R8)
    duration_min: float = Field(gt=0, le=1440)
    effort: int = Field(ge=1, le=10)
    notes: Optional[str] = Field(default=None, max_length=2000)


class WorkoutPatch(BaseModel):
    sport: Optional[str] = Field(default=None, min_length=1, max_length=40)
    start_time: Optional[datetime] = None
    duration_min: Optional[float] = Field(default=None, gt=0, le=1440)
    effort: Optional[int] = Field(default=None, ge=1, le=10)
    notes: Optional[str] = Field(default=None, max_length=2000)


class UnmergeIn(BaseModel):
    record_id: int


class BackfillIn(BaseModel):
    sport: str = Field(min_length=1, max_length=40)
    weekday: int = Field(ge=0, le=6)           # 0 = Monday
    time: str = Field(default="18:00", pattern=r"^\d{2}:\d{2}$")
    duration_min: float = Field(gt=0, le=1440)
    effort: int = Field(ge=1, le=10)
    weeks: int = Field(default=4, ge=1, le=8)


class CheckinIn(BaseModel):
    soreness: Optional[int] = Field(default=None, ge=1, le=5)
    energy: Optional[int] = Field(default=None, ge=1, le=5)
    ill: bool = False
    allergy: bool = False
    pain_note: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=2000)


class Preset(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    sport: str = Field(min_length=1, max_length=40)
    duration_min: float = Field(gt=0, le=1440)
    effort: int = Field(ge=1, le=10)


class SettingsIn(BaseModel):
    thresholds: Optional[dict] = None
    presets: Optional[list[Preset]] = None
    profile: Optional[dict[str, str]] = None
    garmin_key_expires: Optional[str] = None
    backfill_done: Optional[bool] = None


def _local_iso(value: datetime | None) -> str:
    value = value or datetime.now()
    if value.tzinfo is not None:
        value = value.astimezone().replace(tzinfo=None)
    return value.replace(microsecond=0).isoformat()


# ---------- routes ----------

@app.get("/api/today")
def today(conn: sqlite3.Connection = Depends(db)) -> dict:
    return service.today_payload(conn)


@app.get("/api/trends")
def trends(days: int = 30, conn: sqlite3.Connection = Depends(db)) -> list[dict]:
    days = max(7, min(days, 400))
    end = date.today()
    return service.series(conn, end - timedelta(days=days - 1), end)


@app.get("/api/workouts")
def workouts(start: Optional[str] = None, end: Optional[str] = None, conn: sqlite3.Connection = Depends(db)) -> list[dict]:
    return wk.list_workouts(conn, service.get_cfg(conn), start and _date(start).isoformat(), end and _date(end).isoformat())


@app.post("/api/workouts", status_code=201)
def create_workout(body: WorkoutIn, conn: sqlite3.Connection = Depends(db)) -> dict:
    record_id = wk.insert_record(
        conn, source="manual", sport=body.sport.strip().lower(), start_time=_local_iso(body.start_time),
        duration_min=body.duration_min, effort=body.effort, notes=body.notes,
    )
    row = conn.execute("SELECT workout_id FROM records WHERE id = ?", (record_id,)).fetchone()
    return {"workout_id": row["workout_id"]}


@app.patch("/api/workouts/{workout_id}")
def patch_workout(workout_id: int, body: WorkoutPatch, conn: sqlite3.Connection = Depends(db)) -> dict:
    changes = body.model_dump(exclude_unset=True)
    if changes.get("start_time"):
        changes["start_time"] = _local_iso(changes["start_time"])
    if changes.get("sport"):
        changes["sport"] = changes["sport"].strip().lower()
    try:
        wk.update_workout(conn, workout_id, changes)
    except KeyError:
        raise HTTPException(404, "Workout not found") from None
    return {"ok": True}


@app.delete("/api/workouts/{workout_id}")
def delete_workout(workout_id: int, conn: sqlite3.Connection = Depends(db)) -> dict:
    wk.delete_workout(conn, workout_id)
    return {"ok": True}


@app.post("/api/workouts/{workout_id}/unmerge")
def unmerge(workout_id: int, body: UnmergeIn, conn: sqlite3.Connection = Depends(db)) -> dict:
    try:
        return {"workout_id": wk.unmerge(conn, workout_id, body.record_id)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@app.post("/api/backfill")
def backfill(body: BackfillIn, conn: sqlite3.Connection = Depends(db)) -> dict:
    """R12a: add the sessions the watch missed, one per week on the given weekday."""
    today_ = date.today()
    created = 0
    for offset in range(1, body.weeks * 7 + 1):
        day = today_ - timedelta(days=offset)
        if day.weekday() != body.weekday:
            continue
        sport = body.sport.strip().lower()
        exists = conn.execute(
            "SELECT 1 FROM records WHERE deleted = 0 AND source = 'manual' AND sport = ? AND substr(start_time, 1, 10) = ?",
            (sport, day.isoformat()),
        ).fetchone()
        if exists:
            continue
        wk.insert_record(
            conn, source="manual", sport=sport, start_time=f"{day.isoformat()}T{body.time}:00",
            duration_min=body.duration_min, effort=body.effort, estimated=True, notes="Backfilled estimate",
        )
        created += 1
    set_setting(conn, "backfill_done", True)
    return {"created": created}


@app.get("/api/checkin/{day}")
def get_checkin(day: str, conn: sqlite3.Connection = Depends(db)) -> dict | None:
    row = conn.execute("SELECT * FROM checkins WHERE date = ?", (_date(day).isoformat(),)).fetchone()
    return dict(row) if row else None


@app.put("/api/checkin/{day}")
def put_checkin(day: str, body: CheckinIn, conn: sqlite3.Connection = Depends(db)) -> dict:
    conn.execute(
        "INSERT INTO checkins(date, soreness, energy, ill, allergy, pain_note, notes, updated_at) VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(date) DO UPDATE SET soreness=excluded.soreness, energy=excluded.energy, ill=excluded.ill, "
        "allergy=excluded.allergy, pain_note=excluded.pain_note, notes=excluded.notes, updated_at=excluded.updated_at",
        (_date(day).isoformat(), body.soreness, body.energy, int(body.ill), int(body.allergy),
         (body.pain_note or "").strip() or None, (body.notes or "").strip() or None, now_iso()),
    )
    return {"ok": True}


@app.delete("/api/checkin/{day}")
def delete_checkin(day: str, conn: sqlite3.Connection = Depends(db)) -> dict:
    conn.execute("DELETE FROM checkins WHERE date = ?", (_date(day).isoformat(),))
    return {"ok": True}


@app.post("/api/hevy/import")
async def hevy_import(request: Request, conn: sqlite3.Connection = Depends(db)) -> dict:
    """Body is the raw CSV text of a Hevy export."""
    raw = await request.body()
    if len(raw) > 50_000_000:
        raise HTTPException(413, "File too large")
    try:
        return hevy.import_csv(conn, raw.decode("utf-8-sig", errors="replace"))
    except hevy.HevyFormatError as exc:
        conn.commit()  # keep the recorded error for the sync status
        raise HTTPException(400, str(exc)) from None


@app.get("/api/sync/status")
def sync_status(conn: sqlite3.Connection = Depends(db)) -> dict:
    return service.sync_status(conn)


@app.post("/api/sync/run")
def sync_run(background: BackgroundTasks) -> dict:
    if not get_env().garmin_api_key:
        raise HTTPException(400, "GARMIN_API_KEY is not set in .env")
    background.add_task(garmin.sync)
    return {"started": True}


@app.get("/api/settings")
def get_settings(conn: sqlite3.Connection = Depends(db)) -> dict:
    return service.settings_payload(conn)


@app.put("/api/settings")
def put_settings(body: SettingsIn, conn: sqlite3.Connection = Depends(db)) -> dict:
    if body.thresholds is not None:
        set_setting(conn, "thresholds", service.validate_thresholds(body.thresholds))
    if body.presets is not None:
        set_setting(conn, "presets", [p.model_dump() for p in body.presets])
    if body.profile is not None:
        set_setting(conn, "profile", body.profile)
    if body.garmin_key_expires is not None:
        if body.garmin_key_expires:
            _date(body.garmin_key_expires)
        set_setting(conn, "garmin_key_expires", body.garmin_key_expires)
    if body.backfill_done is not None:
        set_setting(conn, "backfill_done", body.backfill_done)
    return service.settings_payload(conn)


@app.get("/api/export", response_class=PlainTextResponse)
def export(start: str, end: str, conn: sqlite3.Connection = Depends(db)) -> str:
    s, e = _date(start), _date(end)
    if e < s or (e - s).days > 92:
        raise HTTPException(422, "Choose a range of up to 3 months, with the end after the start")
    return build_export(conn, s, e)


# ---------- frontend ----------

if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    target = (DIST / path).resolve()
    if path and target.is_file() and DIST.resolve() in target.parents:
        headers = {"Cache-Control": "no-cache"} if path == "sw.js" else None
        return FileResponse(target, headers=headers)
    index = DIST / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return PlainTextResponse("Frontend not built yet. Run: cd frontend && npm install && npm run build", status_code=503)


def run() -> None:
    import uvicorn

    env = get_env()
    logging.basicConfig(level=logging.INFO)
    uvicorn.run("app.main:app", host=env.host, port=env.port, log_level="info")


if __name__ == "__main__":
    run()
