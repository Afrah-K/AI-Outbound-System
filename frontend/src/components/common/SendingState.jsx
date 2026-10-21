import { clsx } from 'clsx'
import { describeWhen } from '../../utils/time'

// Plain-language version of the API's campaign.sending = {state, next_send_at}.
const STATES = {
  sending: { tone: 'green', label: 'Sending now', detail: () => 'Emails are going out' },
  on_break: { tone: 'blue', label: 'On a break', detail: (when) => `Next email ${when || 'shortly'}` },
  outside_hours: { tone: 'amber', label: 'Outside sending hours', detail: (when) => (when ? `Resumes ${when}` : 'Waiting for the send window') },
  daily_limit: { tone: 'amber', label: 'Inbox limits reached', detail: (when) => `Daily limits are used up - resumes ${when || 'tomorrow'}` },
  waiting_followups: { tone: 'blue', label: 'Waiting on follow-ups', detail: (when) => (when ? `Next follow-up is due ${when}` : 'No emails due right now') },
  finishing: { tone: 'gray', label: 'Wrapping up', detail: () => 'Every lead has finished or stopped' },
  no_inboxes: { tone: 'red', label: 'No connected inbox', detail: () => 'Assign a connected inbox to keep sending' },
  invalid_schedule: { tone: 'red', label: 'Schedule problem', detail: () => 'Check the campaign\'s time zone and hours' },
}

const TONES = {
  green: 'bg-green-50 text-green-800 border-green-200',
  blue: 'bg-primary-50 text-primary-800 border-primary-100',
  amber: 'bg-amber-50 text-amber-800 border-amber-200',
  red: 'bg-red-50 text-red-800 border-red-200',
  gray: 'bg-gray-50 text-gray-700 border-gray-200',
}

const DOTS = { green: 'bg-green-500 animate-pulse', blue: 'bg-primary-500', amber: 'bg-amber-500', red: 'bg-red-500', gray: 'bg-gray-400' }

/** Full banner for the campaign page, or a compact one-liner for lists. */
export default function SendingState({ sending, compact = false, className }) {
  const meta = sending && STATES[sending.state]
  if (!meta) return null
  const detail = meta.detail(describeWhen(sending.next_send_at))

  if (compact) {
    return (
      <span className={clsx('inline-flex items-center gap-1.5 text-xs text-gray-600', className)} title={detail}>
        <span className={clsx('h-1.5 w-1.5 rounded-full', DOTS[meta.tone])} />
        {meta.label}
      </span>
    )
  }

  return (
    <div className={clsx('flex items-center gap-3 rounded-card border px-4 py-3', TONES[meta.tone], className)}>
      <span className={clsx('h-2.5 w-2.5 shrink-0 rounded-full', DOTS[meta.tone])} />
      <p className="text-sm">
        <span className="font-medium">{meta.label}</span>
        <span className="opacity-80"> - {detail}</span>
      </p>
    </div>
  )
}
