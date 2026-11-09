# Training Readiness

A personal, locally hosted app that answers one question each day: **can I train today, and how hard?**
It combines Garmin data, Hevy gym workouts and manually logged sessions into one view of fitness, load and readiness.
Rules only, no AI in the scoring, and nothing leaves your PC. Not medical advice.

The full requirements are in [docs/requirements.md](docs/requirements.md).

## Before first use: two things to verify

The app was built without access to your Garmin account or a real Hevy export, so two parts are written from
documentation and still need a check against real data:

1. **Garmin responses.** Paths are from the requirements; the query parameter names for the sleep and daily-summary
   endpoints, and the response field names, are assumptions. Run the probe below. It prints only the *shape* of each
   response (keys and types, no values). If an endpoint fails or a field is named differently, adjust `ENDPOINTS`
   and the `parse_*` functions in `backend/app/sources/garmin.py`.
2. **Hevy CSV columns.** The importer expects Hevy's usual columns (`title, start_time, end_time, exercise_title,
   set_type, weight_kg, reps, rpe, ...`). If your export differs, the import fails with a message listing the columns
   it found; add them to `ALIASES` in `backend/app/sources/hevy.py`.

## Setup (Windows PC)

Requires Python 3.11+ and Node.js 20+.

```powershell
python -m venv .venv
.venv\Scripts\pip install -r backend\requirements.txt
copy .env.example .env        # then put your key in GARMIN_API_KEY
cd frontend; npm install; npm run build; cd ..
```

Check the Garmin connection (prints response shapes only):

```powershell
cd backend; ..\.venv\Scripts\python -m app.sources.garmin --probe
```

Start the app:

```powershell
cd backend; ..\.venv\Scripts\python -m app.main
```

Open http://127.0.0.1:8000. The first sync imports up to a year of history in 28-day chunks and resumes if interrupted.

### Start automatically

```powershell
.\scripts\install-autostart.ps1
```

This registers a scheduled task that starts the app at login. (Script not yet tested on a real Windows machine.)

### Phone access through Tailscale

The app listens on `127.0.0.1` only. Expose it to your own devices, with HTTPS, using:

```powershell
tailscale serve --bg 8000
```

Then open the `https://<pc-name>.<tailnet>.ts.net` address on your phone and use "Add to Home Screen" to install it.
Do not use `tailscale funnel`; that would make it public.

## Trying it without a Garmin key

```bash
DATABASE_PATH=data/demo.db python scripts/seed_demo.py
cd backend && DATABASE_PATH=data/demo.db python -m app.main
```

## How it works

| Part | Where |
|---|---|
| Thresholds and weights (one place) | `backend/app/config.py`, editable in Settings |
| Load on one scale | `backend/app/engine/load.py` |
| Readiness score, verdict, hard limits, confidence | `backend/app/engine/readiness.py` |
| Garmin sync (separate module) | `backend/app/sources/garmin.py` |
| Hevy CSV import (separate module) | `backend/app/sources/hevy.py` |
| Merging records from different sources | `backend/app/workouts.py` |
| Markdown export | `backend/app/export.py` |
| Screens | `frontend/src/` |

**Load.** Manual and gym sessions: minutes x effort (1-10). Watch sessions with heart rate: zone-weighted minutes
(zones 1-5 weighted 1-5) times a scale factor, 2.0 by default and learned from your own data once five watch sessions
with heart rate also have an effort rating. Gym sessions always use effort.

**Readiness.** 60% recovery (HRV, resting HR, sleep, Body Battery against your 28-day baseline), 30% load (ratio of
7-day to 28-day load, weekly ramp, hard days), 10% check-in (moves to recovery if skipped). Verdicts: Go hard from 80,
Train normally from 60, Keep it easy from 40, otherwise Rest. Illness, a pain note or three hard days in a row cap the
verdict at Keep it easy; a load ratio above 1.5 caps it at Train normally.

**Privacy.** Only whitelisted Garmin fields are stored: no owner name, no activity names, no GPS points, no FIT files.
The API key is read from `.env` and never written to the database, logs, exports or API responses.

## Tests

```bash
pip install -r backend/requirements-dev.txt
cd backend && python -m pytest
```

## Development

Run the backend as above and, in a second terminal, `cd frontend && npm run dev` (proxies `/api` to port 8000).
