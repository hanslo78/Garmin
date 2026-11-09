# Handover: Training Readiness app

Written 2026-11-09 for continuing work locally (in `C:\Projekte\Garmin`) without the cloud session.
Read this together with [requirements.md](requirements.md) (the spec) and the [README](../README.md) (setup).

## Where things stand

- Version 1 is built and merged into `main` (commit `624bab3`).
- It runs on the Windows PC and a first Garmin history import was started there.
- 60 automated tests pass. They cover the calculations, merging, the Hevy importer, the API, and the Garmin sync
  against a *fake* server.
- **Not yet confirmed against real data:** whether every Garmin endpoint parses correctly, and the Hevy CSV columns.
  The import started on the PC, but nobody has checked what actually landed in the database.

## First things to do locally

1. **Check what the Garmin import produced.** Open Settings > Sync status. Any endpoint that failed is named there
   ("Partly synced. sleep: HTTP 400 ..."). Then open Trends: each chart (HRV, resting HR, sleep, Body Battery) should
   have data. An empty chart with no sync error means the request worked but the field names did not match.
2. **If something is missing, run the probe** from `backend\`:
   `..\.venv\Scripts\python -m app.sources.garmin --probe`
   It prints the shape of each response (keys and types, no values). Compare with the `parse_*` functions and
   `ENDPOINTS` in `backend/app/sources/garmin.py` and adjust. The most likely trouble spots are listed below.
3. **Import a real Hevy export** (Log > Hevy import). If the columns differ, the error lists the columns found;
   add them to `ALIASES` in `backend/app/sources/hevy.py`.
4. **Do the 4-week backfill** for volleyball (Log > Backfill), so recent load is not understated.
5. **Set the key expiry date** in Settings so the app can warn before the Garmin key runs out.
6. **Autostart and phone:** run `scripts\install-autostart.ps1`, reboot once to confirm it starts, then
   `tailscale serve --bg 8000` and install on the phone via "Add to Home Screen".

## Known assumptions and risks

| Area | Assumption | Where to fix |
|---|---|---|
| Sleep endpoint | Query parameters are `startDate` / `endDate` | `ENDPOINTS["sleep"]` in `garmin.py` |
| Daily summaries (resting HR) | Query parameters are `startDate` / `endDate`; field is `restingHeartRate`. Falls back to `dailyHeartRate` for the last 3 days only | `ENDPOINTS["daily"]`, `parse_daily`, `fill_resting_hr` |
| Body Battery | Level is read from `bodyBatteryValuesArray`; the day's maximum is used as the "morning peak" | `parse_body_battery` |
| HR zone times | `hrTimeInZone_1..5` are in seconds | `parse_activity` |
| Activity start time | `startTimeLocal` is used as local time | `parse_activity` |
| Hevy `start_time` | Treated as local time. If Hevy exports UTC, gym sessions will be offset and may not merge with quick logs | `_parse_time` in `hevy.py` |
| Hevy identity | A workout is identified by its start time. Changing the start time in Hevy creates a second copy on re-import | `parse` in `hevy.py` |
| Windows autostart | Script written but never run on real Windows | `scripts/` |

If older history turns out wrong after a parser fix, the already-imported days are not re-fetched automatically.
To force a full re-import, stop the app and clear the Garmin progress marker:

```powershell
cd backend; ..\.venv\Scripts\python -c "from app.db import session; s=session(); c=s.__enter__(); c.execute(\"DELETE FROM sync_state WHERE source='garmin'\"); s.__exit__(None,None,None)"
```

Existing rows are updated in place on the next sync; nothing is duplicated.

## Design decisions made during the build

These go beyond the written requirements. Change them if they do not feel right once real data is in.

- **Load score:** neutral load scores 75, not 100. Being fresh adds 10 (2 days since a hard session) or 20 (3 or
  more); strain subtracts. With 100 as neutral an entirely average day came out as "Go hard".
- **Morning ratio:** until something is logged today, the 7-day and 28-day averages run through yesterday, so an
  untrained morning is not counted as a rest day.
- **Hard session:** effort 7 or more for at least 30 minutes, or a day totalling 420 load or more. For heart-rate
  sessions without a rating, load divided by minutes stands in for effort.
- **Heart-rate scale:** zone-weighted minutes x 2.0, replaced by the median of your own sessions once 5 non-gym
  watch sessions with heart rate also have an effort rating.
- **Merging:** records from different sources merge when they overlap by at least half of the shorter one, or when
  one is a manual log on the same day with the same kind of sport. One record per source per workout. A split is
  remembered and never re-merged.
- **Past days in Trends and the export** show the morning readiness, before that day's training. Today includes
  sessions already done.
- **Privacy:** activity names are not stored (they often contain a place), along with owner name and GPS. FIT files,
  the single-activity endpoint and the HR zones endpoint are not called.
- **Deleting an imported workout** hides it permanently so a sync does not bring it back. There is no un-delete in
  the UI.
- **Allergy flare-up** lowers the check-in score but does not cap the verdict; only illness and a pain note do.

## Where the data lives

- `data\readiness.db` holds everything: Garmin data, workouts, check-ins, ratings, settings. It is excluded from git,
  so it exists only on the PC. Manual logs, check-ins and ratings cannot be re-imported; back up the `data` folder.
- `.env` holds the Garmin key and is also excluded from git. The key is never written to the database, logs or exports.
- Stopping the app or rebooting loses nothing. The history import resumes from the last finished chunk.

## Code map

| Part | File |
|---|---|
| All thresholds, weights, presets, profile text | `backend/app/config.py` |
| Load calculation | `backend/app/engine/load.py` |
| Readiness score, verdict, caps, confidence | `backend/app/engine/readiness.py` |
| Garmin client, parsers, sync, probe | `backend/app/sources/garmin.py` |
| Hevy CSV importer | `backend/app/sources/hevy.py` |
| Records, merging, combined workout view | `backend/app/workouts.py` |
| Today payload, trends, weekly context, warnings | `backend/app/service.py` |
| Markdown export | `backend/app/export.py` |
| API routes, scheduler, static file serving | `backend/app/main.py` |
| Database schema | `backend/app/db.py` |
| Screens | `frontend/src/Today.jsx`, `Log.jsx`, `History.jsx`, `Trends.jsx`, `Settings.jsx` |
| Chart component | `frontend/src/Chart.jsx` |
| Tests | `backend/tests/` |

## Working on it locally

```powershell
# run the tests (once: .venv\Scripts\pip install -r backend\requirements-dev.txt)
cd backend; ..\.venv\Scripts\python -m pytest

# after changing anything in frontend\src, rebuild and restart the app
cd frontend; npm run build

# frontend development with live reload (backend must be running)
cd frontend; npm run dev
```

After a backend change, restart the app. After a schema change in `db.py`, note that there are no migrations yet:
new tables are created automatically, but new columns on existing tables need a manual `ALTER TABLE`.

## Not built (out of scope or left for later)

- Everything in section 7 of the requirements.
- Hevy API client (the importer is a separate module so it can be added if the account moves to Pro).
- Database migrations, automatic backups, un-delete for hidden imports.
- Tuning of thresholds against real data. All values in `config.py` are starting values.
