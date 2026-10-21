import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import {
  PencilSquareIcon,
  PlayIcon,
  PauseIcon,
  ArrowUpTrayIcon,
  ExclamationTriangleIcon,
  UserGroupIcon,
  PaperAirplaneIcon,
  ChatBubbleLeftRightIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  MinusIcon,
  TrashIcon,
} from '@heroicons/react/24/outline'
import { clsx } from 'clsx'
import { api } from '../services/apiClient'
import Button from '../components/common/Button'
import Card from '../components/common/Card'
import StatCard from '../components/common/StatCard'
import StatusBadge from '../components/common/StatusBadge'
import LoadingSpinner from '../components/common/LoadingSpinner'
import toast from 'react-hot-toast'
import { allTimezones, windowInLocalTime } from '../utils/time'
import SendingState from '../components/common/SendingState'
import ConfirmDialog from '../components/common/ConfirmDialog'

const ALL_PROSPECTS = 'all'

function describeAddResult(data) {
  const skipped = data.skipped || {}
  const parts = []
  if (skipped.already_in_campaign) parts.push(`${skipped.already_in_campaign} already in campaign`)
  if (skipped.uncontactable) parts.push(`${skipped.uncontactable} unsubscribed/bounced/do-not-contact`)
  if (skipped.not_found) parts.push(`${skipped.not_found} not found`)
  return `Added ${data.added} lead${data.added === 1 ? '' : 's'}` + (parts.length ? ` (skipped ${parts.join(', ')})` : '')
}

function RecipientsCard({ campaignId }) {
  const queryClient = useQueryClient()
  const [source, setSource] = useState('list') // list | upload
  const [listId, setListId] = useState('')
  const [file, setFile] = useState(null)
  const fileInputRef = useRef(null)

  const { data: listsData } = useQuery({
    queryKey: ['leadLists'],
    queryFn: async () => (await api.leads.listLists()).data,
  })
  const lists = listsData?.lists || []

  const totalProspects = listsData?.total_prospects || 0

  // Default to the newest list; prospects imported before lists existed belong to none, so fall back to "all".
  useEffect(() => {
    if (listId) return
    if (lists.length) setListId(String(lists[0].id))
    else if (totalProspects > 0) setListId(ALL_PROSPECTS)
  }, [lists, listId, totalProspects])

  const onAdded = (data) => {
    toast.success(describeAddResult(data))
    queryClient.invalidateQueries({ queryKey: ['campaign', campaignId] })
    queryClient.invalidateQueries({ queryKey: ['campaignLeads', campaignId] })
    queryClient.invalidateQueries({ queryKey: ['leadLists'] })
  }

  const addListMutation = useMutation({
    mutationFn: (id) => api.campaigns.addLeadList(campaignId, id),
    onSuccess: (response) => onAdded(response.data),
  })

  const uploadMutation = useMutation({
    mutationFn: (selectedFile) => {
      const formData = new FormData()
      formData.append('file', selectedFile)
      return api.campaigns.uploadLeads(campaignId, formData)
    },
    onSuccess: (response) => {
      onAdded(response.data)
      setFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
    },
  })

  const handleFileSelect = (e) => {
    const selected = e.target.files?.[0]
    if (!selected) return
    if (!/\.(csv|tsv|txt)$/i.test(selected.name)) {
      toast.error('Please select a CSV file')
      return
    }
    setFile(selected)
  }

  const handleAdd = () => {
    if (source === 'upload') {
      if (file) uploadMutation.mutate(file)
    } else if (listId) {
      addListMutation.mutate(listId === ALL_PROSPECTS ? null : parseInt(listId))
    }
  }

  const canAdd = source === 'upload' ? Boolean(file) : Boolean(listId)

  return (
    <Card>
      <Card.Header>
        <Card.Title>Recipients</Card.Title>
        <Card.Description>Choose which uploaded lead list this campaign emails</Card.Description>
      </Card.Header>

      <div className="space-y-4">
        <div className="flex gap-4 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="recipient-source"
              checked={source === 'list'}
              onChange={() => setSource('list')}
              className="h-4 w-4 text-primary-600 border-gray-300 focus:ring-primary-500"
            />
            Use an uploaded list
          </label>
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="recipient-source"
              checked={source === 'upload'}
              onChange={() => setSource('upload')}
              className="h-4 w-4 text-primary-600 border-gray-300 focus:ring-primary-500"
            />
            Upload a new CSV
          </label>
        </div>

        {source === 'list' ? (
          <select
            value={listId}
            onChange={(e) => setListId(e.target.value)}
            className="w-full px-3 py-2 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
          >
            {lists.length === 0 && totalProspects === 0 && <option value="">No prospects yet - upload a CSV</option>}
            {totalProspects > 0 && <option value={ALL_PROSPECTS}>All prospects ({totalProspects})</option>}
            {lists.map((list) => (
              <option key={list.id} value={list.id}>
                {list.name} ({list.lead_count} lead{list.lead_count === 1 ? '' : 's'},{' '}
                {new Date(list.created_at).toLocaleDateString()})
              </option>
            ))}
          </select>
        ) : (
          <div
            onClick={() => fileInputRef.current?.click()}
            className="border-2 border-dashed border-gray-200 rounded-xl p-4 text-center cursor-pointer hover:border-primary-500 transition-colors"
          >
            <input ref={fileInputRef} type="file" accept=".csv,.tsv,.txt,text/csv" onChange={handleFileSelect} className="hidden" />
            {file ? (
              <p className="text-sm font-medium text-gray-900">{file.name}</p>
            ) : (
              <>
                <ArrowUpTrayIcon className="h-6 w-6 mx-auto text-gray-400" />
                <p className="mt-1 text-sm text-gray-600">Click to select a CSV (needs an email column)</p>
                <p className="text-xs text-gray-400">It's also saved to Prospects as a list you can reuse</p>
              </>
            )}
          </div>
        )}

        {source === 'list' && lists.length === 0 && totalProspects > 0 && (
          <p className="text-xs text-gray-500">
            Your existing prospects were imported before lists were tracked, so they aren't in a named list. CSVs
            uploaded from now on each appear here as their own list.
          </p>
        )}

        <Button
          onClick={handleAdd}
          disabled={!canAdd}
          loading={addListMutation.isPending || uploadMutation.isPending}
        >
          Add to campaign
        </Button>
      </div>
    </Card>
  )
}

