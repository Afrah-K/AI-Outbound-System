import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  ShieldCheckIcon,
  ArrowUpTrayIcon,
  ArrowDownTrayIcon,
  ExclamationTriangleIcon,
  CheckCircleIcon,
  XCircleIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  SparklesIcon,
} from '@heroicons/react/24/outline'
import { api } from '../services/apiClient'
import { useTask } from '../context/BackgroundTasks'
import Button from '../components/common/Button'
import Card from '../components/common/Card'
import LoadingSpinner from '../components/common/LoadingSpinner'
import EmptyState from '../components/common/EmptyState'
import toast from 'react-hot-toast'

const RESULTS_PAGE_SIZE = 40
const CACHE_KEY = 'verifier_last_results'

function loadCached() {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function saveCached(data) {
  try {
    if (data) localStorage.setItem(CACHE_KEY, JSON.stringify(data))
    else localStorage.removeItem(CACHE_KEY)
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

  const grouped = new Map()
  for (const line of lines.slice(1)) {
    if (!line.trim()) continue
    const values = splitCSVLine(line)
    const row = {}
    header.forEach((h, i) => { row[h] = (values[i] || '').trim() })

    const email = row.email || row['email address'] || ''
    if (!email) continue
    const name = row.company || row.name || row.company_name || ''
    const website = row.website || row.domain || ''
    const key = `${name}|${website}`

    if (!grouped.has(key)) grouped.set(key, { company_id: null, name, website, emails: [] })
    grouped.get(key).emails.push(email)
  }
  return Array.from(grouped.values())
}

function rowsToCSV(rows) {
  const header = ['company_name', 'website', 'email', 'segment', 'deliverable', 'reason']
  const lines = rows.map((r) => header.map((k) => `"${String(r[k] ?? '').replace(/"/g, '""')}"`).join(','))
  return [header.join(','), ...lines].join('\n')
}

function downloadCSV(rows, filename) {
  const blob = new Blob([rowsToCSV(rows)], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export default function VerifierPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const fileInputRef = useRef(null)
  const autoRunTriggered = useRef(false)

  const [summary, setSummary] = useState(loadCached)
  const [rows, setRows] = useState(() => loadCached()?.rows || [])
  const [hideRisky, setHideRisky] = useState(false)
  const [resultsPage, setResultsPage] = useState(1)
  const [selectedFile, setSelectedFile] = useState(null)
  const [dragActive, setDragActive] = useState(false)

  const incomingResults = location.state?.enrichResults

  // Runs as a server-side job tracked app-wide, so verification keeps going
  // while you're on other pages; the tracker caches the summary under CACHE_KEY.
  const { task, isRunning: jobRunning, start } = useTask('verifier', {
    onComplete: () => {
      const cached = loadCached()
      if (!cached) return
      setSummary(cached)
      setRows(cached.rows || [])
      setResultsPage(1)
    },
  })

  const verifyMutation = useMutation({
    mutationFn: (results) => api.leads.startVerifyJob(results),
    onSuccess: (response) => {
      start(response.data, { label: `Verifying ${response.data.total} address${response.data.total === 1 ? '' : 'es'}` })
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || 'Could not start verification')
    },
  })

  useEffect(() => {
    if (!incomingResults?.length || autoRunTriggered.current) return
    autoRunTriggered.current = true

    const forVerify = incomingResults
      .filter((r) => r.emails?.length > 0)
      .map((r) => ({ company_id: r.company_id, name: r.name, website: r.website, emails: r.emails }))
    verifyMutation.mutate(forVerify)

    navigate(location.pathname, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incomingResults])

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

  const handleUploadVerify = async () => {
    if (!selectedFile) return
    const text = await selectedFile.text()
    const results = parseLeadsCSV(text)
    if (results.length === 0) {
      toast.error('No email column found - expected a "email" column, plus optional company/website')
      return
    }
    verifyMutation.mutate(results)
  }

  const updateSegment = (email, segment) => {
    setRows((prev) => {
      const next = prev.map((r) => (r.email === email ? { ...r, segment } : r))
      saveCached({ ...summary, rows: next })
      return next
    })
  }

  const cameFromEnricher = Boolean(incomingResults?.length) || autoRunTriggered.current
  const isRunning = verifyMutation.isPending || jobRunning
  const visibleRows = hideRisky ? rows.filter((r) => r.deliverable) : rows
  const totalPages = Math.max(1, Math.ceil(visibleRows.length / RESULTS_PAGE_SIZE))
  const pageRows = visibleRows.slice((resultsPage - 1) * RESULTS_PAGE_SIZE, resultsPage * RESULTS_PAGE_SIZE)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-medium tracking-tight text-gray-900">Verifier</h1>
        <p className="mt-1 text-sm text-gray-500">
          Clean a list before it reaches a campaign - verify deliverability, dedupe, drop
          generic addresses where a personal one exists, and tag a segment per lead
        </p>
      </div>

      {cameFromEnricher ? (
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
              onSubmit={handleUploadVerify}
              loading={isRunning}
            />
          </Card>
        </details>
      ) : (
        <Card>
          <Card.Header>
            <Card.Title>Upload a list</Card.Title>
            <Card.Description>
              CSV with an "email" column, plus optional company/name and website columns.
            </Card.Description>
          </Card.Header>
          <UploadCard
            fileInputRef={fileInputRef}
            selectedFile={selectedFile}
            dragActive={dragActive}
            setDragActive={setDragActive}
            handleFile={handleFile}
            handleDrop={handleDrop}
            onSubmit={handleUploadVerify}
            loading={isRunning}
          />
        </Card>
      )}

      {isRunning && (
        <Card>
          <div className="flex flex-col items-center justify-center py-12 gap-3">
            <LoadingSpinner size="lg" />
            <p className="text-sm text-gray-500">
              {task?.total ? `Checked ${task.processed} of ${task.total} addresses` : 'Checking deliverability for each address...'}
            </p>
            {task?.total > 0 && (
              <div className="w-64 bg-gray-200 rounded-full h-2">
                <div
                  className="bg-primary-600 h-2 rounded-full transition-all"
                  style={{ width: `${Math.round((task.processed / task.total) * 100)}%` }}
                />
              </div>
            )}
            <p className="text-xs text-gray-400">Runs in the background - you can use other pages meanwhile</p>
          </div>
        </Card>
      )}

      {!isRunning && summary && (
        <>
          {summary.over_safe_threshold && (
            <div className="flex gap-2 rounded-lg bg-red-50 border border-red-200 p-3">
              <ExclamationTriangleIcon className="h-5 w-5 text-red-500 shrink-0" />
              <p className="text-sm text-red-800">
                Estimated bounce rate is <strong>{summary.estimated_bounce_rate}%</strong>, above the
                {' '}{summary.safe_threshold}% level that risks burning your sending domain's reputation.
                Consider hiding risky emails below before exporting.
              </p>
            </div>
          )}

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
            <Card>
              <p className="text-xs text-gray-500">Input emails</p>
              <p className="mt-1 text-xl font-bold text-gray-900">{summary.total_input_emails}</p>
            </Card>
            <Card>
              <p className="text-xs text-gray-500">After generic filter</p>
              <p className="mt-1 text-xl font-bold text-gray-900">{summary.after_generic_filter}</p>
            </Card>
            <Card>
              <p className="text-xs text-gray-500">After dedupe</p>
              <p className="mt-1 text-xl font-bold text-gray-900">{summary.after_dedupe}</p>
            </Card>
            <Card>
              <p className="text-xs text-gray-500">Deliverable</p>
              <p className="mt-1 text-xl font-bold text-green-600">{summary.deliverable_count}</p>
            </Card>
            <Card>
              <p className="text-xs text-gray-500">Risky</p>
              <p className="mt-1 text-xl font-bold text-red-600">{summary.risky_count}</p>
            </Card>
            <Card>
              <p className="text-xs text-gray-500">Est. bounce rate</p>
              <p className={`mt-1 text-xl font-bold ${summary.over_safe_threshold ? 'text-red-600' : 'text-green-600'}`}>
                {summary.estimated_bounce_rate}%
              </p>
            </Card>
          </div>

          <Card padding={false}>
            <div className="flex flex-wrap items-center justify-between gap-3 p-6 pb-0">
              <Card.Title>Clean list ({visibleRows.length})</Card.Title>
              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={hideRisky}
                    onChange={(e) => { setHideRisky(e.target.checked); setResultsPage(1) }}
                    className="h-4 w-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500"
                  />
                  Hide risky emails
                </label>
                <Button
                  variant="secondary"
                  size="sm"
                  icon={ArrowDownTrayIcon}
                  onClick={() => downloadCSV(visibleRows, 'verified_leads.csv')}
                >
                  Export CSV
                </Button>
                <Button
                  size="sm"
                  icon={SparklesIcon}
                  onClick={() => navigate('/personalizer', { state: { verifiedRows: visibleRows } })}
                >
                  Personalize this list
                </Button>
              </div>
            </div>
            <div className="overflow-x-auto mt-4">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Company</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Email</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Segment</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Deliverable</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {pageRows.map((r) => (
                    <tr key={r.email} className="hover:bg-gray-50">
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                        {r.company_name || '-'}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{r.email}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm">
                        <select
                          value={r.segment}
                          onChange={(e) => updateSegment(r.email, e.target.value)}
                          className="rounded-md border-gray-300 text-xs focus:border-primary-500 focus:ring-primary-500"
                        >
                          <option value="studio">Studio</option>
                          <option value="bdr">BDR</option>
                        </select>
                      </td>
                      <td className="px-6 py-4 text-sm">
                        {r.deliverable ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                            <CheckCircleIcon className="h-3.5 w-3.5" />
                            Deliverable
                          </span>
                        ) : (
                          <div className="flex items-center gap-2">
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800">
                              <XCircleIcon className="h-3.5 w-3.5" />
                              Risky
                            </span>
                            <span className="text-xs text-gray-400">{r.reason}</span>
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
                <p className="text-sm text-gray-500">Page {resultsPage} of {totalPages}</p>
                <div className="flex gap-2">
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

      {!isRunning && !summary && (
        <Card>
          <EmptyState
            icon={ShieldCheckIcon}
            title="No results yet"
            description="Upload a CSV above, or send a list over from the Enricher page"
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
            <p className="mt-2 text-sm text-gray-600">Click to select, or drag and drop a CSV file</p>
          </div>
        )}
      </div>

      <div className="flex justify-end mt-4">
        <Button icon={ShieldCheckIcon} onClick={onSubmit} loading={loading} disabled={!selectedFile}>
          Verify list
        </Button>
      </div>
    </>
  )
}
