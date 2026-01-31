import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { PlusIcon, TrashIcon, InboxIcon } from '@heroicons/react/24/outline'
import { api } from '../services/apiClient'
import Button from '../components/common/Button'
import Card from '../components/common/Card'
import StatusBadge from '../components/common/StatusBadge'
import LoadingSpinner from '../components/common/LoadingSpinner'
import EmptyState from '../components/common/EmptyState'
import toast from 'react-hot-toast'

function HealthScore({ score }) {
  const getColor = () => {
    if (score >= 80) return 'text-green-600'
    if (score >= 50) return 'text-yellow-600'
    return 'text-red-600'
  }

  return (
    <div className="flex items-center gap-2">
      <div className="w-full bg-gray-200 rounded-full h-2">
        <div
          className={`h-2 rounded-full ${
            score >= 80 ? 'bg-green-500' : score >= 50 ? 'bg-yellow-500' : 'bg-red-500'
          }`}
          style={{ width: `${score}%` }}
        />
      </div>
      <span className={`text-sm font-medium ${getColor()}`}>{score}%</span>
    </div>
  )
}

export default function InboxesPage() {
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['inboxes'],
    queryFn: async () => {
      const response = await api.inboxes.list()
      return response.data
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => api.inboxes.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries(['inboxes'])
      toast.success('Inbox deleted')
    },
  })

  const handleAddInbox = async () => {
    try {
      const response = await api.inboxes.initiateOAuth()
      if (response.data.auth_url) {
        window.location.href = response.data.auth_url
      } else {
        toast.error('Gmail OAuth not configured. Please set up Google Cloud credentials.')
      }
    } catch (error) {
      toast.error('Failed to initiate OAuth')
    }
  }

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
          <h1 className="text-2xl font-bold text-gray-900">Inboxes</h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage your connected Gmail accounts
          </p>
        </div>
        <Button icon={PlusIcon} onClick={handleAddInbox}>
          Add Inbox
        </Button>
      </div>

      {data?.inboxes?.length === 0 ? (
        <Card>
          <EmptyState
            icon={InboxIcon}
            title="No inboxes connected"
            description="Connect a Gmail or GSuite account to start sending emails"
            action={
              <Button icon={PlusIcon} onClick={handleAddInbox}>
                Add Your First Inbox
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-4">
          {data?.inboxes?.map((inbox) => (
            <Card key={inbox.id}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="h-10 w-10 rounded-full bg-primary-100 flex items-center justify-center">
                    <InboxIcon className="h-5 w-5 text-primary-600" />
                  </div>
                  <div>
                    <p className="font-medium text-gray-900">{inbox.email_address}</p>
                    <p className="text-sm text-gray-500">{inbox.domain}</p>
                  </div>
                </div>

                <div className="flex items-center gap-6">
                  <div className="text-center">
                    <p className="text-sm text-gray-500">Sent Today</p>
                    <p className="text-lg font-semibold text-gray-900">
                      {inbox.emails_sent_today}/{inbox.daily_limit}
                    </p>
                  </div>

                  <div className="w-32">
                    <p className="text-sm text-gray-500 mb-1">Health</p>
                    <HealthScore score={inbox.health_score} />
                  </div>

                  <div>
                    <StatusBadge status={inbox.warmup_stage || 'not_started'} />
                  </div>

                  <div>
                    <StatusBadge
                      status={inbox.is_active ? 'active' : 'paused'}
                      variant={inbox.is_active ? 'success' : 'warning'}
                    />
                  </div>

                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      if (confirm('Delete this inbox?')) {
                        deleteMutation.mutate(inbox.id)
                      }
                    }}
                  >
                    <TrashIcon className="h-4 w-4 text-gray-400 hover:text-red-500" />
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
