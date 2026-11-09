import { useState } from 'react'
import { api, niceDate, niceDateTime, sportName } from './api.js'
import { Button, Card, Loading, Notice, Scale, Tag, useApi } from './ui.jsx'

export const VERDICT_COLOR = {
  'Go hard': 'var(--good)',
  'Train normally': 'var(--accent)',
  'Keep it easy': 'var(--warning)',
  Rest: 'var(--critical)',
}

function ScoreRing({ score, verdict }) {
  const r = 52
  const c = 2 * Math.PI * r
  return (
    <svg width="132" height="132" viewBox="0 0 132 132" role="img" aria-label={`Readiness ${score} out of 100`}>
      <circle cx="66" cy="66" r={r} fill="none" stroke="var(--line)" strokeWidth="10" />
      <circle
        cx="66" cy="66" r={r} fill="none" stroke={VERDICT_COLOR[verdict]} strokeWidth="10" strokeLinecap="round"
        strokeDasharray={`${(score / 100) * c} ${c}`} transform="rotate(-90 66 66)"
      />
      <text x="66" y="64" textAnchor="middle" dominantBaseline="middle" fontSize="38" fontWeight="700" fill="var(--ink)">{score}</text>
      <text x="66" y="92" textAnchor="middle" fontSize="11" fill="var(--ink2)">of 100</text>
    </svg>
  )
}

function Tile({ label, value, unit }) {
  return (
    <div className="bg-surface border border-line rounded-xl p-3">
      <div className="text-xs text-ink2">{label}</div>
      <div className="text-xl font-semibold">
        {value ?? '–'}
        {value != null && unit && <span className="text-sm font-normal text-ink2"> {unit}</span>}
      </div>
    </div>
  )
}

function RateEffort({ workout, onDone }) {
  const [error, setError] = useState(null)
  const rate = (effort) =>
    api(`/workouts/${workout.id}`, { method: 'PATCH', body: { effort } }).then(onDone).catch((e) => setError(e.message))
  return (
    <div className="py-3 border-t border-line first:border-t-0 first:pt-0">
      <div className="text-sm mb-2">
        <span className="font-medium">{workout.title}</span>
        <span className="text-ink2"> · {niceDate(workout.date)} · {Math.round(workout.duration_min)} min</span>
        {workout.effort != null && <span className="text-ink2"> · estimated {workout.effort}</span>}
      </div>
      <Scale value={null} onChange={rate} lowLabel="very easy" highLabel="maximal" />
      {error && <p className="text-sm mt-1">{error}</p>}
    </div>
  )
}

