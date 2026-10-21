import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar } from 'recharts'
import { api } from '../services/apiClient'
import Card from '../components/common/Card'
import StatCard from '../components/common/StatCard'
import { PaperAirplaneIcon, ChatBubbleLeftRightIcon, ArrowTrendingUpIcon, HeartIcon } from '@heroicons/react/24/outline'
import LoadingSpinner from '../components/common/LoadingSpinner'
import PeriodSwitch from '../components/analytics/PeriodSwitch'
import { PERIODS, formatBucket, formatBucketLong } from '../components/analytics/periods'

const PERIOD_KEY = 'analytics_period'

function loadPeriod() {
  try {
    const saved = localStorage.getItem(PERIOD_KEY)
    return PERIODS.some((p) => p.value === saved) ? saved : 'day'
  } catch {
    return 'day'
  }
}

export default function AnalyticsPage() {
  const [period, setPeriodState] = useState(loadPeriod)
  const setPeriod = (value) => {
    setPeriodState(value)
    try {
      localStorage.setItem(PERIOD_KEY, value)
    } catch {
      // ignore - storage disabled
    }
  }
  const periodInfo = PERIODS.find((p) => p.value === period)

  const { data: dashboard, isLoading: loadingDashboard } = useQuery({
    queryKey: ['analytics-dashboard'],
    queryFn: async () => {
      const response = await api.analytics.dashboard()
      return response.data
    },
  })

  const { data: timeseries, isLoading: loadingDaily } = useQuery({
    queryKey: ['analytics-timeseries', period],
    queryFn: async () => (await api.analytics.timeseries(period)).data,
    placeholderData: keepPreviousData,
  })

  const { data: inboxStats, isLoading: loadingInboxes } = useQuery({
    queryKey: ['analytics-inboxes'],
    queryFn: async () => {
      const response = await api.analytics.inboxes({ days: 7 })
      return response.data
    },
  })

  const isLoading = loadingDashboard || loadingDaily || loadingInboxes

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-medium tracking-tight text-gray-900">Analytics</h1>
          <p className="mt-1 text-sm text-gray-500">
            Track your outreach performance
          </p>
        </div>
        <PeriodSwitch value={period} onChange={setPeriod} />
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard icon={PaperAirplaneIcon} label="Emails sent" value={dashboard?.seven_days?.emails_sent || 0} caption="Last 7 days" />
        <StatCard icon={ChatBubbleLeftRightIcon} label="Replies" value={dashboard?.seven_days?.replies || 0} caption="Last 7 days" />
        <StatCard icon={ArrowTrendingUpIcon} label="Reply rate" value={`${dashboard?.seven_days?.reply_rate || 0}%`} caption="Replies per email sent, last 7 days" />
        <StatCard icon={HeartIcon} label="Avg health score" value={`${Math.round(dashboard?.average_health_score || 100)}%`} caption="Across active inboxes" />
      </div>

      {/* Sending Volume Chart */}
      <Card>
        <Card.Header>
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <Card.Title>Sending volume - {periodInfo.range.toLowerCase()}</Card.Title>
            <div className="flex items-center gap-4 text-xs text-gray-600">
              <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-3 rounded bg-[#2a53f0]" />Sent {timeseries?.totals?.emails_sent ?? 0}</span>
              <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-3 rounded bg-[#34c77b]" />Replies {timeseries?.totals?.replies ?? 0}</span>
            </div>
          </div>
        </Card.Header>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={timeseries?.series || []} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
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
              <Tooltip
                contentStyle={{ background: '#111827', border: 'none', borderRadius: 12, color: '#fff', fontSize: 12 }}
                labelStyle={{ color: '#fff', marginBottom: 4 }}
                itemStyle={{ color: '#fff' }}
                cursor={{ stroke: '#111827', strokeDasharray: '4 4' }}
                labelFormatter={(b) => formatBucketLong(b, period)}
              />
              <Line type="monotone" dataKey="emails_sent" stroke="#2a53f0" name="Sent" strokeWidth={2.5} dot={false} activeDot={{ r: 5 }} />
              <Line type="monotone" dataKey="replies" stroke="#34c77b" name="Replies" strokeWidth={2.5} dot={false} activeDot={{ r: 5 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {/* Inbox Performance */}
      <Card>
        <Card.Header>
          <Card.Title>Inbox Performance</Card.Title>
        </Card.Header>
        {inboxStats?.inboxes?.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead>
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Inbox
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    Sent
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    Replies
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    Reply Rate
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    Bounces
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    Health
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {inboxStats?.inboxes?.map((inbox) => (
                  <tr key={inbox.id}>
                    <td className="px-4 py-4 text-sm text-gray-900">{inbox.email}</td>
                    <td className="px-4 py-4 text-sm text-gray-500 text-right">{inbox.emails_sent}</td>
                    <td className="px-4 py-4 text-sm text-green-600 text-right">{inbox.replies}</td>
                    <td className="px-4 py-4 text-sm text-gray-500 text-right">{inbox.reply_rate}%</td>
                    <td className="px-4 py-4 text-sm text-red-600 text-right">{inbox.bounces}</td>
                    <td className="px-4 py-4 text-right">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                          inbox.health_score >= 80
                            ? 'bg-green-100 text-green-800'
                            : inbox.health_score >= 50
                            ? 'bg-yellow-100 text-yellow-800'
                            : 'bg-red-100 text-red-800'
                        }`}
                      >
                        {inbox.health_score}%
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-gray-500">No inbox data available</p>
        )}
      </Card>
    </div>
  )
}