function InboxesCard({ campaign }) {
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState([])

  const { data: inboxesData } = useQuery({
    queryKey: ['inboxes'],
    queryFn: async () => (await api.inboxes.list()).data,
  })
  const inboxes = inboxesData?.inboxes || []

  const savedIds = JSON.stringify(campaign.inbox_ids || [])
  useEffect(() => {
    setSelected(JSON.parse(savedIds))
  }, [savedIds])

  const saveMutation = useMutation({
    mutationFn: (ids) => api.campaigns.assignInboxes(campaign.id, ids),
    onSuccess: () => {
      toast.success('Sending inboxes saved')
      queryClient.invalidateQueries({ queryKey: ['campaign', String(campaign.id)] })
    },
  })

  const toggle = (id) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))

  const changed =
    selected.length !== (campaign.inbox_ids || []).length ||
    selected.some((id) => !(campaign.inbox_ids || []).includes(id))

  return (
    <Card>
      <Card.Header>
        <Card.Title>Sending inboxes</Card.Title>
        <Card.Description>Emails rotate across the selected inboxes, within each inbox's daily limit</Card.Description>
      </Card.Header>

      {inboxes.length === 0 ? (
        <p className="text-sm text-gray-500">
          No inboxes connected yet. <Link to="/inboxes" className="text-primary-600 hover:underline">Connect one</Link>
        </p>
      ) : (
        <div className="space-y-2">
          {inboxes.map((inbox) => (
            <label key={inbox.id} className="flex items-center justify-between gap-3 text-sm">
              <span className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={selected.includes(inbox.id)}
                  onChange={() => toggle(inbox.id)}
                  disabled={!inbox.is_active}
                  className="h-4 w-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500"
                />
                <span className={inbox.is_active ? 'text-gray-900' : 'text-gray-400'}>{inbox.email_address}</span>
              </span>
              <span className="text-xs text-gray-500">
                {inbox.emails_sent_today}/{inbox.daily_limit} today
              </span>
            </label>
          ))}
          <div className="pt-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => saveMutation.mutate(selected)}
              disabled={!changed}
              loading={saveMutation.isPending}
            >
              Save inboxes
            </Button>
          </div>
        </div>
      )}
    </Card>
  )
}

