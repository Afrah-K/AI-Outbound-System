import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  CheckCircleIcon,
  ExclamationCircleIcon,
  QueueListIcon,
  XMarkIcon,
} from '@heroicons/react/24/outline'
import { TASK_SOURCES, useBackgroundTasks } from '../../context/BackgroundTasks'

function formatElapsed(ms) {
  const seconds = Math.max(0, Math.floor(ms / 1000))
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}:${String(s).padStart(2, '0')}`
}

function Spinner({ className = 'h-4 w-4' }) {
  return (
    <svg className={`animate-spin ${className}`} fill="none" viewBox="0 0 24 24" aria-hidden="true">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  )
}

function TaskRow({ task, now, onDismiss, onNavigate }) {
  const unit = TASK_SOURCES[task.source]?.unit || 'items'
  const running = task.status === 'running'
  const percent = task.total ? Math.min(100, Math.round((task.processed / task.total) * 100)) : null
  const elapsed = (task.finishedAt || now) - task.startedAt

  return (
    <li className="px-4 py-3">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 shrink-0">
          {running && <Spinner className="h-4 w-4 text-primary-600" />}
          {task.status === 'completed' && <CheckCircleIcon className="h-4 w-4 text-green-600" />}
          {task.status === 'failed' && <ExclamationCircleIcon className="h-4 w-4 text-red-600" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <Link to={task.path} onClick={onNavigate} className="truncate text-sm font-medium text-gray-900 hover:underline">
              {task.label}
            </Link>
            <span className="shrink-0 text-xs tabular-nums text-gray-500">{formatElapsed(elapsed)}</span>
          </div>
          <p className="mt-0.5 truncate text-xs text-gray-500">
            {running && (task.message || (task.total ? `${task.processed} of ${task.total} ${unit}` : 'Starting...'))}
            {task.status === 'completed' && (task.summary || 'Done')}
            {task.status === 'failed' && <span className="text-red-600">{task.error || 'Failed'}</span>}
          </p>
          {running && (
            <div className="mt-2 flex items-center gap-2">
              <div className="h-1 flex-1 overflow-hidden rounded-full bg-gray-100">
                <div
                  className={`h-full rounded-full bg-primary-500 transition-[width] duration-500 ${percent === null ? 'w-1/3 animate-pulse' : ''}`}
                  style={percent === null ? undefined : { width: `${Math.max(percent, 3)}%` }}
                />
              </div>
              {task.total > 0 && (
                <span className="shrink-0 text-[11px] tabular-nums text-gray-500">
                  {task.processed}/{task.total}
                </span>
              )}
            </div>
          )}
        </div>
        {!running && (
          <button
            type="button"
            onClick={onDismiss}
            className="shrink-0 rounded p-0.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            aria-label={`Dismiss ${task.label}`}
          >
            <XMarkIcon className="h-4 w-4" />
          </button>
        )}
      </div>
    </li>
  )
}

/**
 * Header button listing background jobs (running and recently finished) so
 * you can see and jump back to them from any page.
 */
export default function TasksMenu() {
  const { tasks, dismissTask, markSeen } = useBackgroundTasks()
  const [open, setOpen] = useState(false)
  const [now, setNow] = useState(Date.now())
  const menuRef = useRef(null)

  const list = Object.values(tasks).sort((a, b) => b.startedAt - a.startedAt)
  const running = list.filter((t) => t.status === 'running')
  const unseen = list.filter((t) => t.status !== 'running' && !t.seen)
  const unseenFailed = unseen.some((t) => t.status === 'failed')

  // Tick the elapsed timers while something runs or the menu is open
  useEffect(() => {
    if (running.length === 0 && !open) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [running.length, open])

  useEffect(() => {
    if (open) markSeen()
  }, [open, markSeen, unseen.length])

  useEffect(() => {
    if (!open) return
    const onClick = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setOpen(false)
    }
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (list.length === 0) return null

  return (
    <div className="relative" ref={menuRef}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={`relative flex items-center gap-2 rounded-full bg-white px-4 py-2 text-sm ${
          running.length ? 'text-primary-700' : 'text-gray-600 hover:text-gray-900'
        }`}
        aria-expanded={open}
        aria-haspopup="true"
      >
        {running.length > 0 ? <Spinner className="h-4 w-4" /> : <QueueListIcon className="h-4 w-4" />}
        <span className="font-medium">
          {running.length > 0 ? `${running.length} running` : 'Tasks'}
        </span>
        {unseen.length > 0 && (
          <span
            className={`absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full ring-2 ring-canvas ${unseenFailed ? 'bg-red-500' : 'bg-green-500'}`}
            aria-label={`${unseen.length} finished`}
          />
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-30 mt-2 w-96 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
            <p className="text-sm font-medium text-gray-900">Background tasks</p>
            <p className="text-xs text-gray-500">Keep running while you use other pages</p>
          </div>
          <ul className="max-h-96 divide-y divide-gray-100 overflow-y-auto">
            {list.map((task) => (
              <TaskRow
                key={task.source}
                task={task}
                now={now}
                onDismiss={() => dismissTask(task.source)}
                onNavigate={() => setOpen(false)}
              />
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
