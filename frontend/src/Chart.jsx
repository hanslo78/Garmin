import { useEffect, useRef, useState } from 'react'
import { niceDate } from './api.js'

function useWidth() {
  const ref = useRef(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    if (!ref.current) return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(ref.current)
    return () => observer.disconnect()
  }, [])
  return [ref, width]
}

function niceTicks(lo, hi) {
  const span = hi - lo || 1
  const step = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000].find((s) => span / s <= 4) || span / 4
  const ticks = []
  for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) ticks.push(Math.round(t * 100) / 100)
  return ticks
}

/**
 * Single-series chart (line or bar) with a hover/touch tooltip.
 * One measure per chart, one axis; the card title names the series.
 */
export default function Chart({ rows, field, type = 'line', unit = '', domain, digits = 0 }) {
  const [ref, width] = useWidth()
  const [hover, setHover] = useState(null)
  const height = 150
  const pad = { l: 34, r: 12, t: 10, b: 22 }
  const values = rows.map((r) => r[field])
  const present = values.filter((v) => v != null)
  const fmt = (v) => (v == null ? 'no data' : `${Number(v).toFixed(digits)}${unit ? ' ' + unit : ''}`)

  let body = null
  if (width > 0 && present.length > 0) {
    let lo = domain ? domain[0] : type === 'bar' ? 0 : Math.min(...present)
    let hi = domain ? domain[1] : Math.max(...present)
    if (!domain) {
      const margin = (hi - lo) * 0.15 || Math.max(1, hi * 0.1)
      hi += margin
      if (type !== 'bar') lo = Math.max(0, lo - margin)
    }
    const ticks = niceTicks(lo, hi)
    const iw = width - pad.l - pad.r
    const ih = height - pad.t - pad.b
    const n = rows.length
    const x = (i) => pad.l + (n === 1 ? iw / 2 : type === 'bar' ? ((i + 0.5) / n) * iw : (i / (n - 1)) * iw)
    const y = (v) => pad.t + ih - ((v - lo) / (hi - lo)) * ih
    const move = (e) => {
      const rect = e.currentTarget.getBoundingClientRect()
      const px = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left
      const frac = (px - pad.l) / iw
      const i = type === 'bar' ? Math.floor(frac * n) : Math.round(frac * (n - 1))
      setHover(Math.max(0, Math.min(n - 1, i)))
    }
    // Line segments break where data is missing instead of bridging the gap.
    const segments = []
    let current = []
    values.forEach((v, i) => {
      if (v == null) { if (current.length) segments.push(current); current = [] } else current.push([x(i), y(v)])
    })
    if (current.length) segments.push(current)
    const barW = Math.max(2, Math.min(18, (iw / n) - 2))
    const lastIdx = values.reduce((acc, v, i) => (v != null ? i : acc), -1)
    const labelIdx = [0, Math.floor((n - 1) / 2), n - 1].filter((v, i, a) => a.indexOf(v) === i)

    body = (
      <>
        <svg width={width} height={height} onMouseMove={move} onMouseLeave={() => setHover(null)}
          onTouchStart={move} onTouchMove={move} style={{ touchAction: 'pan-y', display: 'block' }}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeWidth="1" />
              <text x={pad.l - 6} y={y(t)} textAnchor="end" dominantBaseline="middle" fontSize="10" fill="var(--ink2)">{t}</text>
            </g>
          ))}
          {labelIdx.map((i) => (
            <text key={i} x={x(i)} y={height - 6} fontSize="10" fill="var(--ink2)"
              textAnchor={i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}>
              {niceDate(rows[i].date).slice(4)}
            </text>
          ))}
          {type === 'bar'
            ? values.map((v, i) => v > 0 && (
              <path key={i} fill="var(--accent)" opacity={hover == null || hover === i ? 1 : 0.55}
                d={(() => {
                  const h = y(lo) - y(v), r = Math.min(4, barW / 2, h), x0 = x(i) - barW / 2, yb = y(lo)
                  return `M${x0},${yb} v${-(h - r)} q0,${-r} ${r},${-r} h${barW - 2 * r} q${r},0 ${r},${r} v${h - r} z`
                })()} />
            ))
            : (
              <>
                {segments.map((seg, i) => (seg.length === 1
                  ? <circle key={i} cx={seg[0][0]} cy={seg[0][1]} r="2.5" fill="var(--accent)" />
                  : <polyline key={i} points={seg.map((p) => p.join(',')).join(' ')} fill="none" stroke="var(--accent)"
                      strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />))}
                {lastIdx >= 0 && hover == null && (
                  <circle cx={x(lastIdx)} cy={y(values[lastIdx])} r="4" fill="var(--accent)" stroke="var(--surface)" strokeWidth="2" />
                )}
              </>
            )}
          {hover != null && (
            <>
              <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={pad.t + ih} stroke="var(--ink2)" strokeWidth="1" strokeDasharray="3 3" />
              {type !== 'bar' && values[hover] != null && (
                <circle cx={x(hover)} cy={y(values[hover])} r="4.5" fill="var(--accent)" stroke="var(--surface)" strokeWidth="2" />
              )}
            </>
          )}
        </svg>
        {hover != null && (
          <div className="absolute top-0 pointer-events-none bg-surface border border-line rounded-lg px-2 py-1 text-xs shadow-sm whitespace-nowrap"
            style={x(hover) > width / 2 ? { right: width - x(hover) + 8 } : { left: x(hover) + 8 }}>
            <div className="text-ink2">{niceDate(rows[hover].date)}</div>
            <div className="font-semibold">{fmt(values[hover])}</div>
          </div>
        )}
      </>
    )
  }

  return (
    <div ref={ref} className="relative" style={{ minHeight: height }}>
      {body || (width > 0 && <p className="text-sm text-ink2 pt-12 text-center">No data in this period yet.</p>)}
    </div>
  )
}