const LEADS_PER_PAGE = 30

/**
 * The page title is the rename field: click it and type. Enter or clicking
 * away saves, Escape puts the old name back.
 */
function CampaignName({ campaign }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(campaign.name)
  const inputRef = useRef(null)
  const cancelledRef = useRef(false)

  // Pick up the saved name (or a rename from the settings card) unless mid-edit
  useEffect(() => {
    if (document.activeElement !== inputRef.current) setName(campaign.name)
  }, [campaign.name])

  const renameMutation = useMutation({
    mutationFn: (newName) => api.campaigns.update(campaign.id, { name: newName }),
    onSuccess: (_response, newName) => {
      toast.success(`Renamed to "${newName}"`)
      queryClient.invalidateQueries({ queryKey: ['campaign', String(campaign.id)] })
      queryClient.invalidateQueries({ queryKey: ['campaign', campaign.id] })
      queryClient.invalidateQueries({ queryKey: ['campaigns'] })
    },
    onError: () => setName(campaign.name),
  })

  const save = () => {
    if (cancelledRef.current) {
      cancelledRef.current = false
      return
    }
    const trimmed = name.trim()
    if (!trimmed) {
      toast.error("Campaign name can't be empty")
      setName(campaign.name)
      return
    }
    if (trimmed !== name) setName(trimmed)
    if (trimmed !== campaign.name) renameMutation.mutate(trimmed)
  }

  return (
    <input
      ref={inputRef}
      value={name}
      onChange={(e) => setName(e.target.value)}
      onBlur={save}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur()
        if (e.key === 'Escape') {
          cancelledRef.current = true
          setName(campaign.name)
          e.currentTarget.blur()
        }
      }}
      maxLength={255}
      size={Math.max(8, name.length + 1)}
      aria-label="Campaign name - click to rename"
      title="Click to rename"
      disabled={renameMutation.isPending}
      className="-ml-2 max-w-full rounded-xl border border-transparent bg-transparent px-2 py-0.5 text-3xl font-medium tracking-tight text-gray-900 hover:border-gray-200 focus:border-primary-500 focus:bg-white focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-70"
    />
  )
}

