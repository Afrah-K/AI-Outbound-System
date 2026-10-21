// Time zone helpers for campaign scheduling. Campaign send windows are stored as
// "HH:MM" in the campaign's own IANA time zone; the API returns timestamps as
// naive UTC ISO strings (no trailing "Z").

const FALLBACK_TIMEZONES = [
  'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles', 'America/Toronto',
  'America/Sao_Paulo', 'Europe/London', 'Europe/Paris', 'Europe/Berlin', 'Europe/Madrid', 'Europe/Istanbul',
  'Africa/Cairo', 'Africa/Johannesburg', 'Asia/Dubai', 'Asia/Riyadh', 'Asia/Karachi', 'Asia/Kolkata',
  'Asia/Singapore', 'Asia/Hong_Kong', 'Asia/Tokyo', 'Australia/Sydney', 'Pacific/Auckland', 'UTC',
]

export function browserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

/** Every IANA zone the browser knows (falls back to a common list on older browsers). */
export function allTimezones(include = []) {
  let zones = FALLBACK_TIMEZONES
  try {
    if (typeof Intl.supportedValuesOf === 'function') zones = Intl.supportedValuesOf('timeZone')
  } catch {
    // keep the fallback list
  }
  return [...new Set([...include.filter(Boolean), ...zones, 'UTC'])].sort()
}

/** Parse the API's naive-UTC ISO string into a Date. */
export function parseUtc(value) {
  if (!value) return null
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`)
}

function offsetMinutes(timeZone, date) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(date)
  const v = Object.fromEntries(parts.map((p) => [p.type, Number(p.value)]))
  return (Date.UTC(v.year, v.month - 1, v.day, v.hour, v.minute, v.second) - date.getTime()) / 60000
}

/** Today's "HH:MM" in `timeZone` as a real instant. */
function zonedTimeToday(hhmm, timeZone) {
  const [h, m] = hhmm.split(':').map(Number)
  const now = new Date()
  const guess = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), h, m)
  return new Date(guess - offsetMinutes(timeZone, new Date(guess)) * 60000)
}

export function formatClock(date) {
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

/** "9:00 PM - 2:00 AM your time", or null when the campaign zone matches the browser's. */
export function windowInLocalTime(start, end, timeZone) {
  if (!start || !end || !timeZone) return null
  try {
    const here = browserTimezone()
    const probe = new Date()
    if (timeZone === here || offsetMinutes(timeZone, probe) === offsetMinutes(here, probe)) return null
    return `${formatClock(zonedTimeToday(start, timeZone))} - ${formatClock(zonedTimeToday(end, timeZone))} your time`
  } catch {
    return null
  }
}

/** "around 9:02 PM" today, "Mon 9:00 PM" later this week, or a date further out. */
export function describeWhen(value) {
  const date = parseUtc(value)
  if (!date) return null
  const now = new Date()
  const days = (date - now) / 86400000
  if (date.toDateString() === now.toDateString()) return `around ${formatClock(date)}`
  if (days < 6) return `${date.toLocaleDateString([], { weekday: 'short' })} ${formatClock(date)}`
  return date.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}
