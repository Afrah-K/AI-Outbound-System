import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import {
  UserGroupIcon,
  ArrowUpTrayIcon,
  XMarkIcon,
  MagnifyingGlassIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  SparklesIcon,
  PaperAirplaneIcon,
  ChatBubbleLeftRightIcon,
  MegaphoneIcon,
  QueueListIcon,
  TrashIcon,
} from '@heroicons/react/24/outline'
import { clsx } from 'clsx'
import { api } from '../services/apiClient'
import Button from '../components/common/Button'
import Card from '../components/common/Card'
import StatCard from '../components/common/StatCard'
import StatusBadge from '../components/common/StatusBadge'
import LoadingSpinner from '../components/common/LoadingSpinner'
import EmptyState from '../components/common/EmptyState'
import ConfirmDialog from '../components/common/ConfirmDialog'
import toast from 'react-hot-toast'

const PER_PAGE = 30

const STATUSES = [
  ['new', 'New'],
  ['contacted', 'Contacted'],
  ['replied', 'Replied'],
  ['converted', 'Converted'],
  ['bounced', 'Bounced'],
  ['unsubscribed', 'Unsubscribed'],
  ['do_not_contact', 'Do not contact'],
]

const selectClass =
  'px-3 py-2 border border-gray-200 rounded-full bg-white text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500'

function displayName(person) {
  return person.full_name || [person.first_name, person.last_name].filter(Boolean).join(' ') || null
}

function initials(person) {
  // No name on file -> use the company's initial rather than the mailbox ("hello@", "info@").
  const name = displayName(person) || person.company_name
  if (name) return name.split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase()
  return (person.email?.[0] || '?').toUpperCase()
}

function websiteHref(person) {
  const site = person.company_website || person.company_domain
  if (!site) return null
  return site.startsWith('http') ? site : `https://${site}`
}

function useDebounced(value, delay = 300) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

