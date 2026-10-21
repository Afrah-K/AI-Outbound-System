import { useEffect } from 'react'
import { ExclamationTriangleIcon } from '@heroicons/react/24/outline'
import Button from './Button'

/**
 * "Are you sure?" modal for destructive actions. Escape or clicking outside
 * cancels; focus starts on Cancel so Enter doesn't confirm by accident.
 */
export default function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel = 'Delete',
  cancelLabel = 'Cancel',
  onConfirm,
  onCancel,
  loading = false,
  confirmDisabled = false,
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && !loading && onCancel()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, loading, onCancel])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto" role="alertdialog" aria-modal="true" aria-labelledby="confirm-dialog-title">
      <div className="flex min-h-full items-center justify-center p-4">
        <div className="fixed inset-0 bg-gray-900/40" onClick={() => !loading && onCancel()} />
        <div className="relative bg-white rounded-card shadow-xl max-w-md w-full p-6">
          <div className="flex gap-4">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-red-100">
              <ExclamationTriangleIcon className="h-5 w-5 text-red-600" />
            </div>
            <div className="min-w-0 flex-1">
              <h3 id="confirm-dialog-title" className="text-lg font-medium tracking-tight text-gray-900">
                {title}
              </h3>
              <div className="mt-2 space-y-2 text-sm text-gray-600">{children}</div>
            </div>
          </div>
          <div className="mt-6 flex justify-end gap-3">
            <Button autoFocus variant="secondary" onClick={onCancel} disabled={loading}>
              {cancelLabel}
            </Button>
            <Button variant="danger" onClick={onConfirm} loading={loading} disabled={confirmDisabled}>
              {confirmLabel}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
