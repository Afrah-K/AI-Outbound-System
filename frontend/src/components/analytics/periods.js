// Time-bucket views shared by the Analytics charts. Buckets arrive as UTC ISO
// strings; hourly ones are shown in local time, the rest by their date.

export const PERIODS = [
  { value: 'hour', label: 'Hourly', range: 'Last 24 hours' },
  { value: 'day', label: 'Daily', range: 'Last 30 days' },
  { value: 'month', label: 'Monthly', range: 'Last 12 months' },
  { value: 'year', label: 'Yearly', range: 'Last 5 years' },
]

export function formatBucket(bucket, period) {
  const d = new Date(bucket)
  if (period === 'hour') return d.toLocaleTimeString('en-US', { hour: 'numeric' })
  if (period === 'day') return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
  if (period === 'month') return d.toLocaleDateString('en-US', { month: 'short', year: '2-digit', timeZone: 'UTC' })
  return String(d.getUTCFullYear())
}

export function formatBucketLong(bucket, period) {
  const d = new Date(bucket)
  if (period === 'hour') {
    const end = new Date(d.getTime() + 3600 * 1000)
    return `${d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}, ${d.toLocaleTimeString('en-US', { hour: 'numeric' })}-${end.toLocaleTimeString('en-US', { hour: 'numeric' })}`
  }
  if (period === 'day') return d.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric', timeZone: 'UTC' })
  if (period === 'month') return d.toLocaleDateString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' })
  return String(d.getUTCFullYear())
}
