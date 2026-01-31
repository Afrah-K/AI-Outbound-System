import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  PlusIcon,
  TrashIcon,
  ArrowLeftIcon,
  ArrowUpIcon,
  ArrowDownIcon,
} from '@heroicons/react/24/outline'
import { api } from '../services/apiClient'
import Button from '../components/common/Button'
import Card from '../components/common/Card'
import LoadingSpinner from '../components/common/LoadingSpinner'
import toast from 'react-hot-toast'

export default function SequenceFormPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const isEditing = Boolean(id) && id !== 'new'

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [steps, setSteps] = useState([])

  // Fetch existing sequence for editing
  const { isLoading } = useQuery({
    queryKey: ['sequence', id],
    queryFn: async () => {
      const response = await api.sequences.get(id)
      return response.data
    },
    enabled: isEditing,
    onSuccess: (data) => {
      setName(data.name || '')
      setDescription(data.description || '')
      setSteps(
        data.steps?.map((s) => ({
          id: s.id,
          subject: s.subject || '',
          body: s.body || '',
          delay_days: s.delay_days || 0,
          delay_hours: s.delay_hours || 0,
          use_gpt: s.use_gpt || false,
        })) || []
      )
    },
  })

  const createMutation = useMutation({
    mutationFn: (data) => api.sequences.create(data),
    onSuccess: (response) => {
      queryClient.invalidateQueries(['sequences'])
      toast.success('Sequence created')
      navigate(`/sequences/${response.data.id}`)
    },
  })

  const updateMutation = useMutation({
    mutationFn: (data) => api.sequences.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries(['sequences'])
      queryClient.invalidateQueries(['sequence', id])
      toast.success('Sequence updated')
      navigate(`/sequences/${id}`)
    },
  })

  const addStep = () => {
    setSteps([
      ...steps,
      {
        id: `new-${Date.now()}`,
        subject: '',
        body: '',
        delay_days: steps.length === 0 ? 0 : 1,
        delay_hours: 0,
        use_gpt: false,
      },
    ])
  }

  const removeStep = (index) => {
    setSteps(steps.filter((_, i) => i !== index))
  }

  const updateStep = (index, field, value) => {
    setSteps(
      steps.map((step, i) => (i === index ? { ...step, [field]: value } : step))
    )
  }

  const moveStep = (index, direction) => {
    const newIndex = index + direction
    if (newIndex < 0 || newIndex >= steps.length) return
    const newSteps = [...steps]
    const [removed] = newSteps.splice(index, 1)
    newSteps.splice(newIndex, 0, removed)
    setSteps(newSteps)
  }

  const handleSubmit = (e) => {
    e.preventDefault()

    if (!name.trim()) {
      toast.error('Please enter a sequence name')
      return
    }

    if (steps.length === 0) {
      toast.error('Please add at least one step')
      return
    }

    const data = {
      name: name.trim(),
      description: description.trim(),
      steps: steps.map((step, index) => ({
        order: index + 1,
        subject: step.subject,
        body: step.body,
        delay_days: parseInt(step.delay_days) || 0,
        delay_hours: parseInt(step.delay_hours) || 0,
        use_gpt: step.use_gpt,
      })),
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

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" onClick={() => navigate('/sequences')}>
          <ArrowLeftIcon className="h-5 w-5" />
        </Button>
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            {isEditing ? 'Edit Sequence' : 'New Sequence'}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            {isEditing
              ? 'Update your email sequence'
              : 'Create a multi-step email sequence'}
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        <Card>
          <Card.Header>
            <Card.Title>Sequence Details</Card.Title>
          </Card.Header>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Name *
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Cold Outreach - SaaS Founders"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Description
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Describe what this sequence is for..."
                rows={2}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              />
            </div>
          </div>
        </Card>

        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-900">
              Steps ({steps.length})
            </h2>
            <Button type="button" variant="secondary" icon={PlusIcon} onClick={addStep}>
              Add Step
            </Button>
          </div>

          {steps.length === 0 ? (
            <Card>
              <div className="text-center py-8">
                <p className="text-gray-500 mb-4">No steps added yet</p>
                <Button type="button" icon={PlusIcon} onClick={addStep}>
                  Add First Step
                </Button>
              </div>
            </Card>
          ) : (
            <div className="space-y-4">
              {steps.map((step, index) => (
                <Card key={step.id}>
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="flex items-center justify-center w-8 h-8 rounded-full bg-primary-100 text-primary-700 font-semibold text-sm">
                          {index + 1}
                        </span>
                        <span className="font-medium text-gray-900">
                          Step {index + 1}
                        </span>
                        {index === 0 && (
                          <span className="text-xs text-gray-500">
                            (Send immediately)
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-1">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => moveStep(index, -1)}
                          disabled={index === 0}
                        >
                          <ArrowUpIcon className="h-4 w-4" />
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => moveStep(index, 1)}
                          disabled={index === steps.length - 1}
                        >
                          <ArrowDownIcon className="h-4 w-4" />
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => removeStep(index)}
                        >
                          <TrashIcon className="h-4 w-4 text-red-500" />
                        </Button>
                      </div>
                    </div>

                    {index > 0 && (
                      <div className="flex items-center gap-4 p-3 bg-gray-50 rounded-lg">
                        <span className="text-sm text-gray-600">Wait</span>
                        <input
                          type="number"
                          min="0"
                          value={step.delay_days}
                          onChange={(e) =>
                            updateStep(index, 'delay_days', e.target.value)
                          }
                          className="w-20 px-2 py-1 border border-gray-300 rounded text-center"
                        />
                        <span className="text-sm text-gray-600">days</span>
                        <input
                          type="number"
                          min="0"
                          max="23"
                          value={step.delay_hours}
                          onChange={(e) =>
                            updateStep(index, 'delay_hours', e.target.value)
                          }
                          className="w-20 px-2 py-1 border border-gray-300 rounded text-center"
                        />
                        <span className="text-sm text-gray-600">
                          hours after previous step
                        </span>
                      </div>
                    )}

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        Subject Line
                      </label>
                      <input
                        type="text"
                        value={step.subject}
                        onChange={(e) =>
                          updateStep(index, 'subject', e.target.value)
                        }
                        placeholder="e.g., Quick question about {{company}}"
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                      />
                      <p className="mt-1 text-xs text-gray-500">
                        Use {'{{first_name}}'}, {'{{company}}'}, {'{{title}}'} for
                        personalization
                      </p>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        Email Body
                      </label>
                      <textarea
                        value={step.body}
                        onChange={(e) =>
                          updateStep(index, 'body', e.target.value)
                        }
                        placeholder="Write your email content..."
                        rows={6}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 font-mono text-sm"
                      />
                    </div>

                    <div className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        id={`gpt-${step.id}`}
                        checked={step.use_gpt}
                        onChange={(e) =>
                          updateStep(index, 'use_gpt', e.target.checked)
                        }
                        className="h-4 w-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500"
                      />
                      <label
                        htmlFor={`gpt-${step.id}`}
                        className="text-sm text-gray-700"
                      >
                        Use GPT to personalize this email
                      </label>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-3 pt-4 border-t">
          <Button
            type="button"
            variant="secondary"
            onClick={() => navigate('/sequences')}
          >
            Cancel
          </Button>
          <Button type="submit" loading={isSaving}>
            {isEditing ? 'Save Changes' : 'Create Sequence'}
          </Button>
        </div>
      </form>
    </div>
  )
}
