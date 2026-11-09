# Training Readiness App: Requirements

Status: version 1 built on 2026-11-09; Garmin parsing and Hevy CSV columns still to be verified against real data (see section 9).
Last updated 2026-11-09.

## 1. Purpose

A personal, locally hosted app that answers one question each day: can I train today, and how hard? It combines Garmin data, Hevy gym workouts and manually logged sessions (such as volleyball without the watch) into a single view of fitness, load and readiness.

## 2. User profile

| Item | Value |
|---|---|
| Goal | General fitness and staying healthy |
| Current training | About 5 sessions a week: volleyball once (no watch), gym (not on watch), swimming (recorded on watch) |
| Direction | Wants to increase training volume safely |
| Watch | Garmin Vivoactive 5, worn during sleep |
| Gym logging | Hevy, free plan (no API access) |
| Health notes | Allergy medication. Hamstring strain about 5 months ago, expected healed. No training restrictions |
| Language and units | English, metric |

## 3. Data sources

### 3.1 Garmin Personal API

- Key is stored in `.env` as `GARMIN_API_KEY`.
- The app exchanges the key for an access token that lasts 24 hours. There are no refresh tokens, so it requests a new one when needed.
- Base URL: `https://personal.connectapi.garmin.com`
- Read-only and pull-only. The app cannot push workouts to the watch.

| Data | Endpoint | Range limit |
|---|---|---|
| Activities | `/activitylist-service/activities/search/activities`, `/activity-service/activity/{id}` | Paged, 100 per request tested |
| Original FIT file | `/download-service/files/activity/{id}` | Per activity |
| HR zones | `/biometric-service/heartRateZones/v2` | n/a |
| HRV | `/hrv-service/hrv/daily/{from}/{to}` | 28 days tested |
| Sleep | `/sleep-service/sleep/dailySleepSummariesByDate` | 31 days |
| Body Battery | `/wellness-service/wellness/bodyBattery/reports/daily` | 31 days |
| Stress | `/usersummary-service/stats/stress/daily/{start}/{end}` | 28 days |
| Steps | `/usersummary-service/stats/steps/daily/{start}/{end}` | 28 days |
| Resting HR and daily stats | `/usersummary-service/v2/dailysummaries`, `/wellness-service/wellness/dailyHeartRate` | 1 year (v2 summaries) |

Not offered by the API: Training Readiness, Training Status, Acute Load, Recovery Time.

Token call notes: `POST /personalapitoken-service/personal-api/personal-api-key/token` with `Authorization: ApiKey <key>`. It returns HTTP 406 if `Accept: application/json` is sent, and the token comes back as a plain value rather than a JSON object.

Results of the live test on 2026-11-09 (last 28 days, latest 100 activities):

| Data | Result |
|---|---|
| Resting HR, stress, Body Battery | Present on 28 of 28 days |
| HRV | Overnight value on 22 of 28 days, including Garmin's own baseline range |
| Sleep | 22 of 28 nights. Missing nights come back as empty records |
| History | HRV available from a year ago. Earliest activity is 2024-02-07 |
| Training load, training effect, VO2max per activity | Empty on all 100 activities |
| Time in HR zones | Present on most activities, including lap swimming (14 of 14) |
| No heart rate | swimming (5), other (12) and a few others have duration only |

Activity responses include the owner's name and GPS start and end points. These are not needed and must not be stored or exported.

### 3.2 Hevy CSV import

- The Hevy API requires Hevy Pro, which is not available on this account.
- Hevy's export is at Profile > Settings > Export & Import Data > Export Data > Export Workouts. The user uploads the file to the app, from phone or PC.
- Direction: Hevy to app only. Hevy's own import accepts only Strong-format CSV, so sending workouts from the app to Hevy is not supported.
- Decision: the user quick-logs gym sessions in the app (duration and effort), which keeps the score current. Importing is optional and adds exercise detail.
- Each export is expected to be the full history, so repeat imports must not create duplicates.
- The exact CSV columns must be confirmed against a real export.
- The importer stays a separate module, so the Hevy API can be added later if the account moves to Pro.

### 3.3 Manual entry

For any session with no watch or Hevy record. See section 4.

## 4. Functional requirements

### Sync

- **R1** Import available Garmin history on first run, in chunks that respect range limits, and resume if interrupted.
- **R2** Sync automatically on a schedule and on demand, using modest polling.
- **R3** Show last sync time and a clear error per source.
- **R4** Warn before the Garmin key expires (keys last 30 days to 1 year).
- **R5** Keep working from stored data when a source is unavailable.

### Workout logging

- **R6** Log a manual workout with sport, date and time, duration, effort (1 to 10) and optional notes. Duration and effort are the only required measurements.
- **R7** Provide presets for frequent sports such as volleyball, so logging takes about 15 seconds.
- **R8** Allow backdated entries, editing and deletion.
- **R9** Import Hevy CSV files and store exercises, sets, weight, reps and set RPE. Show the date of the last import and the number of workouts added or updated.
- **R10** Prompt for an overall effort rating on imported Hevy workouts that have no matching quick log, because Hevy has no workout-level effort field. Until rated, estimate from set RPE where logged and mark the value as estimated.
- **R11** Allow an optional effort rating on Garmin workouts.
- **R12** Detect overlapping records from different sources and merge them into one workout (for example Hevy detail plus Garmin heart rate), so load is never counted twice. A quick gym log and the matching Hevy import are merged the same way. Allow the user to undo a merge.
- **R12a** First-run backfill: add the last 4 weeks of sessions the watch missed, in bulk, such as "volleyball every Tuesday, about 90 minutes, effort 7". Backfilled sessions are marked as estimated.

