import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import {
  CheckCircleIcon,
  ExclamationTriangleIcon,
  ShieldExclamationIcon,
  QuestionMarkCircleIcon,
  BeakerIcon,
  InformationCircleIcon,
} from '@heroicons/react/24/outline'
import toast from 'react-hot-toast'
import { api } from '../../services/apiClient'
import Button from '../common/Button'
import Card from '../common/Card'
import LoadingSpinner from '../common/LoadingSpinner'
import PeriodSwitch from './PeriodSwitch'
import { PERIODS, formatBucket, formatBucketLong } from './periods'

const PERIOD_KEY = 'placement_period'

function loadPeriod() {
  try {
    const saved = localStorage.getItem(PERIOD_KEY)
    return PERIODS.some((p) => p.value === saved) ? saved : 'day'
  } catch {
    return 'day'
  }
}

// Status colours (fixed meaning - always shown with an icon + label, never alone)
export const PLACEMENT_GROUPS = [
  { key: 'inbox', label: 'Primary inbox', color: '#0ca30c', icon: CheckCircleIcon, iconClass: 'text-green-600', parts: ['inbox'] },
  {
    key: 'tabs',
    label: 'Gmail tabs',
    hint: 'Promotions, Updates, Social or Forums - still in the inbox, but not Primary',
    color: '#fab219',
    icon: ExclamationTriangleIcon,
    iconClass: 'text-amber-500',
    parts: ['promotions', 'updates', 'social', 'forums'],
  },
  { key: 'spam', label: 'Spam', color: '#d03b3b', icon: ShieldExclamationIcon, iconClass: 'text-red-600', parts: ['spam'] },
  {
    key: 'missing',
    label: 'Not delivered',
    hint: 'Never arrived within 30 minutes, or was filtered out of the inbox',
    color: '#9ca3af',
    icon: QuestionMarkCircleIcon,
    iconClass: 'text-gray-400',
    parts: ['missing', 'other'],
  },
]

const PLACEMENT_LABEL = {
  inbox: 'Primary inbox',
  promotions: 'Promotions tab',
  updates: 'Updates tab',
  social: 'Social tab',
  forums: 'Forums tab',
  spam: 'Spam',
  other: 'Filtered out',
  missing: 'Not delivered',
  pending: 'Checking...',
}

const SOURCES = [
  ['all', 'All checks'],
  ['warmup', 'Warmup emails'],
  ['test', 'Placement tests'],
]

function grouped(counts) {
  return Object.fromEntries(PLACEMENT_GROUPS.map((g) => [g.key, g.parts.reduce((n, p) => n + (counts?.[p] || 0), 0)]))
}

const pct = (n, total) => (total ? Math.round((n / total) * 1000) / 10 : null)

function PlacementTooltip({ active, payload, label, period }) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  const total = PLACEMENT_GROUPS.reduce((n, g) => n + (row[g.key] || 0), 0)
  return (
    <div className="rounded-xl bg-gray-900 px-3 py-2 text-xs text-white shadow-lg">
      <p className="mb-1 font-medium">{formatBucketLong(label, period)}</p>
      {total === 0 ? (
        <p className="text-gray-300">No emails checked{row.pending ? ` (${row.pending} still checking)` : ''}</p>
      ) : (
        PLACEMENT_GROUPS.map((g) => (
          <p key={g.key} className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-sm" style={{ background: g.color }} />
            <span className="text-gray-300">{g.label}</span>
            <span className="ml-auto pl-3 tabular-nums">
              {row[g.key]} ({pct(row[g.key], total)}%)
            </span>
          </p>
        ))
      )}
    </div>
  )
}