function Pager({ page, pageCount, total, shown, onPage, busy }) {
  if (!total) return null
  const first = page * PER_PAGE + 1
  const last = page * PER_PAGE + shown
  const arrow =
    'h-8 w-8 rounded-full border border-gray-200 bg-white flex items-center justify-center text-gray-600 hover:border-primary-500 hover:text-primary-600 disabled:opacity-40 disabled:hover:border-gray-200 disabled:hover:text-gray-600'
  return (
    <div className="flex items-center gap-3 text-sm text-gray-500">
      <span>
        {first}-{last} of {total}
      </span>
      <div className="flex items-center gap-1">
        <button onClick={() => onPage(page - 1)} disabled={page === 0 || busy} aria-label="Previous page" className={arrow}>
          <ChevronLeftIcon className="h-4 w-4" />
        </button>
        <span className="px-2 text-xs">
          Page {page + 1} of {pageCount}
        </span>
        <button onClick={() => onPage(page + 1)} disabled={page >= pageCount - 1 || busy} aria-label="Next page" className={arrow}>
          <ChevronRightIcon className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}

function ImportModal({ onClose }) {
  const queryClient = useQueryClient()
  const [selectedFile, setSelectedFile] = useState(null)
  const [updateExisting, setUpdateExisting] = useState(true)
  const [listName, setListName] = useState('')
  const fileInputRef = useRef(null)

  const importMutation = useMutation({
    mutationFn: async () => {
      const formData = new FormData()
      formData.append('file', selectedFile)
      return api.leads.importCSV(formData, updateExisting, listName)
    },
    onSuccess: (response) => {
      const data = response.data
      const warnings = data.warnings || []
      queryClient.invalidateQueries({ queryKey: ['people'] })
      queryClient.invalidateQueries({ queryKey: ['leadLists'] })

      // Nothing usable in the file (e.g. no email column) - say why and keep
      // the dialog open so another file can be picked
      if (!data.people_in_file) {
        toast.error(warnings[0] || 'No rows with an email address were found in this file', { duration: 8000 })
        return
      }

      const messages = []
      if (data.imported_people > 0) messages.push(`${data.imported_people} new`)
      if (data.updated_people > 0) messages.push(`${data.updated_people} updated`)
      if (data.skipped > 0) messages.push(`${data.skipped} already existed`)
      if (data.imported_companies > 0) messages.push(`${data.imported_companies} companies`)
      toast.success(
        `Import complete: ${messages.join(', ') || 'nothing new'}` +
          (data.lead_list_name ? ` - saved as list "${data.lead_list_name}"` : '')
      )
      warnings.forEach((w) => toast(w, { icon: '⚠️', duration: 8000 }))
      onClose()
    },
  })

  const handleFileSelect = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!/\.(csv|tsv|txt)$/i.test(file.name)) {
      toast.error('Please select a CSV file')
      return
    }
    setSelectedFile(file)
  }

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex min-h-full items-center justify-center p-4">
        <div className="fixed inset-0 bg-gray-900/40" onClick={onClose} />
        <div className="relative bg-white rounded-card shadow-xl max-w-md w-full p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-medium tracking-tight text-gray-900">Import prospects</h3>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close">
              <XMarkIcon className="h-5 w-5" />
            </button>
          </div>

          <div className="space-y-4">
            <div>
              <p className="text-sm text-gray-600 mb-2">Upload a CSV. Expected columns:</p>
              <ul className="text-xs text-gray-500 list-disc list-inside space-y-1">
                <li><strong>email</strong> (required - "Email Address", "E-mail", "Work Email" etc. also work)</li>
                <li>first_name, last_name</li>
                <li>company, domain / website</li>
                <li>role / title</li>
                <li>linkedin, phone</li>
              </ul>
            </div>

            <div
              onClick={() => fileInputRef.current?.click()}
              className="border-2 border-dashed border-gray-200 rounded-2xl p-6 text-center cursor-pointer hover:border-primary-500 transition-colors"
            >
              <input ref={fileInputRef} type="file" accept=".csv,.tsv,.txt,text/csv" onChange={handleFileSelect} className="hidden" />
              {selectedFile ? (
                <div>
                  <p className="text-sm font-medium text-gray-900">{selectedFile.name}</p>
                  <p className="text-xs text-gray-500 mt-1">{(selectedFile.size / 1024).toFixed(1)} KB</p>
                </div>
              ) : (
                <div>
                  <ArrowUpTrayIcon className="h-8 w-8 mx-auto text-primary-500" />
                  <p className="mt-2 text-sm text-gray-600">Click to select a CSV file</p>
                </div>
              )}
            </div>

            <div>
              <label htmlFor="listName" className="block text-sm font-medium text-gray-700 mb-1">
                List name <span className="font-normal text-gray-400">(optional)</span>
              </label>
              <input
                id="listName"
                type="text"
                value={listName}
                onChange={(e) => setListName(e.target.value)}
                placeholder={selectedFile?.name || 'Defaults to the file name'}
                className="w-full px-3 py-2 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              />
              <p className="mt-1 text-xs text-gray-500">Pick this list on a campaign's page to email everyone in it</p>
            </div>

            <label className="flex items-center gap-2 p-3 bg-canvas rounded-xl text-sm text-gray-700">
              <input
                type="checkbox"
                checked={updateExisting}
                onChange={(e) => setUpdateExisting(e.target.checked)}
                className="h-4 w-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500"
              />
              Update existing prospects (match by email)
            </label>

            <div className="flex gap-3 pt-2">
              <Button variant="secondary" className="flex-1" onClick={onClose}>
                Cancel
              </Button>
              <Button className="flex-1" onClick={() => importMutation.mutate()} loading={importMutation.isPending} disabled={!selectedFile}>
                Import
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function skippedSummary(skipped) {
  const parts = []
  if (skipped?.already_in_campaign) parts.push(`${skipped.already_in_campaign} already in it`)
  if (skipped?.uncontactable) parts.push(`${skipped.uncontactable} not contactable`)
  if (skipped?.not_found) parts.push(`${skipped.not_found} no longer exist`)
  return parts.length ? ` (skipped ${parts.join(', ')})` : ''
}

