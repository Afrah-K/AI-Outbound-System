import { PERIODS } from './periods'

/** Hourly / Daily / Monthly / Yearly segmented control for the time-bucketed charts. */
export default function PeriodSwitch({ value, onChange, size = 'md' }) {
  const pad = size === 'sm' ? 'px-3 py-1 text-xs' : 'px-4 py-1.5 text-sm'
  return (
    <div className={`inline-flex rounded-full bg-white p-1 ${size === 'sm' ? 'border border-gray-200' : 'shadow-sm'}`} role="tablist" aria-label="Time range">
      {PERIODS.map((p) => (
        <button
          key={p.value}
          type="button"
          role="tab"
          aria-selected={value === p.value}
          title={p.range}
          onClick={() => onChange(p.value)}
          className={`rounded-full ${pad} font-medium transition-colors ${
            value === p.value ? 'bg-primary-600 text-white' : 'text-gray-600 hover:text-gray-900'
          }`}
        >
          {p.label}
        </button>
      ))}
    </div>
  )
}
