import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeftIcon } from '@heroicons/react/24/outline'
import { api } from '../services/apiClient'
import Button from '../components/common/Button'
import Card from '../components/common/Card'
import toast from 'react-hot-toast'
import { allTimezones, browserTimezone, windowInLocalTime } from '../utils/time'


export default function CampaignFormPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [formData, setFormData] = useState({
    name: '',
    description: '',
    sequence_id: '',
    send_start_time: '09:00',
    send_end_time: '17:00',
    timezone: browserTimezone(),
    send_on_weekends: false,
    stop_on_reply: true,
    min_gap_minutes: 2,
    max_gap_minutes: 5,
  })

  // Fetch sequences for dropdown
  const { data: sequencesData } = useQuery({
    queryKey: ['sequences'],
    queryFn: async () => {
      const response = await api.sequences.list()
      return response.data
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
      min_gap_minutes: parseInt(formData.min_gap_minutes, 10) || 0,
      max_gap_minutes: parseInt(formData.max_gap_minutes, 10) || 0,
    }

    if (data.min_gap_minutes > data.max_gap_minutes) {
      toast.error('The minimum pause can\'t be longer than the maximum')
      return
    }

    createMutation.mutate(data)
  }

  const isSaving = createMutation.isPending
  const sequences = sequencesData?.sequences || []

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" onClick={() => navigate('/campaigns')}>
          <ArrowLeftIcon className="h-5 w-5" />
        </Button>
        <div>
          <h1 className="text-3xl font-medium tracking-tight text-gray-900">
            New Campaign
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Create a new email campaign - you'll add recipients and inboxes on the next page
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
                className="w-full px-3 py-2 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
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
                className="w-full px-3 py-2 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
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
                className="w-full px-3 py-2 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
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
                  className="w-full px-3 py-2 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
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
                  className="w-full px-3 py-2 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
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
                className="w-full px-3 py-2 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              >
                {allTimezones([formData.timezone]).map((tz) => (
                  <option key={tz} value={tz}>
                    {tz.replaceAll('_', ' ')}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-xs text-gray-500">
                Emails only go out between the start and end time in this time zone
                {windowInLocalTime(formData.send_start_time, formData.send_end_time, formData.timezone)
                  ? ` (${windowInLocalTime(formData.send_start_time, formData.send_end_time, formData.timezone)})`
                  : ''}
                .
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Pause between emails
              </label>
              <div className="flex items-center gap-2 text-sm">
                <input
                  type="number"
                  name="min_gap_minutes"
                  min={0}
                  max={240}
                  value={formData.min_gap_minutes}
                  onChange={handleChange}
                  className="w-24 px-3 py-2 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                />
                <span className="text-gray-500">to</span>
                <input
                  type="number"
                  name="max_gap_minutes"
                  min={0}
                  max={240}
                  value={formData.max_gap_minutes}
                  onChange={handleChange}
                  className="w-24 px-3 py-2 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                />
                <span className="text-gray-500">minutes</span>
              </div>
              <p className="mt-1 text-xs text-gray-500">
                Emails go out one at a time with a random break in this range between them. Set both to 0 for no pause.
              </p>
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
            Create Campaign
          </Button>
        </div>
      </form>
    </div>
  )
}