/** Shown while a lead list is picked in the filter: send the whole list to a campaign. */
function ListCampaignBar({ list, onClear }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [campaignId, setCampaignId] = useState('')

  const { data: campaignsData } = useQuery({
    queryKey: ['campaigns'],
    queryFn: async () => (await api.campaigns.list()).data,
  })
  const campaigns = (campaignsData?.campaigns || []).filter((c) => c.status !== 'archived')

  const [confirmingDelete, setConfirmingDelete] = useState(false)

  // A different list picked - don't carry the previous choices over
  useEffect(() => {
    setCampaignId('')
    setConfirmingDelete(false)
  }, [list.id])

  const deleteMutation = useMutation({
    mutationFn: () => api.leads.deleteList(list.id),
    onSuccess: () => {
      toast.success(`Deleted the list "${list.name}" - its prospects are still in Prospects`)
      queryClient.invalidateQueries({ queryKey: ['leadLists'] })
      queryClient.invalidateQueries({ queryKey: ['people'] })
      onClear()
    },
  })

  const addMutation = useMutation({
    mutationFn: () => api.campaigns.addLeadList(parseInt(campaignId), list.id),
    onSuccess: (response) => {
      const r = response.data
      const campaign = campaigns.find((c) => String(c.id) === String(campaignId))
      toast.success(
        (t) => (
          <span className="flex items-center gap-3">
            <span>
              Added {r.added} from "{list.name}" to {campaign?.name || 'the campaign'}
              {skippedSummary(r.skipped)}
            </span>
            <button
              type="button"
              onClick={() => {
                toast.dismiss(t.id)
                navigate(`/campaigns/${campaignId}`)
              }}
              className="shrink-0 rounded-full bg-white/15 px-2.5 py-1 text-xs font-medium hover:bg-white/25"
            >
              View
            </button>
          </span>
        ),
        { duration: 8000 }
      )
      queryClient.invalidateQueries({ queryKey: ['people'] })
      queryClient.invalidateQueries({ queryKey: ['campaigns'] })
      setCampaignId('')
    },
  })

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-card border border-primary-200 bg-primary-50 px-5 py-3">
      <QueueListIcon className="h-5 w-5 text-primary-600 shrink-0" />
      <span className="text-sm text-gray-900">
        <span className="font-medium">{list.name}</span>
        <span className="text-gray-500"> - {list.lead_count} prospect{list.lead_count === 1 ? '' : 's'}</span>
      </span>
      <div className="flex items-center gap-2">
        <select
          value={campaignId}
          onChange={(e) => setCampaignId(e.target.value)}
          className="px-3 py-1.5 rounded-full border border-gray-200 bg-white text-sm text-gray-900"
          aria-label="Campaign to add this list to"
        >
          <option value="">Add this list to a campaign...</option>
          {campaigns.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <Button size="sm" onClick={() => addMutation.mutate()} loading={addMutation.isPending} disabled={!campaignId}>
          Add list
        </Button>
      </div>
      {campaignsData && campaigns.length === 0 && (
        <Link to="/campaigns/new" className="text-sm text-primary-700 hover:underline">
          Create a campaign first
        </Link>
      )}
      <div className="ml-auto flex items-center gap-3">
        {confirmingDelete ? (
          <div className="flex items-center gap-2 rounded-full bg-white border border-red-200 pl-3 pr-1 py-1">
            <span className="text-sm text-gray-700">
              Delete this list? The {list.lead_count} prospect{list.lead_count === 1 ? '' : 's'} stay.
            </span>
            <Button size="sm" variant="secondary" onClick={() => setConfirmingDelete(false)} disabled={deleteMutation.isPending}>
              Cancel
            </Button>
            <Button size="sm" variant="danger" onClick={() => deleteMutation.mutate()} loading={deleteMutation.isPending}>
              Delete
            </Button>
          </div>
        ) : (
          <>
            <button onClick={onClear} className="text-sm text-gray-500 hover:text-gray-900">
              Show all lists
            </button>
            <button
              onClick={() => setConfirmingDelete(true)}
              className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-red-600"
              aria-label={`Delete lead list ${list.name}`}
            >
              <TrashIcon className="h-4 w-4" />
              Delete list
            </button>
          </>
        )}
      </div>
    </div>
  )
}

