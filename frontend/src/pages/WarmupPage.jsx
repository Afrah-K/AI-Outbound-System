import { useQuery } from '@tanstack/react-query'
import { FireIcon } from '@heroicons/react/24/outline'
import { api } from '../services/apiClient'
import Card from '../components/common/Card'
import StatusBadge from '../components/common/StatusBadge'
import LoadingSpinner from '../components/common/LoadingSpinner'
import EmptyState from '../components/common/EmptyState'
import PlacementSection from '../components/analytics/PlacementSection'

function WarmupProgress({ stage }) {
  const stages = ['not_started', 'stage_1', 'stage_2', 'stage_3', 'completed']
  const currentIndex = stages.indexOf(stage)
  const percentage = ((currentIndex + 1) / stages.length) * 100

  return (
    <div className="space-y-2">
      <div className="flex justify-between text-sm">
        <span className="text-gray-500">Progress</span>
        <span className="font-medium text-gray-900">{Math.round(percentage)}%</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2">
        <div
          className="bg-primary-600 h-2 rounded-full transition-all"
          style={{ width: `${percentage}%` }}
        />
      </div>
      <div className="flex justify-between text-xs text-gray-500">
        <span>5/day</span>
        <span>10/day</span>
        <span>20/day</span>
        <span>Ready</span>
      </div>
    </div>
  )
}

export default function WarmupPage() {
  const { data: inboxes, isLoading } = useQuery({
    queryKey: ['inboxes'],
    queryFn: async () => {
      const response = await api.inboxes.list()
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
        <h1 className="text-3xl font-medium tracking-tight text-gray-900">Inbox Warmup</h1>
        <p className="mt-1 text-sm text-gray-500">
          Gradually increase sending volume to build sender reputation
        </p>
      </div>

      {/* Info Card */}
      <Card className="bg-primary-50 border border-primary-100">
        <div className="flex items-start gap-4">
          <FireIcon className="h-8 w-8 text-primary-600 flex-shrink-0" />
          <div>
            <h3 className="font-medium text-primary-900">How Warmup Works</h3>
            <p className="mt-1 text-sm text-primary-700">
              New inboxes start with a low sending volume (5 emails/day) and gradually increase
              over 3 weeks. This helps build sender reputation and avoid spam filters.
            </p>
            <ul className="mt-2 text-sm text-primary-700 list-disc list-inside space-y-1">
              <li>Stage 1: 5 emails/day for 7 days</li>
              <li>Stage 2: 10 emails/day for 7 days</li>
              <li>Stage 3: 20 emails/day for 7 days</li>
            </ul>
          </div>
        </div>
      </Card>

      {inboxes?.inboxes?.length === 0 ? (
        <Card>
          <EmptyState
            icon={FireIcon}
            title="No inboxes to warm up"
            description="Connect a Gmail account first to start the warmup process"
          />
        </Card>
      ) : (
        <div className="grid gap-4">
          {inboxes?.inboxes?.map((inbox) => (
            <Card key={inbox.id}>
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-full bg-primary-600 flex items-center justify-center">
                    <FireIcon className="h-5 w-5 text-white" />
                  </div>
                  <div>
                    <p className="font-medium text-gray-900">{inbox.email_address}</p>
                    <p className="text-sm text-gray-500">{inbox.domain}</p>
                  </div>
                </div>
                <StatusBadge status={inbox.warmup_stage || 'not_started'} />
              </div>

              <WarmupProgress stage={inbox.warmup_stage || 'not_started'} />

              <div className="mt-4 flex items-center justify-between text-sm">
                <span className="text-gray-500">
                  Warmup emails sent: {inbox.warmup_emails_sent || 0}
                </span>
                <span className="text-gray-500">
                  Health: {inbox.health_score}%
                </span>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Where the warmup emails land - the result warmup is working toward */}
      <PlacementSection />
    </div>
  )
}