function LeadsTable({ campaignId, campaignStatus }) {
  const queryClient = useQueryClient()
  const [page, setPage] = useState(0)
  const [confirmRemoveAll, setConfirmRemoveAll] = useState(false)

  const removeAllMutation = useMutation({
    mutationFn: () => api.campaigns.removeAllLeads(campaignId),
    onSuccess: (response) => {
      toast.success(`Removed all ${response.data.removed} leads from the campaign`)
      setConfirmRemoveAll(false)
      setPage(0)
      queryClient.invalidateQueries({ queryKey: ['campaignLeads', campaignId] })
      queryClient.invalidateQueries({ queryKey: ['campaign', campaignId] })
      queryClient.invalidateQueries({ queryKey: ['campaigns'] })
      queryClient.invalidateQueries({ queryKey: ['people'] })
    },
  })

  const removeMutation = useMutation({
    mutationFn: (personId) => api.campaigns.removeLeads(campaignId, [personId]),
    onSuccess: () => {
      toast.success('Removed from campaign')
      queryClient.invalidateQueries({ queryKey: ['campaignLeads', campaignId] })
      queryClient.invalidateQueries({ queryKey: ['campaign', campaignId] })
      queryClient.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })

  const removeLead = (lead) => {
    const who = lead.name ? `${lead.name} (${lead.email})` : lead.email
    if (confirm(`Remove ${who} from this campaign? They won't get any further emails from it.`)) {
      removeMutation.mutate(lead.person_id)
    }
  }
  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['campaignLeads', campaignId, page],
    queryFn: async () =>
      (await api.campaigns.getLeads(campaignId, { skip: page * LEADS_PER_PAGE, limit: LEADS_PER_PAGE })).data,
    placeholderData: keepPreviousData,
  })

  const total = data?.total || 0
  const pageCount = Math.max(1, Math.ceil(total / LEADS_PER_PAGE))

  // If leads were removed and this page no longer exists, step back to the last one.
  useEffect(() => {
    if (page > 0 && page >= pageCount) setPage(pageCount - 1)
  }, [page, pageCount])

  if (isLoading) return null
  const leads = data?.leads || []
  const first = total ? page * LEADS_PER_PAGE + 1 : 0
  const last = page * LEADS_PER_PAGE + leads.length

  return (
    <Card>
      <Card.Header>
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Card.Title>Leads</Card.Title>
            {total > 0 && (
              <button
                type="button"
                onClick={() => setConfirmRemoveAll(true)}
                className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 px-3 py-1 text-xs text-gray-600 hover:border-red-200 hover:bg-red-50 hover:text-red-700"
              >
                <TrashIcon className="h-3.5 w-3.5" />
                Remove all ({total})
              </button>
            )}
          </div>
          <ConfirmDialog
            open={confirmRemoveAll}
            title={`Remove all ${total} leads from this campaign?`}
            confirmLabel={`Remove all ${total}`}
            loading={removeAllMutation.isPending}
            onConfirm={() => removeAllMutation.mutate()}
            onCancel={() => setConfirmRemoveAll(false)}
          >
            <p>
              Are you sure?{' '}
              {campaignStatus === 'active'
                ? "The campaign is sending right now - they won't get any further emails from it."
                : "They won't get any further emails from this campaign."}
            </p>
            <p className="text-gray-500">
              The prospects stay in Prospects, and emails already sent stay in your history. You can add them back later,
              but they'd start the sequence from the beginning.
            </p>
          </ConfirmDialog>
          {total > 0 && (
            <div className="flex items-center gap-3 text-sm text-gray-500">
              <span>
                {first}-{last} of {total}
              </span>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0 || isFetching}
                  aria-label="Previous page"
                  className="h-8 w-8 rounded-full border border-gray-200 bg-white flex items-center justify-center text-gray-600 hover:border-primary-500 hover:text-primary-600 disabled:opacity-40 disabled:hover:border-gray-200 disabled:hover:text-gray-600"
                >
                  <ChevronLeftIcon className="h-4 w-4" />
                </button>
                <span className="px-2 text-xs text-gray-500">
                  Page {page + 1} of {pageCount}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                  disabled={page >= pageCount - 1 || isFetching}
                  aria-label="Next page"
                  className="h-8 w-8 rounded-full border border-gray-200 bg-white flex items-center justify-center text-gray-600 hover:border-primary-500 hover:text-primary-600 disabled:opacity-40 disabled:hover:border-gray-200 disabled:hover:text-gray-600"
                >
                  <ChevronRightIcon className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}
        </div>
      </Card.Header>
      {leads.length === 0 ? (
        <p className="text-sm text-gray-500">No leads yet - add a lead list above.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b">
                <th className="py-2 pr-4 font-medium">Email</th>
                <th className="py-2 pr-4 font-medium">Name</th>
                <th className="py-2 pr-4 font-medium">Company</th>
                <th className="py-2 pr-4 font-medium">Status</th>
                <th className="py-2 pr-4 font-medium">Emails sent</th>
                <th className="py-2 pr-4 font-medium">Next send</th>
                <th className="py-2 w-10"><span className="sr-only">Remove</span></th>
              </tr>
            </thead>
            <tbody>
              {leads.map((lead) => (
                <tr key={lead.id} className="border-b last:border-0">
                  <td className="py-2 pr-4 text-gray-900">{lead.email}</td>
                  <td className="py-2 pr-4 text-gray-600">{lead.name || '-'}</td>
                  <td className="py-2 pr-4 text-gray-600">{lead.company_name || '-'}</td>
                  <td className="py-2 pr-4 text-gray-600">
                    {lead.status.replaceAll('_', ' ')}
                    {lead.stop_reason && <span className="text-gray-400"> ({lead.stop_reason.replaceAll('_', ' ')})</span>}
                  </td>
                  <td className="py-2 pr-4 text-gray-600">{lead.current_step}</td>
                  <td className="py-2 pr-4 text-gray-600">
                    {lead.next_send_at ? new Date(lead.next_send_at + 'Z').toLocaleString() : '-'}
                  </td>
                  <td className="py-2 text-right">
                    <button
                      onClick={() => removeLead(lead)}
                      disabled={removeMutation.isPending && removeMutation.variables === lead.person_id}
                      title="Remove from campaign"
                      aria-label={`Remove ${lead.email} from campaign`}
                      className="h-7 w-7 rounded-full border border-gray-200 bg-white inline-flex items-center justify-center text-gray-400 hover:border-red-300 hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
                    >
                      <MinusIcon className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

const inputClass =
  'w-full px-3 py-2 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500'

// Shows a sequence step exactly as a real lead would receive it (before any GPT rewrite).
function PreviewCard({ campaign }) {
  const [step, setStep] = useState(0)
  const [leadIndex, setLeadIndex] = useState(0)
  const stepCount = campaign.step_count || 0

  const { data: leadsData } = useQuery({
    queryKey: ['campaignLeads', String(campaign.id), 'preview'],
    queryFn: async () => (await api.campaigns.getLeads(campaign.id, { limit: 50 })).data,
    enabled: stepCount > 0,
  })
  const leads = leadsData?.leads || []
  const lead = leads.length ? leads[leadIndex % leads.length] : null

  const { data: preview, isFetching, error } = useQuery({
    queryKey: ['campaignPreview', campaign.id, step, lead?.person_id],
    queryFn: async () => (await api.campaigns.preview(campaign.id, { step, person_id: lead.person_id })).data,
    enabled: Boolean(lead) && stepCount > 0,
    retry: false,
  })

  if (!stepCount) return null

  return (
    <Card>
      <Card.Header>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <Card.Title>Email preview</Card.Title>
            <Card.Description>A step rendered for one of this campaign's leads, exactly as it will be sent</Card.Description>
          </div>
          <div className="flex items-center gap-2">
            {stepCount > 1 && (
              <select value={step} onChange={(e) => setStep(Number(e.target.value))} className="px-3 py-1.5 border border-gray-200 rounded-full text-sm">
                {Array.from({ length: stepCount }, (_, i) => (
                  <option key={i} value={i}>
                    {i === 0 ? 'First email' : `Follow-up ${i}`}
                  </option>
                ))}
              </select>
            )}
            {leads.length > 1 && (
              <Button variant="secondary" size="sm" onClick={() => setLeadIndex((i) => i + 1)}>
                Another lead
              </Button>
            )}
          </div>
        </div>
      </Card.Header>

      {!lead ? (
        <p className="text-sm text-gray-500">Add leads to preview the emails they'll get.</p>
      ) : error ? (
        <p className="text-sm text-red-700">Couldn't render this step for {lead.email}.</p>
      ) : !preview ? (
        <div className="flex justify-center py-6">
          <LoadingSpinner />
        </div>
      ) : (
        <div className={clsx('rounded-2xl border border-gray-100 bg-canvas p-4 space-y-2 text-sm', isFetching && 'opacity-60')}>
          <p className="text-xs text-gray-500">
            To <span className="text-gray-800">{preview.to_email}</span>
            {preview.from_email && (
              <>
                {' '}from <span className="text-gray-800">{preview.from_email}</span>
              </>
            )}
          </p>
          <p className="font-medium text-gray-900">{preview.subject}</p>
          <p className="whitespace-pre-wrap text-gray-800">{preview.body}</p>
          {preview.missing_variables?.length > 0 && (
            <p className="text-xs text-amber-700">
              This lead has no value for {preview.missing_variables.map((v) => `{{${v}}}`).join(', ')} - they'll be skipped.
              Add a fallback like {'{{first_name|there}}'} to the sequence to include them.
            </p>
          )}
          {preview.use_gpt && <p className="text-xs text-primary-700">This step is rewritten per lead by GPT when it's sent.</p>}
        </div>
      )}
    </Card>
  )
}

function settingsFrom(campaign) {
  return {
    name: campaign.name || '',
    description: campaign.description || '',
    sequence_id: campaign.sequence_id || '',
    send_start_time: campaign.send_start_time || '09:00',
    send_end_time: campaign.send_end_time || '17:00',
    timezone: campaign.timezone || 'America/New_York',
    send_on_weekends: Boolean(campaign.send_on_weekends),
    stop_on_reply: campaign.stop_on_reply !== false,
    min_gap_minutes: campaign.min_gap_minutes ?? 2,
    max_gap_minutes: campaign.max_gap_minutes ?? 5,
  }
}

function paceLabel(low, high) {
  if (!high) return 'No pause - as fast as inbox limits allow'
  return low === high ? `One email every ${high} min` : `One email every ${low}-${high} min (random)`
}

function SettingsCard({ campaign }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState(() => settingsFrom(campaign))

  const { data: sequencesData } = useQuery({
    queryKey: ['sequences'],
    queryFn: async () => (await api.sequences.list()).data,
    enabled: editing,
  })
  const sequences = sequencesData?.sequences || []

  const saveMutation = useMutation({
    mutationFn: (data) => api.campaigns.update(campaign.id, data),
    onSuccess: () => {
      toast.success('Campaign settings saved')
      setEditing(false)
      queryClient.invalidateQueries({ queryKey: ['campaign', String(campaign.id)] })
      queryClient.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })

  const startEditing = () => {
    setForm(settingsFrom(campaign))
    setEditing(true)
  }

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target
    setForm((prev) => ({ ...prev, [name]: type === 'checkbox' ? checked : value }))
  }

  const handleSave = () => {
    if (!form.name.trim()) {
      toast.error('Please enter a campaign name')
      return
    }
    const minGap = parseInt(form.min_gap_minutes, 10)
    const maxGap = parseInt(form.max_gap_minutes, 10)
    if ([minGap, maxGap].some((n) => Number.isNaN(n) || n < 0 || n > 240)) {
      toast.error('Pause between emails must be 0-240 minutes')
      return
    }
    if (minGap > maxGap) {
      toast.error('The minimum pause can\'t be longer than the maximum')
      return
    }
    saveMutation.mutate({
      ...form,
      name: form.name.trim(),
      description: form.description.trim(),
      sequence_id: form.sequence_id ? parseInt(form.sequence_id) : null,
      min_gap_minutes: minGap,
      max_gap_minutes: maxGap,
    })
  }

  const isActive = campaign.status === 'active'

  return (
    <Card>
      <Card.Header>
        <div className="flex items-center justify-between">
          <Card.Title>Campaign Settings</Card.Title>
          {!editing && (
            <Button variant="ghost" size="sm" icon={PencilSquareIcon} onClick={startEditing}>
              Edit
            </Button>
          )}
        </div>
      </Card.Header>

      {editing ? (
        <div className="space-y-4 text-sm">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block font-medium text-gray-700 mb-1">Campaign name *</label>
              <input type="text" name="name" value={form.name} onChange={handleChange} className={inputClass} />
            </div>
            <div>
              <label className="block font-medium text-gray-700 mb-1">Email sequence</label>
              <select
                name="sequence_id"
                value={form.sequence_id}
                onChange={handleChange}
                disabled={isActive}
                className={inputClass}
              >
                <option value="">Select a sequence...</option>
                {sequences.map((seq) => (
                  <option key={seq.id} value={seq.id}>
                    {seq.name} ({seq.step_count} steps)
                  </option>
                ))}
              </select>
              {isActive && <p className="mt-1 text-xs text-gray-500">Pause the campaign to change its sequence</p>}
            </div>
          </div>

          <div>
            <label className="block font-medium text-gray-700 mb-1">Description</label>
            <textarea name="description" value={form.description} onChange={handleChange} rows={2} className={inputClass} />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block font-medium text-gray-700 mb-1">Start time</label>
              <input type="time" name="send_start_time" value={form.send_start_time} onChange={handleChange} className={inputClass} />
            </div>
            <div>
              <label className="block font-medium text-gray-700 mb-1">End time</label>
              <input type="time" name="send_end_time" value={form.send_end_time} onChange={handleChange} className={inputClass} />
            </div>
            <div>
              <label className="block font-medium text-gray-700 mb-1">Timezone</label>
              <select name="timezone" value={form.timezone} onChange={handleChange} className={inputClass}>
                {allTimezones([form.timezone]).map((tz) => (
                  <option key={tz} value={tz}>
                    {tz.replaceAll('_', ' ')}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {windowInLocalTime(form.send_start_time, form.send_end_time, form.timezone) && (
            <p className="-mt-2 text-xs text-gray-500">
              That's {windowInLocalTime(form.send_start_time, form.send_end_time, form.timezone)}.
            </p>
          )}

          <div>
            <label className="block font-medium text-gray-700 mb-1">Pause between emails</label>
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="number"
                name="min_gap_minutes"
                min={0}
                max={240}
                value={form.min_gap_minutes}
                onChange={handleChange}
                className="w-24 px-3 py-2 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              />
              <span className="text-gray-500">to</span>
              <input
                type="number"
                name="max_gap_minutes"
                min={0}
                max={240}
                value={form.max_gap_minutes}
                onChange={handleChange}
                className="w-24 px-3 py-2 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              />
              <span className="text-gray-500">minutes</span>
            </div>
            <p className="mt-1 text-xs text-gray-500">
              The campaign sends one email, then waits a random time in this range before the next - so emails go out in
              breaks instead of all at once. Set both to 0 for no pause.
            </p>
          </div>

          <div className="flex flex-wrap gap-6">
            <label className="flex items-center gap-2 text-gray-700">
              <input
                type="checkbox"
                name="send_on_weekends"
                checked={form.send_on_weekends}
                onChange={handleChange}
                className="h-4 w-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500"
              />
              Send emails on weekends
            </label>
            <label className="flex items-center gap-2 text-gray-700">
              <input
                type="checkbox"
                name="stop_on_reply"
                checked={form.stop_on_reply}
                onChange={handleChange}
                className="h-4 w-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500"
              />
              Stop sequence when lead replies
            </label>
          </div>

          <div className="flex justify-end gap-3 pt-2 border-t">
            <Button variant="secondary" onClick={() => setEditing(false)}>
              Cancel
            </Button>
            <Button onClick={handleSave} loading={saveMutation.isPending}>
              Save changes
            </Button>
          </div>
        </div>
      ) : (
        <dl className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <dt className="text-gray-500">Sequence</dt>
            <dd className="font-medium text-gray-900">
              {campaign.sequence_id ? (
                <Link to={`/sequences/${campaign.sequence_id}`} className="hover:text-primary-600">
                  {campaign.sequence_name} ({campaign.step_count} step{campaign.step_count === 1 ? '' : 's'})
                </Link>
              ) : (
                'None'
              )}
            </dd>
          </div>
          <div>
            <dt className="text-gray-500">Schedule</dt>
            <dd className="font-medium text-gray-900">
              {campaign.send_start_time} - {campaign.send_end_time}
              {windowInLocalTime(campaign.send_start_time, campaign.send_end_time, campaign.timezone) && (
                <span className="block text-xs font-normal text-gray-500">
                  {windowInLocalTime(campaign.send_start_time, campaign.send_end_time, campaign.timezone)}
                </span>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-gray-500">Timezone</dt>
            <dd className="font-medium text-gray-900">{campaign.timezone}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Stop on Reply</dt>
            <dd className="font-medium text-gray-900">{campaign.stop_on_reply ? 'Yes' : 'No'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Send on Weekends</dt>
            <dd className="font-medium text-gray-900">{campaign.send_on_weekends ? 'Yes' : 'No'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Sending pace</dt>
            <dd className="font-medium text-gray-900">
              {paceLabel(campaign.min_gap_minutes, campaign.max_gap_minutes)}
            </dd>
          </div>
        </dl>
      )}
    </Card>
  )
}

export default function CampaignDetailPage() {
  const { id } = useParams()
  const queryClient = useQueryClient()

  const { data: campaign, isLoading } = useQuery({
    queryKey: ['campaign', id],
    queryFn: async () => {
      const response = await api.campaigns.get(id)
      return response.data
    },
  })

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['campaign', id] })
    queryClient.invalidateQueries({ queryKey: ['campaigns'] })
  }

  const startMutation = useMutation({
    mutationFn: () => (campaign.status === 'paused' ? api.campaigns.resume(id) : api.campaigns.start(id)),
    onSuccess: (response) => {
      toast.success(
        response.data.in_send_window === false
          ? 'Campaign started - emails go out once the send window opens'
          : 'Campaign started - emails are going out'
      )
      refresh()
    },
  })

  const pauseMutation = useMutation({
    mutationFn: () => api.campaigns.pause(id),
    onSuccess: () => {
      toast.success('Campaign paused')
      refresh()
    },
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (!campaign) {
    return <div>Campaign not found</div>
  }

  const canStart = ['draft', 'paused', 'completed'].includes(campaign.status)
  const readinessErrors = campaign.readiness_errors || []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <CampaignName campaign={campaign} />
          <p className="mt-1 text-sm text-gray-500">{campaign.description}</p>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={campaign.status} />
          {campaign.status === 'active' && (
            <Button variant="secondary" icon={PauseIcon} onClick={() => pauseMutation.mutate()} loading={pauseMutation.isPending}>
              Pause
            </Button>
          )}
          {canStart && (
            <Button
              variant="primary"
              icon={PlayIcon}
              onClick={() => startMutation.mutate()}
              loading={startMutation.isPending}
              disabled={readinessErrors.length > 0}
            >
              {campaign.status === 'paused' ? 'Resume' : 'Start sending'}
            </Button>
          )}
        </div>
      </div>

      {campaign.status === 'active' && <SendingState sending={campaign.sending} />}

      {canStart && readinessErrors.length > 0 && (
        <div className="flex gap-3 p-4 rounded-lg bg-yellow-50 border border-yellow-200">
          <ExclamationTriangleIcon className="h-5 w-5 text-yellow-600 flex-shrink-0" />
          <div className="text-sm text-yellow-800">
            <p className="font-medium">Before this campaign can send:</p>
            <ul className="mt-1 list-disc list-inside">
              {readinessErrors.map((error) => (
                <li key={error}>{error}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <StatCard icon={UserGroupIcon} label="Total leads" value={campaign.total_leads} caption="In this campaign" />
        <StatCard icon={PaperAirplaneIcon} label="Emails sent" value={campaign.emails_sent} caption="Across all sequence steps" />
        <StatCard
          icon={ChatBubbleLeftRightIcon}
          label="Replies"
          value={campaign.replies_received}
          caption={campaign.bounces ? `${campaign.bounces} bounced` : 'Leads who wrote back'}
        />
      </div>

      {campaign.status !== 'archived' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <RecipientsCard campaignId={id} />
          <InboxesCard campaign={campaign} />
        </div>
      )}

      <PreviewCard campaign={campaign} />

      <LeadsTable campaignId={id} campaignStatus={campaign.status} />

      <SettingsCard campaign={campaign} />
    </div>
  )
}
