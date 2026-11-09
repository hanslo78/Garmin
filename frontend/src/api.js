export async function api(path, { method = 'GET', body, raw } = {}) {
  const init = { method }
  if (raw !== undefined) {
    init.body = raw
    init.headers = { 'Content-Type': 'text/csv' }
  } else if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = { 'Content-Type': 'application/json' }
  }
  let response
  try {
    response = await fetch('/api' + path, init)
  } catch {
    throw new Error('Cannot reach the app on your PC. Is it running, and is Tailscale connected?')
  }
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const data = await response.json()
      message = typeof data.detail === 'string' ? data.detail : 'Some values are not valid. Please check and try again.'
    } catch { /* keep default */ }
    throw new Error(message)
  }
  const type = response.headers.get('content-type') || ''
  return type.includes('json') ? response.json() : response.text()
}

const pad = (n) => String(n).padStart(2, '0')
export const isoDate = (d = new Date()) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
export const isoTime = (d = new Date()) => `${pad(d.getHours())}:${pad(d.getMinutes())}`
export const addDays = (iso, n) => {
  const d = new Date(iso + 'T12:00:00')
  d.setDate(d.getDate() + n)
  return isoDate(d)
}
export const niceDate = (iso) =>
  new Date(iso.slice(0, 10) + 'T12:00:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
export const niceDateTime = (iso) => (iso ? `${niceDate(iso)}, ${iso.slice(11, 16)}` : 'never')
export const sportName = (s) => (s || '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())
