import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import {
  CalendarDaysIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  VideoCameraIcon,
  MapPinIcon,
  KeyIcon,
  ArrowPathIcon,
} from '@heroicons/react/24/outline'
import { clsx } from 'clsx'
import { api } from '../services/apiClient'
import Button from '../components/common/Button'
import Card from '../components/common/Card'
import StatCard from '../components/common/StatCard'
import StatusBadge from '../components/common/StatusBadge'
import LoadingSpinner from '../components/common/LoadingSpinner'
import EmptyState from '../components/common/EmptyState'
import toast from 'react-hot-toast'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const inputClass =
  'w-full px-3 py-2 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500'

function startOfMonth(d) {
  return new Date(d.getFullYear(), d.getMonth(), 1)
}

/** The 6-week Monday-first grid that contains `month`. */
function gridDays(month) {
  const first = startOfMonth(month)
  const offset = (first.getDay() + 6) % 7
  const start = new Date(first)
  start.setDate(first.getDate() - offset)
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(start)
    d.setDate(start.getDate() + i)
    return d
  })
}

const dayKey = (d) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
const clock = (d) => d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })

function TokenSetup({ settings }) {
  const queryClient = useQueryClient()
  const [token, setToken] = useState('')
  const save = useMutation({
    mutationFn: () => api.calendar.updateSettings({ calendly_token: token.trim() }),
    onSuccess: (response) => {
      queryClient.setQueryData(['calendar-settings'], response.data)
      queryClient.invalidateQueries({ queryKey: ['calendar-events'] })
      setToken('')
      toast.success('Calendly connected')
    },
  })

  return (
    <Card className="max-w-2xl">
      <EmptyState
        icon={CalendarDaysIcon}
        title="See your booked calls here"
        description="Connect Calendly with a personal access token to show every booked call, matched to the prospect and campaign it came from."
        className="py-6"
      />
      <ol className="mb-4 list-decimal list-inside space-y-1 text-sm text-gray-600">
        <li>
          In Calendly, open{' '}
          <a href="https://calendly.com/integrations/api_webhooks" target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:underline">
            Integrations → API &amp; Webhooks
          </a>
          .
        </li>
        <li>
          Click <strong>Generate new token</strong>, and under scopes tick{' '}
          {(settings?.required_scopes || ['users:read', 'scheduled_events:read']).map((scope, i, all) => (
            <span key={scope}>
              <code className="rounded bg-canvas px-1.5 py-0.5 text-xs text-gray-800">{scope}</code>
              {i < all.length - 2 ? ', ' : i === all.length - 2 ? ' and ' : ''}
            </span>
          ))}{' '}
          (read-only is enough).
        </li>
        <li>Copy the token and paste it below.</li>
      </ol>
      <div className="flex gap-2">
        <input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="Calendly personal access token"
          className={inputClass}
          autoComplete="off"
        />
        <Button icon={KeyIcon} onClick={() => save.mutate()} loading={save.isPending} disabled={!token.trim()}>
          Connect
        </Button>
      </div>
      <p className="mt-2 text-xs text-gray-500">
        The token stays in your local database and is only used to read your scheduled events.
        {!settings?.calendly_url && ' Your booking link is filled in from your account automatically.'}
      </p>
    </Card>
  )
}

