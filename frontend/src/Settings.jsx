import { useEffect, useState } from 'react'
import { api, niceDateTime } from './api.js'
import { HevyImport } from './Log.jsx'
import { Button, Card, Field, Loading, Notice, useApi } from './ui.jsx'

const THRESHOLD_LABELS = {
  sleep_target_hours: 'Sleep target (hours)',
  default_effort: 'Effort assumed when not rated',
  hr_to_effort_scale: 'Heart-rate to effort scale (default)',
  hard_effort_min: 'Hard session: effort from',
  hard_min_duration: 'Hard session: at least (minutes)',
  hard_day_load: 'Hard day: total load from',
  ratio_safe_high: 'Load ratio: top of safe range',
  ratio_cap: 'Load ratio: well above safe range',
  ramp_warn: 'Weekly increase that starts to count (0.15 = 15%)',
  max_weekly_increase: 'Safe weekly step up (0.10 = 10%)',
  verdict_go_hard: 'Go hard from score',
  verdict_normal: 'Train normally from score',
  verdict_easy: 'Keep it easy from score',
  weight_recovery: 'Weight: recovery',
  weight_load: 'Weight: load',
  weight_checkin: 'Weight: check-in',
  baseline_days: 'Baseline window (days)',
  key_expiry_warning_days: 'Warn before key expiry (days)',
}

export default function Settings({ version, onChanged }) {
  const state = useApi('/settings', [version])
  const [presets, setPresets] = useState([])
  const [thresholds, setThresholds] = useState({})
  const [expires, setExpires] = useState('')
  const [message, setMessage] = useState(null)
  const [error, setError] = useState(null)
  const d = state.data

  useEffect(() => {
    if (!d) return
    setPresets(d.presets)
    setThresholds(Object.fromEntries(Object.keys(THRESHOLD_LABELS).map((k) => [k, String(d.thresholds[k])])))
    setExpires(d.garmin_key_expires || '')
  }, [d])

  if (!d) return <><h1 className="text-2xl font-bold">Settings</h1><Loading state={state} /></>

  const save = async (body, text) => {
    setError(null)
    setMessage(null)
    try {
      await api('/settings', { method: 'PUT', body })
      setMessage(text)
      onChanged()
    } catch (e) {
      setError(e.message)
    }
  }
  const saveThresholds = () => {
    const numbers = Object.fromEntries(Object.entries(thresholds).map(([k, v]) => [k, Number(v)]).filter(([, v]) => Number.isFinite(v)))
    save({ thresholds: numbers }, 'Thresholds saved. Scores are recalculated with the new values.')
  }
  const setPreset = (i, key, value) => setPresets(presets.map((p, j) => (j === i ? { ...p, [key]: value } : p)))
  const savePresets = () => save({
    presets: presets.filter((p) => p.name.trim() && p.sport.trim())
      .map((p) => ({ ...p, sport: p.sport.trim().toLowerCase(), duration_min: Number(p.duration_min), effort: Number(p.effort) })),
  }, 'Presets saved.')
  const g = d.sync.garmin
  const h = d.sync.hevy

  return (
    <>
      <h1 className="text-2xl font-bold">Settings</h1>
      {message && <Notice kind="ok">{message}</Notice>}
      {error && <Notice kind="error">{error}</Notice>}

      <Card title="Sync status">
        <div className="text-sm space-y-2">
          <div>
            <p className="font-medium">Garmin {g.configured ? '' : '(no API key in .env)'}</p>
            <p className="text-ink2">Last success: {niceDateTime(g.last_success)} · last attempt: {niceDateTime(g.last_attempt)}</p>
            <p className="text-ink2">
              History: {g.history_complete ? 'fully imported' : g.history_from ? `imported back to ${g.history_from}, continuing` : 'not started'} ·
              automatic sync every {d.sync_interval_minutes} min
            </p>
            {g.last_error && <p><span aria-hidden>! </span>{g.last_error}</p>}
          </div>
          <div>
            <p className="font-medium">Hevy</p>
            <p className="text-ink2">
              Last import: {niceDateTime(h.last_success)}
              {h.info?.total != null && ` · ${h.info.added} added, ${h.info.updated} updated`}
            </p>
            {h.last_error && <p><span aria-hidden>! </span>{h.last_error}</p>}
          </div>
        </div>
        <Button variant="secondary" className="mt-3" disabled={!g.configured}
          onClick={() => api('/sync/run', { method: 'POST' }).then(() => setMessage('Garmin sync started.')).catch((e) => setError(e.message))}>
          Sync Garmin now
        </Button>
      </Card>

      <Card title="Garmin API key">
        <Field label="Key expires on" hint="Keys last 30 days to 1 year. The app warns you before this date. The key itself stays in .env and is never shown here.">
          <input type="date" value={expires} onChange={(e) => setExpires(e.target.value)} />
        </Field>
        <Button className="mt-3" onClick={() => save({ garmin_key_expires: expires }, 'Expiry date saved.')}>Save date</Button>
      </Card>

      <HevyImport onImported={onChanged} />

      <Card title="Quick-log presets">
        <div className="space-y-3">
          {presets.map((p, i) => (
            <div key={i} className="grid grid-cols-[1fr_1fr_4rem_3.5rem_2.75rem] gap-1 items-end">
              <Field label={i === 0 ? 'Name' : ''}><input aria-label="Name" value={p.name} onChange={(e) => setPreset(i, 'name', e.target.value)} /></Field>
              <Field label={i === 0 ? 'Sport' : ''}><input aria-label="Sport" value={p.sport} onChange={(e) => setPreset(i, 'sport', e.target.value)} /></Field>
              <Field label={i === 0 ? 'Min' : ''}><input aria-label="Minutes" type="number" inputMode="numeric" value={p.duration_min} onChange={(e) => setPreset(i, 'duration_min', e.target.value)} /></Field>
              <Field label={i === 0 ? 'Effort' : ''}><input aria-label="Effort" type="number" inputMode="numeric" min="1" max="10" value={p.effort} onChange={(e) => setPreset(i, 'effort', e.target.value)} /></Field>
              <button aria-label={`Remove ${p.name}`} className="min-h-11 rounded-lg border border-line" onClick={() => setPresets(presets.filter((_, j) => j !== i))}>×</button>
            </div>
          ))}
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setPresets([...presets, { name: '', sport: '', duration_min: 60, effort: 5 }])}>Add preset</Button>
            <Button onClick={savePresets}>Save presets</Button>
          </div>
        </div>
      </Card>

      <Card title="Scoring thresholds">
        <p className="text-sm text-ink2 mb-3">
          Starting values, meant to be tuned against your own data. Heart-rate scale currently in use: {d.hr_scale_in_use}
          {d.hr_scale_in_use !== d.thresholds.hr_to_effort_scale ? ' (learned from your rated sessions)' : ' (default until 5 watch sessions with heart rate are rated)'}.
        </p>
        <div className="grid sm:grid-cols-2 gap-3">
          {Object.entries(THRESHOLD_LABELS).map(([key, label]) => (
            <Field key={key} label={label} hint={`Default ${d.defaults[key]}`}>
              <input type="number" inputMode="decimal" step="any" value={thresholds[key] ?? ''} onChange={(e) => setThresholds({ ...thresholds, [key]: e.target.value })} />
            </Field>
          ))}
        </div>
        <div className="flex gap-2 mt-3">
          <Button onClick={saveThresholds}>Save thresholds</Button>
          <Button variant="secondary" onClick={() => save({ thresholds: {} }, 'Thresholds reset to defaults.')}>Reset to defaults</Button>
        </div>
      </Card>
    </>
  )
}
