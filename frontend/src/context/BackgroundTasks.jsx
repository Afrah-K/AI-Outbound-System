import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { api } from '../services/apiClient'

/**
 * App-wide tracker for long-running server jobs (scrapes, enrichment,
 * verification, personalization). Lives above the routes, so a job keeps
 * being polled - and its results saved - while you're on other pages.
 *
 * Each source has at most one tracked job (the latest). On completion the
 * result is written to the same localStorage key the source's page already
 * reads its results from, so the page shows it whenever you go back.
 */

const STORAGE_KEY = 'background_tasks'
const POLL_INTERVAL_MS = 1500

function readStorage(key) {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function writeStorage(key, value) {
  try {
    if (value === null || value === undefined) localStorage.removeItem(key)
    else localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // ignore - e.g. private browsing, or the result is too big to cache
  }
}

export const TASK_SOURCES = {
  clutch: {
    label: 'Clutch scrape',
    path: '/scrapers',
    unit: 'pages',
    poll: (id) => api.scrapers.getJob(id),
    cacheKey: 'scraper_last_results',
    toCache: (job) => ({ rows: job.result.rows, stats: job.result.stats }),
    summary: (job) => `${job.result.count} leads found`,
  },
  awwwards: {
    label: 'Awwwards scrape',
    path: '/scrapers',
    unit: 'requests',
    poll: (id) => api.scrapers.getJob(id),
    cacheKey: 'scraper_last_results_awwwards',
    toCache: (job) => ({ rows: job.result.rows, stats: job.result.stats }),
    summary: (job) => `${job.result.count} studios found`,
  },
  google_maps: {
    label: 'Google Maps search',
    path: '/scrapers',
    unit: 'requests',
    poll: (id) => api.scrapers.getJob(id),
    cacheKey: 'scraper_last_results_google_maps',
    toCache: (job) => ({ rows: job.result.rows, stats: job.result.stats }),
    summary: (job) => `${job.result.count} businesses found`,
  },
  enricher: {
    label: 'Email enrichment',
    path: '/enricher',
    unit: 'companies',
    poll: (id) => api.leads.getEnrichJob(id),
    cacheKey: 'enricher_last_job',
    toCache: (job) => job,
    // The page renders the job object itself, so keep its cache current while running
    cacheWhileRunning: true,
    summary: (job) => `${job.emails_found} emails found across ${job.total} companies`,
  },
  verifier: {
    label: 'List verification',
    path: '/verifier',
    unit: 'emails',
    poll: (id) => api.leads.getVerifyJob(id),
    cacheKey: 'verifier_last_results',
    toCache: (job) => job.result,
    summary: (job) => `${job.result.after_dedupe} clean leads, ${job.result.estimated_bounce_rate}% est. bounce rate`,
    warning: (job) =>
      job.result.over_safe_threshold
        ? `Estimated bounce rate ${job.result.estimated_bounce_rate}% is over the ${job.result.safe_threshold}% safe threshold`
        : null,
  },
  personalizer: {
    label: 'Personalization',
    path: '/personalizer',
    unit: 'leads',
    poll: (id) => api.leads.getPersonalizeJob(id),
    cacheKey: 'personalizer_last_job',
    toCache: (job) => job,
    cacheWhileRunning: true,
    summary: (job) => `${job.total} emails drafted`,
  },
}

// Pages that render a cached job object would otherwise show it as running forever
function markCachedJobFailed(config, error) {
  if (!config.cacheWhileRunning) return
  const cached = readStorage(config.cacheKey)
  if (cached?.status === 'running') writeStorage(config.cacheKey, { ...cached, status: 'failed', error })
}

const BackgroundTasksContext = createContext(null)

// Only metadata is persisted - results go to each source's own cache key
function persistable(tasks) {
  return Object.fromEntries(
    Object.entries(tasks).map(([source, { data, ...meta }]) => [source, meta])
  )
}

function fromJob(job) {
  return {
    status: job.status,
    processed: job.processed ?? 0,
    total: job.total ?? 0,
    message: job.message || '',
    error: job.error || null,
  }
}

export function BackgroundTasksProvider({ children }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [tasks, setTasks] = useState(() => readStorage(STORAGE_KEY) || {})
  const tasksRef = useRef(tasks)
  const pathRef = useRef(location.pathname)
  const pollingRef = useRef(false)

  tasksRef.current = tasks
  pathRef.current = location.pathname

  useEffect(() => {
    writeStorage(STORAGE_KEY, persistable(tasks))
  }, [tasks])

  const updateTask = useCallback((source, patch) => {
    setTasks((prev) => (prev[source] ? { ...prev, [source]: { ...prev[source], ...patch } } : prev))
  }, [])

  const notify = useCallback(
    (source, kind, text) => {
      const config = TASK_SOURCES[source]
      const awayFromPage = pathRef.current !== config.path
      const show = kind === 'success' ? toast.success : toast.error
      const verb = { success: 'finished', warning: 'finished with a warning', error: 'failed' }[kind]
      show(
        (t) => (
          <span className="flex items-center gap-3">
            <span>
              <strong className="font-medium">{config.label}</strong> {verb} - {text}
            </span>
            {awayFromPage && (
              <button
                type="button"
                onClick={() => {
                  toast.dismiss(t.id)
                  navigate(config.path)
                }}
                className="shrink-0 rounded-full bg-white/15 px-2.5 py-1 text-xs font-medium hover:bg-white/25"
              >
                View
              </button>
            )}
          </span>
        ),
        { duration: awayFromPage ? 10000 : 5000 }
      )
    },
    [navigate]
  )

  const pollOnce = useCallback(async () => {
    if (pollingRef.current) return
    const running = Object.entries(tasksRef.current).filter(([, t]) => t.status === 'running')
    if (running.length === 0) return
    pollingRef.current = true

    try {
      await Promise.all(
        running.map(async ([source, task]) => {
          const config = TASK_SOURCES[source]
          if (!config) return
          let job
          try {
            job = (await config.poll(task.jobId)).data
          } catch (error) {
            if (error.response?.status === 404) {
              const lost = 'Lost track of this job - the API server was restarted'
              markCachedJobFailed(config, lost)
              updateTask(source, { status: 'failed', error: lost, finishedAt: Date.now() })
              notify(source, 'error', lost)
            }
            return // other errors: transient, retry next tick
          }

          // A newer job may have replaced this one while the request was in flight
          if (tasksRef.current[source]?.jobId !== task.jobId) return

          if (job.status === 'completed') {
            writeStorage(config.cacheKey, config.toCache(job))
            updateTask(source, { ...fromJob(job), data: null, finishedAt: Date.now(), summary: config.summary(job) })
            const warning = config.warning?.(job)
            if (warning) notify(source, 'warning', warning)
            else notify(source, 'success', config.summary(job))
          } else if (job.status === 'failed') {
            if (config.cacheWhileRunning) writeStorage(config.cacheKey, config.toCache(job))
            updateTask(source, { ...fromJob(job), data: null, finishedAt: Date.now() })
            notify(source, 'error', job.error || 'something went wrong')
          } else {
            if (config.cacheWhileRunning) writeStorage(config.cacheKey, config.toCache(job))
            updateTask(source, { ...fromJob(job), data: job })
          }
        })
      )
    } finally {
      pollingRef.current = false
    }
  }, [notify, updateTask])

  const hasRunning = Object.values(tasks).some((t) => t.status === 'running')

  useEffect(() => {
    if (!hasRunning) return
    pollOnce()
    const interval = setInterval(pollOnce, POLL_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [hasRunning, pollOnce])

  /** Register a job the server just started. `job` is the start endpoint's response. */
  const startTask = useCallback((source, job, { label } = {}) => {
    const config = TASK_SOURCES[source]
    if (config.cacheWhileRunning) writeStorage(config.cacheKey, config.toCache(job))
    setTasks((prev) => ({
      ...prev,
      [source]: {
        source,
        jobId: job.job_id,
        label: label || config.label,
        path: config.path,
        startedAt: Date.now(),
        finishedAt: null,
        summary: null,
        seen: false,
        ...fromJob({ ...job, status: 'running' }),
        data: job,
      },
    }))
  }, [])

  const dismissTask = useCallback((source) => {
    setTasks((prev) => {
      const { [source]: _removed, ...rest } = prev
      return rest
    })
  }, [])

  const markSeen = useCallback(() => {
    setTasks((prev) => {
      const unseen = Object.entries(prev).filter(([, t]) => t.status !== 'running' && !t.seen)
      if (unseen.length === 0) return prev
      const next = { ...prev }
      unseen.forEach(([source, t]) => { next[source] = { ...t, seen: true } })
      return next
    })
  }, [])

  const value = useMemo(
    () => ({ tasks, startTask, dismissTask, markSeen }),
    [tasks, startTask, dismissTask, markSeen]
  )

  return <BackgroundTasksContext.Provider value={value}>{children}</BackgroundTasksContext.Provider>
}

export function useBackgroundTasks() {
  const ctx = useContext(BackgroundTasksContext)
  if (!ctx) throw new Error('useBackgroundTasks must be used inside BackgroundTasksProvider')
  return ctx
}

/**
 * A page's view of its source's latest job.
 *
 * - onProgress(job): latest poll payload while it runs
 * - onComplete(): the job finished and its result is in the page's cache key -
 *   re-read it. Also fires on mount for an already-finished job, which is
 *   harmless since the cache is the source of truth.
 * - onFail(error): the job failed (also re-fires on mount, like onComplete)
 */
export function useTask(source, { onProgress, onComplete, onFail } = {}) {
  const { tasks, startTask } = useBackgroundTasks()
  const task = tasks[source] || null
  const progressRef = useRef(onProgress)
  const completeRef = useRef(onComplete)
  const failRef = useRef(onFail)
  progressRef.current = onProgress
  completeRef.current = onComplete
  failRef.current = onFail

  useEffect(() => {
    if (task?.status === 'running' && task.data) progressRef.current?.(task.data)
  }, [task?.status, task?.data])

  useEffect(() => {
    if (task?.status === 'completed' && task.finishedAt) completeRef.current?.()
    if (task?.status === 'failed' && task.finishedAt) failRef.current?.(task.error)
  }, [task?.status, task?.finishedAt])

  const start = useCallback((job, options) => startTask(source, job, options), [source, startTask])

  return {
    task,
    isRunning: task?.status === 'running',
    start,
  }
}