function EventDetails({ event }) {
  const queryClient = useQueryClient()
  const start = new Date(event.start_time)
  const end = new Date(event.end_time)
  const isPast = end < new Date()

  const convert = useMutation({
    mutationFn: (personId) => api.leads.updatePersonStatus(personId, 'converted'),
    onSuccess: () => {
      toast.success('Marked as converted')
      queryClient.invalidateQueries({ queryKey: ['calendar-events'] })
    },
  })

  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-primary-600">{event.name}</p>
        <p className="mt-1 text-lg font-medium tracking-tight text-gray-900">
          {start.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })}
        </p>
        <p className="text-sm text-gray-600">
          {clock(start)} - {clock(end)}
          {event.status === 'canceled' && <span className="ml-2 text-red-600">Canceled</span>}
        </p>
      </div>

      {(event.join_url || event.location) && (
        <div className="flex items-center gap-2 text-sm">
          {event.join_url ? <VideoCameraIcon className="h-4 w-4 text-primary-600" /> : <MapPinIcon className="h-4 w-4 text-primary-600" />}
          {event.join_url ? (
            <a href={event.join_url} target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:underline">
              Join {event.location || 'call'}
            </a>
          ) : (
            <span className="text-gray-700">{event.location}</span>
          )}
        </div>
      )}

      {event.invitees.map((inv) => (
        <div key={inv.email} className="rounded-2xl bg-canvas p-4 space-y-2">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="font-medium text-gray-900 truncate">{inv.name || inv.email}</p>
              <p className="text-xs text-gray-500 truncate">{inv.email}</p>
            </div>
            {inv.prospect?.status && <StatusBadge status={inv.prospect.status} />}
          </div>
          {inv.prospect ? (
            <p className="text-xs text-gray-600">
              Prospect{inv.prospect.company_name ? ` at ${inv.prospect.company_name}` : ''}
              {inv.campaign && (
                <>
                  {' '}from{' '}
                  <Link to={`/campaigns/${inv.campaign.id}`} className="text-primary-600 hover:underline">
                    {inv.campaign.name}
                  </Link>
                </>
              )}
            </p>
          ) : (
            <p className="text-xs text-gray-500">Not in your prospects</p>
          )}
          {inv.answers?.length > 0 && (
            <dl className="space-y-1 pt-1">
              {inv.answers.map((qa) => (
                <div key={qa.question} className="text-xs">
                  <dt className="text-gray-500">{qa.question}</dt>
                  <dd className="text-gray-800">{qa.answer}</dd>
                </div>
              ))}
            </dl>
          )}
          <div className="flex flex-wrap gap-2 pt-1">
            {inv.prospect && inv.prospect.status !== 'converted' && (
              <Button size="sm" onClick={() => convert.mutate(inv.prospect.id)} loading={convert.isPending}>
                Mark converted
              </Button>
            )}
            {!isPast && inv.reschedule_url && (
              <a href={inv.reschedule_url} target="_blank" rel="noopener noreferrer">
                <Button size="sm" variant="secondary">Reschedule</Button>
              </a>
            )}
            {!isPast && inv.cancel_url && (
              <a href={inv.cancel_url} target="_blank" rel="noopener noreferrer">
                <Button size="sm" variant="ghost">Cancel</Button>
              </a>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

export default function CalendarPage() {
  const [month, setMonth] = useState(() => startOfMonth(new Date()))
  const [selectedUri, setSelectedUri] = useState(null)
  const days = useMemo(() => gridDays(month), [month])

  const { data: settings, isLoading: settingsLoading } = useQuery({
    queryKey: ['calendar-settings'],
    queryFn: async () => (await api.calendar.getSettings()).data,
  })

  const rangeStart = days[0]
  const rangeEnd = new Date(days[41].getFullYear(), days[41].getMonth(), days[41].getDate() + 1)
  const eventsQuery = useQuery({
    queryKey: ['calendar-events', rangeStart.toISOString()],
    queryFn: async () =>
      (
        await api.calendar.events({
          start: rangeStart.toISOString().slice(0, 19),
          end: rangeEnd.toISOString().slice(0, 19),
        })
      ).data,
    enabled: Boolean(settings?.has_token),
    placeholderData: keepPreviousData,
    retry: false,
  })

  const events = eventsQuery.data?.events || []
  const byDay = useMemo(() => {
    const map = {}
    for (const e of events) (map[dayKey(new Date(e.start_time))] ||= []).push(e)
    return map
  }, [events])

  const now = new Date()
  const upcoming = events.filter((e) => new Date(e.end_time) >= now)
  const selected = events.find((e) => e.uri === selectedUri) || upcoming[0] || null
  const thisWeekEnd = new Date(now)
  thisWeekEnd.setDate(now.getDate() + 7)
  const fromProspects = events.filter((e) => e.invitees.some((i) => i.prospect)).length

  if (settingsLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-medium tracking-tight text-gray-900">Calendar</h1>
          <p className="mt-1 text-sm text-gray-500">Calls booked through your Calendly, matched to your prospects</p>
        </div>
        {settings?.has_token && (
          <div className="flex items-center gap-2">
            <Link to="/booking">
              <Button variant="secondary">Book a call</Button>
            </Link>
            <Button variant="secondary" icon={ArrowPathIcon} onClick={() => eventsQuery.refetch()} loading={eventsQuery.isFetching}>
              Refresh
            </Button>
          </div>
        )}
      </div>

      {!settings?.has_token ? (
        <TokenSetup settings={settings} />
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <StatCard icon={CalendarDaysIcon} label="Upcoming calls" value={eventsQuery.data ? upcoming.length : '-'} caption="In the visible range" />
            <StatCard
              icon={CalendarDaysIcon}
              label="Next 7 days"
              value={eventsQuery.data ? upcoming.filter((e) => new Date(e.start_time) <= thisWeekEnd).length : '-'}
              caption="Calls coming up this week"
            />
            <StatCard icon={CalendarDaysIcon} label="Booked by prospects" value={eventsQuery.data ? fromProspects : '-'} caption="Matched to your prospect list" />
          </div>

          {eventsQuery.error && (
            <div className="rounded-card border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              Couldn't load events from Calendly. {eventsQuery.error.response?.data?.detail || ''}
            </div>
          )}

          <div className="grid grid-cols-1 xl:grid-cols-12 gap-4 items-start">
            <Card padding={false} className="xl:col-span-8 overflow-hidden">
              <div className="flex items-center justify-between px-5 py-4">
                <h2 className="text-lg font-medium tracking-tight text-gray-900">
                  {month.toLocaleDateString([], { month: 'long', year: 'numeric' })}
                </h2>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}
                    aria-label="Previous month"
                    className="h-8 w-8 rounded-full border border-gray-200 bg-white flex items-center justify-center text-gray-600 hover:border-primary-500 hover:text-primary-600"
                  >
                    <ChevronLeftIcon className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => setMonth(startOfMonth(new Date()))}
                    className="px-3 h-8 rounded-full border border-gray-200 bg-white text-xs text-gray-700 hover:border-primary-500 hover:text-primary-600"
                  >
                    Today
                  </button>
                  <button
                    onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}
                    aria-label="Next month"
                    className="h-8 w-8 rounded-full border border-gray-200 bg-white flex items-center justify-center text-gray-600 hover:border-primary-500 hover:text-primary-600"
                  >
                    <ChevronRightIcon className="h-4 w-4" />
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-7 border-t border-gray-100 text-xs text-gray-500">
                {WEEKDAYS.map((d) => (
                  <div key={d} className="px-2 py-2 text-center font-medium">
                    {d}
                  </div>
                ))}
              </div>
              <div className={clsx('grid grid-cols-7 border-t border-gray-100', eventsQuery.isFetching && 'opacity-60')}>
                {days.map((d) => {
                  const inMonth = d.getMonth() === month.getMonth()
                  const isToday = d.toDateString() === now.toDateString()
                  const dayEvents = byDay[dayKey(d)] || []
                  return (
                    <div key={d.toISOString()} className="min-h-[92px] border-b border-r border-gray-100 p-1.5 [&:nth-child(7n)]:border-r-0">
                      <span
                        className={clsx(
                          'inline-flex h-6 w-6 items-center justify-center rounded-full text-xs',
                          isToday ? 'bg-primary-600 text-white font-semibold' : inMonth ? 'text-gray-800' : 'text-gray-300'
                        )}
                      >
                        {d.getDate()}
                      </span>
                      <div className="mt-1 space-y-1">
                        {dayEvents.slice(0, 3).map((e) => (
                          <button
                            key={e.uri}
                            onClick={() => setSelectedUri(e.uri)}
                            className={clsx(
                              'w-full truncate rounded-md px-1.5 py-0.5 text-left text-[11px] transition-colors',
                              selected?.uri === e.uri ? 'bg-primary-600 text-white' : 'bg-primary-50 text-primary-800 hover:bg-primary-100'
                            )}
                            title={`${clock(new Date(e.start_time))} ${e.invitees[0]?.name || e.name}`}
                          >
                            {clock(new Date(e.start_time))} {e.invitees[0]?.name || e.name}
                          </button>
                        ))}
                        {dayEvents.length > 3 && <p className="px-1 text-[11px] text-gray-500">+{dayEvents.length - 3} more</p>}
                      </div>
                    </div>
                  )
                })}
              </div>
            </Card>

            <div className="xl:col-span-4 space-y-4">
              <Card>
                {eventsQuery.isLoading ? (
                  <div className="flex justify-center py-8">
                    <LoadingSpinner />
                  </div>
                ) : selected ? (
                  <EventDetails event={selected} />
                ) : (
                  <EmptyState icon={CalendarDaysIcon} title="No calls this month" description="Share your booking link to get calls on the calendar" className="py-6" />
                )}
              </Card>

              {upcoming.length > 1 && (
                <Card>
                  <Card.Header>
                    <Card.Title>Upcoming</Card.Title>
                  </Card.Header>
                  <ul className="divide-y divide-gray-100">
                    {upcoming.slice(0, 8).map((e) => (
                      <li key={e.uri}>
                        <button onClick={() => setSelectedUri(e.uri)} className="w-full text-left py-2.5 hover:text-primary-700">
                          <p className="text-sm font-medium text-gray-900 truncate">{e.invitees[0]?.name || e.name}</p>
                          <p className="text-xs text-gray-500">
                            {new Date(e.start_time).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })} · {clock(new Date(e.start_time))}
                          </p>
                        </button>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
