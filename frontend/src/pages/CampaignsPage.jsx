import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { PlusIcon, MegaphoneIcon, PlayIcon, PauseIcon, TrashIcon } from '@heroicons/react/24/outline'
import { api } from '../services/apiClient'
import Button from '../components/common/Button'
import Card from '../components/common/Card'
import StatusBadge from '../components/common/StatusBadge'
import SendingState from '../components/common/SendingState'
import LoadingSpinner from '../components/common/LoadingSpinner'
import EmptyState from '../components/common/EmptyState'
import toast from 'react-hot-toast'

export default function CampaignsPage() {
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['campaigns'],
    queryFn: async () => {
      const response = await api.campaigns.list()
      return response.data
    },
  })

  const startMutation = useMutation({
    mutationFn: (id) => api.campaigns.start(id),
    onSuccess: () => {
      queryClient.invalidateQueries(['campaigns'])
      toast.success('Campaign started')
    },
  })

  const pauseMutation = useMutation({
    mutationFn: (id) => api.campaigns.pause(id),
    onSuccess: () => {
      queryClient.invalidateQueries(['campaigns'])
      toast.success('Campaign paused')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => api.campaigns.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries(['campaigns'])
      toast.success('Campaign deleted')
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-medium tracking-tight text-gray-900">Campaigns</h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage your outreach campaigns
          </p>
        </div>
        <Link to="/campaigns/new">
          <Button icon={PlusIcon}>New Campaign</Button>
        </Link>
      </div>

      {data?.campaigns?.length === 0 ? (
        <Card>
          <EmptyState
            icon={MegaphoneIcon}
            title="No campaigns yet"
            description="Create your first campaign to start reaching out"
            action={
              <Link to="/campaigns/new">
                <Button icon={PlusIcon}>Create Campaign</Button>
              </Link>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-4">
          {data?.campaigns?.map((campaign) => (
            <Card key={campaign.id}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="h-10 w-10 rounded-full bg-primary-600 flex items-center justify-center">
                    <MegaphoneIcon className="h-5 w-5 text-white" />
                  </div>
                  <div>
                    <Link
                      to={`/campaigns/${campaign.id}`}
                      className="font-medium text-gray-900 hover:text-primary-600"
                    >
                      {campaign.name}
                    </Link>
                    <p className="text-sm text-gray-500">{campaign.description || 'No description'}</p>
                  </div>
                </div>

                <div className="flex items-center gap-6">
                  <div className="text-center">
                    <p className="text-sm text-gray-500">Leads</p>
                    <p className="text-lg font-semibold text-gray-900">{campaign.total_leads}</p>
                  </div>

                  <div className="text-center">
                    <p className="text-sm text-gray-500">Sent</p>
                    <p className="text-lg font-semibold text-gray-900">{campaign.emails_sent}</p>
                  </div>

                  <div className="text-center">
                    <p className="text-sm text-gray-500">Replies</p>
                    <p className="text-lg font-semibold text-green-600">{campaign.replies_received}</p>
                  </div>

                  <div className="flex flex-col items-end gap-1">
                    <StatusBadge status={campaign.status} />
                    {campaign.status === 'active' && <SendingState sending={campaign.sending} compact />}
                  </div>

                  <div className="flex items-center gap-2">
                    {campaign.status === 'active' ? (
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => pauseMutation.mutate(campaign.id)}
                        loading={pauseMutation.isPending}
                      >
                        <PauseIcon className="h-4 w-4" />
                      </Button>
                    ) : campaign.status === 'paused' || campaign.status === 'draft' ? (
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={() => startMutation.mutate(campaign.id)}
                        loading={startMutation.isPending}
                      >
                        <PlayIcon className="h-4 w-4" />
                      </Button>
                    ) : null}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        if (confirm('Delete this campaign?')) {
                          deleteMutation.mutate(campaign.id)
                        }
                      }}
                    >
                      <TrashIcon className="h-4 w-4 text-gray-400 hover:text-red-500" />
                    </Button>
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