const KEEP_REASON_LABELS = {
  contacted: 'contacted',
  emailed: 'emailed',
  replied: 'replied',
  converted: 'converted',
  bounced: 'bounced',
  unsubscribed: 'unsubscribed',
  do_not_contact: 'marked do-not-contact',
}

/** "Remove all" for whatever the current search/filters match, behind an are-you-sure dialog. */
function RemoveAllProspects({ filters, total, filtering, onDone }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)

  const previewQuery = useQuery({
    queryKey: ['bulkDeletePreview', filters],
    queryFn: async () => (await api.leads.bulkDelete(filters, true)).data,
    enabled: open,
    staleTime: 0,
    gcTime: 0,
  })
  const preview = previewQuery.data

  const deleteMutation = useMutation({
    mutationFn: () => api.leads.bulkDelete(filters),
    onSuccess: (response) => {
      const r = response.data
      toast.success(
        `Deleted ${r.deleted} prospect${r.deleted === 1 ? '' : 's'}` +
          (r.kept ? ` - kept ${r.kept} who've been emailed or opted out` : '')
      )
      queryClient.invalidateQueries({ queryKey: ['people'] })
      queryClient.invalidateQueries({ queryKey: ['leadLists'] })
      queryClient.invalidateQueries({ queryKey: ['campaigns'] })
      setOpen(false)
      onDone()
    },
  })

  const keptText = preview
    ? Object.entries(preview.kept_reasons || {})
        .map(([reason, n]) => `${n} ${KEEP_REASON_LABELS[reason] || reason}`)
        .join(', ')
    : ''

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={!total}
        className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:border-red-200 hover:bg-red-50 hover:text-red-700 disabled:opacity-50"
      >
        <TrashIcon className="h-4 w-4" />
        Remove all{filtering ? ' matching' : ''} ({total})
      </button>

      <ConfirmDialog
        open={open}
        title={
          preview && preview.deleted === 0
            ? 'Nothing to remove'
            : `Delete ${preview ? preview.deleted : total} prospect${(preview ? preview.deleted : total) === 1 ? '' : 's'}?`
        }
        confirmLabel={preview ? `Delete ${preview.deleted}` : 'Delete'}
        confirmDisabled={!preview || preview.deleted === 0}
        loading={deleteMutation.isPending}
        onConfirm={() => deleteMutation.mutate()}
        onCancel={() => setOpen(false)}
      >
        {previewQuery.isLoading || !preview ? (
          <p>Checking which prospects can be removed...</p>
        ) : preview.deleted === 0 ? (
          <p>
            All {preview.matched} {filtering ? 'matching ' : ''}prospects have been emailed or have opted out ({keptText}), so
            they're kept to preserve their history.
          </p>
        ) : (
          <>
            <p>
              Are you sure? This permanently deletes {preview.deleted}
              {filtering ? ' matching' : ''} prospect{preview.deleted === 1 ? '' : 's'} and{' '}
              <strong>can't be undone</strong>.
            </p>
            {preview.in_campaigns > 0 && (
              <p>
                {preview.in_campaigns} of them {preview.in_campaigns === 1 ? 'is' : 'are'} in a campaign and will be removed
                from it.
              </p>
            )}
            {preview.kept > 0 && (
              <p className="text-gray-500">
                {preview.kept} will be kept ({keptText}) so their email history and opt-outs aren't lost.
              </p>
            )}
          </>
        )}
      </ConfirmDialog>
    </>
  )
}