function RunTestButton({ onStarted }) {
  const [campaignId, setCampaignId] = useState('')
  const { data: campaignsData } = useQuery({
    queryKey: ['campaigns'],
    queryFn: async () => (await api.campaigns.list()).data,
  })
  const campaigns = (campaignsData?.campaigns || []).filter((c) => c.status !== 'archived')

  const testMutation = useMutation({
    mutationFn: () => api.analytics.runPlacementTest(campaignId ? parseInt(campaignId) : null),
    onSuccess: (response) => {
      const r = response.data
      toast.success(
        `Sent ${r.sent} test email${r.sent === 1 ? '' : 's'} to your own inboxes - results in about ${Math.ceil(
          r.check_after_seconds / 60
        )} min`
      )
      if (r.errors?.length) toast.error(`${r.errors.length} couldn't be sent: ${r.errors[0]}`)
      onStarted()
    },
  })

  return (
    <div className="flex flex-wrap items-center gap-2">
      <select
        value={campaignId}
        onChange={(e) => setCampaignId(e.target.value)}
        className="w-auto max-w-[260px] rounded-full border border-gray-200 bg-white py-1.5 pl-3 pr-8 text-sm"
        aria-label="What to test"
      >
        <option value="">Test a generic email</option>
        {campaigns.map((c) => (
          <option key={c.id} value={c.id}>
            Test "{c.name}" email
          </option>
        ))}
      </select>
      <Button size="sm" icon={BeakerIcon} onClick={() => testMutation.mutate()} loading={testMutation.isPending}>
        Run placement test
      </Button>
    </div>
  )
}

