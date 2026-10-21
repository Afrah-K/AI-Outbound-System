import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  PhoneIcon,
  LinkIcon,
  ClipboardDocumentIcon,
  CalendarDaysIcon,
  SparklesIcon,
  ArrowTopRightOnSquareIcon,
  XMarkIcon,
} from '@heroicons/react/24/outline'
import { api } from '../services/apiClient'
import Button from '../components/common/Button'
import Card from '../components/common/Card'
import LoadingSpinner from '../components/common/LoadingSpinner'
import EmptyState from '../components/common/EmptyState'
import toast from 'react-hot-toast'

const inputClass =
  'w-full px-3 py-2 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500'

function useDebounced(value, delay = 300) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

/** Calendly's documented query params: embed flags plus name/email prefill. */
function embedUrl(base, prospect) {
  try {
    const url = new URL(base)
    url.searchParams.set('embed_domain', window.location.hostname || 'localhost')
    url.searchParams.set('embed_type', 'Inline')
    url.searchParams.set('hide_gdpr_banner', '1')
    if (prospect) {
      const name = prospect.full_name || [prospect.first_name, prospect.last_name].filter(Boolean).join(' ')
      if (name) url.searchParams.set('name', name)
      url.searchParams.set('email', prospect.email)
    }
    return url.toString()
  } catch {
    return base
  }
}

export function BookingLinkForm({ settings, compact = false }) {
  const queryClient = useQueryClient()
  const [url, setUrl] = useState(settings?.calendly_url || '')
  useEffect(() => setUrl(settings?.calendly_url || ''), [settings?.calendly_url])

  const save = useMutation({
    mutationFn: () => api.calendar.updateSettings({ calendly_url: url.trim() }),
    onSuccess: (response) => {
      queryClient.setQueryData(['calendar-settings'], response.data)
      toast.success(url.trim() ? 'Booking link saved' : 'Booking link removed')
    },
  })

  return (
    <div className="space-y-2">
      {!compact && <label className="block text-sm font-medium text-gray-700">Your Calendly link</label>}
      <div className="flex gap-2">
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://calendly.com/your-name/30min"
          className={inputClass}
        />
        <Button onClick={() => save.mutate()} loading={save.isPending} disabled={url.trim() === (settings?.calendly_url || '')}>
          Save
        </Button>
      </div>
      <p className="text-xs text-gray-500">
        Copy it from Calendly: open the event type you want leads to book, then <strong>Copy link</strong>.
      </p>
    </div>
  )
}

function ProspectPicker({ onPick }) {
  const [search, setSearch] = useState('')
  const debounced = useDebounced(search)
  const { data, isFetching } = useQuery({
    queryKey: ['booking-prospects', debounced],
    queryFn: async () => (await api.leads.listPeople({ search: debounced, limit: 8 })).data,
    enabled: debounced.trim().length >= 2,
  })
  const people = debounced.trim().length >= 2 ? data?.people || [] : []

  return (
    <div className="space-y-2">
      <input
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search a prospect by name, email or company..."
        className={inputClass}
      />
      {isFetching && <p className="text-xs text-gray-400">Searching...</p>}
      {people.length > 0 && (
        <ul className="divide-y divide-gray-100 rounded-xl border border-gray-100 overflow-hidden">
          {people.map((p) => (
            <li key={p.id}>
              <button
                onClick={() => {
                  onPick(p)
                  setSearch('')
                }}
                className="w-full text-left px-3 py-2 hover:bg-primary-50"
              >
                <p className="text-sm text-gray-900 truncate">{p.full_name || [p.first_name, p.last_name].filter(Boolean).join(' ') || p.email}</p>
                <p className="text-xs text-gray-500 truncate">
                  {p.email}
                  {p.company_name ? ` · ${p.company_name}` : ''}
                </p>
              </button>
            </li>
          ))}
        </ul>
      )}
      {debounced.trim().length >= 2 && !isFetching && people.length === 0 && <p className="text-xs text-gray-400">No prospects match.</p>}
    </div>
  )
}

