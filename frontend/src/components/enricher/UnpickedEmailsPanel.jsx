import { useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { ArrowDownTrayIcon, ArrowPathIcon, PlusIcon } from '@heroicons/react/24/outline'
import toast from 'react-hot-toast'
import { api } from '../../services/apiClient'
import Button from '../common/Button'
import Card from '../common/Card'

const REASONS = {
  over_limit: {
    label: 'Over the limit',
    hint: 'The Enricher keeps the top 3 addresses per company - this one ranked lower',
  },
  off_domain: {
    label: 'Different domain',
    hint: "Not on the company's own domain (e.g. a personal Gmail or a partner's address) while on-domain ones exist",
  },
}

function downloadCSV(items) {
  const header = ['company', 'website', 'email', 'reason']
  const rows = items.map((i) => [i.company, i.website || '', i.email, REASONS[i.reason]?.label || i.reason])
  const csv = [header, ...rows]
    .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
    .join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'unpicked_emails.csv'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/**
 * Every email the Enricher found but didn't keep, listed with its company,
 * with a "Use" action that turns it into a prospect.
 */
export default function UnpickedEmailsPanel({ results, onPicked, untrackedCount, onRescan, rescanning }) {
  const [search, setSearch] = useState('')
  const [reason, setReason] = useState('')

  const items = useMemo(
    () =>
      results.flatMap((r) =>
        (r.unpicked_emails || []).map((u) => ({
          companyId: r.company_id,
          company: r.name,
          website: r.website,
          email: u.email,
          reason: u.reason,
        }))
      ),
    [results]
  )

  const q = search.trim().toLowerCase()
  const visible = items.filter(
    (i) =>
      (!reason || i.reason === reason) &&
      (!q || i.company.toLowerCase().includes(q) || i.email.toLowerCase().includes(q))
  )

  const pickMutation = useMutation({
    mutationFn: ({ companyId, email }) => api.leads.pickEmail(companyId, email),
    onSuccess: (_response, { companyId, email, company }) => {
      onPicked(companyId, email)
      toast.success(`Added ${email} as a prospect for ${company}`)
    },
  })

  return (
    <Card padding={false}>
      <div className="flex flex-wrap items-center justify-between gap-3 p-6 pb-0">
        <div>
          <Card.Title>Unpicked emails ({items.length})</Card.Title>
          <p className="text-xs text-gray-500 mt-0.5">
            Found on the companies' sites but not added as prospects
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search company or email..."
            className="w-56 rounded-lg border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 text-sm"
          />
          <select
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="rounded-lg border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 text-sm"
          >
            <option value="">All reasons</option>
            {Object.entries(REASONS).map(([key, r]) => (
              <option key={key} value={key}>{r.label}</option>
            ))}
          </select>
          <Button variant="secondary" size="sm" icon={ArrowDownTrayIcon} onClick={() => downloadCSV(visible)} disabled={!visible.length}>
            Export
          </Button>
        </div>
      </div>

      {untrackedCount > 0 && (
        <div className="mx-6 mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
          <p className="text-sm text-amber-800">
            {untrackedCount} compan{untrackedCount === 1 ? 'y was' : 'ies were'} enriched before unpicked emails were
            tracked, so any extras they had aren't listed.
          </p>
          <Button size="sm" variant="secondary" icon={ArrowPathIcon} onClick={onRescan} loading={rescanning}>
            Re-scan {untrackedCount === 1 ? 'it' : 'them'}
          </Button>
        </div>
      )}

      {visible.length > 0 ? (
        <div className="overflow-x-auto mt-4 max-h-[480px] overflow-y-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50 sticky top-0">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Company</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Email</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Why it wasn't picked</th>
                <th className="px-6 py-3" />
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {visible.map((i) => {
                const picking = pickMutation.isPending && pickMutation.variables?.email === i.email
                return (
                  <tr key={`${i.companyId}-${i.email}`} className="hover:bg-gray-50">
                    <td className="px-6 py-3 text-sm">
                      <div className="font-medium text-gray-900">{i.company}</div>
                      {i.website && (
                        <a
                          href={i.website.startsWith('http') ? i.website : `https://${i.website}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs text-primary-600 hover:underline"
                        >
                          {i.website.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')}
                        </a>
                      )}
                    </td>
                    <td className="px-6 py-3 text-sm text-gray-700">{i.email}</td>
                    <td className="px-6 py-3 text-xs text-gray-500" title={REASONS[i.reason]?.hint}>
                      <span className="rounded-full bg-gray-100 px-2 py-0.5 text-gray-700">
                        {REASONS[i.reason]?.label || i.reason}
                      </span>
                    </td>
                    <td className="px-6 py-3 text-right">
                      <Button
                        size="sm"
                        variant="secondary"
                        icon={PlusIcon}
                        loading={picking}
                        disabled={pickMutation.isPending && !picking}
                        onClick={() => pickMutation.mutate({ companyId: i.companyId, email: i.email, company: i.company })}
                      >
                        Use
                      </Button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-6 py-8 text-center text-sm text-gray-500">
          {items.length === 0 ? 'No unpicked emails - every address found was kept.' : 'No unpicked emails match your search.'}
        </p>
      )}
    </Card>
  )
}
