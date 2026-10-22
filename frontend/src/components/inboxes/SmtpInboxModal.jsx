import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ExclamationTriangleIcon, ServerStackIcon, XMarkIcon } from '@heroicons/react/24/outline'
import toast from 'react-hot-toast'
import { api, formatErrorDetail } from '../../services/apiClient'
import Button from '../common/Button'

// Server settings for common providers. Most need an app password (not the normal one).
export const PROVIDER_PRESETS = [
  {
    id: 'microsoft',
    label: 'Microsoft 365 / Outlook',
    smtp: ['smtp.office365.com', 587, 'starttls'],
    imap: ['outlook.office365.com', 993, 'ssl'],
    hint:
      'Heads-up: Microsoft has turned off password sign-in for IMAP on most Microsoft 365 and Outlook.com accounts, so this usually fails. It only works where your admin still allows basic authentication for IMAP and SMTP.',
  },
  {
    id: 'google',
    label: 'Google Workspace / Gmail (app password)',
    smtp: ['smtp.gmail.com', 465, 'ssl'],
    imap: ['imap.gmail.com', 993, 'ssl'],
    hint: 'Needs 2-Step Verification and an app password - or use "Connect Gmail" instead.',
  },
  {
    id: 'zoho',
    label: 'Zoho Mail',
    smtp: ['smtp.zoho.com', 465, 'ssl'],
    imap: ['imap.zoho.com', 993, 'ssl'],
    hint: 'EU accounts use smtp.zoho.eu / imap.zoho.eu. Turn on IMAP access in Zoho Mail settings.',
  },
  {
    id: 'yahoo',
    label: 'Yahoo Mail',
    smtp: ['smtp.mail.yahoo.com', 465, 'ssl'],
    imap: ['imap.mail.yahoo.com', 993, 'ssl'],
    hint: 'Generate an app password in your Yahoo account security settings.',
  },
  {
    id: 'icloud',
    label: 'iCloud Mail',
    smtp: ['smtp.mail.me.com', 587, 'starttls'],
    imap: ['imap.mail.me.com', 993, 'ssl'],
    hint: 'Use an app-specific password from appleid.apple.com.',
  },
  {
    id: 'fastmail',
    label: 'Fastmail',
    smtp: ['smtp.fastmail.com', 465, 'ssl'],
    imap: ['imap.fastmail.com', 993, 'ssl'],
    hint: 'Create an app password under Settings > Privacy & Security.',
  },
  {
    id: 'privateemail',
    label: 'Namecheap Private Email',
    smtp: ['mail.privateemail.com', 465, 'ssl'],
    imap: ['mail.privateemail.com', 993, 'ssl'],
  },
  { id: 'custom', label: 'Other / custom server', hint: 'Your provider lists these as "SMTP" and "IMAP" settings.' },
]

const DEFAULT_PORTS = { smtp: { ssl: 465, starttls: 587 }, imap: { ssl: 993, starttls: 143 } }

const EMPTY = {
  email_address: '',
  display_name: '',
  smtp_host: '',
  smtp_port: 465,
  smtp_security: 'ssl',
  imap_host: '',
  imap_port: 993,
  imap_security: 'ssl',
  username: '',
  password: '',
}

const inputClass =
  'mt-1 w-full rounded-xl border border-gray-200 px-3 py-2 text-sm focus:border-primary-500 focus:ring-2 focus:ring-primary-500'

