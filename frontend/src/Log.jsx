import { useEffect, useState } from 'react'
import { api, isoDate, isoTime } from './api.js'
import { Button, Card, Field, Notice, Scale, useApi } from './ui.jsx'

const MODES = [
  { id: 'workout', label: 'Workout' },
  { id: 'checkin', label: 'Check-in' },
  { id: 'backfill', label: 'Backfill' },
  { id: 'hevy', label: 'Hevy import' },
]
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

function useSubmit(onSaved) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const submit = async (fn) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
      onSaved?.()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, submit }
}

function WorkoutForm({ preset, presets, onSaved }) {
  const [f, setF] = useState({
    sport: preset?.sport || '', duration: preset?.duration_min || '', effort: preset?.effort || null,
    date: isoDate(), time: isoTime(), notes: '',
  })
  const { busy, error, submit } = useSubmit(onSaved)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const apply = (p) => setF({ ...f, sport: p.sport, duration: p.duration_min, effort: p.effort })
  const valid = f.sport.trim() && Number(f.duration) > 0 && f.effort
  const save = () => submit(() => api('/workouts', {
    method: 'POST',
    body: { sport: f.sport, duration_min: Number(f.duration), effort: f.effort, start_time: `${f.date}T${f.time}:00`, notes: f.notes || null },
  }))
  return (
    <Card title="Log a workout">
      <div className="space-y-4">
        <div className="flex flex-wrap gap-2">
          {presets.map((p) => (
            <button key={p.name} type="button" onClick={() => apply(p)}
              className={`min-h-11 px-3 rounded-full border text-sm ${f.sport === p.sport ? 'border-accent bg-accent-soft' : 'border-line bg-surface'}`}>
              {p.name}
            </button>
          ))}
        </div>
        <Field label="Sport"><input value={f.sport} onChange={set('sport')} placeholder="e.g. volleyball" autoCapitalize="none" /></Field>
        <Field label="Duration (minutes)"><input type="number" inputMode="numeric" min="1" value={f.duration} onChange={set('duration')} /></Field>
        <Field label="Effort (1 to 10)">
          <Scale value={f.effort} onChange={(effort) => setF({ ...f, effort })} lowLabel="very easy" highLabel="maximal" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Date"><input type="date" max={isoDate()} value={f.date} onChange={set('date')} /></Field>
          <Field label="Start time"><input type="time" value={f.time} onChange={set('time')} /></Field>
        </div>
        <Field label="Notes (optional)"><textarea rows="2" value={f.notes} onChange={set('notes')} /></Field>
        {error && <Notice kind="error">{error}</Notice>}
        <Button className="w-full" disabled={!valid || busy} onClick={save}>{busy ? 'Saving…' : 'Save workout'}</Button>
      </div>
    </Card>
  )
}

function CheckinForm({ onSaved }) {
  const [date, setDate] = useState(isoDate())
  const [f, setF] = useState({ soreness: null, energy: null, ill: false, allergy: false, pain_note: '', notes: '' })
  const [exists, setExists] = useState(false)
  const { busy, error, submit } = useSubmit(onSaved)
  useEffect(() => {
    api(`/checkin/${date}`).then((c) => {
      setExists(Boolean(c))
      setF(c
        ? { soreness: c.soreness, energy: c.energy, ill: Boolean(c.ill), allergy: Boolean(c.allergy), pain_note: c.pain_note || '', notes: c.notes || '' }
        : { soreness: null, energy: null, ill: false, allergy: false, pain_note: '', notes: '' })
    }).catch(() => {})
  }, [date])
  const save = () => submit(() => api(`/checkin/${date}`, { method: 'PUT', body: f }))
  const remove = () => submit(() => api(`/checkin/${date}`, { method: 'DELETE' }))
  return (
    <Card title="Morning check-in">
      <div className="space-y-4">
        <p className="text-sm text-ink2">Optional. Everything here can be left empty; the score works without it.</p>
        <Field label="Date"><input type="date" max={isoDate()} value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        <Field label="Muscle soreness">
          <Scale max={5} allowClear value={f.soreness} onChange={(soreness) => setF({ ...f, soreness })} lowLabel="none" highLabel="very sore" />
        </Field>
        <Field label="Energy">
          <Scale max={5} allowClear value={f.energy} onChange={(energy) => setF({ ...f, energy })} lowLabel="drained" highLabel="great" />
        </Field>
        <label className="flex items-center gap-3 min-h-11">
          <input type="checkbox" checked={f.ill} onChange={(e) => setF({ ...f, ill: e.target.checked })} />
          <span>I feel ill</span>
        </label>
        <label className="flex items-center gap-3 min-h-11">
          <input type="checkbox" checked={f.allergy} onChange={(e) => setF({ ...f, allergy: e.target.checked })} />
          <span>Allergy flare-up</span>
        </label>
        <Field label="Pain or injury (optional)" hint="Any note here limits today's verdict to Keep it easy.">
          <input value={f.pain_note} onChange={(e) => setF({ ...f, pain_note: e.target.value })} placeholder="e.g. left hamstring tight" />
        </Field>
        <Field label="Notes (optional)"><textarea rows="2" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
        {error && <Notice kind="error">{error}</Notice>}
        <div className="flex gap-2">
          <Button className="flex-1" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save check-in'}</Button>
          {exists && <Button variant="danger" disabled={busy} onClick={remove}>Delete</Button>}
        </div>
      </div>
    </Card>
  )
}

