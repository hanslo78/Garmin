import { useMemo, useState } from 'react'
import { api, addDays, isoDate, niceDateTime, sportName } from './api.js'
import { Button, Card, Field, Loading, Notice, Scale, Tag, useApi } from './ui.jsx'

const SOURCE_LABEL = { garmin: 'Garmin', hevy: 'Hevy', manual: 'Manual' }

function Detail({ w, onChanged }) {
  const manual = w.sources.includes('manual')
  const [f, setF] = useState({
    effort: w.effort_source === 'user' ? w.effort : null, notes: w.notes || '',
    sport: w.sport, duration: w.duration_min, date: w.start_time.slice(0, 10), time: w.start_time.slice(11, 16),
  })
  const [error, setError] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const run = (promise) => promise.then(onChanged).catch((e) => setError(e.message))
  const save = () => {
    const body = { notes: f.notes || null }
    if (f.effort) body.effort = f.effort
    if (manual) Object.assign(body, { sport: f.sport, duration_min: Number(f.duration), start_time: `${f.date}T${f.time}:00` })
    run(api(`/workouts/${w.id}`, { method: 'PATCH', body }))
  }
  return (
    <div className="mt-3 pt-3 border-t border-line space-y-4 text-sm">
      {w.avg_hr && <p className="text-ink2">Average HR {Math.round(w.avg_hr)} bpm{w.max_hr ? `, max ${Math.round(w.max_hr)}` : ''}</p>}
      {w.exercises && (
        <ul className="space-y-1">
          {w.exercises.map((ex, i) => (
            <li key={i}>
              <span className="font-medium">{ex.name}</span>{' '}
              <span className="text-ink2">
                {ex.sets.map((s) => (s.reps != null ? `${s.weight_kg != null ? s.weight_kg + ' kg × ' : ''}${s.reps}` : s.duration_s != null ? `${s.duration_s}s` : '–')).join(', ')}
              </span>
            </li>
          ))}
        </ul>
      )}
      <Field label={w.effort_source === 'user' ? 'Effort' : 'Rate the overall effort'}>
        <Scale value={f.effort} onChange={(effort) => setF({ ...f, effort })} lowLabel="very easy" highLabel="maximal" />
      </Field>
      {manual && (
        <div className="grid grid-cols-2 gap-3">
          <Field label="Sport"><input value={f.sport} onChange={(e) => setF({ ...f, sport: e.target.value })} /></Field>
          <Field label="Minutes"><input type="number" inputMode="numeric" value={f.duration} onChange={(e) => setF({ ...f, duration: e.target.value })} /></Field>
          <Field label="Date"><input type="date" max={isoDate()} value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
          <Field label="Time"><input type="time" value={f.time} onChange={(e) => setF({ ...f, time: e.target.value })} /></Field>
        </div>
      )}
      <Field label="Notes"><textarea rows="2" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
      {w.records.length > 1 && (
        <div>
          <p className="font-medium mb-1">Merged from {w.records.length} records</p>
          <ul className="space-y-2">
            {w.records.map((rec) => (
              <li key={rec.id} className="flex items-center justify-between gap-2">
                <span className="text-ink2">{SOURCE_LABEL[rec.source]} · {rec.start_time.slice(11, 16)} · {Math.round(rec.duration_min)} min</span>
                <Button variant="secondary" onClick={() => run(api(`/workouts/${w.id}/unmerge`, { method: 'POST', body: { record_id: rec.id } }))}>
                  Split off
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {error && <Notice kind="error">{error}</Notice>}
      <div className="flex gap-2">
        <Button className="flex-1" onClick={save}>Save changes</Button>
        {confirmDelete
          ? <Button variant="danger" onClick={() => run(api(`/workouts/${w.id}`, { method: 'DELETE' }))}>Really delete</Button>
          : <Button variant="danger" onClick={() => setConfirmDelete(true)}>Delete</Button>}
      </div>
    </div>
  )
}

export default function History({ version, onChanged }) {
  const [range, setRange] = useState('90')
  const [source, setSource] = useState('all')
  const [sport, setSport] = useState('all')
  const [open, setOpen] = useState(null)
  const query = range === 'all' ? '' : `?start=${addDays(isoDate(), -Number(range))}`
  const state = useApi('/workouts' + query, [version])
  const all = state.data || []
  const sports = useMemo(() => [...new Set(all.map((w) => w.sport))].sort(), [all])
  const shown = all.filter((w) => (source === 'all' || w.sources.includes(source)) && (sport === 'all' || w.sport === sport))

  return (
    <>
      <h1 className="text-2xl font-bold">History</h1>
      <div className="grid grid-cols-3 gap-2">
        <Field label="Period">
          <select value={range} onChange={(e) => setRange(e.target.value)}>
            <option value="30">30 days</option><option value="90">90 days</option><option value="365">1 year</option><option value="all">Everything</option>
          </select>
        </Field>
        <Field label="Source">
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="all">All</option><option value="garmin">Garmin</option><option value="hevy">Hevy</option><option value="manual">Manual</option>
          </select>
        </Field>
        <Field label="Sport">
          <select value={sport} onChange={(e) => setSport(e.target.value)}>
            <option value="all">All</option>
            {sports.map((s) => <option key={s} value={s}>{sportName(s)}</option>)}
          </select>
        </Field>
      </div>
      <Loading state={state} />
      {state.data && <p className="text-sm text-ink2">{shown.length} workout{shown.length === 1 ? '' : 's'}</p>}
      {state.data && shown.length === 0 && <Card><p className="text-sm text-ink2">Nothing here yet. Log a session or sync your watch.</p></Card>}
      <div className="space-y-2">
        {shown.map((w) => (
          <div key={w.id} className="bg-surface border border-line rounded-2xl p-4">
            <button className="w-full text-left" aria-expanded={open === w.id} onClick={() => setOpen(open === w.id ? null : w.id)}>
              <div className="flex justify-between gap-2">
                <span className="font-semibold">{w.title || sportName(w.sport)}</span>
                <span className="font-semibold whitespace-nowrap">{Math.round(w.load)} load</span>
              </div>
              <div className="text-sm text-ink2">
                {niceDateTime(w.start_time)} · {Math.round(w.duration_min)} min
                {w.effort != null && ` · effort ${w.effort}${w.effort_source !== 'user' ? ' (est.)' : ''}`}
              </div>
              <div className="flex flex-wrap gap-1 mt-2">
                {w.sources.map((s) => <Tag key={s}>{SOURCE_LABEL[s]}</Tag>)}
                {w.sources.length > 1 && <Tag>merged</Tag>}
                {w.load_method === 'heart_rate' && <Tag>heart-rate load</Tag>}
                {w.estimated && <Tag>backfilled estimate</Tag>}
                {w.load_estimated && !w.estimated && <Tag>needs effort rating</Tag>}
                {w.hard && <Tag>hard</Tag>}
              </div>
            </button>
            {open === w.id && <Detail w={w} onChanged={() => { setOpen(null); onChanged() }} />}
          </div>
        ))}
      </div>
    </>
  )
}
