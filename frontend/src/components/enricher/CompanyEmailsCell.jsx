import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { CheckCircleIcon, EnvelopeIcon, PencilSquareIcon, PlusIcon, XCircleIcon, XMarkIcon } from '@heroicons/react/24/outline'
import toast from 'react-hot-toast'
import { api } from '../../services/apiClient'

/**
 * The "Emails found" cell of an Enricher result, editable by hand: add emails
 * you found yourself (LinkedIn, a site the Enricher couldn't read), fix typos,
 * remove wrong ones. Saving replaces the company's emails; onSaved(result)
 * gets { emails, status, unpicked_emails, kept_as_prospects }.
 */
export default function CompanyEmailsCell({ row, onSaved }) {
  const [editing, setEditing] = useState(false)
  const [drafts, setDrafts] = useState([])
  const domain = (row.website || '').replace(/^https?:\/\//, '').replace(/^www\./, '').split('/')[0]

  const startEditing = () => {
    // Each draft remembers the email it started as, so a fixed typo keeps its prospect
    const existing = row.emails.map((email) => ({ email, previous: email }))
    setDrafts(existing.length ? existing : [{ email: '', previous: null }])
    setEditing(true)
  }

  const setDraft = (i, email) => setDrafts((prev) => prev.map((d, j) => (j === i ? { ...d, email } : d)))
  const removeDraft = (i) => setDrafts((prev) => prev.filter((_, j) => j !== i))
  const addDraft = () => setDrafts((prev) => [...prev, { email: '', previous: null }])

  const saveMutation = useMutation({
    mutationFn: () =>
      api.leads.setCompanyEmails(
        row.company_id,
        drafts.filter((d) => d.email.trim()).map((d) => ({ email: d.email.trim(), previous: d.previous }))
      ),
    onSuccess: (response) => {
      const result = response.data
      onSaved(result)
      setEditing(false)
      toast.success(`Saved ${result.emails.length} email${result.emails.length === 1 ? '' : 's'} for ${row.name}`)
      if (result.kept_as_prospects) {
        toast(`${result.kept_as_prospects} removed email${result.kept_as_prospects === 1 ? ' was' : 's were'} already contacted, so kept in Prospects`, {
          icon: 'ℹ️',
          duration: 6000,
        })
      }
    },
    onError: (error) => toast.error(error.response?.data?.detail || 'Could not save the emails'),
  })

  if (editing) {
    return (
      <form
        className="space-y-1.5"
        onSubmit={(e) => {
          e.preventDefault()
          if (!saveMutation.isPending) saveMutation.mutate()
        }}
        onKeyDown={(e) => e.key === 'Escape' && setEditing(false)}
      >
        {drafts.map((d, i) => (
          <div key={i} className="flex items-center gap-1">
            <input
              type="email"
              value={d.email}
              onChange={(e) => setDraft(i, e.target.value)}
              placeholder={`name@${domain || 'company.com'}`}
              aria-label={`Email ${i + 1} for ${row.name}`}
              autoFocus={i === drafts.length - 1}
              className="w-64 rounded-lg border-gray-300 px-2 py-1 text-xs shadow-sm focus:border-primary-500 focus:ring-primary-500"
            />
            <button
              type="button"
              onClick={() => removeDraft(i)}
              className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-red-600"
              aria-label={`Remove ${d.email || 'this email'}`}
              title="Remove"
            >
              <XMarkIcon className="h-4 w-4" />
            </button>
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-1 pt-0.5">
          <button
            type="button"
            onClick={addDraft}
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-primary-600 hover:bg-primary-50"
          >
            <PlusIcon className="h-3 w-3" />
            Add another
          </button>
          <span className="flex-1" />
          <button type="button" onClick={() => setEditing(false)} className="rounded-lg px-2 py-1 text-xs text-gray-500 hover:bg-gray-100">
            Cancel
          </button>
          <button
            type="submit"
            disabled={saveMutation.isPending}
            className="rounded-lg bg-primary-600 px-3 py-1 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
          >
            {saveMutation.isPending ? 'Saving...' : 'Save'}
          </button>
        </div>
      </form>
    )
  }

  const editButton = row.company_id && (
    <button
      type="button"
      onClick={startEditing}
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium text-primary-600 hover:bg-primary-50 hover:text-primary-800"
    >
      {row.emails.length ? <PencilSquareIcon className="h-3 w-3" /> : <PlusIcon className="h-3 w-3" />}
      {row.emails.length ? 'Edit' : 'Add email'}
    </button>
  )

  if (row.emails.length === 0) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-gray-400">
        <XCircleIcon className="h-4 w-4 shrink-0" />
        {row.error || 'No public email found'}
        {editButton}
      </div>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <CheckCircleIcon className="h-4 w-4 text-green-500 shrink-0" />
      <div className="flex flex-wrap gap-1">
        {row.emails.map((email) => (
          <span key={email} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
            <EnvelopeIcon className="h-3 w-3" />
            {email}
          </span>
        ))}
        {editButton}
      </div>
    </div>
  )
}
