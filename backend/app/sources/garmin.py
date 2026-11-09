"""Garmin Personal API: token handling, parsing and sync (requirements 3.1, R1-R5).

Read-only. Only whitelisted fields are stored: the owner's name, activity names
(which often contain a place) and GPS points never reach the database.

NOTE: this module was written from the endpoint list in the requirements without
live access to the API. Paths live in ENDPOINTS; query parameter names marked
"assumed" and the response field names should be checked with:

    python -m app.sources.garmin --probe

which prints the *shape* of each response (keys and types, never values).
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterator

import httpx

from .. import workouts as wk
from ..config import get_env
from ..db import get_sync_state, now_iso, session, update_sync_state

BASE_URL = "https://personal.connectapi.garmin.com"
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
TOKEN_LIFETIME = timedelta(hours=23)       # tokens last 24 h; there are no refresh tokens
CHUNK_DAYS = 28                            # smallest range limit across the daily endpoints
ACTIVITY_PAGE = 100

ENDPOINTS: dict[str, dict] = {
    "hrv": {"path": "/hrv-service/hrv/daily/{start}/{end}"},
    "stress": {"path": "/usersummary-service/stats/stress/daily/{start}/{end}"},
    "steps": {"path": "/usersummary-service/stats/steps/daily/{start}/{end}"},
    "body_battery": {"path": "/wellness-service/wellness/bodyBattery/reports/daily",
                     "params": {"startDate": "{start}", "endDate": "{end}"}},
    "sleep": {"path": "/sleep-service/sleep/dailySleepSummariesByDate",
              "params": {"startDate": "{start}", "endDate": "{end}"}},          # param names assumed
    "daily": {"path": "/usersummary-service/v2/dailysummaries",
              "params": {"startDate": "{start}", "endDate": "{end}"}},          # param names assumed
}
ACTIVITIES_PATH = "/activitylist-service/activities/search/activities"
DAILY_HR_PATH = "/wellness-service/wellness/dailyHeartRate"                    # ?date=YYYY-MM-DD

SPORT_MAP = {
    "lap_swimming": "swimming", "open_water_swimming": "swimming", "swimming": "swimming",
    "strength_training": "strength", "indoor_cardio": "cardio", "treadmill_running": "running",
    "street_running": "running", "trail_running": "running", "indoor_cycling": "cycling",
    "road_biking": "cycling", "mountain_biking": "cycling", "casual_walking": "walking",
}

_sync_lock = threading.Lock()


class GarminError(Exception):
    """Message is safe to show: it never contains the key or a token."""


class GarminClient:
    def __init__(self, api_key: str, transport: httpx.BaseTransport | None = None, pause: float = 1.0):
        self._key = api_key
        self._http = httpx.Client(base_url=BASE_URL, timeout=30, transport=transport)
        self._token: str | None = None
        self._token_time: datetime | None = None
        self._pause = pause                # modest polling: wait between requests

    def _get_token(self, force: bool = False) -> str:
        if not self._key:
            raise GarminError("GARMIN_API_KEY is not set in .env")
        fresh = self._token and self._token_time and datetime.now() - self._token_time < TOKEN_LIFETIME
        if fresh and not force:
            return self._token  # type: ignore[return-value]
        try:
            # No Accept header on purpose: the endpoint answers 406 to application/json.
            resp = self._http.post(TOKEN_PATH, headers={"Authorization": f"ApiKey {self._key}", "Accept": "*/*"})
        except httpx.HTTPError as exc:
            raise GarminError(f"Could not reach Garmin ({type(exc).__name__})") from None
        if resp.status_code in (401, 403):
            raise GarminError("Garmin rejected the API key. It may have expired or been revoked; create a new key and update .env")
        if resp.status_code != 200:
            raise GarminError(f"Garmin token request failed (HTTP {resp.status_code})")
        token = resp.text.strip()
        if token.startswith("{"):          # tolerate a JSON object should the format change
            body = json.loads(token)
            token = body.get("access_token") or body.get("token") or ""
        token = token.strip('"')
        if not token:
            raise GarminError("Garmin returned an empty token")
        self._token, self._token_time = token, datetime.now()
        return token

    def get(self, path: str, params: dict | None = None) -> Any:
        for attempt in (1, 2):
            token = self._get_token(force=attempt == 2)
            try:
                resp = self._http.get(path, params=params, headers={"Authorization": f"Bearer {token}"})
            except httpx.HTTPError as exc:
                raise GarminError(f"Could not reach Garmin ({type(exc).__name__})") from None
            if resp.status_code == 401 and attempt == 1:
                continue                   # token expired early: fetch a new one once
            break
        if self._pause:
            time.sleep(self._pause)
        if resp.status_code == 429:
            raise GarminError("Garmin rate limit reached; will try again at the next sync")
        if resp.status_code not in (200, 204):
            raise GarminError(f"HTTP {resp.status_code} from {path.split('?')[0]}")
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            raise GarminError(f"Unexpected non-JSON answer from {path}") from None


# ---------- parsing helpers (tolerant of nesting differences) ----------

DATE_KEYS = ("calendarDate", "date", "summaryDate", "calendarDateStr")


def iter_day_records(payload: Any) -> Iterator[tuple[str, dict]]:
    """Yield (YYYY-MM-DD, record) for every dict in the payload that carries a date."""
    if isinstance(payload, list):
        for item in payload:
            yield from iter_day_records(item)
    elif isinstance(payload, dict):
        for key in DATE_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and len(value) >= 10 and value[4] == "-" and value[7] == "-":
                yield value[:10], payload
                return
        for value in payload.values():
            if isinstance(value, (list, dict)):
                yield from iter_day_records(value)


def find_number(record: Any, names: tuple[str, ...], depth: int = 3) -> float | None:
    """First numeric value stored under one of `names`, searching nested dicts."""
    if not isinstance(record, dict) or depth < 0:
        return None
    for name in names:
        value = record.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    for value in record.values():
        if isinstance(value, dict):
            found = find_number(value, names, depth - 1)
            if found is not None:
                return found
    return None


def _positive(value: float | None) -> float | None:
    return value if value is not None and value > 0 else None      # Garmin uses -1 / -2 for "no data"


def parse_hrv(rec: dict) -> dict:
    baseline = rec.get("baseline") if isinstance(rec.get("baseline"), dict) else {}
    status = rec.get("status")
    return {
        "hrv": _positive(find_number(rec, ("lastNightAvg", "lastNightAverage"), 0)),
        "hrv_baseline_low": _positive(find_number(baseline, ("balancedLow",), 0)),
        "hrv_baseline_high": _positive(find_number(baseline, ("balancedUpper", "balancedHigh"), 0)),
        "hrv_status": status if isinstance(status, str) else None,
    }


def parse_sleep(rec: dict) -> dict:
    score = None
    scores = rec.get("sleepScores")
    if isinstance(scores, dict) and isinstance(scores.get("overall"), dict):
        score = find_number(scores["overall"], ("value",), 0)
    if score is None:
        score = find_number(rec, ("overallSleepScore", "sleepScore", "overallScore"))
    return {
        "sleep_seconds": _positive(find_number(rec, ("sleepTimeSeconds", "totalSleepSeconds", "totalSleepTimeInSeconds"))),
        "sleep_score": _positive(score),
    }


def parse_body_battery(rec: dict) -> dict:
    levels: list[float] = []
    index = None
    for desc in rec.get("bodyBatteryValueDescriptorDTOList") or []:
        if isinstance(desc, dict) and "level" in str(desc.get("bodyBatteryValueDescriptorKey", "")).lower():
            index = desc.get("bodyBatteryValueDescriptorIndex")
    for entry in rec.get("bodyBatteryValuesArray") or []:
        if not isinstance(entry, list):
            continue
        if isinstance(index, int) and index < len(entry) and isinstance(entry[index], (int, float)):
            levels.append(float(entry[index]))
            continue
        for value in entry[1:]:            # entry[0] is the timestamp
            if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 100:
                levels.append(float(value))
                break
    if levels:
        return {"body_battery_high": max(levels), "body_battery_low": min(levels)}
    return {
        "body_battery_high": _positive(find_number(rec, ("bodyBatteryHighestValue", "highestBodyBattery", "highBodyBattery"))),
        "body_battery_low": _positive(find_number(rec, ("bodyBatteryLowestValue", "lowestBodyBattery", "lowBodyBattery"))),
    }


def parse_stress(rec: dict) -> dict:
    return {"stress_avg": _positive(find_number(rec, ("overallStressLevel", "averageStressLevel", "avgStressLevel")))}


def parse_steps(rec: dict) -> dict:
    return {"steps": _positive(find_number(rec, ("totalSteps", "steps")))}


def parse_daily(rec: dict) -> dict:
    out = {"resting_hr": _positive(find_number(rec, ("restingHeartRate", "restingHR", "restingHeartRateInBeatsPerMinute")))}
    out.update({k: v for k, v in parse_steps(rec).items() if v})
    out.update({k: v for k, v in parse_stress(rec).items() if v})
    return out


PARSERS: dict[str, Callable[[dict], dict]] = {
    "hrv": parse_hrv, "sleep": parse_sleep, "body_battery": parse_body_battery,
    "stress": parse_stress, "steps": parse_steps, "daily": parse_daily,
}


def parse_activity(a: dict) -> dict | None:
    """Whitelist of activity fields. Name, owner and GPS are deliberately dropped."""
    activity_id = a.get("activityId")
    start = a.get("startTimeLocal")
    if activity_id is None or not isinstance(start, str):
        return None
    type_key = (a.get("activityType") or {}).get("typeKey") if isinstance(a.get("activityType"), dict) else None
    type_key = type_key or "other"
    seconds = find_number(a, ("duration", "elapsedDuration", "movingDuration"), 0) or 0
    zones = [find_number(a, (f"hrTimeInZone_{i}",), 0) or 0 for i in range(1, 6)]
    return {
        "external_id": str(activity_id),
        "sport": SPORT_MAP.get(type_key, type_key),
        "title": None,
        "start_time": start.strip().replace(" ", "T")[:19],
        "duration_min": round(seconds / 60.0, 1),
        "avg_hr": _positive(find_number(a, ("averageHR",), 0)),
        "max_hr": _positive(find_number(a, ("maxHR",), 0)),
        "zone_seconds": zones if any(zones) else None,
        "distance_m": _positive(find_number(a, ("distance",), 0)),
        "calories": _positive(find_number(a, ("calories",), 0)),
    }


# ---------- storing ----------

METRIC_COLUMNS = (
    "resting_hr", "hrv", "hrv_baseline_low", "hrv_baseline_high", "hrv_status", "sleep_seconds",
    "sleep_score", "body_battery_high", "body_battery_low", "stress_avg", "steps",
)


def store_metrics(conn: sqlite3.Connection, day: str, values: dict) -> None:
    values = {k: v for k, v in values.items() if k in METRIC_COLUMNS and v is not None}
    if not values:
        return
    cols = list(values)
    conn.execute(
        f"INSERT INTO daily_metrics(date, {', '.join(cols)}, updated_at) "
        f"VALUES(?, {', '.join('?' for _ in cols)}, ?) "
        f"ON CONFLICT(date) DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in cols)}, updated_at = excluded.updated_at",
        [day, *values.values(), now_iso()],
    )


def fetch_metrics(client: GarminClient, conn: sqlite3.Connection, start: date, end: date) -> dict[str, str]:
    """Fetch every daily endpoint for one range. Returns {endpoint: error} for those that failed."""
    errors: dict[str, str] = {}
    fmt = {"start": start.isoformat(), "end": end.isoformat()}
    parsed: list[tuple[str, dict]] = []
    for kind, spec in ENDPOINTS.items():   # network first, so the database is not locked meanwhile
        try:
            params = {k: v.format(**fmt) for k, v in spec.get("params", {}).items()} or None
            payload = client.get(spec["path"].format(**fmt), params)
        except GarminError as exc:
            errors[kind] = str(exc)
            continue
        for day, rec in iter_day_records(payload):
            if fmt["start"] <= day <= fmt["end"]:
                parsed.append((day, PARSERS[kind](rec)))
    for day, values in parsed:
        store_metrics(conn, day, values)
    return errors


def fill_resting_hr(client: GarminClient, conn: sqlite3.Connection, days: list[date]) -> None:
    """Fallback for days the daily summaries left without a resting HR (recent days only)."""
    for day in days:
        row = conn.execute("SELECT resting_hr FROM daily_metrics WHERE date = ?", (day.isoformat(),)).fetchone()
        if row and row["resting_hr"]:
            continue
        try:
            payload = client.get(DAILY_HR_PATH, {"date": day.isoformat()})
        except GarminError:
            return
        store_metrics(conn, day.isoformat(), {"resting_hr": _positive(find_number(payload, ("restingHeartRate",)))})


def fetch_activities(client: GarminClient, conn: sqlite3.Connection, offset: int, limit: int) -> tuple[int, int]:
    """Fetch one page. Returns (number received, number newly added)."""
    payload = client.get(ACTIVITIES_PATH, {"start": offset, "limit": limit})
    items = payload if isinstance(payload, list) else (payload or {}).get("activities") or []
    added = 0
    for item in items:
        parsed = parse_activity(item) if isinstance(item, dict) else None
        if parsed is None:
            continue
        external_id = parsed.pop("external_id")
        if wk.upsert_external(conn, "garmin", external_id, parsed) == "added":
            added += 1
    return len(items), added


# ---------- sync ----------

def sync(client: GarminClient | None = None, db_path: Any = None, history_days: int | None = None,
         today: date | None = None) -> dict:
    """Refresh recent data, then continue the history backfill where it stopped (R1).

    Progress is committed after every chunk, so an interrupted first run resumes.
    """
    if not _sync_lock.acquire(blocking=False):
        return {"status": "already_running"}
    env = get_env()
    today = today or date.today()
    history_days = history_days or env.garmin_history_days
    errors: dict[str, str] = {}
    try:
        with session(db_path) as conn:
            update_sync_state(conn, "garmin", last_attempt=now_iso())
        client = client or GarminClient(env.garmin_api_key)

        # 1. Recent days and newest activities.
        with session(db_path) as conn:
            errors.update(fetch_metrics(client, conn, today - timedelta(days=3), today))
            fill_resting_hr(client, conn, [today - timedelta(days=i) for i in range(3)])
        if len(errors) == len(ENDPOINTS):
            raise GarminError("; ".join(sorted(set(errors.values()))))
        with session(db_path) as conn:
            fetch_activities(client, conn, 0, 20)

        # 2. History backfill, newest to oldest, resumable.
        horizon = today - timedelta(days=history_days)
        while True:
            with session(db_path) as conn:
                info = get_sync_state(conn, "garmin")["info"]
                done_through = info.get("metrics_done_through")
                end = date.fromisoformat(done_through) - timedelta(days=1) if done_through else today - timedelta(days=4)
                if info.get("metrics_complete") or end < horizon:
                    info["metrics_complete"] = True
                    update_sync_state(conn, "garmin", info=info)
                    break
                start = max(horizon, end - timedelta(days=CHUNK_DAYS - 1))
                chunk_errors = fetch_metrics(client, conn, start, end)
                if len(chunk_errors) == len(ENDPOINTS):
                    raise GarminError("; ".join(sorted(set(chunk_errors.values()))))
                errors.update(chunk_errors)
                info["metrics_done_through"] = start.isoformat()
                update_sync_state(conn, "garmin", info=info)
        while True:
            with session(db_path) as conn:
                info = get_sync_state(conn, "garmin")["info"]
                if info.get("activities_complete"):
                    break
                offset = int(info.get("activities_offset", 0))
                received, _ = fetch_activities(client, conn, offset, ACTIVITY_PAGE)
                info["activities_offset"] = offset + received
                info["activities_complete"] = received < ACTIVITY_PAGE
                update_sync_state(conn, "garmin", info=info)

        with session(db_path) as conn:
            message = None
            if errors:
                message = "Partly synced. " + "; ".join(f"{k}: {v}" for k, v in sorted(errors.items()))
            update_sync_state(conn, "garmin", last_success=now_iso(), last_error=message)
        return {"status": "ok" if not errors else "partial", "errors": errors}
    except GarminError as exc:
        with session(db_path) as conn:
            update_sync_state(conn, "garmin", last_error=str(exc))
        return {"status": "error", "error": str(exc)}
    except Exception as exc:  # never let a parsing surprise kill the scheduler
        with session(db_path) as conn:
            update_sync_state(conn, "garmin", last_error=f"Unexpected error during sync ({type(exc).__name__})")
        return {"status": "error", "error": type(exc).__name__}
    finally:
        _sync_lock.release()


# ---------- probe: print response shapes without values ----------

def shape(value: Any, depth: int = 0) -> Any:
    if isinstance(value, dict):
        return {k: shape(v, depth + 1) for k, v in value.items()} if depth < 4 else "{...}"
    if isinstance(value, list):
        return [shape(value[0], depth + 1), f"... {len(value)} items"] if value else []
    return type(value).__name__


def probe() -> None:
    client = GarminClient(get_env().garmin_api_key)
    end = date.today()
    fmt = {"start": (end - timedelta(days=6)).isoformat(), "end": end.isoformat()}
    calls = [(k, s["path"].format(**fmt), {a: b.format(**fmt) for a, b in s.get("params", {}).items()} or None)
             for k, s in ENDPOINTS.items()]
    calls.append(("activities", ACTIVITIES_PATH, {"start": 0, "limit": 3}))
    calls.append(("daily_hr", DAILY_HR_PATH, {"date": fmt["end"]}))
    for kind, path, params in calls:
        print(f"\n=== {kind}: {path} params={sorted(params) if params else None}")
        try:
            print(json.dumps(shape(client.get(path, params)), indent=1))
        except GarminError as exc:
            print(f"FAILED: {exc}")


if __name__ == "__main__":
    if "--probe" in sys.argv:
        probe()
    else:
        print(json.dumps(sync(), indent=1))