function Field({ id, label, hint, className = '', ...props }) {
  return (
    <div className={className}>
      <label htmlFor={id} className="block text-sm font-medium text-gray-700">
        {label}
      </label>
      <input id={id} className={inputClass} {...props} />
      {hint && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
    </div>
  )
}

function ServerFields({ kind, form, setForm, failed }) {
  const prefix = kind === 'smtp' ? 'SMTP' : 'IMAP'
  const set = (key) => (e) => setForm((prev) => ({ ...prev, [`${kind}_${key}`]: e.target.value }))
  const setSecurity = (e) => {
    const security = e.target.value
    setForm((prev) => {
      const port = Number(prev[`${kind}_port`])
      // Switching between SSL and STARTTLS usually means switching to that one's standard port
      const isDefault = Object.values(DEFAULT_PORTS[kind]).includes(port)
      return { ...prev, [`${kind}_security`]: security, ...(isDefault ? { [`${kind}_port`]: DEFAULT_PORTS[kind][security] } : {}) }
    })
  }
  return (
    <fieldset className={`rounded-xl border p-3 ${failed ? 'border-red-300 bg-red-50/40' : 'border-gray-200'}`}>
      <legend className="px-1 text-sm font-medium text-gray-900">
        {prefix} <span className="font-normal text-gray-500">- {kind === 'smtp' ? 'sending' : 'reading replies'}</span>
      </legend>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-6">
        <Field
          id={`${kind}-host`}
          label="Server"
          className="sm:col-span-3"
          value={form[`${kind}_host`]}
          onChange={set('host')}
          placeholder={kind === 'smtp' ? 'smtp.example.com' : 'imap.example.com'}
          required
          autoComplete="off"
        />
        <Field
          id={`${kind}-port`}
          label="Port"
          className="sm:col-span-1"
          type="number"
          min={1}
          max={65535}
          value={form[`${kind}_port`]}
          onChange={set('port')}
          required
        />
        <div className="sm:col-span-2">
          <label htmlFor={`${kind}-security`} className="block text-sm font-medium text-gray-700">
            Security
          </label>
          <select id={`${kind}-security`} value={form[`${kind}_security`]} onChange={setSecurity} className={inputClass}>
            <option value="ssl">SSL/TLS</option>
            <option value="starttls">STARTTLS</option>
          </select>
        </div>
      </div>
    </fieldset>
  )
}

/**
 * Connect an inbox over SMTP + IMAP, or (with `inbox`) update one's settings
 * and password. The server tests both logins before saving and says which
 * one failed and why.
 */
export default function SmtpInboxModal({ inbox, onClose }) {
  const queryClient = useQueryClient()
  const editing = Boolean(inbox)
  const [form, setForm] = useState(() =>
    editing
      ? { ...EMPTY, ...inbox.smtp, email_address: inbox.email_address, display_name: inbox.display_name || '', password: '' }
      : EMPTY
  )
  const [presetId, setPresetId] = useState(editing ? 'custom' : '')
  const [error, setError] = useState(null) // { message, server }
  const preset = PROVIDER_PRESETS.find((p) => p.id === presetId)

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const applyPreset = (id) => {
    setPresetId(id)
    const chosen = PROVIDER_PRESETS.find((p) => p.id === id)
    if (!chosen?.smtp) return
    const [smtpHost, smtpPort, smtpSecurity] = chosen.smtp
    const [imapHost, imapPort, imapSecurity] = chosen.imap
    setForm((prev) => ({
      ...prev,
      smtp_host: smtpHost,
      smtp_port: smtpPort,
      smtp_security: smtpSecurity,
      imap_host: imapHost,
      imap_port: imapPort,
      imap_security: imapSecurity,
    }))
  }

  const saveMutation = useMutation({
    mutationFn: () => {
      const data = {
        ...form,
        smtp_port: Number(form.smtp_port),
        imap_port: Number(form.imap_port),
        username: form.username.trim() || form.email_address.trim(),
      }
      if (editing) {
        const { email_address, ...settings } = data // eslint-disable-line no-unused-vars
        return api.inboxes.updateSmtp(inbox.id, settings)
      }
      return api.inboxes.connectSmtp(data)
    },
    onMutate: () => setError(null),
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ['inboxes'] })
      toast.success(editing ? `Updated ${response.data.email_address}` : `Connected ${response.data.email_address}`)
      onClose()
    },
    onError: (err) => {
      const detail = err.response?.data?.detail
      setError({ message: formatErrorDetail(detail) || err.message || 'Could not connect', server: detail?.server })
    },
  })

  const set = (key) => (e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto" role="dialog" aria-modal="true" aria-labelledby="smtp-inbox-title">
      <div className="flex min-h-full items-center justify-center p-4">
        <div className="fixed inset-0 bg-gray-900/40" onClick={() => !saveMutation.isPending && onClose()} />
        <form
          className="relative w-full max-w-2xl rounded-card bg-white p-6 shadow-xl"
          onSubmit={(e) => {
            e.preventDefault()
            saveMutation.mutate()
          }}
        >
          <div className="flex items-center justify-between">
            <h3 id="smtp-inbox-title" className="flex items-center gap-2 text-lg font-medium tracking-tight text-gray-900">
              <ServerStackIcon className="h-5 w-5 text-gray-500" />
              {editing ? `Update ${inbox.email_address}` : 'Connect an SMTP/IMAP inbox'}
            </h3>
            <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close">
              <XMarkIcon className="h-5 w-5" />
            </button>
          </div>
          <p className="mt-1 text-sm text-gray-600">
            {editing
              ? 'Leave the password empty to keep the saved one. Both logins are tested before saving.'
              : 'Any mail account - Outlook, Zoho, a cold-email inbox provider or your own server. Both logins are tested before anything is saved; the password is stored encrypted.'}
          </p>

          <div className="mt-4 space-y-4">
            {!editing && (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Field
                  id="smtp-email"
                  label="Email address"
                  type="email"
                  value={form.email_address}
                  onChange={set('email_address')}
                  required
                  autoFocus
                  autoComplete="off"
                />
                <Field id="smtp-name" label="Sender name" value={form.display_name} onChange={set('display_name')} placeholder="Jane Smith" />
              </div>
            )}

            <div>
              <label htmlFor="smtp-preset" className="block text-sm font-medium text-gray-700">
                Mail provider
              </label>
              <select id="smtp-preset" value={presetId} onChange={(e) => applyPreset(e.target.value)} className={inputClass}>
                <option value="" disabled>
                  Choose to fill in the server settings...
                </option>
                {PROVIDER_PRESETS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
              {preset?.hint && <p className="mt-1 text-xs text-gray-500">{preset.hint}</p>}
            </div>

            <ServerFields kind="smtp" form={form} setForm={setForm} failed={error?.server === 'SMTP'} />
            <ServerFields kind="imap" form={form} setForm={setForm} failed={error?.server === 'IMAP'} />

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field
                id="smtp-username"
                label="Username"
                value={form.username}
                onChange={set('username')}
                placeholder={form.email_address || 'Usually your email address'}
                autoComplete="off"
              />
              <Field
                id="smtp-password"
                label="Password"
                type="password"
                value={form.password}
                onChange={set('password')}
                required={!editing}
                placeholder={editing ? 'Unchanged' : 'App password, if your provider uses them'}
                autoComplete="new-password"
              />
            </div>

            {error && (
              <div role="alert" className="flex gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                <ExclamationTriangleIcon className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{error.message}</span>
              </div>
            )}
          </div>

          <div className="mt-6 flex justify-end gap-3">
            <Button type="button" variant="secondary" onClick={onClose} disabled={saveMutation.isPending}>
              Cancel
            </Button>
            <Button type="submit" loading={saveMutation.isPending}>
              {saveMutation.isPending ? 'Testing logins...' : editing ? 'Test & save' : 'Test & connect'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
