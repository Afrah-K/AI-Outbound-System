import { useEffect, useState } from 'react'
import LoadingSpinner from '../common/LoadingSpinner'

export const inputClass =
  'w-full rounded-lg border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 text-sm'

export function loadCached(key) {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function saveCached(key, value) {
  try {
    if (value) localStorage.setItem(key, JSON.stringify(value))
    else localStorage.removeItem(key)
  } catch {
    // ignore - e.g. private browsing with storage disabled
  }
}

export function formatDuration(seconds) {
  if (seconds < 60) return `~${Math.max(1, Math.round(seconds))}s`
  return `~${Math.round(seconds / 60)} min`
}

function formatClock(seconds) {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

/**
 * Shown while a scrape job runs. With `total` (from the server job) the bar
 * shows real progress; otherwise it tracks elapsed time against the
 * estimate, capped short of full. `startedAt` keeps the timer right when you
 * come back to the page mid-run.
 */
export function ScrapeProgress({ title, detail, estimatedSeconds, done, total, message, startedAt, background = true }) {
  const [now, setNow] = useState(Date.now())
  const [mountedAt] = useState(Date.now())

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(timer)
  }, [])

  const elapsed = Math.max(0, (now - (startedAt || mountedAt)) / 1000)
  const estimate = Math.max(estimatedSeconds || 0, 1)
  const hasRealProgress = total > 0
  const percent = hasRealProgress
    ? Math.min(100, Math.max(2, (done / total) * 100))
    : Math.min(95, (elapsed / estimate) * 100)
  const overdue = !hasRealProgress && elapsed > estimate

  return (
    <div className="rounded-xl border border-primary-200 bg-primary-50/40 p-6" role="status" aria-live="polite">
      <div className="flex items-center gap-4">
        <LoadingSpinner size="lg" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-gray-900">{title}</p>
          <p className="text-xs text-gray-500 mt-0.5 truncate">{message || detail}</p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-sm tabular-nums text-gray-600">
            {formatClock(elapsed)}
            <span className="text-gray-400"> / {formatDuration(estimate)}</span>
          </p>
          {hasRealProgress && (
            <p className="text-xs tabular-nums text-gray-500">{done} of {total} done</p>
          )}
        </div>
      </div>
      <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-primary-100">
        <div
          className={`h-full rounded-full bg-primary-500 transition-[width] duration-500 ease-linear ${overdue ? 'animate-pulse' : ''}`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="mt-2 text-xs text-gray-500">
        {overdue
          ? 'Taking longer than estimated - still working. '
          : ''}
        {background && "Runs in the background - feel free to use other pages; you'll get a notification when it's done."}
      </p>
    </div>
  )
}

export function errorMessage(error, fallback) {
  const detail = error.response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

export function SelectField({ label, value, onChange, options = [] }) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)} className={inputClass}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  )
}

export function Toggle({ label, hint, checked, onChange, disabled }) {
  return (
    <label className={`flex items-start gap-2 text-sm ${disabled ? 'opacity-60' : 'cursor-pointer'}`}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500"
      />
      <span>
        <span className="text-gray-800">{label}</span>
        {hint && <span className="block text-xs text-gray-500">{hint}</span>}
      </span>
    </label>
  )
}