### Daily check-in (optional)

- **R13** Morning check-in of about 20 seconds: soreness, energy, illness or allergy flare-up, and an optional pain or injury note.
- **R14** Skipping the check-in must never block the score.

### Readiness and guidance

- **R15** Produce a daily readiness score from 0 to 100 and one verdict: Go hard, Train normally, Keep it easy or Rest.
- **R16** Always list the reasons behind the verdict in plain language. No workout prescriptions in version 1.
- **R17** Recalculate after any new workout, check-in or sync, so the app can answer whether another session today is reasonable.
- **R18** Show weekly context: whether there is room to add a session, or whether load is rising too quickly.
- **R19** Show confidence, and lower it when data is missing (for example no watch overnight or an early baseline).
- **R20** Rules only. No AI or external service in the scoring.
- **R21** State that the app is not medical advice.

### Screens

- **R22** Today: score, verdict, reasons, weekly context, quick log button.
- **R23** History: all workouts from all sources, with filters.
- **R24** Log workout and check-in forms, optimised for phone use.
- **R25** Trends: load, HRV, resting HR, sleep, readiness.
- **R26** Settings: sync status, presets, thresholds.

### Weekly data export

- **R27** One action to export a selected week or custom date range for pasting into any AI assistant, with copy to clipboard and download as Markdown.
- **R28** The export must be self-contained and include:
  - short profile and goal context
  - a one-paragraph explanation of how each metric is defined
  - a daily table of readiness, verdict, HRV, resting HR, sleep, Body Battery, stress and load
  - each workout with source, duration, effort, load and a Hevy exercise summary
  - check-ins and notes
  - the week compared with the previous 4-week average
  - flagged missing data
- **R29** Export happens only when the user triggers it. The app sends no data to AI services.

## 5. Calculation model

Starting values. All thresholds live in one configuration and will be tuned against real data.

### 5.1 Load: one scale across all sources

| Session type | Load calculation |
|---|---|
| Manual or Hevy | Duration in minutes × effort (session RPE) |
| Garmin with heart rate | Zone-weighted heart-rate minutes from `hrTimeInZone_1` to `_5` |
| Garmin without heart rate | Duration × effort. Asks for effort on recent sessions, otherwise estimated and marked as such |
| Both available | Used to calibrate the two scales for this user |

Heart-rate load underestimates strength work, so merged gym sessions use effort-based load, with heart rate as supporting data.

Tracked measures: 7-day and 28-day exponentially weighted load, their ratio, week-over-week ramp, consecutive hard days, days since last hard session.

### 5.2 Readiness inputs

| Group | Inputs | Starting weight |
|---|---|---|
| Recovery | Overnight HRV, resting HR, sleep, Body Battery, compared with personal baseline | 60% |
| Load | Load ratio, ramp, recent hard days | 30% |
| Check-in | Soreness, energy (weight moves to Recovery if skipped) | 10% |

### 5.3 Hard limits on the verdict

- Illness reported: no higher than Keep it easy.
- Pain or injury note: no higher than Keep it easy, naming the note in the reasons.
- Three or more hard days in a row: no higher than Keep it easy.
- Load ratio well above the safe range: no higher than Train normally.

### 5.4 Missing history

Untracked past sessions make recent load look lower than it was, so the first-run backfill (R12a) covers the last 4 weeks. Confidence stays slightly reduced while the 28-day window still contains estimated sessions.

## 6. Technical requirements

- **T1** Backend: Python with FastAPI. Database: SQLite. Frontend: React with Tailwind CSS.
- **T2** Responsive, installable web app (PWA). Phone use is part of version 1.
- **T3** Phone access through Tailscale, using `tailscale serve` for HTTPS.
- **T4** App listens on localhost only and is exposed solely through Tailscale. No public internet exposure.
- **T5** Runs on the always-on Windows PC and starts automatically.
- **T6** `.env`, the SQLite database and raw Garmin or Hevy files are excluded from git. A `.env.example` documents the required variables.
- **T7** Secrets never appear in logs, exports or API responses.
- **T8** Unit tests cover the load and readiness calculations.
- **T9** Each data source is a separate module, so one can change without affecting the rest.

## 7. Out of scope for version 1

- Workout recommendations or training plans
- AI chat or AI-generated coaching
- Pushing data to Garmin or Hevy
- Nutrition tracking
- Multiple users
- Volleyball session type and jump tracking
- Muscle-group fatigue in the score (data is stored for later)

## 8. Build order

1. Data test: Garmin done on 2026-11-09. Check a real Hevy CSV export before building that importer.
2. Database and Garmin sync.
3. Manual logging, backfill, Hevy CSV import and check-in.
4. Load and readiness engine with tests.
5. Today, History and Trends screens.
6. Weekly export.
7. Tailscale and phone install.

## 9. Open questions

Raised while building version 1 (2026-11-09):

- **Garmin response shapes.** The sync was written without live API access. Query parameter names for the sleep and daily-summary endpoints and the response field names are assumptions; verify with `python -m app.sources.garmin --probe`. Also confirm that `hrTimeInZone_*` is in seconds.
- **Hevy CSV columns and time zone.** The importer assumes Hevy's usual export columns and treats `start_time` as local time. Confirm against a real export.
- **Not used in version 1:** FIT file download, the single-activity endpoint and the HR zones endpoint. Nothing in section 4 needs them, and FIT files contain GPS tracks.
- **Windows autostart script** (`scripts/install-autostart.ps1`) is untested on a real Windows machine.