function BackfillForm({ presets, onSaved }) {
  const first = presets[0] || { sport: 'volleyball', duration_min: 90, effort: 7 }
  const [f, setF] = useState({ sport: first.sport, weekday: 1, time: '19:00', duration: first.duration_min, effort: first.effort, weeks: 4 })
  const [result, setResult] = useState(null)
  const { busy, error, submit } = useSubmit()
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const save = () => submit(async () => {
    const r = await api('/backfill', {
      method: 'POST',
      body: { sport: f.sport, weekday: Number(f.weekday), time: f.time, duration_min: Number(f.duration), effort: f.effort, weeks: Number(f.weeks) },
    })
    setResult(r.created)
  })
  return (
    <Card title="Backfill missed sessions">
      <div className="space-y-4">
        <p className="text-sm text-ink2">
          Add a weekly session the watch did not record, for the last few weeks in one go. These are marked as estimated.
          Repeat for each regular session.
        </p>
        <Field label="Sport"><input value={f.sport} onChange={set('sport')} autoCapitalize="none" /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Every">
            <select value={f.weekday} onChange={set('weekday')}>{WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}</select>
          </Field>
          <Field label="Start time"><input type="time" value={f.time} onChange={set('time')} /></Field>
          <Field label="About (minutes)"><input type="number" inputMode="numeric" min="1" value={f.duration} onChange={set('duration')} /></Field>
          <Field label="Weeks back">
            <select value={f.weeks} onChange={set('weeks')}>{[1, 2, 3, 4, 6, 8].map((n) => <option key={n}>{n}</option>)}</select>
          </Field>
        </div>
        <Field label="Typical effort (1 to 10)"><Scale value={f.effort} onChange={(effort) => setF({ ...f, effort })} /></Field>
        {error && <Notice kind="error">{error}</Notice>}
        {result != null && <Notice kind="ok">Added {result} session{result === 1 ? '' : 's'}. Add another, or go back to Today.</Notice>}
        <div className="flex gap-2">
          <Button className="flex-1" disabled={busy || !f.sport.trim() || !f.effort || !(Number(f.duration) > 0)} onClick={save}>
            {busy ? 'Adding…' : 'Add sessions'}
          </Button>
          {result != null && <Button variant="secondary" onClick={onSaved}>Done</Button>}
        </div>
      </div>
    </Card>
  )
}

export function HevyImport({ onImported }) {
  const [result, setResult] = useState(null)
  const { busy, error, submit } = useSubmit()
  const upload = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setResult(null)
    submit(async () => {
      setResult(await api('/hevy/import', { method: 'POST', raw: await file.text() }))
      onImported?.()
    })
    e.target.value = ''
  }
  return (
    <Card title="Import from Hevy">
      <div className="space-y-3">
        <p className="text-sm text-ink2">
          In Hevy: Profile › Settings › Export &amp; Import Data › Export Data › Export Workouts. Then choose the CSV file here.
          Importing the full history again never creates duplicates.
        </p>
        <input type="file" accept=".csv,text/csv" onChange={upload} disabled={busy} aria-label="Hevy CSV file" />
        {busy && <p className="text-sm text-ink2">Importing…</p>}
        {error && <Notice kind="error">{error}</Notice>}
        {result && (
          <Notice kind="ok">
            {result.total} workouts in the file: {result.added} added, {result.updated} updated, {result.unchanged} unchanged
            {result.skipped ? `, ${result.skipped} skipped (deleted earlier)` : ''}.
          </Notice>
        )}
      </div>
    </Card>
  )
}

export default function Log({ initial, onSaved }) {
  const [mode, setMode] = useState(initial?.mode || 'workout')
  const settings = useApi('/settings')
  const presets = settings.data?.presets || []
  return (
    <>
      <h1 className="text-2xl font-bold">Log</h1>
      <div className="grid grid-cols-4 gap-1 bg-surface border border-line rounded-xl p-1" role="tablist">
        {MODES.map((m) => (
          <button key={m.id} role="tab" aria-selected={mode === m.id} onClick={() => setMode(m.id)}
            className={`min-h-10 rounded-lg text-sm ${mode === m.id ? 'bg-accent text-white font-semibold' : 'text-ink2'}`}>
            {m.label}
          </button>
        ))}
      </div>
      {mode === 'workout' && <WorkoutForm preset={initial?.preset} presets={presets} onSaved={onSaved} />}
      {mode === 'checkin' && <CheckinForm onSaved={onSaved} />}
      {mode === 'backfill' && settings.data && <BackfillForm presets={presets} onSaved={onSaved} />}
      {mode === 'hevy' && <HevyImport />}
    </>
  )
}
