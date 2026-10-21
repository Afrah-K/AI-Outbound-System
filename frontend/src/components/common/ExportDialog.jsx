import { useEffect, useState } from 'react'
import { ArrowDownTrayIcon } from '@heroicons/react/24/outline'
import Button from './Button'
import { toFileName } from '../../utils/listNames'

/**
 * "Save as" for a CSV export: shows the suggested name (also what the lead list
 * will be called if the file is imported later), editable before downloading.
 * onExport(fileName, name) does the actual download.
 */
export default function ExportDialog({ open, defaultName, count, onExport, onClose }) {
  const [name, setName] = useState(defaultName)

  useEffect(() => {
    if (open) setName(defaultName)
  }, [open, defaultName])

  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto" role="dialog" aria-modal="true" aria-labelledby="export-dialog-title">
      <div className="flex min-h-full items-center justify-center p-4">
        <div className="fixed inset-0 bg-gray-900/40" onClick={onClose} />
        <form
          className="relative w-full max-w-md rounded-card bg-white p-6 shadow-xl"
          onSubmit={(e) => {
            e.preventDefault()
            if (!name.trim()) return
            onExport(toFileName(name.trim()), name.trim())
            onClose()
          }}
        >
          <h3 id="export-dialog-title" className="text-lg font-medium tracking-tight text-gray-900">
            Export {count} row{count === 1 ? '' : 's'}
          </h3>
          <label htmlFor="export-name" className="mt-4 block text-sm font-medium text-gray-700">Name</label>
          <input
            id="export-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={120}
            autoFocus
            onFocus={(e) => e.target.select()}
            className="mt-1 w-full rounded-xl border border-gray-200 px-3 py-2 text-sm focus:border-primary-500 focus:ring-2 focus:ring-primary-500"
          />
          <p className="mt-1.5 text-xs text-gray-500">
            Saved as <span className="font-mono">{toFileName(name.trim())}</span>. Import it on Prospects later and the lead list
            gets this name too.
          </p>
          <div className="mt-6 flex justify-end gap-3">
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" icon={ArrowDownTrayIcon} disabled={!name.trim()}>
              Download
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
