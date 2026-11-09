import { useEffect, useState, useCallback } from 'react'
import { api } from './api.js'

export function Card({ title, children, action }) {
  return (
    <section className="bg-surface border border-line rounded-2xl p-4">
      {(title || action) && (
        <div className="flex items-center justify-between mb-3 gap-2">
          {title && <h2 className="text-sm font-semibold text-ink2 uppercase tracking-wide">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  )
}

export function Button({ children, variant = 'primary', className = '', ...props }) {
  const styles = {
    primary: 'bg-accent text-white',
    secondary: 'bg-surface border border-line text-ink',
    danger: 'bg-surface border border-critical text-ink',
  }
  return (
    <button
      {...props}
      className={`min-h-11 px-4 rounded-xl font-medium disabled:opacity-50 active:opacity-80 ${styles[variant]} ${className}`}
    >
      {children}
    </button>
  )
}

export function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="block text-sm font-medium mb-1">{label}</span>
      {children}
      {hint && <span className="block text-xs text-ink2 mt-1">{hint}</span>}
    </label>
  )
}

/** Row of numbered buttons, e.g. effort 1-10 or soreness 1-5. */
export function Scale({ value, onChange, max = 10, lowLabel, highLabel, allowClear = false }) {
  return (
    <div>
      <div className="grid gap-1" style={{ gridTemplateColumns: `repeat(${max}, minmax(0, 1fr))` }}>
        {Array.from({ length: max }, (_, i) => i + 1).map((n) => (
          <button
            key={n}
            type="button"
            aria-pressed={value === n}
            onClick={() => onChange(allowClear && value === n ? null : n)}
            className={`min-h-11 rounded-lg border text-sm font-semibold ${
              value === n ? 'bg-accent border-accent text-white' : 'bg-surface border-line text-ink'
            }`}
          >
            {n}
          </button>
        ))}
      </div>
      {(lowLabel || highLabel) && (
        <div className="flex justify-between text-xs text-ink2 mt-1">
          <span>{lowLabel}</span>
          <span>{highLabel}</span>
        </div>
      )}
    </div>
  )
}

export function Notice({ kind = 'info', children }) {
  const color = { info: 'border-accent', warn: 'border-warning', error: 'border-critical', ok: 'border-good' }[kind]
  const icon = { info: 'i', warn: '!', error: '×', ok: '✓' }[kind]
  return (
    <div className={`flex gap-3 items-start bg-surface border-l-4 ${color} border-y border-r border-y-line border-r-line rounded-lg p-3 text-sm`}>
      <span aria-hidden className="font-bold w-4 text-center">{icon}</span>
      <div className="flex-1">{children}</div>
    </div>
  )
}

export function Tag({ children }) {
  return <span className="inline-block text-xs px-2 py-0.5 rounded-full border border-line text-ink2">{children}</span>
}

/** Fetch helper: returns { data, error, loading, reload }. */
export function useApi(path, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const load = useCallback(() => {
    let cancelled = false
    setState((s) => ({ ...s, loading: true }))
    api(path)
      .then((data) => !cancelled && setState({ data, error: null, loading: false }))
      .catch((error) => !cancelled && setState((s) => ({ data: s.data, error: error.message, loading: false })))
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps])
  useEffect(() => load(), [load])
  return { ...state, reload: load }
}

export function Loading({ state }) {
  if (state.error) return <Notice kind="error">{state.error}</Notice>
  if (state.loading && !state.data) return <p className="text-ink2 text-sm p-4">Loading…</p>
  return null
}