export default function BookingPage() {
  const [prospect, setProspect] = useState(null)
  const { data: settings, isLoading } = useQuery({
    queryKey: ['calendar-settings'],
    queryFn: async () => (await api.calendar.getSettings()).data,
  })

  const link = settings?.calendly_url
  const src = useMemo(() => (link ? embedUrl(link, prospect) : null), [link, prospect])

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link)
      toast.success('Booking link copied')
    } catch {
      toast.error("Couldn't copy - select the link and copy it manually")
    }
  }

  if (isLoading) {
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
          <h1 className="text-3xl font-medium tracking-tight text-gray-900">Book a Call</h1>
          <p className="mt-1 text-sm text-gray-500">Your Calendly booking page - share it with leads, or book a call for one of them</p>
        </div>
        {link && (
          <div className="flex items-center gap-2">
            <Button variant="secondary" icon={ClipboardDocumentIcon} onClick={copy}>
              Copy link
            </Button>
            <a href={link} target="_blank" rel="noopener noreferrer">
              <Button variant="secondary" icon={ArrowTopRightOnSquareIcon}>
                Open in Calendly
              </Button>
            </a>
          </div>
        )}
      </div>

      {!link ? (
        <Card className="max-w-2xl">
          <EmptyState
            icon={PhoneIcon}
            title="Connect your Calendly"
            description="Add your Calendly booking link to embed it here and let the reply agent offer it when a lead wants to talk."
            className="py-6"
          />
          <BookingLinkForm settings={settings} />
        </Card>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-4 items-start">
          <Card padding={false} className="xl:col-span-8 overflow-hidden">
            {prospect && (
              <div className="flex items-center justify-between gap-3 px-5 py-3 bg-primary-50 text-sm text-primary-900">
                <span>
                  Booking for <strong>{prospect.full_name || prospect.first_name || prospect.email}</strong> - name and email are prefilled
                </span>
                <button onClick={() => setProspect(null)} className="inline-flex items-center gap-1 text-primary-700 hover:text-primary-900">
                  <XMarkIcon className="h-4 w-4" /> Clear
                </button>
              </div>
            )}
            <iframe key={src} src={src} title="Calendly booking" className="w-full border-0" style={{ height: 760 }} />
          </Card>

          <div className="xl:col-span-4 space-y-4">
            <Card>
              <Card.Header>
                <Card.Title>Book for a prospect</Card.Title>
                <Card.Description>Pick a lead and the booking form above fills in their name and email</Card.Description>
              </Card.Header>
              <ProspectPicker onPick={setProspect} />
            </Card>

            <Card>
              <Card.Header>
                <Card.Title>Share your link</Card.Title>
              </Card.Header>
              <div className="flex items-center gap-2 rounded-xl bg-canvas px-3 py-2">
                <LinkIcon className="h-4 w-4 shrink-0 text-primary-600" />
                <span className="text-sm text-gray-800 truncate">{link}</span>
              </div>
              <ul className="mt-3 space-y-2 text-sm text-gray-600">
                <li className="flex gap-2">
                  <SparklesIcon className="h-4 w-4 shrink-0 mt-0.5 text-primary-600" />
                  The reply agent offers this link when a lead wants to talk.
                </li>
                <li className="flex gap-2">
                  <CalendarDaysIcon className="h-4 w-4 shrink-0 mt-0.5 text-primary-600" />
                  Booked calls show up on the{' '}
                  <Link to="/calendar" className="text-primary-600 hover:underline">
                    Calendar
                  </Link>
                  {settings?.has_token ? '.' : ' once you add a Calendly token there.'}
                </li>
              </ul>
            </Card>

            <Card>
              <Card.Header>
                <Card.Title>Change link</Card.Title>
              </Card.Header>
              <BookingLinkForm settings={settings} compact />
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}