function BulkBar({ selectedIds, onClear }) {
  const queryClient = useQueryClient()
  const [campaignId, setCampaignId] = useState('')

  const { data: campaignsData } = useQuery({
    queryKey: ['campaigns'],
    queryFn: async () => (await api.campaigns.list()).data,
  })
  const campaigns = (campaignsData?.campaigns || []).filter((c) => c.status !== 'archived')

  const addMutation = useMutation({
    mutationFn: () => api.campaigns.addLeads(parseInt(campaignId), selectedIds),
    onSuccess: (response) => {
      const r = response.data
      const skipped = Object.values(r.skipped || {}).reduce((a, b) => a + b, 0)
      toast.success(`Added ${r.added} to the campaign${skipped ? ` (${skipped} skipped - already in it or not contactable)` : ''}`)
      queryClient.invalidateQueries({ queryKey: ['people'] })
      queryClient.invalidateQueries({ queryKey: ['campaigns'] })
      onClear()
    },
  })

  const statusMutation = useMutation({
    mutationFn: (status) => api.leads.bulkUpdateStatus(selectedIds, status),
    onSuccess: (response, status) => {
      toast.success(`${response.data.updated} marked ${status.replaceAll('_', ' ')}`)
      queryClient.invalidateQueries({ queryKey: ['people'] })
      onClear()
    },
  })

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-card bg-primary-600 px-5 py-3 text-white shadow-sm shadow-primary-600/25">
      <span className="text-sm font-medium">{selectedIds.length} selected</span>
      <div className="flex items-center gap-2">
        <select
          value={campaignId}
          onChange={(e) => setCampaignId(e.target.value)}
          className="px-3 py-1.5 rounded-full border-0 text-sm text-gray-900"
          aria-label="Campaign"
        >
          <option value="">Add to campaign...</option>
          {campaigns.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <button
          onClick={() => addMutation.mutate()}
          disabled={!campaignId || addMutation.isPending}
          className="px-4 py-1.5 rounded-full bg-white text-primary-700 text-sm font-medium hover:bg-primary-50 disabled:opacity-50"
        >
          {addMutation.isPending ? 'Adding...' : 'Add'}
        </button>
      </div>
      <select
        value=""
        onChange={(e) => e.target.value && statusMutation.mutate(e.target.value)}
        disabled={statusMutation.isPending}
        className="px-3 py-1.5 rounded-full border-0 text-sm text-gray-900"
        aria-label="Change status"
      >
        <option value="">Change status...</option>
        {STATUSES.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
      <button onClick={onClear} className="ml-auto text-sm text-primary-100 hover:text-white">
        Clear selection
      </button>
    </div>
  )
}

export default function ProspectsPage() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [listId, setListId] = useState('')
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState(() => new Set())
  const [showImport, setShowImport] = useState(false)
  const debouncedSearch = useDebounced(search)

  // New filters start from page 1 with nothing selected.
  useEffect(() => {
    setPage(0)
    setSelected(new Set())
  }, [debouncedSearch, status, listId])

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['people', debouncedSearch, status, listId, page],
    queryFn: async () =>
      (
        await api.leads.listPeople({
          search: debouncedSearch || undefined,
          status: status || undefined,
          list_id: listId || undefined,
          skip: page * PER_PAGE,
          limit: PER_PAGE,
        })
      ).data,
    placeholderData: keepPreviousData,
  })

  const { data: listsData } = useQuery({
    queryKey: ['leadLists'],
    queryFn: async () => (await api.leads.listLists()).data,
  })

  const people = data?.people || []
  const total = data?.total || 0
  const pageCount = Math.max(1, Math.ceil(total / PER_PAGE))
  const counts = data?.status_counts || {}
  const filtering = Boolean(debouncedSearch || status || listId)
  const selectedList = (listsData?.lists || []).find((l) => String(l.id) === String(listId))

  const pageIds = useMemo(() => people.map((p) => p.id), [people])
  const allOnPageSelected = pageIds.length > 0 && pageIds.every((id) => selected.has(id))

  const toggle = (id) =>
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  const togglePage = () =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (allOnPageSelected) pageIds.forEach((id) => next.delete(id))
      else pageIds.forEach((id) => next.add(id))
      return next
    })

  const clearFilters = () => {
    setSearch('')
    setStatus('')
    setListId('')
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-medium tracking-tight text-gray-900">Prospects</h1>
          <p className="mt-1 text-sm text-gray-500">Everyone you can reach out to - search, filter and add them to campaigns</p>
        </div>
        <Button icon={ArrowUpTrayIcon} onClick={() => setShowImport(true)}>
          Import CSV
        </Button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <StatCard icon={UserGroupIcon} label="Total prospects" value={data ? data.total_prospects : '-'} caption="In your database" />
        <StatCard icon={SparklesIcon} label="Not contacted yet" value={data ? counts.new ?? 0 : '-'} caption="Status: new" />
        <StatCard icon={PaperAirplaneIcon} label="Contacted" value={data ? counts.contacted ?? 0 : '-'} caption="Emailed, no reply yet" />
        <StatCard
          icon={ChatBubbleLeftRightIcon}
          label="Replied"
          value={data ? (counts.replied ?? 0) + (counts.converted ?? 0) : '-'}
          caption={data ? `${counts.converted ?? 0} converted` : 'Replied or converted'}
        />
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[240px] max-w-md">
          <MagnifyingGlassIcon className="h-4 w-4 text-gray-400 absolute left-4 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name, email, role or company..."
            className="w-full pl-10 pr-4 py-2 border border-gray-200 rounded-full bg-white text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
          />
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className={selectClass} aria-label="Status">
          <option value="">All statuses</option>
          {STATUSES.map(([value, label]) => (
            <option key={value} value={value}>
              {label} {counts[value] !== undefined ? `(${counts[value]})` : ''}
            </option>
          ))}
        </select>
        <select value={listId} onChange={(e) => setListId(e.target.value)} className={selectClass} aria-label="Lead list">
          <option value="">All lead lists</option>
          {(listsData?.lists || []).map((list) => (
            <option key={list.id} value={list.id}>
              {list.name} ({list.lead_count})
            </option>
          ))}
        </select>
        {filtering && (
          <button onClick={clearFilters} className="text-sm text-gray-500 hover:text-gray-900">
            Clear filters
          </button>
        )}
      </div>

      {selected.size > 0 ? (
        <BulkBar selectedIds={[...selected]} onClear={() => setSelected(new Set())} />
      ) : (
        selectedList && <ListCampaignBar list={selectedList} onClear={() => setListId('')} />
      )}

      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <LoadingSpinner size="lg" />
        </div>
      ) : people.length === 0 ? (
        <Card>
          {filtering ? (
            <EmptyState
              icon={MagnifyingGlassIcon}
              title="No prospects match"
              description="Try a different search or clear the filters"
              action={
                <Button variant="secondary" onClick={clearFilters}>
                  Clear filters
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon={UserGroupIcon}
              title="No prospects yet"
              description="Import a CSV to get started"
              action={
                <Button icon={ArrowUpTrayIcon} onClick={() => setShowImport(true)}>
                  Import CSV
                </Button>
              }
            />
          )}
        </Card>
      ) : (
        <Card padding={false} className="overflow-hidden">
          <div className="flex items-center justify-between gap-3 px-5 py-4">
            <div className="flex items-center gap-3">
              <h2 className="text-lg font-medium tracking-tight text-gray-900">
                {filtering ? 'Matching prospects' : 'All prospects'}
              </h2>
              <RemoveAllProspects
                filters={{ search: debouncedSearch || undefined, status: status || undefined, list_id: listId ? parseInt(listId) : undefined }}
                total={total}
                filtering={filtering}
                onDone={() => {
                  setSelected(new Set())
                  setPage(0)
                }}
              />
            </div>
            <Pager page={page} pageCount={pageCount} total={total} shown={people.length} onPage={setPage} busy={isFetching} />
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-500 border-y border-gray-100 bg-canvas/60">
                  <th className="pl-5 pr-2 py-3 w-10">
                    <input
                      type="checkbox"
                      checked={allOnPageSelected}
                      onChange={togglePage}
                      aria-label="Select all on this page"
                      className="h-4 w-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500"
                    />
                  </th>
                  <th className="px-3 py-3 font-medium">Prospect</th>
                  <th className="px-3 py-3 font-medium">Company</th>
                  <th className="px-3 py-3 font-medium">Role</th>
                  <th className="px-3 py-3 font-medium">Status</th>
                  <th className="px-3 py-3 font-medium">Campaigns</th>
                  <th className="px-3 py-3 font-medium">Added</th>
                  <th className="pl-3 pr-5 py-3 font-medium text-right">Links</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {people.map((person) => {
                  const name = displayName(person)
                  const site = websiteHref(person)
                  const isSelected = selected.has(person.id)
                  return (
                    <tr key={person.id} className={clsx('transition-colors', isSelected ? 'bg-primary-50/60' : 'hover:bg-gray-50')}>
                      <td className="pl-5 pr-2 py-3">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggle(person.id)}
                          aria-label={`Select ${person.email}`}
                          className="h-4 w-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500"
                        />
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-3 min-w-0">
                          <div className="h-9 w-9 shrink-0 rounded-full bg-primary-50 text-primary-700 flex items-center justify-center text-xs font-semibold">
                            {initials(person)}
                          </div>
                          <div className="min-w-0">
                            {name ? (
                              <>
                                <p className="font-medium text-gray-900 truncate">{name}</p>
                                <p className="text-xs text-gray-500 truncate">{person.email}</p>
                              </>
                            ) : (
                              <p className="font-medium text-gray-900 truncate">{person.email}</p>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        {person.company_name ? (
                          <div className="min-w-0">
                            <p className="text-gray-900 truncate max-w-[220px]">{person.company_name}</p>
                            <p className="text-xs text-gray-500 truncate max-w-[220px]">
                              {[person.company_domain, person.industry].filter(Boolean).join(' · ') || ' '}
                            </p>
                          </div>
                        ) : (
                          <span className="text-gray-400">-</span>
                        )}
                      </td>
                      <td className="px-3 py-3 text-gray-600">{person.role || <span className="text-gray-400">-</span>}</td>
                      <td className="px-3 py-3">
                        <StatusBadge status={person.status} />
                      </td>
                      <td className="px-3 py-3">
                        {person.campaign_count > 0 ? (
                          <span className="inline-flex items-center gap-1 text-xs text-primary-700 bg-primary-50 rounded-full px-2 py-0.5">
                            <MegaphoneIcon className="h-3.5 w-3.5" />
                            {person.campaign_count}
                          </span>
                        ) : (
                          <span className="text-gray-400">-</span>
                        )}
                      </td>
                      <td className="px-3 py-3 text-gray-500 whitespace-nowrap">
                        {person.created_at ? new Date(person.created_at + 'Z').toLocaleDateString() : '-'}
                      </td>
                      <td className="pl-3 pr-5 py-3 text-right whitespace-nowrap">
                        <div className="inline-flex items-center gap-2">
                          {site && (
                            <a href={site} target="_blank" rel="noopener noreferrer" className="text-xs text-primary-600 hover:underline">
                              Website
                            </a>
                          )}
                          {person.linkedin_url && (
                            <a
                              href={person.linkedin_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-xs text-primary-600 hover:underline"
                            >
                              LinkedIn
                            </a>
                          )}
                          {!site && !person.linkedin_url && <span className="text-gray-400">-</span>}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between gap-3 px-5 py-4 border-t border-gray-100">
            <p className="text-xs text-gray-500">
              Tip: select prospects to add them to a campaign. Or add a whole lead list from a{' '}
              <Link to="/campaigns" className="text-primary-600 hover:underline">campaign's page</Link>.
            </p>
            <Pager page={page} pageCount={pageCount} total={total} shown={people.length} onPage={setPage} busy={isFetching} />
          </div>
        </Card>
      )}

      {showImport && <ImportModal onClose={() => setShowImport(false)} />}
    </div>
  )
}
