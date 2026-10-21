import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import {
  InboxStackIcon,
  ExclamationTriangleIcon,
  PaperAirplaneIcon,
  PlusIcon,
  ArrowPathIcon,
  MagnifyingGlassIcon,
  SparklesIcon,
  XMarkIcon,
  BellAlertIcon,
  Cog6ToothIcon,
  ChatBubbleLeftRightIcon,
  PencilSquareIcon,
  HandThumbUpIcon,
  ArrowTrendingUpIcon,
  CalendarDaysIcon,
  ChevronDownIcon,
  ChevronUpIcon,
} from '@heroicons/react/24/outline'
import { clsx } from 'clsx'
import { api } from '../services/apiClient'
import Button from '../components/common/Button'
import Card from '../components/common/Card'
import StatusBadge from '../components/common/StatusBadge'
import LoadingSpinner from '../components/common/LoadingSpinner'
import EmptyState from '../components/common/EmptyState'
import StatCard from '../components/common/StatCard'
import toast from 'react-hot-toast'

const REFRESH_MS = 2 * 60 * 1000
const LEGACY_INSTRUCTIONS_KEY = 'unibox.agentInstructions'

const CATEGORIES = {
  interested: { label: 'Interested', className: 'bg-green-100 text-green-800' },
  question: { label: 'Question', className: 'bg-primary-50 text-primary-700' },
  not_interested: { label: 'Not interested', className: 'bg-gray-200 text-gray-700' },
  out_of_office: { label: 'Out of office', className: 'bg-yellow-100 text-yellow-800' },
  unsubscribe: { label: 'Unsubscribe', className: 'bg-red-100 text-red-800' },
  wrong_person: { label: 'Wrong person', className: 'bg-orange-100 text-orange-800' },
  other: { label: 'Other', className: 'bg-gray-100 text-gray-700' },
}

// Quick outcomes for a lead's conversation - they also keep the lead out of future campaigns where relevant.
const LEAD_ACTIONS = [
  { status: 'converted', label: 'Interested / converted' },
  { status: 'unsubscribed', label: 'Unsubscribe' },
  { status: 'do_not_contact', label: 'Do not contact' },
]

const inputClass =
  'w-full px-3 py-2 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500'

function CategoryBadge({ category }) {
  const meta = CATEGORIES[category] || CATEGORIES.other
  return <span className={clsx('text-[10px] font-medium rounded px-1.5 py-0.5', meta.className)}>{meta.label}</span>
}

function parseFrom(from) {
  const match = from?.match(/^"?([^"<]*)"?\s*<?([^<>]*@[^<>]*)>?$/)
  if (match) {
    const name = match[1].trim()
    const email = match[2].trim()
    return { name: name || email, email }
  }
  return { name: from || 'Unknown', email: from || '' }
}

function relativeTime(value) {
  const ms = typeof value === 'string' && value.includes('T') ? Date.parse(value + 'Z') : Number(value)
  if (!ms) return ''
  const diff = Date.now() - ms
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  return new Date(ms).toLocaleDateString()
}

function Toggle({ checked, onChange, disabled, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={clsx(
        'relative inline-flex h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-50',
        checked ? 'bg-primary-600' : 'bg-gray-300'
      )}
    >
      <span
        className={clsx(
          'inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform mt-0.5',
          checked ? 'translate-x-4' : 'translate-x-0.5'
        )}
      />
    </button>
  )
}

function InboxErrors({ errors }) {
  if (!errors?.length) return null
  return (
    <div className="flex gap-2 rounded-lg bg-amber-50 border border-amber-200 p-3">
      <ExclamationTriangleIcon className="h-5 w-5 text-amber-500 shrink-0" />
      <div className="text-sm text-amber-800">
        {errors.map((e) => (
          <p key={e.inbox_id}>
            <strong>{e.email}</strong> couldn't be loaded ({e.error}) -{' '}
            <Link to="/inboxes" className="underline">reconnect it on the Inboxes page</Link>
          </p>
        ))}
      </div>
    </div>
  )
}

function useBookingLink() {
  const { data } = useQuery({
    queryKey: ['calendar-settings'],
    queryFn: async () => (await api.calendar.getSettings()).data,
    staleTime: 5 * 60 * 1000,
  })
  return data?.calendly_url || null
}

/** Appends the Calendly link to a reply on its own line (skips it if already there). */
function InsertBookingLink({ value, onChange }) {
  const link = useBookingLink()
  if (!link) return null
  return (
    <button
      type="button"
      onClick={() => !value.includes(link) && onChange(`${value.trimEnd()}${value.trim() ? '\n\n' : ''}${link}`)}
      className="inline-flex items-center gap-1 text-xs text-primary-600 hover:text-primary-800"
      title={link}
    >
      <CalendarDaysIcon className="h-3.5 w-3.5" /> Insert booking link
    </button>
  )
}

