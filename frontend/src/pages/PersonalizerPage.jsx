import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  SparklesIcon,
  ArrowUpTrayIcon,
  ArrowDownTrayIcon,
  DocumentDuplicateIcon,
  ArrowPathIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ExclamationTriangleIcon,
} from '@heroicons/react/24/outline'
import { api } from '../services/apiClient'
import { useTask } from '../context/BackgroundTasks'
import Button from '../components/common/Button'
import Card from '../components/common/Card'
import LoadingSpinner from '../components/common/LoadingSpinner'
import EmptyState from '../components/common/EmptyState'
import toast from 'react-hot-toast'

const RESULTS_PAGE_SIZE = 40
const OFFER_CACHE_KEY = 'personalizer_offer'
const JOB_CACHE_KEY = 'personalizer_last_job'

function loadCache(key) {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function saveCache(key, value) {
  try {
    if (value === null || value === undefined) localStorage.removeItem(key)
    else localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // ignore
  }
}

function splitCSVLine(line) {
  const result = []
  let current = ''
  let inQuotes = false
  for (let i = 0; i < line.length; i++) {
    const char = line[i]
    if (char === '"') {
      if (inQuotes && line[i + 1] === '"') { current += '"'; i++ }
      else inQuotes = !inQuotes
    } else if (char === ',' && !inQuotes) {
      result.push(current); current = ''
    } else {
      current += char
    }
  }
  result.push(current)
  return result
}

function parseLeadsCSV(text) {
  const lines = text.trim().split(/\r?\n/)
  if (lines.length < 2) return []
  const header = splitCSVLine(lines[0]).map((h) => h.trim().toLowerCase())

  return lines.slice(1).filter(Boolean).map((line) => {
    const values = splitCSVLine(line)
    const row = {}
    header.forEach((h, i) => { row[h] = (values[i] || '').trim() })
    return {
      company_name: row.company_name || row.company || row.name || '',
      website: row.website || row.domain || '',
      email: row.email || '',
      segment: row.segment || null,
    }
  }).filter((r) => r.email)
}

function resultsToCSV(rows) {
  const header = ['company_name', 'email', 'segment', 'subject', 'body']
  const lines = rows.map((r) => header.map((k) => `"${String(r[k] ?? '').replace(/"/g, '""')}"`).join(','))
  return [header.join(','), ...lines].join('\n')
}

function downloadCSV(rows, filename) {
  const blob = new Blob([resultsToCSV(rows)], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export default function PersonalizerPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const fileInputRef = useRef(null)
  const autoRunTriggered = useRef(false)

  const [offer, setOffer] = useState(() => loadCache(OFFER_CACHE_KEY) || '')
  const [job, setJob] = useState(loadCache(JOB_CACHE_KEY))
  const [pendingLeads, setPendingLeads] = useState(null)
  const [resultsPage, setResultsPage] = useState(1)
  const [selectedFile, setSelectedFile] = useState(null)
  const [dragActive, setDragActive] = useState(false)

  const incomingRows = location.state?.verifiedRows

  useEffect(() => {
    saveCache(OFFER_CACHE_KEY, offer || null)
  }, [offer])

  const startJob = useMutation({
    mutationFn: (leads) => api.leads.personalize(leads, offer),
    onSuccess: (response) => {
      const { job_id, total } = response.data
      const newJob = { job_id, status: 'running', total, processed: 0, results: [] }
      setJob(newJob)
      start(newJob, { label: `Drafting ${total} email${total === 1 ? '' : 's'}` })
      setPendingLeads(null)
      setResultsPage(1)
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || 'Failed to start personalization')
    },
  })

  const regenerateMutation = useMutation({
    mutationFn: (row) => api.leads.personalize([{
      company_id: row.company_id,
      company_name: row.company_name,
      website: row.website,
      email: row.email,
      segment: row.segment,
    }], offer),
    onSuccess: async (response, row) => {
      const { job_id } = response.data
      // Small single-lead job - poll until done, then splice the result in
      let updated
      for (let i = 0; i < 20; i++) {
        await new Promise((r) => setTimeout(r, 1000))
        const poll = await api.leads.getPersonalizeJob(job_id)
        if (poll.data.status === 'completed') { updated = poll.data.results[0]; break }
        if (poll.data.status === 'failed') break
      }
      if (updated) {
        setJob((prev) => {
          const next = {
            ...prev,
            results: prev.results.map((r) => (r.email === row.email ? updated : r)),
          }
          saveCache(JOB_CACHE_KEY, next)
          return next
        })
        toast.success('Regenerated')
      } else {
        toast.error('Regeneration timed out')
      }
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || 'Failed to regenerate')
    },
  })

  // The app-wide task tracker polls the job (so it keeps going while you're on
  // other pages) and caches it under JOB_CACHE_KEY; mirror it here.
  const { task, start } = useTask('personalizer', {
    onProgress: (latest) => setJob(latest),
    onComplete: () => setJob(loadCache(JOB_CACHE_KEY)),
    onFail: () => setJob(loadCache(JOB_CACHE_KEY)),
  })

  // A job cached as running that the tracker doesn't know about - hand it over
  useEffect(() => {
    if (job?.status === 'running' && task?.jobId !== job.job_id) start(job)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!incomingRows?.length || autoRunTriggered.current) return
    autoRunTriggered.current = true

    const leads = incomingRows.map((r) => ({
      company_id: r.company_id,
      company_name: r.company_name,
      website: r.website,
      email: r.email,
      segment: r.segment,
    }))

    if (offer.trim()) {
      startJob.mutate(leads)
    } else {
      setPendingLeads(leads)
      toast('Describe your offer below, then hit Generate', { icon: '✍️' })
    }

    navigate(location.pathname, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incomingRows])

  const handleFile = (file) => {
    if (!file) return
    if (!file.name.endsWith('.csv')) {
      toast.error('Please select a CSV file')
      return
    }
    setSelectedFile(file)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setDragActive(false)
    handleFile(e.dataTransfer.files?.[0])
  }

  const handleGenerate = async () => {
    if (!offer.trim()) {
      toast.error('Describe what you\'re offering first')
      return
    }
    if (pendingLeads) {
      startJob.mutate(pendingLeads)
      return
    }
    if (selectedFile) {
      const text = await selectedFile.text()
      const leads = parseLeadsCSV(text)
      if (leads.length === 0) {
        toast.error('No valid rows found - expected an "email" column')
        return
      }
      startJob.mutate(leads)
    }
  }

  const isRunning = job?.status === 'running'
  const results = job?.status === 'completed' ? job.results : []
  const totalPages = Math.max(1, Math.ceil(results.length / RESULTS_PAGE_SIZE))
  const pageResults = results.slice((resultsPage - 1) * RESULTS_PAGE_SIZE, resultsPage * RESULTS_PAGE_SIZE)
  const canGenerate = Boolean(offer.trim()) && Boolean(pendingLeads || selectedFile)

  const copyEmail = (row) => {
    navigator.clipboard.writeText(`Subject: ${row.subject || ''}\n\n${row.body || ''}`)
    toast.success('Copied')
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-medium tracking-tight text-gray-900">Personalizer</h1>
        <p className="mt-1 text-sm text-gray-500">
          AI drafts one specific email per lead, scoped to everything known about their company
        </p>
      </div>

      <Card>
        <Card.Header>
          <Card.Title>Your offer</Card.Title>
          <Card.Description>
            What are you pitching? The AI uses this plus each company's scraped data (industry,
            location, homepage content, segment) to write a specific email - not a generic template.
          </Card.Description>
        </Card.Header>
        <textarea
          value={offer}
          onChange={(e) => setOffer(e.target.value)}
          rows={3}
          placeholder="e.g. We run done-for-you cold email outreach for design studios, typically booking 5-10 qualified calls a month"
          className="w-full rounded-lg border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
        />

        {pendingLeads && (
          <p className="mt-2 text-sm text-primary-700">
            {pendingLeads.length} leads ready from the Verifier - waiting on your offer above.
          </p>
        )}

        {!pendingLeads && (
          <div className="mt-4">
            <div
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragActive(true) }}
              onDragLeave={() => setDragActive(false)}
              onDrop={handleDrop}
              className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors ${
                dragActive ? 'border-primary-500 bg-primary-50' : 'border-gray-300 hover:border-primary-500'
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv"
                onChange={(e) => handleFile(e.target.files?.[0])}
                className="hidden"
              />
              {selectedFile ? (
                <p className="text-sm font-medium text-gray-900">{selectedFile.name}</p>
              ) : (
                <div>
                  <ArrowUpTrayIcon className="h-6 w-6 mx-auto text-gray-400" />
                  <p className="mt-1 text-sm text-gray-600">
                    Or upload a CSV (company_name, website, email, segment - matches the Verifier's export)
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        <div className="flex justify-end mt-4">
          <Button
            icon={SparklesIcon}
            onClick={handleGenerate}
            loading={startJob.isPending || isRunning}
            disabled={!canGenerate}
          >
            Generate
          </Button>
        </div>
      </Card>

      {isRunning && (
        <Card>
          <div className="flex flex-col items-center justify-center py-12 gap-4">
            <LoadingSpinner size="lg" />
            <div className="w-full max-w-sm">
              <div className="flex justify-between text-sm text-gray-600 mb-1">
                <span>{job.processed} / {job.total} emails</span>
                <span>{job.total ? Math.round((job.processed / job.total) * 100) : 0}%</span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div
                  className="bg-primary-600 h-2 rounded-full transition-all"
                  style={{ width: `${job.total ? (job.processed / job.total) * 100 : 0}%` }}
                />
              </div>
            </div>
          </div>
        </Card>
      )}

      {job?.status === 'failed' && (
        <Card>
          <div className="flex items-center gap-2 text-red-600">
            <ExclamationTriangleIcon className="h-5 w-5 shrink-0" />
            <p className="text-sm">{job.error || 'Personalization job failed'}</p>
          </div>
        </Card>
      )}

      {!isRunning && results.length > 0 && (
        <Card padding={false}>
          <div className="flex flex-wrap items-center justify-between gap-3 p-6 pb-0">
            <Card.Title>{results.length} drafted emails</Card.Title>
            <Button variant="secondary" size="sm" icon={ArrowDownTrayIcon} onClick={() => downloadCSV(results, 'personalized_emails.csv')}>
              Export CSV
            </Button>
          </div>

          <div className="divide-y divide-gray-200 mt-4">
            {pageResults.map((row) => (
              <div key={`${row.company_id}-${row.email}`} className="p-6">
                <div className="flex flex-wrap items-start justify-between gap-3 mb-2">
                  <div>
                    <p className="text-sm font-medium text-gray-900">{row.company_name}</p>
                    <p className="text-xs text-gray-500">{row.email} {row.segment && `- ${row.segment}`}</p>
                    {!row.error && (row.pages_crawled > 0 || row.web_mentions > 0) && (
                      <p className="text-xs text-gray-400 mt-0.5">
                        {row.pages_crawled > 0 && `Crawled ${row.pages_crawled} page${row.pages_crawled === 1 ? '' : 's'}`}
                        {row.pages_crawled > 0 && row.web_mentions > 0 && ' · '}
                        {row.web_mentions > 0 && `${row.web_mentions} web mention${row.web_mentions === 1 ? '' : 's'}`}
                      </p>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <Button variant="ghost" size="sm" icon={ArrowPathIcon} onClick={() => regenerateMutation.mutate(row)} loading={regenerateMutation.isPending && regenerateMutation.variables?.email === row.email}>
                      Regenerate
                    </Button>
                    <Button variant="ghost" size="sm" icon={DocumentDuplicateIcon} onClick={() => copyEmail(row)} disabled={!row.body}>
                      Copy
                    </Button>
                  </div>
                </div>

                {row.error ? (
                  <p className="text-sm text-red-600">{row.error}</p>
                ) : (
                  <div className="bg-gray-50 rounded-lg p-3">
                    <p className="text-sm font-semibold text-gray-900 mb-1">{row.subject}</p>
                    <p className="text-sm text-gray-700 whitespace-pre-wrap">{row.body}</p>
                  </div>
                )}
              </div>
            ))}
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between px-6 py-4 border-t border-gray-200">
              <p className="text-sm text-gray-500">Page {resultsPage} of {totalPages}</p>
              <div className="flex gap-2">
                <Button variant="secondary" size="sm" icon={ChevronLeftIcon} onClick={() => setResultsPage((p) => Math.max(1, p - 1))} disabled={resultsPage === 1}>
                  Prev
                </Button>
                <Button variant="secondary" size="sm" onClick={() => setResultsPage((p) => Math.min(totalPages, p + 1))} disabled={resultsPage === totalPages}>
                  Next
                  <ChevronRightIcon className="h-4 w-4 ml-2 -mr-1" />
                </Button>
              </div>
            </div>
          )}
        </Card>
      )}

      {!isRunning && !job && !pendingLeads && (
        <Card>
          <EmptyState
            icon={SparklesIcon}
            title="No emails drafted yet"
            description="Describe your offer above, then upload a CSV or send a list over from the Verifier page"
          />
        </Card>
      )}
    </div>
  )
}
