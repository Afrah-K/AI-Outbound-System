import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { PlusIcon, TrashIcon, InboxIcon, PaperAirplaneIcon, SignalIcon, XMarkIcon, ServerStackIcon, PencilSquareIcon } from '@heroicons/react/24/outline'
import { api } from '../services/apiClient'
import Button from '../components/common/Button'
import Card from '../components/common/Card'
import StatusBadge from '../components/common/StatusBadge'
import LoadingSpinner from '../components/common/LoadingSpinner'
import EmptyState from '../components/common/EmptyState'
import toast from 'react-hot-toast'
import SmtpInboxModal from '../components/inboxes/SmtpInboxModal'

function ProviderBadge({ inbox }) {
  const smtp = inbox.provider === 'smtp'
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
        smtp ? 'bg-gray-100 text-gray-700' : 'bg-blue-50 text-blue-700'
      }`}
      title={smtp ? `SMTP ${inbox.smtp?.smtp_host} · IMAP ${inbox.smtp?.imap_host}` : 'Connected with Google'}
    >
      {smtp ? <ServerStackIcon className="h-3 w-3" /> : <InboxIcon className="h-3 w-3" />}
      {smtp ? 'SMTP/IMAP' : 'Gmail'}
    </span>
  )
}

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
  const [sendModalInbox, setSendModalInbox] = useState(null)
  const [testRecipient, setTestRecipient] = useState('')
  // null = closed, 'new' = connect a new SMTP/IMAP inbox, an inbox = update its settings
  const [smtpModal, setSmtpModal] = useState(null)

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

  const testMutation = useMutation({
    mutationFn: (id) => api.inboxes.test(id),
    onSuccess: (response) => {
      if (response.data.success) {
        toast.success(`Connected - ${response.data.email} (${response.data.messages_total} messages)`)
      } else {
        toast.error(response.data.error || 'Connection test failed')
      }
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || 'Connection test failed')
    },
  })

  const sendTestMutation = useMutation({
    mutationFn: ({ id, to }) => api.inboxes.sendTest(id, to),
    onSuccess: () => {
      toast.success(`Test email sent to ${testRecipient}`)
      setSendModalInbox(null)
      setTestRecipient('')
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || 'Failed to send test email')
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

  const handleSendTest = () => {
    if (!testRecipient.trim()) {
      toast.error('Enter a recipient email address')
      return
    }
    sendTestMutation.mutate({ id: sendModalInbox.id, to: testRecipient.trim() })
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
          <h1 className="text-3xl font-medium tracking-tight text-gray-900">Inboxes</h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage your connected inboxes - Gmail, or any provider over SMTP/IMAP
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" icon={ServerStackIcon} onClick={() => setSmtpModal('new')}>
            Connect SMTP/IMAP inbox
          </Button>
          <Button icon={PlusIcon} onClick={handleAddInbox}>
            Connect Gmail
          </Button>
        </div>
      </div>

      {data?.inboxes?.length === 0 ? (
        <Card>
          <EmptyState
            icon={InboxIcon}
            title="No inboxes connected"
            description="Connect a Gmail / Google Workspace account, or any other mail account over SMTP/IMAP, to start sending emails"
            action={
              <div className="flex flex-wrap justify-center gap-2">
                <Button variant="secondary" icon={ServerStackIcon} onClick={() => setSmtpModal('new')}>
                  Connect SMTP/IMAP inbox
                </Button>
                <Button icon={PlusIcon} onClick={handleAddInbox}>
                  Connect Gmail
                </Button>
              </div>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-4">
          {data?.inboxes?.map((inbox) => (
            <Card key={inbox.id}>
              <div className="flex items-center justify-between flex-wrap gap-4">
                <div className="flex items-center gap-4">
                  <div className="h-10 w-10 rounded-full bg-primary-600 flex items-center justify-center">
                    <InboxIcon className="h-5 w-5 text-white" />
                  </div>
                  <div>
                    <p className="font-medium text-gray-900">{inbox.email_address}</p>
                    <p className="mt-0.5 flex items-center gap-2 text-sm text-gray-500">
                      <ProviderBadge inbox={inbox} />
                      {inbox.domain}
                      {inbox.connected === false && <span className="text-xs text-red-600">Not connected</span>}
                    </p>
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
                    icon={SignalIcon}
                    onClick={() => testMutation.mutate(inbox.id)}
                    loading={testMutation.isPending && testMutation.variables === inbox.id}
                  >
                    Test
                  </Button>

                  {inbox.provider === 'smtp' && (
                    <Button variant="ghost" size="sm" icon={PencilSquareIcon} onClick={() => setSmtpModal(inbox)}>
                      Settings
                    </Button>
                  )}

                  <Button
                    variant="secondary"
                    size="sm"
                    icon={PaperAirplaneIcon}
                    onClick={() => setSendModalInbox(inbox)}
                  >
                    Send test email
                  </Button>

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

      {sendModalInbox && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-full items-center justify-center p-4">
            <div
              className="fixed inset-0 bg-gray-500 bg-opacity-75"
              onClick={() => setSendModalInbox(null)}
            />
            <div className="relative bg-white rounded-lg shadow-xl max-w-md w-full p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-gray-900">Send test email</h3>
                <button
                  onClick={() => setSendModalInbox(null)}
                  className="text-gray-400 hover:text-gray-500"
                >
                  <XMarkIcon className="h-5 w-5" />
                </button>
              </div>

              <p className="text-sm text-gray-600 mb-4">
                Sends a real email from <strong>{sendModalInbox.email_address}</strong>{' '}
                {sendModalInbox.provider === 'smtp' ? 'over SMTP' : 'via Gmail'}, to confirm this inbox can actually send.
              </p>

              <label className="block text-sm font-medium text-gray-700 mb-1">
                Recipient
              </label>
              <input
                type="email"
                value={testRecipient}
                onChange={(e) => setTestRecipient(e.target.value)}
                placeholder="you@example.com"
                className="w-full rounded-lg border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
                autoFocus
              />

              <div className="flex gap-3 pt-4">
                <Button
                  variant="secondary"
                  className="flex-1"
                  onClick={() => setSendModalInbox(null)}
                >
                  Cancel
                </Button>
                <Button
                  className="flex-1"
                  onClick={handleSendTest}
                  loading={sendTestMutation.isPending}
                >
                  Send
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {smtpModal && <SmtpInboxModal inbox={smtpModal === 'new' ? null : smtpModal} onClose={() => setSmtpModal(null)} />}
    </div>
  )
}
