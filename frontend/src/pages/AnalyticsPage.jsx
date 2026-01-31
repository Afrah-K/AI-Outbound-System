import { useQuery } from '@tanstack/react-query'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar } from 'recharts'
import { api } from '../services/apiClient'
import Card from '../components/common/Card'
import LoadingSpinner from '../components/common/LoadingSpinner'

export default function AnalyticsPage() {
  const { data: dashboard, isLoading: loadingDashboard } = useQuery({
    queryKey: ['analytics-dashboard'],
    queryFn: async () => {
      const response = await api.analytics.dashboard()
      return response.data
    },
  })

  const { data: daily, isLoading: loadingDaily } = useQuery({
    queryKey: ['analytics-daily'],
    queryFn: async () => {
      const response = await api.analytics.daily({ days: 14 })
      return response.data
    },
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
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Analytics</h1>
        <p className="mt-1 text-sm text-gray-500">
          Track your outreach performance
        </p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <p className="text-sm font-medium text-gray-500">Emails Sent (7d)</p>
          <p className="mt-2 text-3xl font-bold text-gray-900">
            {dashboard?.seven_days?.emails_sent || 0}
          </p>
        </Card>
        <Card>
          <p className="text-sm font-medium text-gray-500">Replies (7d)</p>
          <p className="mt-2 text-3xl font-bold text-green-600">
            {dashboard?.seven_days?.replies || 0}
          </p>
        </Card>
        <Card>
          <p className="text-sm font-medium text-gray-500">Reply Rate</p>
          <p className="mt-2 text-3xl font-bold text-primary-600">
            {dashboard?.seven_days?.reply_rate || 0}%
          </p>
        </Card>
        <Card>
          <p className="text-sm font-medium text-gray-500">Avg Health Score</p>
          <p className="mt-2 text-3xl font-bold text-gray-900">
            {Math.round(dashboard?.average_health_score || 100)}%
          </p>
        </Card>
      </div>

      {/* Sending Volume Chart */}
      <Card>
        <Card.Header>
          <Card.Title>Sending Volume (14 days)</Card.Title>
        </Card.Header>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={daily?.daily_stats || []}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="date"
                tickFormatter={(date) => new Date(date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
              />
              <YAxis />
              <Tooltip
                labelFormatter={(date) => new Date(date).toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' })}
              />
              <Line type="monotone" dataKey="emails_sent" stroke="#3b82f6" name="Sent" strokeWidth={2} />
              <Line type="monotone" dataKey="replies" stroke="#22c55e" name="Replies" strokeWidth={2} />
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
