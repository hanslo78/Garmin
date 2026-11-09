import { useState } from 'react'
import { api, addDays, isoDate, niceDate } from './api.js'
import Chart from './Chart.jsx'
import { Button, Card, Field, Loading, Notice, useApi } from './ui.jsx'

const CHARTS = [
  { field: 'readiness', title: 'Readiness (0 to 100)', domain: [0, 100] },
  { field: 'load', title: 'Daily training load', type: 'bar' },
  { field: 'hrv', title: 'Overnight HRV (ms)', unit: 'ms' },
  { field: 'resting_hr', title: 'Resting heart rate (bpm)', unit: 'bpm' },
  { field: 'sleep_hours', title: 'Sleep (hours)', unit: 'h', digits: 1 },
  { field: 'body_battery', title: 'Body Battery peak', domain: [0, 100] },
]

function mondayOf(iso) {
  const d = new Date(iso + 'T12:00:00')
  return addDays(iso, -((d.getDay() + 6) % 7))
}

function ExportCard() {
  const today = isoDate()
  const thisMonday = mondayOf(today)
  const [start, setStart] = useState(addDays(thisMonday, -7))
  const [end, setEnd] = useState(addDays(thisMonday, -1))
  const [text, setText] = useState(null)
  const [message, setMessage] = useState(null)
  const [error, setError] = useState(null)
  const pick = (s, e) => { setStart(s); setEnd(e); setText(null); setMessage(null) }
  const build = async () => {
    setError(null)
    try {
      const markdown = await api(`/export?start=${start}&end=${end}`)
      setText(markdown)
      return markdown
    } catch (e) {
      setError(e.message)
      return null
    }
  }
  const copy = async () => {
    const markdown = text || (await build())
    if (!markdown) return
    try {
      await navigator.clipboard.writeText(markdown)
      setMessage('Copied. Paste it into any assistant.')
    } catch {
      setMessage('Could not access the clipboard. Select the text below and copy it manually.')
    }
  }
  const download = async () => {
    const markdown = text || (await build())
    if (!markdown) return
    const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown' }))
    const a = Object.assign(document.createElement('a'), { href: url, download: `training-${start}-to-${end}.md` })
    a.click()
    URL.revokeObjectURL(url)
  }
  return (
    <Card title="Export for an AI assistant">
      <div className="space-y-3">
        <p className="text-sm text-ink2">
          Builds a self-contained summary you can paste anywhere. Nothing leaves this app unless you copy or download it.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => pick(addDays(thisMonday, -7), addDays(thisMonday, -1))}>Last week</Button>
          <Button variant="secondary" onClick={() => pick(thisMonday, today)}>This week</Button>
          <Button variant="secondary" onClick={() => pick(addDays(today, -27), today)}>Last 28 days</Button>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="From"><input type="date" value={start} max={end} onChange={(e) => pick(e.target.value, end)} /></Field>
          <Field label="To"><input type="date" value={end} min={start} max={today} onChange={(e) => pick(start, e.target.value)} /></Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Button onClick={copy}>Copy</Button>
          <Button variant="secondary" onClick={download}>Download .md</Button>
        </div>
        {error && <Notice kind="error">{error}</Notice>}
        {message && <Notice kind="ok">{message}</Notice>}
        {text && <textarea readOnly rows="8" value={text} className="font-mono text-xs" aria-label="Export text" />}
      </div>
    </Card>
  )
}

export default function Trends({ version }) {
  const [days, setDays] = useState(30)
  const [table, setTable] = useState(false)
  const state = useApi(`/trends?days=${days}`, [version])
  const rows = state.data || []
  return (
    <>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Trends</h1>
        <div className="flex gap-1 bg-surface border border-line rounded-xl p-1">
          {[14, 30, 90, 365].map((n) => (
            <button key={n} onClick={() => setDays(n)} aria-pressed={days === n}
              className={`min-h-9 px-3 rounded-lg text-sm ${days === n ? 'bg-accent text-white font-semibold' : 'text-ink2'}`}>
              {n === 365 ? '1y' : `${n}d`}
            </button>
          ))}
        </div>
      </div>
      <Loading state={state} />
      {state.data && CHARTS.map((c) => (
        <Card key={c.field} title={c.title}>
          <Chart rows={rows} {...c} />
        </Card>
      ))}
      {state.data && (
        <Card title="Data table" action={<Button variant="secondary" onClick={() => setTable(!table)}>{table ? 'Hide' : 'Show'}</Button>}>
          {table ? (
            <div className="overflow-x-auto">
              <table className="text-xs w-full whitespace-nowrap">
                <thead>
                  <tr className="text-left text-ink2">
                    {['Date', 'Readiness', 'Verdict', 'Load', 'Ratio', 'HRV', 'RHR', 'Sleep h', 'Body Battery', 'Stress'].map((h) => <th key={h} className="pr-3 py-1 font-medium">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {[...rows].reverse().map((r) => (
                    <tr key={r.date} className="border-t border-line">
                      {[niceDate(r.date), r.readiness, r.verdict, r.load, r.ratio, r.hrv && Math.round(r.hrv), r.resting_hr && Math.round(r.resting_hr),
                        r.sleep_hours?.toFixed(1), r.body_battery && Math.round(r.body_battery), r.stress && Math.round(r.stress)]
                        .map((v, i) => <td key={i} className="pr-3 py-1">{v ?? '–'}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="text-sm text-ink2">The same numbers as the charts, day by day.</p>}
        </Card>
      )}
      <ExportCard />
    </>
  )
}
