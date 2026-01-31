import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../services/apiClient'
import Card from '../components/common/Card'
import StatusBadge from '../components/common/StatusBadge'
import LoadingSpinner from '../components/common/LoadingSpinner'

export default function CampaignDetailPage() {
  const { id } = useParams()

  const { data: campaign, isLoading } = useQuery({
    queryKey: ['campaign', id],
    queryFn: async () => {
      const response = await api.campaigns.get(id)
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

  if (!campaign) {
    return <div>Campaign not found</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{campaign.name}</h1>
          <p className="mt-1 text-sm text-gray-500">{campaign.description}</p>
        </div>
        <StatusBadge status={campaign.status} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card>
          <Card.Title>Total Leads</Card.Title>
          <p className="mt-2 text-3xl font-bold text-gray-900">{campaign.total_leads}</p>
        </Card>
        <Card>
          <Card.Title>Emails Sent</Card.Title>
          <p className="mt-2 text-3xl font-bold text-gray-900">{campaign.emails_sent}</p>
        </Card>
        <Card>
          <Card.Title>Replies</Card.Title>
          <p className="mt-2 text-3xl font-bold text-green-600">{campaign.replies_received}</p>
        </Card>
      </div>

      <Card>
        <Card.Header>
          <Card.Title>Campaign Settings</Card.Title>
        </Card.Header>
        <dl className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <dt className="text-gray-500">Schedule</dt>
            <dd className="font-medium text-gray-900">
              {campaign.send_start_time} - {campaign.send_end_time}
            </dd>
          </div>
          <div>
            <dt className="text-gray-500">Timezone</dt>
            <dd className="font-medium text-gray-900">{campaign.timezone}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Stop on Reply</dt>
            <dd className="font-medium text-gray-900">{campaign.stop_on_reply ? 'Yes' : 'No'}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Send on Weekends</dt>
            <dd className="font-medium text-gray-900">{campaign.send_on_weekends ? 'Yes' : 'No'}</dd>
          </div>
        </dl>
      </Card>
    </div>
  )
}