// ---------------------------------------------------------------------------
// Left: leads
// ---------------------------------------------------------------------------

function ConversationList({ items, selected, onSelect }) {
  return (
    <div className="divide-y divide-gray-200 max-h-[52vh] overflow-y-auto">
      {items.map((item) => {
        const isSelected = selected?.thread_id === item.thread_id && selected?.inbox_id === item.inbox_id
        return (
          <button
            key={`${item.inbox_id}-${item.thread_id}-${item.key}`}
            onClick={() => onSelect({ inbox_id: item.inbox_id, thread_id: item.thread_id })}
            className={clsx('w-full text-left px-3 py-3 hover:bg-gray-50 transition-colors', isSelected && 'bg-primary-50')}
          >
            <div className="flex items-center justify-between gap-2">
              <p className={clsx('text-sm truncate', item.unread ? 'font-semibold text-gray-900' : 'text-gray-700')}>
                {item.unread && <span className="inline-block h-2 w-2 rounded-full bg-primary-600 mr-1.5 align-middle" />}
                {item.name}
              </p>
              <span className="text-xs text-gray-400 shrink-0">{relativeTime(item.internal_date)}</span>
            </div>
            {item.company && <p className="text-xs text-gray-500 truncate">{item.company}</p>}
            <p className={clsx('text-xs truncate mt-0.5', item.unread ? 'font-medium text-gray-900' : 'text-gray-600')}>
              {item.subject || '(no subject)'}
            </p>
            <p className="text-xs text-gray-400 truncate">{item.snippet}</p>
            <div className="flex flex-wrap gap-1 mt-1">
              {item.state === 'awaiting' && (
                <span className="text-[10px] text-amber-800 bg-amber-50 rounded px-1.5 py-0.5">
                  No reply · {item.days_since_last_email === 0 ? 'today' : `${item.days_since_last_email}d`}
                  {item.emails_sent > 1 ? ` · ${item.emails_sent} sent` : ''}
                </span>
              )}
              {item.state === 'bounced' && <span className="text-[10px] text-red-700 bg-red-50 rounded px-1.5 py-0.5">Bounced</span>}
              {item.state === 'replied' && !item.agent && <span className="text-[10px] text-green-800 bg-green-50 rounded px-1.5 py-0.5">Replied</span>}
              {item.agent?.category && item.agent.status !== 'failed' && <CategoryBadge category={item.agent.category} />}
              {item.agent?.status === 'pending' && item.agent.draft_body && (
                <span className="text-[10px] font-medium text-white bg-primary-600 rounded px-1.5 py-0.5">Draft ready</span>
              )}
              {item.campaign && (
                <span className="text-[10px] text-primary-700 bg-primary-50 rounded px-1.5 py-0.5">{item.campaign.name}</span>
              )}
            </div>
          </button>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Middle: the conversation
// ---------------------------------------------------------------------------

function ThreadView({ selected, thread, isLoading, item, threadKey }) {
  const queryClient = useQueryClient()
  const [replyBody, setReplyBody] = useState('')
  const [stopFollowups, setStopFollowups] = useState(true)

  useEffect(() => {
    setReplyBody('')
    setStopFollowups(true)
  }, [selected.inbox_id, selected.thread_id])

  const automation = thread?.automation
  const followupsActive = Boolean(automation?.active)

  const person = thread?.person || item?.person
  const campaign = thread?.campaign || item?.campaign
  const replyTo = person?.email || item?.fromEmail || parseFrom([...(thread?.messages || [])].reverse().find((m) => !m.from_me)?.from).email
  const subject = item?.subject || thread?.messages?.[0]?.subject

  const replyMutation = useMutation({
    mutationFn: () =>
      api.unibox.reply(selected.inbox_id, selected.thread_id, {
        to: replyTo,
        subject,
        body: replyBody,
        stop_followups: followupsActive && stopFollowups,
      }),
    onSuccess: (response) => {
      toast.success(
        `Sent to ${replyTo}` + (response.data.stopped_followups ? ' - automatic follow-ups stopped for this lead' : '')
      )
      setReplyBody('')
      queryClient.invalidateQueries({ queryKey: threadKey })
      queryClient.invalidateQueries({ queryKey: ['unibox-replies'] })
      queryClient.invalidateQueries({ queryKey: ['unibox-conversations'] })
    },
  })

  const statusMutation = useMutation({
    mutationFn: (status) => api.leads.updatePersonStatus(person.id, status),
    onSuccess: (_, status) => {
      toast.success(`Marked ${person.name || person.email} as ${status.replaceAll('_', ' ')}`)
      queryClient.invalidateQueries({ queryKey: threadKey })
      queryClient.invalidateQueries({ queryKey: ['unibox-replies'] })
    },
  })

  const send = () => {
    if (replyBody.trim() && replyTo && !replyMutation.isPending) replyMutation.mutate()
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <h3 className="text-lg font-semibold text-gray-900">{subject || '(no subject)'}</h3>
        {person && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <span className="font-medium text-gray-900">{person.name || person.email}</span>
            {person.role && <span className="text-gray-500">{person.role}</span>}
            {person.company_name && <span className="text-gray-500">@ {person.company_name}</span>}
            {person.status && <StatusBadge status={person.status} />}
            {campaign && (
              <Link to={`/campaigns/${campaign.id}`} className="text-primary-700 hover:underline">
                {campaign.name}
              </Link>
            )}
          </div>
        )}
        {person && (
          <div className="flex flex-wrap gap-2">
            {LEAD_ACTIONS.filter((a) => a.status !== person.status).map((action) => (
              <Button
                key={action.status}
                variant="secondary"
                size="sm"
                onClick={() => statusMutation.mutate(action.status)}
                disabled={statusMutation.isPending}
              >
                {action.label}
              </Button>
            ))}
          </div>
        )}
      </div>

      <div className="space-y-3 max-h-[46vh] overflow-y-auto pr-1">
        {thread?.messages.map((msg) => (
          <div
            key={msg.id}
            className={clsx(
              'rounded-lg p-3 border',
              msg.from_me ? 'ml-8 bg-primary-50 border-primary-100' : 'mr-8 bg-white border-gray-200'
            )}
          >
            <div className="flex items-center justify-between text-xs text-gray-500 mb-2 gap-2">
              <span className="font-medium text-gray-700">{msg.from_me ? 'You' : parseFrom(msg.from).name}</span>
              <span>{msg.internal_date ? new Date(Number(msg.internal_date)).toLocaleString() : msg.date}</span>
            </div>
            <p className="text-sm text-gray-800 whitespace-pre-wrap break-words">{msg.body || msg.snippet}</p>
          </div>
        ))}
      </div>

      <div className="border-t border-gray-200 pt-3">
        {followupsActive && (
          <div className="mb-2 rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-xs text-amber-900">
            <p>
              Automatic email {automation.current_step + 1} of {automation.total_steps} is scheduled
              {automation.next_send_at ? ` for ${new Date(automation.next_send_at).toLocaleString([], { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}` : ''}
              {!automation.campaign_running ? ' (campaign paused)' : ''}.
            </p>
            <label className="mt-1.5 flex items-center gap-2 font-medium">
              <input
                type="checkbox"
                checked={stopFollowups}
                onChange={(e) => setStopFollowups(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-amber-300 text-primary-600 focus:ring-primary-500"
              />
              Stop the automatic emails for this lead when I send (so they don't get two)
            </label>
          </div>
        )}
        <label className="block text-sm font-medium text-gray-700 mb-1">
          {thread?.messages?.length && thread.messages[thread.messages.length - 1].from_me ? 'Write a follow-up' : 'Write your own reply'}
          {replyTo ? ` to ${replyTo}` : ''}{' '}
          <span className="font-normal text-gray-400">from {thread?.inbox_email || item?.inbox_email}</span>
        </label>
        <textarea
          value={replyBody}
          onChange={(e) => setReplyBody(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send()
          }}
          rows={3}
          placeholder="Type your message... (or let the agent above draft it)"
          className={inputClass}
        />
        <div className="flex items-center justify-between mt-2">
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-400">Ctrl/⌘ + Enter to send</span>
            <InsertBookingLink value={replyBody} onChange={setReplyBody} />
          </div>
          <Button icon={PaperAirplaneIcon} onClick={send} loading={replyMutation.isPending} disabled={!replyBody.trim() || !replyTo}>
            Send
          </Button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Right: the agent (vertical)
// ---------------------------------------------------------------------------

function ConversationAgent({ selected, thread, threadLoading, threadKey }) {
  const queryClient = useQueryClient()
  const [draftBody, setDraftBody] = useState('')
  const [guidance, setGuidance] = useState('')

  const agent = thread?.agent
  const pendingDraft = agent?.status === 'pending' ? agent : null
  const isLead = Boolean(thread?.person)
  const hasPlaceholders = draftBody.includes('[[')

  // Load each new draft into the editor (switching conversations or a fresh redraft).
  useEffect(() => {
    setDraftBody(pendingDraft?.draft_body || '')
  }, [pendingDraft?.id, pendingDraft?.draft_body])

  useEffect(() => {
    setGuidance('')
  }, [selected.inbox_id, selected.thread_id])

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: threadKey })
    queryClient.invalidateQueries({ queryKey: ['unibox-replies'] })
  }

  const draftMutation = useMutation({
    mutationFn: () => api.unibox.draftThread(selected.inbox_id, selected.thread_id, guidance),
    onSuccess: () => {
      toast.success('Draft ready - review it before sending')
      setGuidance('')
      refresh()
    },
  })

  const sendMutation = useMutation({
    mutationFn: () => api.unibox.sendDraft(pendingDraft.id, draftBody),
    onSuccess: () => {
      toast.success(`Sent to ${thread.person.email}`)
      refresh()
    },
  })

  const dismissMutation = useMutation({
    mutationFn: () => api.unibox.dismissDraft(pendingDraft.id),
    onSuccess: () => {
      toast.success('Draft dismissed')
      refresh()
    },
  })

  const statusMutation = useMutation({
    mutationFn: (status) => api.leads.updatePersonStatus(thread.person.id, status),
    onSuccess: (_, status) => {
      toast.success(`Marked as ${status.replaceAll('_', ' ')}`)
      refresh()
    },
  })

  if (threadLoading) {
    return (
      <div className="flex justify-center py-6">
        <LoadingSpinner />
      </div>
    )
  }

  if (!isLead) {
    return <p className="text-sm text-gray-500">The agent drafts replies for prospects in your Prospects list. This sender isn't one.</p>
  }

  const busy = draftMutation.isPending

  return (
    <div className="space-y-3">
      {agent && agent.status !== 'superseded' && (
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            {agent.status === 'failed' ? (
              <span className="text-sm text-red-700">Last attempt failed: {agent.error}</span>
            ) : (
              <>
                <CategoryBadge category={agent.category} />
                {agent.status !== 'pending' && <span className="text-xs text-gray-500">draft {agent.status}</span>}
              </>
            )}
          </div>
          {agent.summary && <p className="text-sm text-gray-800">{agent.summary}</p>}
          {pendingDraft && agent.suggested_status && agent.suggested_status !== thread.person.status && (
            <Button size="sm" variant="secondary" onClick={() => statusMutation.mutate(agent.suggested_status)} disabled={statusMutation.isPending}>
              Apply suggested status: {agent.suggested_status.replaceAll('_', ' ')}
            </Button>
          )}
        </div>
      )}

      {pendingDraft && pendingDraft.draft_body ? (
        <div className="space-y-2">
          <label className="block text-xs font-medium text-gray-600">Draft reply - edit, then approve</label>
          <textarea value={draftBody} onChange={(e) => setDraftBody(e.target.value)} rows={9} className={inputClass} />
          <InsertBookingLink value={draftBody} onChange={setDraftBody} />
          {hasPlaceholders && (
            <p className="text-xs text-amber-700">Fill in the [[placeholders]] first - the agent leaves those where it didn't know a fact.</p>
          )}
          <div className="flex gap-2">
            <Button
              className="flex-1"
              icon={PaperAirplaneIcon}
              onClick={() => sendMutation.mutate()}
              loading={sendMutation.isPending}
              disabled={!draftBody.trim() || hasPlaceholders}
            >
              Approve & send
            </Button>
            <Button variant="secondary" icon={XMarkIcon} onClick={() => dismissMutation.mutate()} loading={dismissMutation.isPending}>
              Dismiss
            </Button>
          </div>
        </div>
      ) : pendingDraft ? (
        <div className="flex items-center justify-between gap-2 text-sm text-gray-600">
          No reply needed for this one.
          <Button size="sm" variant="ghost" onClick={() => dismissMutation.mutate()} loading={dismissMutation.isPending}>
            Mark handled
          </Button>
        </div>
      ) : null}

      <div className="space-y-2 pt-2 border-t border-gray-100">
        <input
          value={guidance}
          onChange={(e) => setGuidance(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !busy) draftMutation.mutate()
          }}
          placeholder={pendingDraft ? 'Guidance, e.g. "shorter", "offer Thursday 2pm"' : 'Optional guidance for the draft'}
          className={inputClass}
        />
        <Button
          variant={pendingDraft?.draft_body ? 'secondary' : 'primary'}
          className="w-full"
          icon={SparklesIcon}
          onClick={() => draftMutation.mutate()}
          loading={busy}
        >
          {busy ? 'Drafting...' : pendingDraft?.draft_body ? 'Redraft' : 'Draft reply with agent'}
        </Button>
      </div>
    </div>
  )
}

function AgentSettingsPanel({ settings }) {
  const queryClient = useQueryClient()
  const [instructions, setInstructions] = useState(settings.instructions)
  const [notifyEmail, setNotifyEmail] = useState(settings.notify_email)

  useEffect(() => setInstructions(settings.instructions), [settings.instructions])
  useEffect(() => setNotifyEmail(settings.notify_email), [settings.notify_email])

  const saveMutation = useMutation({
    mutationFn: (data) => api.unibox.updateAgentSettings(data),
    onSuccess: (response) => queryClient.setQueryData(['agent-settings'], response.data),
  })

  const testMutation = useMutation({
    mutationFn: () => api.unibox.testAlert(),
    onSuccess: (response) => toast.success(`Test alert sent from ${response.data.sent_from}`),
  })

  const emailChanged = notifyEmail.trim() !== (settings.notify_email || '')

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Instructions for every draft</label>
        <textarea
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          rows={4}
          placeholder="What you offer, prices it may quote, the next step to propose (e.g. 'book a 15-min call at cal.com/you'), tone..."
          className={inputClass}
        />
        <div className="flex items-center justify-between mt-1">
          <span className="text-[11px] text-gray-400">Facts not given here come back as [[placeholders]].</span>
          <Button
            size="sm"
            variant="secondary"
            disabled={instructions === settings.instructions}
            loading={saveMutation.isPending}
            onClick={() => saveMutation.mutate({ instructions }, { onSuccess: () => toast.success('Instructions saved') })}
          >
            Save
          </Button>
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-1.5 text-xs font-medium text-gray-600">
            <BellAlertIcon className="h-4 w-4" /> Email me when drafts are waiting
          </span>
          <Toggle
            label="Email alerts"
            checked={settings.email_alerts_enabled}
            disabled={saveMutation.isPending || !settings.notify_email}
            onChange={(value) => saveMutation.mutate({ email_alerts_enabled: value })}
          />
        </div>
        <div className="flex gap-2">
          <input
            type="email"
            value={notifyEmail}
            onChange={(e) => setNotifyEmail(e.target.value)}
            placeholder="you@yourcompany.com"
            className={inputClass}
          />
          <Button
            size="sm"
            variant="secondary"
            disabled={!emailChanged || !notifyEmail.trim()}
            onClick={() =>
              saveMutation.mutate(
                { notify_email: notifyEmail.trim(), ...(settings.notify_email ? {} : { email_alerts_enabled: true }) },
                { onSuccess: () => toast.success('Alert email saved') }
              )
            }
          >
            Save
          </Button>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-gray-400">
            {settings.alert_sent_from ? `Sent from ${settings.alert_sent_from}` : 'Connect an inbox to send alerts'}
          </span>
          <Button size="sm" variant="ghost" disabled={!settings.notify_email} loading={testMutation.isPending} onClick={() => testMutation.mutate()}>
            Send test
          </Button>
        </div>
      </div>
    </div>
  )
}

function AgentPanel({ selected, thread, threadLoading, threadKey, onCollapse }) {
  const queryClient = useQueryClient()
  const [showSettings, setShowSettings] = useState(false)

  const { data: settings } = useQuery({
    queryKey: ['agent-settings'],
    queryFn: async () => (await api.unibox.getAgentSettings()).data,
    refetchInterval: REFRESH_MS,
  })

  // One-time move of instructions saved in the browser by the previous version onto the server.
  useEffect(() => {
    if (!settings || settings.instructions) return
    let legacy = ''
    try {
      legacy = localStorage.getItem(LEGACY_INSTRUCTIONS_KEY) || ''
    } catch {
      return
    }
    if (!legacy) return
    api.unibox.updateAgentSettings({ instructions: legacy }).then((response) => {
      queryClient.setQueryData(['agent-settings'], response.data)
      try {
        localStorage.removeItem(LEGACY_INSTRUCTIONS_KEY)
      } catch {
        // ignore
      }
    })
  }, [settings, queryClient])

  const autoMutation = useMutation({
    mutationFn: (value) => api.unibox.updateAgentSettings({ auto_draft: value }),
    onSuccess: (response) => queryClient.setQueryData(['agent-settings'], response.data),
  })

  const runMutation = useMutation({
    mutationFn: () => api.unibox.runAgent(),
    onSuccess: (response) => {
      const r = response.data
      const parts = [`${r.drafted} new draft${r.drafted === 1 ? '' : 's'}`]
      if (r.already_drafted) parts.push(`${r.already_drafted} already handled`)
      if (r.skipped) parts.push(`${r.skipped} skipped (already answered)`)
      if (r.failed) parts.push(`${r.failed} failed`)
      if (r.deferred) parts.push(`${r.deferred} left for the next run`)
      toast.success(`Agent finished: ${parts.join(', ')}`, { duration: 6000 })
      queryClient.invalidateQueries({ queryKey: ['unibox-replies'] })
      if (selected) queryClient.invalidateQueries({ queryKey: threadKey })
    },
  })

  return (
    <Card padding={false} className="overflow-hidden">
      <div className="px-4 py-3 border-b border-primary-100 bg-primary-50">
        <div className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-2 font-semibold text-primary-900">
            <SparklesIcon className="h-5 w-5 text-primary-600" /> Agent
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setShowSettings((v) => !v)}
              className={clsx('p-1 rounded hover:bg-primary-100', showSettings ? 'text-primary-700' : 'text-primary-400')}
              title="Agent settings"
            >
              <Cog6ToothIcon className="h-5 w-5" />
            </button>
            {onCollapse && (
              <button
                onClick={onCollapse}
                className="p-1 rounded text-primary-400 hover:bg-primary-100 hover:text-primary-700"
                title="Hide the agent"
                aria-label="Hide the agent panel"
              >
                <ChevronUpIcon className="h-5 w-5" />
              </button>
            )}
          </div>
        </div>
        <p className="text-xs text-primary-800 mt-0.5">Triages lead replies and drafts responses. Nothing is sent without your approval.</p>
        {settings && !settings.openai_configured && (
          <p className="text-xs text-red-700 mt-1">Set OPENAI_API_KEY in backend/.env to use the agent.</p>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 divide-y lg:divide-y-0 lg:divide-x divide-gray-100">
        <div className="divide-y divide-gray-100">
        <div className="px-4 py-3 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <div>
              <p className="text-sm font-medium text-gray-900">Auto-draft new replies</p>
              <p className="text-[11px] text-gray-500">
                {settings?.auto_draft
                  ? `Checks every ${settings.auto_interval_minutes} min${settings.last_auto_run_at ? ` - last ${relativeTime(settings.last_auto_run_at)}` : ''}`
                  : 'Off - drafts only when you ask'}
              </p>
            </div>
            <Toggle
              label="Auto-draft"
              checked={Boolean(settings?.auto_draft)}
              disabled={!settings || autoMutation.isPending}
              onChange={(value) => autoMutation.mutate(value)}
            />
          </div>
          <Button variant="secondary" className="w-full" icon={ArrowPathIcon} onClick={() => runMutation.mutate()} loading={runMutation.isPending}>
            {runMutation.isPending ? 'Reading replies...' : 'Draft all new replies now'}
          </Button>
        </div>

        {showSettings && settings && (
          <div className="px-4 py-3">
            <AgentSettingsPanel settings={settings} />
          </div>
        )}
        </div>

        <div className="px-4 py-3 lg:col-span-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">This conversation</p>
          {selected ? (
            <ConversationAgent selected={selected} thread={thread} threadLoading={threadLoading} threadKey={threadKey} />
          ) : (
            <p className="text-sm text-gray-500">Select a lead below to see the agent's read and draft.</p>
          )}
        </div>
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const AGENT_OPEN_KEY = 'leadbox_agent_below_open'

function loadAgentOpen() {
  try {
    return localStorage.getItem(AGENT_OPEN_KEY) !== 'false' // open unless you've folded it away
  } catch {
    return true
  }
}

/** The agent folded down to one line above the inbox. */
function AgentBar({ onExpand, draftCount, draftHere }) {
  return (
    <button
      type="button"
      onClick={onExpand}
      aria-label="Show the agent panel"
      className="flex w-full items-center gap-3 rounded-card bg-white px-5 py-3 text-left shadow-sm hover:bg-primary-50"
    >
      <SparklesIcon className="h-5 w-5 text-primary-600" />
      <span className="font-semibold text-primary-900">Agent</span>
      <span className="text-sm text-gray-500">
        {draftCount > 0 ? `${draftCount} draft${draftCount === 1 ? '' : 's'} waiting for your approval` : 'Drafts replies for you to review'}
        {draftHere ? ' - one is ready for this conversation' : ''}
      </span>
      <span className="ml-auto inline-flex items-center gap-1 text-sm font-medium text-primary-700">
        Show <ChevronDownIcon className="h-4 w-4" />
      </span>
    </button>
  )
}

export default function UniboxPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('all') // all | drafts | <category>
  const [agentOpen, setAgentOpenState] = useState(loadAgentOpen)
  const setAgentOpen = (open) => {
    setAgentOpenState(open)
    try {
      localStorage.setItem(AGENT_OPEN_KEY, String(open))
    } catch {
      // ignore - storage disabled
    }
  }
  // replies = leads who wrote back (live from Gmail, with the agent);
  // awaiting / all = every conversation you've started, from the email log
  const [folder, setFolder] = useState('replies')

  // Selection lives in the URL so alert-email links (?inbox=&thread=) open straight to the conversation.
  const selected = useMemo(() => {
    const inbox = Number(searchParams.get('inbox'))
    const thread = searchParams.get('thread')
    return inbox && thread ? { inbox_id: inbox, thread_id: thread } : null
  }, [searchParams])
  const setSelected = (sel) => setSearchParams(sel ? { inbox: String(sel.inbox_id), thread: sel.thread_id } : {}, { replace: true })

  const { data: inboxesData } = useQuery({
    queryKey: ['inboxes'],
    queryFn: async () => (await api.inboxes.list()).data,
  })
  const hasInboxes = (inboxesData?.total ?? 0) > 0

  const repliesQuery = useQuery({
    queryKey: ['unibox-replies'],
    queryFn: async () => (await api.unibox.listReplies()).data,
    enabled: hasInboxes,
    refetchInterval: REFRESH_MS,
  })

  const conversationsQuery = useQuery({
    queryKey: ['unibox-conversations'],
    queryFn: async () => (await api.unibox.listConversations('all')).data,
    enabled: hasInboxes,
    refetchInterval: REFRESH_MS,
  })

  const threadKey = ['unibox-thread', selected?.inbox_id, selected?.thread_id]
  const threadQuery = useQuery({
    queryKey: threadKey,
    queryFn: async () => (await api.unibox.getThread(selected.inbox_id, selected.thread_id)).data,
    enabled: Boolean(selected),
  })

  const items = useMemo(() => {
    const toItem = (r) => ({
      ...r,
      key: r.message_id,
      name: r.person?.name || r.person?.email || parseFrom(r.from).name,
      company: r.person?.company_name,
      fromEmail: r.person?.email,
    })
    if (folder === 'replies') return (repliesQuery.data?.replies || []).map(toItem)
    const conversations = conversationsQuery.data?.conversations || []
    return (folder === 'awaiting' ? conversations.filter((c) => c.state === 'awaiting') : conversations).map(toItem)
  }, [folder, repliesQuery.data, conversationsQuery.data])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    let list = items
    if (filter === 'drafts') list = list.filter((i) => i.agent?.status === 'pending' && i.agent.draft_body)
    else if (filter !== 'all') list = list.filter((i) => i.agent?.category === filter)
    if (!q) return list
    return list.filter((i) =>
      [i.name, i.company, i.subject, i.snippet, i.fromEmail, i.campaign?.name]
        .filter(Boolean)
        .some((v) => v.toLowerCase().includes(q))
    )
  }, [items, search, filter])

  const draftCount = (repliesQuery.data?.replies || []).filter((r) => r.agent?.status === 'pending' && r.agent.draft_body).length
  const interestedCount = (repliesQuery.data?.replies || []).filter((r) => r.agent?.category === 'interested').length

  const { data: metrics } = useQuery({
    queryKey: ['analytics-dashboard'],
    queryFn: async () => (await api.analytics.dashboard()).data,
    enabled: hasInboxes,
  })
  const selectedItem =
    selected &&
    [...items, ...(conversationsQuery.data?.conversations || [])].find(
      (i) => i.inbox_id === selected.inbox_id && i.thread_id === selected.thread_id
    )
  const activeQuery = folder === 'replies' ? repliesQuery : conversationsQuery

  // Start where the work is: with no replies yet, open on the leads awaiting a follow-up
  const folderChosen = useRef(false)
  useEffect(() => {
    if (folderChosen.current || !repliesQuery.data || !conversationsQuery.data) return
    folderChosen.current = true
    if (repliesQuery.data.total === 0 && conversationsQuery.data.counts?.awaiting > 0) setFolder('awaiting')
  }, [repliesQuery.data, conversationsQuery.data])

  // A conversation opened by link (?inbox=&thread=) that isn't in this folder - show its folder
  useEffect(() => {
    if (!selected || !conversationsQuery.data) return
    const inList = items.some((i) => i.inbox_id === selected.inbox_id && i.thread_id === selected.thread_id)
    if (inList) return
    const conversation = conversationsQuery.data.conversations.find(
      (c) => c.inbox_id === selected.inbox_id && c.thread_id === selected.thread_id
    )
    if (conversation) {
      folderChosen.current = true
      setFolder(conversation.state === 'awaiting' ? 'awaiting' : 'all')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.inbox_id, selected?.thread_id, conversationsQuery.data])
  const folderCounts = {
    replies: repliesQuery.data?.total,
    awaiting: conversationsQuery.data?.counts?.awaiting,
    all: conversationsQuery.data?.counts?.all,
  }

  useEffect(() => {
    if (repliesQuery.data?.newly_recorded) {
      toast.success(`${repliesQuery.data.newly_recorded} new lead repl${repliesQuery.data.newly_recorded === 1 ? 'y' : 'ies'} - their follow-ups were stopped`)
    }
  }, [repliesQuery.data])

  const handleConnect = async () => {
    try {
      const response = await api.inboxes.initiateOAuth()
      if (response.data.auth_url) {
        window.location.href = response.data.auth_url
      } else {
        toast.error('Gmail OAuth not configured')
      }
    } catch {
      toast.error('Failed to initiate OAuth')
    }
  }

  if (!hasInboxes) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-medium tracking-tight text-gray-900">Lead Box</h1>
        <Card>
          <EmptyState
            icon={InboxStackIcon}
            title="No inboxes connected"
            description="Connect a Google account to see your leads' replies here"
            action={
              <Button icon={PlusIcon} onClick={handleConnect}>
                Connect Google Account
              </Button>
            }
          />
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-medium tracking-tight text-gray-900">Lead Box</h1>
          <p className="mt-1 text-sm text-gray-500">
            Every conversation with your leads in one inbox - read replies, and follow up by hand with anyone who hasn't answered
          </p>
        </div>
        <Button
          variant="secondary"
          icon={ArrowPathIcon}
          onClick={() => {
            repliesQuery.refetch()
            conversationsQuery.refetch()
          }}
          loading={repliesQuery.isFetching || conversationsQuery.isFetching}
        >
          Refresh
        </Button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <StatCard
          icon={ChatBubbleLeftRightIcon}
          label="Lead replies"
          value={repliesQuery.data ? repliesQuery.data.total : '-'}
          caption="Conversations in the last 30 days"
        />
        <StatCard
          icon={PencilSquareIcon}
          label="Drafts waiting"
          value={repliesQuery.data ? draftCount : '-'}
          caption="Agent replies ready for your approval"
        />
        <StatCard
          icon={HandThumbUpIcon}
          label="Interested"
          value={repliesQuery.data ? interestedCount : '-'}
          caption="Leads the agent marked as interested"
        />
        <StatCard
          icon={ArrowTrendingUpIcon}
          label="Reply rate"
          value={metrics ? `${metrics.seven_days?.reply_rate ?? 0}%` : '-'}
          caption={metrics ? `${metrics.seven_days?.replies ?? 0} replies to ${metrics.seven_days?.emails_sent ?? 0} emails, last 7 days` : 'Last 7 days'}
        />
      </div>

      <InboxErrors errors={repliesQuery.data?.inbox_errors} />

      {/* Above the inbox: the agent */}
      {agentOpen ? (
        <AgentPanel
          selected={selected}
          thread={threadQuery.data}
          threadLoading={threadQuery.isLoading}
          threadKey={threadKey}
          onCollapse={() => setAgentOpen(false)}
        />
      ) : (
        <AgentBar
          onExpand={() => setAgentOpen(true)}
          draftCount={draftCount}
          draftHere={threadQuery.data?.agent?.status === 'pending' && Boolean(threadQuery.data?.agent?.draft_body)}
        />
      )}

      <div className="flex flex-col lg:flex-row gap-4 items-stretch lg:items-start">
        {/* Left: leads */}
        <Card padding={false} className="w-full lg:w-[340px] lg:shrink-0 overflow-hidden">
          <div className="p-3 space-y-2 border-b border-gray-200">
            <div className="grid grid-cols-3 gap-1 rounded-xl bg-canvas p-1" role="tablist" aria-label="Folders">
              {[
                ['replies', 'Replies'],
                ['awaiting', 'Awaiting'],
                ['all', 'All sent'],
              ].map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={folder === key}
                  onClick={() => {
                    setFolder(key)
                    setFilter('all')
                  }}
                  className={clsx(
                    'rounded-lg px-2 py-1.5 text-xs font-medium transition-colors',
                    folder === key ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-800'
                  )}
                >
                  {label}
                  {folderCounts[key] !== undefined && <span className="ml-1 text-gray-400">{folderCounts[key]}</span>}
                </button>
              ))}
            </div>
            <div className="relative">
              <MagnifyingGlassIcon className="h-4 w-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search..."
                className="w-full pl-9 pr-3 py-1.5 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              />
            </div>
            {folder === 'replies' && (
            <select value={filter} onChange={(e) => setFilter(e.target.value)} className="w-full px-2 py-1.5 border border-gray-200 rounded-xl text-xs">
              <option value="all">All conversations</option>
              <option value="drafts">Drafts ready ({draftCount})</option>
              {Object.entries(CATEGORIES).map(([key, meta]) => (
                <option key={key} value={key}>{meta.label}</option>
              ))}
            </select>
            )}
          </div>
          {activeQuery.isLoading ? (
            <div className="flex justify-center py-10">
              <LoadingSpinner />
            </div>
          ) : filtered.length === 0 ? (
            <p className="p-4 text-sm text-gray-500">
              {search || filter !== 'all'
                ? 'No matches.'
                : folder === 'replies'
                ? 'No lead replies yet. When a prospect writes back (last 30 days), it shows up here.'
                : folder === 'awaiting'
                ? "Nobody's waiting on a follow-up - every lead you've emailed has replied."
                : "You haven't emailed any leads yet (last 90 days)."}
            </p>
          ) : (
            <ConversationList items={filtered} selected={selected} onSelect={setSelected} />
          )}
        </Card>

        {/* Middle: conversation */}
        <Card className="min-w-0 flex-1">
          {selected ? (
            <ThreadView
              selected={selected}
              thread={threadQuery.data}
              isLoading={threadQuery.isLoading}
              item={selectedItem}
              threadKey={threadKey}
            />
          ) : (
            <EmptyState
              icon={InboxStackIcon}
              title="Select a conversation"
              description={folder === 'awaiting' ? 'Pick a lead on the left to read what you sent and write a follow-up' : 'Pick a lead on the left to read the thread'}
            />
          )}
        </Card>

        {/* Right: agent */}
      </div>

    </div>
  )
}