export default function Today({ version, onChanged, openLog }) {
  const state = useApi('/today', [version])
  const [syncing, setSyncing] = useState(false)
  const [syncError, setSyncError] = useState(null)
  const d = state.data
  if (!d) return <Loading state={state} />

  const r = d.readiness
  const g = d.sync.garmin
  const syncNow = async () => {
    setSyncing(true)
    setSyncError(null)
    try {
      await api('/sync/run', { method: 'POST' })
      setTimeout(() => { setSyncing(false); onChanged() }, 6000)
    } catch (e) {
      setSyncError(e.message)
      setSyncing(false)
    }
  }
  const dismissBackfill = () => api('/settings', { method: 'PUT', body: { backfill_done: true } }).then(onChanged)

  return (
    <>
      <header className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold">Today</h1>
        <span className="text-sm text-ink2">{niceDate(d.date)}</span>
      </header>

      {state.error && <Notice kind="error">{state.error} Showing the last loaded data.</Notice>}
      {d.warnings.map((w) => <Notice key={w} kind="warn">{w}</Notice>)}

      <Card>
        <div className="flex items-center gap-4">
          <ScoreRing score={r.score} verdict={r.verdict} />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span aria-hidden className="inline-block w-3 h-3 rounded-full" style={{ background: VERDICT_COLOR[r.verdict] }} />
              <span className="text-2xl font-bold leading-tight">{r.verdict}</span>
            </div>
            <div className="text-sm text-ink2 mt-1">Confidence: <span className="font-medium text-ink">{r.confidence}</span></div>
            <div className="flex flex-wrap gap-1 mt-2">
              <Tag>Recovery {r.components.recovery ?? '–'}</Tag>
              <Tag>Load {r.components.load}</Tag>
              <Tag>Check-in {r.components.checkin ?? 'skipped'}</Tag>
            </div>
          </div>
        </div>
        <h3 className="text-sm font-semibold mt-4 mb-1">Why</h3>
        <ul className="text-sm space-y-1 list-disc pl-5">
          {r.reasons.length ? r.reasons.map((x) => <li key={x}>{x}</li>) : <li>No data yet. Sync your watch or log a session.</li>}
        </ul>
        {r.confidence_notes.length > 0 && (
          <>
            <h3 className="text-sm font-semibold mt-3 mb-1">What lowers confidence</h3>
            <ul className="text-sm text-ink2 space-y-1 list-disc pl-5">
              {r.confidence_notes.map((x) => <li key={x}>{x}</li>)}
            </ul>
          </>
        )}
      </Card>

      <div className="grid grid-cols-2 gap-3">
        <Button onClick={() => openLog('workout')}>+ Log workout</Button>
        <Button variant="secondary" onClick={() => openLog('checkin')}>
          {d.checkin ? 'Edit check-in' : 'Morning check-in'}
        </Button>
      </div>
      <div className="flex flex-wrap gap-2">
        {d.presets.map((p) => (
          <button key={p.name} onClick={() => openLog('workout', p)} className="min-h-11 px-3 rounded-full border border-line bg-surface text-sm">
            {p.name} · {p.duration_min} min
          </button>
        ))}
      </div>

      {d.suggest_backfill && (
        <Notice kind="info">
          <p className="mb-2">
            Sessions without the watch (like volleyball) in the last 4 weeks are missing, so your recent load looks lower than it was.
          </p>
          <div className="flex gap-2">
            <Button onClick={() => openLog('backfill')}>Add them</Button>
            <Button variant="secondary" onClick={dismissBackfill}>Not needed</Button>
          </div>
        </Notice>
      )}

      {d.needs_effort.length > 0 && (
        <Card title="How hard were these?">
          <p className="text-sm text-ink2 mb-3">These sessions have no effort rating, so their load is a guess. Tap 1 to 10.</p>
          {d.needs_effort.map((w) => <RateEffort key={w.id} workout={w} onDone={onChanged} />)}
        </Card>
      )}

      <Card title="This week">
        <p className="font-medium">{d.weekly.message}</p>
        <dl className="grid grid-cols-3 gap-2 mt-3 text-sm">
          <div><dt className="text-ink2 text-xs">Last 7 days</dt><dd className="font-semibold">{Math.round(d.weekly.load_7d)} load</dd></div>
          <div><dt className="text-ink2 text-xs">4-week average</dt><dd className="font-semibold">{Math.round(d.weekly.avg_4_weeks)} / week</dd></div>
          <div><dt className="text-ink2 text-xs">Sessions (7 days)</dt><dd className="font-semibold">{d.weekly.sessions_7d}</dd></div>
        </dl>
        <p className="text-xs text-ink2 mt-2">
          Load ratio {d.weekly.ratio ?? 'n/a'}
          {d.weekly.ramp != null && ` · week on week ${d.weekly.ramp > 0 ? '+' : ''}${Math.round(d.weekly.ramp * 100)}%`}
        </p>
      </Card>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Tile label="Overnight HRV" value={d.metrics.hrv != null ? Math.round(d.metrics.hrv) : null} unit="ms" />
        <Tile label="Resting HR" value={d.metrics.resting_hr != null ? Math.round(d.metrics.resting_hr) : null} unit="bpm" />
        <Tile label="Sleep" value={d.metrics.sleep_hours != null ? d.metrics.sleep_hours.toFixed(1) : null} unit="h" />
        <Tile label="Body Battery peak" value={d.metrics.body_battery != null ? Math.round(d.metrics.body_battery) : null} />
      </div>

      {d.workouts_today.length > 0 && (
        <Card title="Done today">
          <ul className="text-sm space-y-1">
            {d.workouts_today.map((w) => (
              <li key={w.id} className="flex justify-between gap-2">
                <span>{w.title || sportName(w.sport)} · {Math.round(w.duration_min)} min</span>
                <span className="text-ink2">load {Math.round(w.load)}{w.load_estimated ? ' (est.)' : ''}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="Sync">
        <div className="text-sm space-y-1">
          <p>Garmin: last synced {niceDateTime(g.last_success)}{!g.history_complete && g.last_success ? ' (history still importing)' : ''}</p>
          {g.last_error && <p><span aria-hidden>! </span>{g.last_error}</p>}
          <p>Hevy: last import {niceDateTime(d.sync.hevy.last_success)}</p>
          {syncError && <p>{syncError}</p>}
        </div>
        <Button variant="secondary" className="mt-3" disabled={syncing || !g.configured} onClick={syncNow}>
          {syncing ? 'Syncing…' : 'Sync Garmin now'}
        </Button>
      </Card>

      <p className="text-xs text-ink2">{d.disclaimer}</p>
    </>
  )
}