export default function PlacementSection() {
  const [period, setPeriodState] = useState(loadPeriod)
  const [source, setSource] = useState('all')
  const setPeriod = (value) => {
    setPeriodState(value)
    try {
      localStorage.setItem(PERIOD_KEY, value)
    } catch {
      // ignore - storage disabled
    }
  }
  const periodInfo = PERIODS.find((p) => p.value === period)

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['analytics-placement', period, source],
    queryFn: async () => (await api.analytics.placement(period, source)).data,
    // Keep polling while checks are still being resolved
    refetchInterval: (query) => (query.state.data?.totals?.pending ? 15000 : false),
  })

  const totals = grouped(data?.totals)
  const checked = data?.checked || 0
  const series = (data?.series || []).map((b) => ({ ...grouped(b), bucket: b.bucket, pending: b.pending }))

  return (
    <Card>
      <Card.Header>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <Card.Title>Inbox placement</Card.Title>
            <Card.Description>
              Where your warmup and test emails landed - Primary inbox, a Gmail tab, or spam ({periodInfo.range.toLowerCase()})
            </Card.Description>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <PeriodSwitch value={period} onChange={setPeriod} size="sm" />
            <select
              value={source}
              onChange={(e) => setSource(e.target.value)}
              className="w-auto max-w-[260px] rounded-full border border-gray-200 bg-white py-1.5 pl-3 pr-8 text-sm"
              aria-label="Which emails"
            >
              {SOURCES.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
            <RunTestButton onStarted={() => refetch()} />
          </div>
        </div>
      </Card.Header>

      {isLoading ? (
        <div className="flex h-40 items-center justify-center"><LoadingSpinner /></div>
      ) : (
        <div className="space-y-6">
          {/* Headline rates */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {PLACEMENT_GROUPS.map((g) => {
              const Icon = g.icon
              const rate = pct(totals[g.key], checked)
              return (
                <div key={g.key} className="rounded-xl border border-gray-100 p-4" title={g.hint}>
                  <div className="flex items-center gap-2 text-sm text-gray-500">
                    <Icon className={`h-4 w-4 ${g.iconClass}`} />
                    {g.label}
                  </div>
                  <p className="mt-1 text-3xl font-medium tracking-tight text-gray-900 tabular-nums">
                    {rate === null ? '-' : `${rate}%`}
                  </p>
                  <p className="text-xs text-gray-500 tabular-nums">
                    {totals[g.key]} of {checked} checked
                  </p>
                </div>
              )
            })}
          </div>

          {data?.totals?.pending > 0 && (
            <p className="flex items-center gap-2 text-xs text-gray-500">
              <LoadingSpinner size="sm" /> {data.totals.pending} email{data.totals.pending === 1 ? ' is' : 's are'} still being
              checked - this updates automatically
            </p>
          )}

          {checked === 0 ? (
            <div className="rounded-xl bg-canvas p-6 text-center text-sm text-gray-600">
              {data?.connected_inboxes < 2 ? (
                <p>Connect at least two inboxes to measure placement - one sends, the other receives and reports where it landed.</p>
              ) : (
                <p>
                  No placement data for this period yet. Every warmup email is checked automatically, or click{' '}
                  <strong>Run placement test</strong> to check now.
                </p>
              )}
            </div>
          ) : (
            <>
              {/* Over time */}
              <div>
                <div className="mb-2 flex flex-wrap items-center gap-4 text-xs text-gray-600" aria-label="Legend">
                  {PLACEMENT_GROUPS.map((g) => (
                    <span key={g.key} className="inline-flex items-center gap-1.5">
                      <span className="h-2.5 w-2.5 rounded-sm" style={{ background: g.color }} />
                      {g.label}
                    </span>
                  ))}
                </div>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={series} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                      <CartesianGrid stroke="#eef0f4" vertical={false} />
                      <XAxis
                        dataKey="bucket"
                        axisLine={false}
                        tickLine={false}
                        tick={{ fill: '#6b7280', fontSize: 12 }}
                        tickMargin={10}
                        minTickGap={16}
                        tickFormatter={(b) => formatBucket(b, period)}
                      />
                      <YAxis axisLine={false} tickLine={false} tick={{ fill: '#6b7280', fontSize: 12 }} allowDecimals={false} />
                      <Tooltip content={<PlacementTooltip period={period} />} cursor={{ fill: '#11182708' }} />
                      {PLACEMENT_GROUPS.map((g, i) => (
                        <Bar
                          key={g.key}
                          dataKey={g.key}
                          name={g.label}
                          stackId="placement"
                          fill={g.color}
                          stroke="#ffffff"
                          strokeWidth={2}
                          maxBarSize={36}
                          radius={i === PLACEMENT_GROUPS.length - 1 ? [4, 4, 0, 0] : 0}
                          isAnimationActive={false}
                        />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* By sending inbox */}
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-xs uppercase text-gray-500">
                      <th className="py-2 pr-4 font-medium">Sending inbox</th>
                      <th className="py-2 pr-4 text-right font-medium">Checked</th>
                      {PLACEMENT_GROUPS.map((g) => (
                        <th key={g.key} className="py-2 pr-4 text-right font-medium">{g.label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {(data?.by_sender || []).map((s) => {
                      const g = grouped(s)
                      return (
                        <tr key={s.inbox_id}>
                          <td className="py-2.5 pr-4 text-gray-900">{s.email}</td>
                          <td className="py-2.5 pr-4 text-right tabular-nums text-gray-500">{s.checked}</td>
                          {PLACEMENT_GROUPS.map((grp) => (
                            <td key={grp.key} className="py-2.5 pr-4 text-right tabular-nums text-gray-700">
                              {s.checked ? `${pct(g[grp.key], s.checked)}%` : '-'}
                            </td>
                          ))}
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {/* Recent checks */}
          {data?.recent?.length > 0 && (
            <details>
              <summary className="cursor-pointer text-sm font-medium text-gray-600 hover:text-gray-900">
                Recent checks ({data.recent.length})
              </summary>
              <ul className="mt-3 divide-y divide-gray-100 text-sm">
                {data.recent.map((c) => (
                  <li key={c.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                    <span className="w-28 shrink-0 font-medium text-gray-900">{PLACEMENT_LABEL[c.placement] || c.placement}</span>
                    <span className="min-w-0 flex-1 truncate text-gray-600">
                      {c.subject} <span className="text-gray-400">- {c.from} → {c.to}</span>
                    </span>
                    <span className="text-xs text-gray-400">
                      {c.source === 'test' ? 'Test' : 'Warmup'} · {new Date(c.sent_at).toLocaleString()}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          )}

          <p className="flex gap-2 text-xs text-gray-500">
            <InformationCircleIcon className="h-4 w-4 shrink-0" />
            Measured on emails sent between your own connected inboxes (you can't see inside a prospect's mailbox), so it
            reflects how Gmail treats your sending inboxes and copy - a strong signal, not a guarantee for every recipient.
          </p>
        </div>
      )}
    </Card>
  )
}
