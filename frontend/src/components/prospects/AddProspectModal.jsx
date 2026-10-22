import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { UserPlusIcon, XMarkIcon } from '@heroicons/react/24/outline'
import toast from 'react-hot-toast'
import { api } from '../../services/apiClient'
import Button from '../common/Button'

const EMPTY = {
  email: '',
  first_name: '',
  last_name: '',
  role: '',
  company_name: '',
  website: '',
  linkedin_url: '',
  phone: '',
}

const MANUAL_LIST_NAME = 'Added manually'

const inputClass =
  'mt-1 w-full rounded-xl border border-gray-200 px-3 py-2 text-sm focus:border-primary-500 focus:ring-2 focus:ring-primary-500'

function Field({ id, label, hint, ...props }) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-gray-700">
        {label}
        {hint && <span className="ml-1 font-normal text-gray-400">{hint}</span>}
      </label>
      <input id={id} className={inputClass} {...props} />
    </div>
  )
}

/**
 * Add one prospect by hand. Only the email is required; a company is matched
 * by website or name (or created). It goes in the chosen lead list, else "Added manually".
 * onAdded(result) gets { id, email, company, list_id, list_name }.
 */
export default function AddProspectModal({ lists, defaultListId, onClose, onAdded }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState(EMPTY)
  // '' = the "Added manually" list (the backend finds or creates it)
  const [listId, setListId] = useState(() => {
    const current = (lists || []).find((l) => String(l.id) === String(defaultListId))
    return current && current.name !== MANUAL_LIST_NAME ? String(current.id) : ''
  })
  const set = (key) => (e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const addMutation = useMutation({
    mutationFn: (addAnother) =>
      api.leads.createPerson({ ...form, list_id: listId ? Number(listId) : null }).then((r) => ({ ...r.data, addAnother })),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['people'] })
      queryClient.invalidateQueries({ queryKey: ['leadLists'] })
      toast.success(`Added ${result.email}${result.list_name ? ` to "${result.list_name}"` : ''}`)
      onAdded?.(result)
      if (result.addAnother) {
        // Keep the company and list - the next one is often a colleague
        setForm((prev) => ({ ...EMPTY, company_name: prev.company_name, website: prev.website }))
        document.getElementById('prospect-email')?.focus()
      } else {
        onClose()
      }
    },
    onError: (error) => toast.error(error.response?.data?.detail || 'Could not add this prospect'),
  })

  const submit = (addAnother) => {
    if (form.email.trim() && !addMutation.isPending) addMutation.mutate(addAnother)
  }

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto" role="dialog" aria-modal="true" aria-labelledby="add-prospect-title">
      <div className="flex min-h-full items-center justify-center p-4">
        <div className="fixed inset-0 bg-gray-900/40" onClick={onClose} />
        <form
          className="relative w-full max-w-lg rounded-card bg-white p-6 shadow-xl"
          onSubmit={(e) => {
            e.preventDefault()
            submit(false)
          }}
        >
          <div className="flex items-center justify-between">
            <h3 id="add-prospect-title" className="text-lg font-medium tracking-tight text-gray-900">
              Add a prospect
            </h3>
            <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close">
              <XMarkIcon className="h-5 w-5" />
            </button>
          </div>
          <p className="mt-1 text-sm text-gray-600">Only the email is required.</p>

          <div className="mt-4 space-y-3">
            <Field id="prospect-email" label="Email" type="email" value={form.email} onChange={set('email')} autoFocus required maxLength={255} />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field id="prospect-first" label="First name" value={form.first_name} onChange={set('first_name')} maxLength={100} />
              <Field id="prospect-last" label="Last name" value={form.last_name} onChange={set('last_name')} maxLength={100} />
              <Field id="prospect-company" label="Company" value={form.company_name} onChange={set('company_name')} maxLength={255} />
              <Field id="prospect-website" label="Website" placeholder="company.com" value={form.website} onChange={set('website')} maxLength={512} />
              <Field id="prospect-role" label="Job title" value={form.role} onChange={set('role')} maxLength={255} />
              <Field id="prospect-phone" label="Phone" type="tel" value={form.phone} onChange={set('phone')} maxLength={50} />
            </div>
            <Field id="prospect-linkedin" label="LinkedIn" placeholder="linkedin.com/in/..." value={form.linkedin_url} onChange={set('linkedin_url')} maxLength={512} />
            <div>
              <label htmlFor="prospect-list" className="block text-sm font-medium text-gray-700">Lead list</label>
              <select id="prospect-list" value={listId} onChange={(e) => setListId(e.target.value)} className={inputClass}>
                <option value="">{MANUAL_LIST_NAME}</option>
                {(lists || []).filter((l) => l.name !== MANUAL_LIST_NAME).map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="mt-6 flex flex-wrap justify-end gap-3">
            <Button type="button" variant="secondary" onClick={onClose} disabled={addMutation.isPending}>
              Cancel
            </Button>
            <Button type="button" variant="secondary" onClick={() => submit(true)} disabled={!form.email.trim() || addMutation.isPending}>
              Add &amp; add another
            </Button>
            <Button type="submit" icon={UserPlusIcon} loading={addMutation.isPending} disabled={!form.email.trim()}>
              Add prospect
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
