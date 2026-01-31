import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeftIcon } from '@heroicons/react/24/outline'
import { api } from '../services/apiClient'
import Button from '../components/common/Button'
import Card from '../components/common/Card'
import LoadingSpinner from '../components/common/LoadingSpinner'
import toast from 'react-hot-toast'

const TIMEZONES = [
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Toronto',
  'Europe/London',
  'Europe/Paris',
  'Europe/Berlin',
  'Asia/Tokyo',
  'Asia/Singapore',
  'Australia/Sydney',
  'UTC',
]

export default function CampaignFormPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const isEditing = Boolean(id) && id !== 'new'

  const [formData, setFormData] = useState({
    name: '',
    description: '',
    sequence_id: '',
    send_start_time: '09:00',
    send_end_time: '17:00',
    timezone: 'America/New_York',
    send_on_weekends: false,
    stop_on_reply: true,
  })

  // Fetch sequences for dropdown
  const { data: sequencesData } = useQuery({
    queryKey: ['sequences'],
    queryFn: async () => {
      const response = await api.sequences.list()
      return response.data
    },
  })

  // Fetch existing campaign for editing
  const { isLoading } = useQuery({
    queryKey: ['campaign', id],
    queryFn: async () => {
      const response = await api.campaigns.get(id)
      return response.data
    },
    enabled: isEditing,
    onSuccess: (data) => {
      setFormData({
        name: data.name || '',
        description: data.description || '',
        sequence_id: data.sequence_id || '',
        send_start_time: data.send_start_time || '09:00',
        send_end_time: data.send_end_time || '17:00',
        timezone: data.timezone || 'America/New_York',
        send_on_weekends: data.send_on_weekends || false,
        stop_on_reply: data.stop_on_reply !== false,
      })
    },
  })

  const createMutation = useMutation({
    mutationFn: (data) => api.campaigns.create(data),
    onSuccess: (response) => {
      queryClient.invalidateQueries(['campaigns'])
      toast.success('Campaign created')
      navigate(`/campaigns/${response.data.id}`)
    },
  })

  const updateMutation = useMutation({
    mutationFn: (data) => api.campaigns.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries(['campaigns'])
      queryClient.invalidateQueries(['campaign', id])
      toast.success('Campaign updated')
      navigate(`/campaigns/${id}`)
    },
  })

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target
    setFormData((prev) => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value,
    }))
  }

  const handleSubmit = (e) => {
    e.preventDefault()

    if (!formData.name.trim()) {
      toast.error('Please enter a campaign name')
      return
    }

    if (!formData.sequence_id) {
      toast.error('Please select a sequence')
      return
    }

    const data = {
      ...formData,
      name: formData.name.trim(),
      description: formData.description.trim(),
      sequence_id: parseInt(formData.sequence_id),
    }

    if (isEditing) {
      updateMutation.mutate(data)
    } else {
      createMutation.mutate(data)
    }
  }

  if (isEditing && isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  const isSaving = createMutation.isLoading || updateMutation.isLoading
  const sequences = sequencesData?.sequences || []

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" onClick={() => navigate('/campaigns')}>
          <ArrowLeftIcon className="h-5 w-5" />
        </Button>
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            {isEditing ? 'Edit Campaign' : 'New Campaign'}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            {isEditing
              ? 'Update your campaign settings'
              : 'Create a new email campaign'}
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        <Card>
          <Card.Header>
            <Card.Title>Campaign Details</Card.Title>
          </Card.Header>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Campaign Name *
              </label>
              <input
                type="text"
                name="name"
                value={formData.name}
                onChange={handleChange}
                placeholder="e.g., Q1 2024 - SaaS Outreach"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Description
              </label>
              <textarea
                name="description"
                value={formData.description}
                onChange={handleChange}
                placeholder="Describe what this campaign is for..."
                rows={2}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Email Sequence *
              </label>
              <select
                name="sequence_id"
                value={formData.sequence_id}
                onChange={handleChange}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                required
              >
                <option value="">Select a sequence...</option>
                {sequences.map((seq) => (
                  <option key={seq.id} value={seq.id}>
                    {seq.name} ({seq.step_count} steps)
                  </option>
                ))}
              </select>
              {sequences.length === 0 && (
                <p className="mt-1 text-sm text-amber-600">
                  No sequences available.{' '}
                  <a href="/sequences/new" className="underline">
                    Create one first
                  </a>
                </p>
              )}
            </div>
          </div>
        </Card>

        <Card>
          <Card.Header>
            <Card.Title>Send Schedule</Card.Title>
            <Card.Description>
              Configure when emails should be sent
            </Card.Description>
          </Card.Header>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Start Time
                </label>
                <input
                  type="time"
                  name="send_start_time"
                  value={formData.send_start_time}
                  onChange={handleChange}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  End Time
                </label>
                <input
                  type="time"
                  name="send_end_time"
                  value={formData.send_end_time}
                  onChange={handleChange}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Timezone
              </label>
              <select
                name="timezone"
                value={formData.timezone}
                onChange={handleChange}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              >
                {TIMEZONES.map((tz) => (
                  <option key={tz} value={tz}>
                    {tz}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-3 pt-2">
              <div className="flex items-center gap-3">
                <input
                  type="checkbox"
                  id="send_on_weekends"
                  name="send_on_weekends"
                  checked={formData.send_on_weekends}
                  onChange={handleChange}
                  className="h-4 w-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500"
                />
                <label
                  htmlFor="send_on_weekends"
                  className="text-sm text-gray-700"
                >
                  Send emails on weekends
                </label>
              </div>

              <div className="flex items-center gap-3">
                <input
                  type="checkbox"
                  id="stop_on_reply"
                  name="stop_on_reply"
                  checked={formData.stop_on_reply}
                  onChange={handleChange}
                  className="h-4 w-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500"
                />
                <label htmlFor="stop_on_reply" className="text-sm text-gray-700">
                  Stop sequence when lead replies
                </label>
              </div>
            </div>
          </div>
        </Card>

        <div className="flex items-center justify-end gap-3 pt-4 border-t">
          <Button
            type="button"
            variant="secondary"
            onClick={() => navigate('/campaigns')}
          >
            Cancel
          </Button>
          <Button type="submit" loading={isSaving}>
            {isEditing ? 'Save Changes' : 'Create Campaign'}
          </Button>
        </div>
      </form>
    </div>
  )
}
