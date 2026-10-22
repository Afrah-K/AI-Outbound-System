import { useQuery } from '@tanstack/react-query'
import {
  EnvelopeIcon,
  ChatBubbleLeftRightIcon,
  MegaphoneIcon,
  InboxIcon,
} from '@heroicons/react/24/outline'
import { api } from '../services/apiClient'
import Card from '../components/common/Card'
import LoadingSpinner from '../components/common/LoadingSpinner'

function MetricCard({ title, value, subtitle, icon: Icon, color }) {
  const colors = {
    blue: 'bg-blue-500',
    green: 'bg-green-500',
    purple: 'bg-primary-500',
    orange: 'bg-orange-500',
  }

  return (
    <Card>
      <div className="flex items-center">
        <div className={`${colors[color]} rounded-lg p-3`}>
          <Icon className="h-6 w-6 text-white" />
        </div>
        <div className="ml-4">
          <p className="text-sm font-medium text-gray-500">{title}</p>
          <p className="text-2xl font-semibold text-gray-900">{value}</p>
          {subtitle && (
            <p className="text-sm text-gray-500">{subtitle}</p>
          )}
        </div>
      </div>
    </Card>
  )
}

export default function DashboardPage() {
  const { data: dashboard, isLoading } = useQuery({
    queryKey: ['dashboard'],
    queryFn: async () => {
      const response = await api.analytics.dashboard()
      return response.data
    },
  })

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
        <h1 className="text-3xl font-medium tracking-tight text-gray-900">Dashboard</h1>
        <p className="mt-1 text-sm text-gray-500">
          Overview of your cold email campaigns
        </p>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          title="Emails Sent Today"
          value={dashboard?.today?.emails_sent || 0}
          subtitle={`${dashboard?.seven_days?.emails_sent || 0} in last 7 days`}
          icon={EnvelopeIcon}
          color="blue"
        />
        <MetricCard
          title="Replies Today"
          value={dashboard?.today?.replies || 0}
          subtitle={`${dashboard?.seven_days?.reply_rate || 0}% reply rate (7d)`}
          icon={ChatBubbleLeftRightIcon}
          color="green"
        />
        <MetricCard
          title="Active Campaigns"
          value={dashboard?.active_campaigns || 0}
          icon={MegaphoneIcon}
          color="purple"
        />
        <MetricCard
          title="Active Inboxes"
          value={dashboard?.active_inboxes || 0}
          subtitle={`${dashboard?.average_health_score || 100}% avg health`}
          icon={InboxIcon}
          color="orange"
        />
      </div>

      {/* Quick Actions */}
      <Card>
        <Card.Header>
          <Card.Title>Quick Actions</Card.Title>
        </Card.Header>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <a
            href="/campaigns"
            className="flex items-center gap-3 p-4 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors"
          >
            <MegaphoneIcon className="h-8 w-8 text-primary-600" />
            <div>
              <p className="font-medium text-gray-900">Create Campaign</p>
              <p className="text-sm text-gray-500">Start a new outreach campaign</p>
            </div>
          </a>
          <a
            href="/prospects"
            className="flex items-center gap-3 p-4 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors"
          >
            <EnvelopeIcon className="h-8 w-8 text-primary-600" />
            <div>
              <p className="font-medium text-gray-900">Import Prospects</p>
              <p className="text-sm text-gray-500">Upload CSV from Apollo</p>
            </div>
          </a>
          <a
            href="/inboxes"
            className="flex items-center gap-3 p-4 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors"
          >
            <InboxIcon className="h-8 w-8 text-primary-600" />
            <div>
              <p className="font-medium text-gray-900">Add Inbox</p>
              <p className="text-sm text-gray-500">Connect Gmail or any SMTP/IMAP inbox</p>
            </div>
          </a>
        </div>
      </Card>

      {/* Getting Started */}
      {dashboard?.active_inboxes === 0 && (
        <Card className="bg-primary-50 border-primary-200">
          <div className="flex items-start gap-4">
            <div className="flex-shrink-0">
              <InboxIcon className="h-8 w-8 text-primary-600" />
            </div>
            <div>
              <h3 className="text-lg font-medium text-primary-900">
                Get Started
              </h3>
              <p className="mt-1 text-sm text-primary-700">
                Welcome to your cold email platform! To get started, you'll need to:
              </p>
              <ol className="mt-3 list-decimal list-inside text-sm text-primary-700 space-y-1">
                <li>Connect an inbox (Gmail or any SMTP/IMAP account)</li>
                <li>Import your prospects from Apollo</li>
                <li>Create an email sequence</li>
                <li>Launch your first campaign</li>
              </ol>
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}
