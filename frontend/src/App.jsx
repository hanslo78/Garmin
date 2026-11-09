import { useState } from 'react'
import Today from './Today.jsx'
import Log from './Log.jsx'
import History from './History.jsx'
import Trends from './Trends.jsx'
import Settings from './Settings.jsx'

const TABS = [
  { id: 'today', label: 'Today', icon: 'M12 3a9 9 0 1 0 9 9M12 7v5l3 2' },
  { id: 'log', label: 'Log', icon: 'M12 5v14M5 12h14' },
  { id: 'history', label: 'History', icon: 'M5 6h14M5 12h14M5 18h14' },
  { id: 'trends', label: 'Trends', icon: 'M4 17l5-6 4 3 7-9' },
  { id: 'settings', label: 'Settings', icon: 'M5 7h9m4 0h1M5 17h1m4 0h9M16 5v4M8 15v4' },
]

export default function App() {
  const [tab, setTab] = useState('today')
  const [logPreset, setLogPreset] = useState(null)   // { mode, preset } passed from Today to Log
  const [version, setVersion] = useState(0)          // bumped after any change so screens reload

  const changed = () => setVersion((v) => v + 1)
  const openLog = (mode = 'workout', preset = null) => {
    setLogPreset({ mode, preset, key: Date.now() })
    setTab('log')
  }

  return (
    <div className="max-w-3xl mx-auto min-h-dvh flex flex-col">
      <main className="flex-1 px-4 pt-4 pb-28 space-y-4">
        {tab === 'today' && <Today version={version} onChanged={changed} openLog={openLog} />}
        {tab === 'log' && (
          <Log key={logPreset?.key} initial={logPreset} onSaved={() => { changed(); setTab('today') }} />
        )}
        {tab === 'history' && <History version={version} onChanged={changed} />}
        {tab === 'trends' && <Trends version={version} />}
        {tab === 'settings' && <Settings version={version} onChanged={changed} />}
      </main>
      <nav
        className="fixed bottom-0 inset-x-0 bg-surface border-t border-line"
        style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
      >
        <div className="max-w-3xl mx-auto grid grid-cols-5">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => { if (t.id === 'log') setLogPreset(null); setTab(t.id) }}
              aria-current={tab === t.id ? 'page' : undefined}
              className={`flex flex-col items-center gap-0.5 py-2 min-h-14 text-xs ${
                tab === t.id ? 'text-accent font-semibold' : 'text-ink2'
              }`}
            >
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d={t.icon} />
              </svg>
              {t.label}
            </button>
          ))}
        </div>
      </nav>
    </div>
  )
}
