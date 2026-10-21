import { useState, useRef, useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  MagnifyingGlassCircleIcon,
  ArrowUpTrayIcon,
  ArrowDownTrayIcon,
  EnvelopeIcon,
  CheckCircleIcon,
  XCircleIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ShieldCheckIcon,
  EyeIcon,
  EyeSlashIcon,
} from '@heroicons/react/24/outline'
import { api } from '../services/apiClient'
import { useTask } from '../context/BackgroundTasks'
import Button from '../components/common/Button'
import Card from '../components/common/Card'
import LoadingSpinner from '../components/common/LoadingSpinner'
import EmptyState from '../components/common/EmptyState'
import UnpickedEmailsPanel from '../components/enricher/UnpickedEmailsPanel'
import toast from 'react-hot-toast'

const RESULTS_PAGE_SIZE = 40
const JOB_CACHE_KEY = 'enricher_last_job'

function scrapedRowsToCSV(rows) {
  const header = ['name', 'website', 'location', 'rating']
  const lines = rows.map((r) => header.map((k) => `"${String(r[k] || '').replace(/"/g, '""')}"`).join(','))
  return [header.join(','), ...lines].join('\n')
}

function downloadResultsCSV(results) {
  const header = ['name', 'website', 'status', 'emails', 'unpicked_emails']
  const rows = results.map((r) => [
    r.name || '',
    r.website || '',
    r.status || '',
    r.emails.join('; '),
    (r.unpicked_emails || []).map((u) => u.email).join('; '),
  ])
  const csv = [header, ...rows]
    .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
    .join('\n')

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'enriched_leads.csv'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function loadCachedJob() {
  try {
    const raw = localStorage.getItem(JOB_CACHE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export default function EnricherPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const [selectedFile, setSelectedFile] = useState(null)
  const [dragActive, setDragActive] = useState(false)
  const [job, setJob] = useState(loadCachedJob)
  const [resultsPage, setResultsPage] = useState(1)
  const [showUnpicked, setShowUnpicked] = useState(false)
  const fileInputRef = useRef(null)
  const autoRunTriggered = useRef(false)

  const incomingRows = location.state?.scrapedRows

  const startJob = useMutation({
    mutationFn: async (file) => {
      const formData = new FormData()
      formData.append('file', file)
      return api.leads.enrichUpload(formData)
    },
    onSuccess: (response) => handleJobStarted(response, (total) => `Enriching ${total} compan${total === 1 ? 'y' : 'ies'}`),
    onError: (error) => {
      toast.error(error.response?.data?.detail || 'Failed to start enrichment')
    },
  })

  const handleJobStarted = (response, label) => {
    const { job_id, total } = response.data
    const newJob = { job_id, status: 'running', total, processed: 0, emails_found: 0, results: [] }
    setJob(newJob)
    start(newJob, { label: label(total) })
    setResultsPage(1)
  }

  // Re-run the current list, re-scraping only companies enriched before
  // unpicked emails were tracked (the rest come back from cache)
  const rescanMutation = useMutation({
    mutationFn: () => {
      const all = job.results.map((r) => r.company_id)
      const untracked = job.results.filter((r) => r.unpicked_tracked === false).map((r) => r.company_id)
      return api.leads.rescanEnrich(all, untracked)
    },
    onSuccess: (response) => handleJobStarted(response, (total) => `Re-scanning ${total} companies for unpicked emails`),
  })

  // "Use" on an unpicked email: it's now a prospect, so move it into the row's emails
  const handlePicked = (companyId, email) => {
    setJob((prev) => {
      const next = {
        ...prev,
        emails_found: (prev.emails_found || 0) + 1,
        results: prev.results.map((r) =>
          r.company_id === companyId
            ? {
                ...r,
                status: 'completed',
                emails: [...r.emails, email],
                unpicked_emails: (r.unpicked_emails || []).filter((u) => u.email !== email),
              }
            : r
        ),
      }
      try {
        localStorage.setItem(JOB_CACHE_KEY, JSON.stringify(next))
      } catch {
        // ignore - storage full or disabled
      }
      return next
    })
  }

  // The app-wide task tracker polls the job (so it keeps going while you're on
  // other pages) and caches it under JOB_CACHE_KEY; mirror it here.
  const { task, start } = useTask('enricher', {
    onProgress: (latest) => setJob(latest),
    onComplete: () => setJob(loadCachedJob()),
    onFail: () => setJob(loadCachedJob()),
  })

  // A job cached as running that the tracker doesn't know about (e.g. started
  // before background tracking existed) - hand it over so it gets polled
  useEffect(() => {
    if (job?.status === 'running' && task?.jobId !== job.job_id) start(job)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!incomingRows?.length || autoRunTriggered.current) return
    autoRunTriggered.current = true

    const csv = scrapedRowsToCSV(incomingRows)
    const blob = new Blob([csv], { type: 'text/csv' })
    const file = new File([blob], 'scraped_leads.csv', { type: 'text/csv' })
    startJob.mutate(file)

    // Clear the handoff state so a refresh or revisit doesn't re-trigger it
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

  const isRunning = job?.status === 'running'
  const results = job?.status === 'completed' ? job.results : []
  const totalFound = job?.emails_found ?? 0
  const totalProcessed = job?.total ?? 0
  const hitRate = totalProcessed ? Math.round((results.filter((r) => r.emails.length > 0).length / totalProcessed) * 100) : 0
  const cameFromScraper = Boolean(incomingRows?.length) || autoRunTriggered.current
  const unpickedCount = results.reduce((n, r) => n + (r.unpicked_emails?.length || 0), 0)
  const untrackedCount = results.filter((r) => r.unpicked_tracked === false).length
  const totalPages = Math.max(1, Math.ceil(results.length / RESULTS_PAGE_SIZE))
  const pageResults = results.slice((resultsPage - 1) * RESULTS_PAGE_SIZE, resultsPage * RESULTS_PAGE_SIZE)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-medium tracking-tight text-gray-900">Enricher</h1>
        <p className="mt-1 text-sm text-gray-500">
          Find contact emails for a scraped company list
        </p>
      </div>

      {cameFromScraper ? (
        <details>
          <summary className="cursor-pointer text-sm font-medium text-gray-500 hover:text-gray-700">
            Upload a different list instead
          </summary>
          <Card className="mt-3">
            <UploadCard
              fileInputRef={fileInputRef}
              selectedFile={selectedFile}
              dragActive={dragActive}
              setDragActive={setDragActive}
              handleFile={handleFile}
              handleDrop={handleDrop}
              onSubmit={() => startJob.mutate(selectedFile)}
              loading={startJob.isPending || isRunning}
            />
          </Card>
        </details>
      ) : (
        <Card>
          <Card.Header>
            <Card.Title>Upload a list</Card.Title>
            <Card.Description>
              CSV with company name and website columns (e.g. a Clutch or directory export
              with no emails yet - name, website, location, category). We'll visit each
              site's homepage and contact/about pages to find a public email address.
            </Card.Description>
          </Card.Header>
          <UploadCard
            fileInputRef={fileInputRef}
            selectedFile={selectedFile}
            dragActive={dragActive}
            setDragActive={setDragActive}
            handleFile={handleFile}
            handleDrop={handleDrop}
            onSubmit={() => startJob.mutate(selectedFile)}
            loading={startJob.isPending || isRunning}
          />
        </Card>
      )}

      {isRunning && (
        <Card>
          <div className="flex flex-col items-center justify-center py-12 gap-4">
            <LoadingSpinner size="lg" />
            <div className="w-full max-w-sm">
              <div className="flex justify-between text-sm text-gray-600 mb-1">
                <span>{job.processed} / {job.total} companies</span>
                <span>{job.total ? Math.round((job.processed / job.total) * 100) : 0}%</span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div
                  className="bg-primary-600 h-2 rounded-full transition-all"
                  style={{ width: `${job.total ? (job.processed / job.total) * 100 : 0}%` }}
                />
              </div>
            </div>
            <p className="text-sm text-gray-500">
              Visiting each company's website for a contact email - large lists can take a while
            </p>
          </div>
        </Card>
      )}

      {job?.status === 'failed' && (
        <Card>
          <div className="flex items-center gap-2 text-red-600">
            <XCircleIcon className="h-5 w-5 shrink-0" />
            <p className="text-sm">{job.error || 'Enrichment job failed'}</p>
          </div>
        </Card>
      )}

      {!isRunning && results.length > 0 && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Card>
              <p className="text-sm text-gray-500">Companies processed</p>
              <p className="mt-1 text-3xl font-medium tracking-tight text-gray-900">{totalProcessed}</p>
            </Card>
            <Card>
              <p className="text-sm text-gray-500">Emails found</p>
              <p className="mt-1 text-3xl font-medium tracking-tight text-gray-900">{totalFound}</p>
            </Card>
            <Card>
              <p className="text-sm text-gray-500">Hit rate</p>
              <p className="mt-1 text-3xl font-medium tracking-tight text-gray-900">{hitRate}%</p>
            </Card>
          </div>

          {showUnpicked && (
            <UnpickedEmailsPanel
              results={results}
              onPicked={handlePicked}
              untrackedCount={untrackedCount}
              onRescan={() => rescanMutation.mutate()}
              rescanning={rescanMutation.isPending}
            />
          )}

          <Card padding={false}>
            <div className="flex flex-wrap items-center justify-between gap-3 p-6 pb-0">
              <Card.Title>Results</Card.Title>
              <div className="flex gap-2">
                <Button
                  variant={showUnpicked ? 'primary' : 'secondary'}
                  size="sm"
                  icon={showUnpicked ? EyeSlashIcon : EyeIcon}
                  onClick={() => setShowUnpicked((v) => !v)}
                >
                  {showUnpicked ? 'Hide' : 'Show'} unpicked emails ({unpickedCount})
                </Button>
                <Button variant="secondary" size="sm" icon={ArrowDownTrayIcon} onClick={() => downloadResultsCSV(results)}>
                  Export CSV
                </Button>
                <Button
                  size="sm"
                  icon={ShieldCheckIcon}
                  onClick={() => navigate('/verifier', { state: { enrichResults: results } })}
                >
                  Verify this list
                </Button>
              </div>
            </div>
            <div className="overflow-x-auto mt-4">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Company</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Website</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Emails found</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {pageResults.map((r) => (
                    <tr key={r.company_id} className="hover:bg-gray-50">
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                        {r.name}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {r.website ? (
                          <a
                            href={r.website.startsWith('http') ? r.website : `https://${r.website}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-primary-600 hover:text-primary-800 hover:underline"
                          >
                            {r.website}
                          </a>
                        ) : '-'}
                      </td>
                      <td className="px-6 py-4 text-sm">
                        {r.emails.length > 0 ? (
                          <div className="flex flex-wrap items-center gap-2">
                            <CheckCircleIcon className="h-4 w-4 text-green-500 shrink-0" />
                            <div className="flex flex-wrap gap-1">
                              {r.emails.map((email) => (
                                <span
                                  key={email}
                                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800"
                                >
                                  <EnvelopeIcon className="h-3 w-3" />
                                  {email}
                                </span>
                              ))}
                            </div>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2 text-gray-400">
                            <XCircleIcon className="h-4 w-4 shrink-0" />
                            {r.error || 'No public email found'}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {totalPages > 1 && (
              <div className="flex items-center justify-between px-6 py-4 border-t border-gray-200">
                <p className="text-sm text-gray-500">
                  Page {resultsPage} of {totalPages}
                </p>
                <div className="flex gap-2">
                  <Button variant="secondary" size="sm" icon={ArrowDownTrayIcon} onClick={() => downloadResultsCSV(results)}>
                    Export CSV
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={ChevronLeftIcon}
                    onClick={() => setResultsPage((p) => Math.max(1, p - 1))}
                    disabled={resultsPage === 1}
                  >
                    Prev
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setResultsPage((p) => Math.min(totalPages, p + 1))}
                    disabled={resultsPage === totalPages}
                  >
                    Next
                    <ChevronRightIcon className="h-4 w-4 ml-2 -mr-1" />
                  </Button>
                </div>
              </div>
            )}
          </Card>
        </>
      )}

      {!isRunning && !job && (
        <Card>
          <EmptyState
            icon={MagnifyingGlassCircleIcon}
            title="No results yet"
            description="Upload a CSV above to start finding contact emails, or send a list over from the Scrapers page"
          />
        </Card>
      )}
    </div>
  )
}

function UploadCard({ fileInputRef, selectedFile, dragActive, setDragActive, handleFile, handleDrop, onSubmit, loading }) {
  return (
    <>
      <div
        onClick={() => fileInputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragActive(true) }}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
        className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
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
          <div>
            <p className="text-sm font-medium text-gray-900">{selectedFile.name}</p>
            <p className="text-xs text-gray-500 mt-1">{(selectedFile.size / 1024).toFixed(1)} KB</p>
          </div>
        ) : (
          <div>
            <ArrowUpTrayIcon className="h-8 w-8 mx-auto text-gray-400" />
            <p className="mt-2 text-sm text-gray-600">
              Click to select, or drag and drop a CSV file
            </p>
            <p className="mt-1 text-xs text-gray-400">Up to 100,000 companies per upload</p>
          </div>
        )}
      </div>

      <div className="flex justify-end mt-4">
        <Button
          icon={MagnifyingGlassCircleIcon}
          onClick={onSubmit}
          loading={loading}
          disabled={!selectedFile}
        >
          Find emails
        </Button>
      </div>
    </>
  )
}
