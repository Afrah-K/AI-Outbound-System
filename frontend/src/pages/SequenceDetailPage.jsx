import { Link, useParams } from 'react-router-dom'
import { PencilSquareIcon } from '@heroicons/react/24/outline'
import { useQuery } from '@tanstack/react-query'
import { api } from '../services/apiClient'
import Button from '../components/common/Button'
import Card from '../components/common/Card'
import LoadingSpinner from '../components/common/LoadingSpinner'

export default function SequenceDetailPage() {
  const { id } = useParams()

  const { data: sequence, isLoading } = useQuery({
    queryKey: ['sequence', id],
    queryFn: async () => {
      const response = await api.sequences.get(id)
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

  if (!sequence) {
    return <div>Sequence not found</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-medium tracking-tight text-gray-900">{sequence.name}</h1>
          <p className="mt-1 text-sm text-gray-500">{sequence.description}</p>
        </div>
        <Link to={`/sequences/${sequence.id}/edit`}>
          <Button variant="secondary" icon={PencilSquareIcon}>Edit</Button>
        </Link>
      </div>

      <div className="space-y-4">
        {sequence.steps?.map((step, index) => (
          <Card key={step.id}>
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary-100 flex items-center justify-center text-primary-600 font-medium">
                {index + 1}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-sm text-gray-500">
                    {step.delay_days > 0 || step.delay_hours > 0
                      ? `Wait ${step.delay_days}d ${step.delay_hours}h`
                      : 'Send immediately'}
                  </span>
                  {step.use_gpt && (
                    <span className="px-2 py-0.5 text-xs bg-primary-100 text-primary-800 rounded-full">
                      GPT
                    </span>
                  )}
                </div>
                <p className="font-medium text-gray-900">{step.subject}</p>
                <p className="mt-2 text-sm text-gray-600 whitespace-pre-wrap">{step.body}</p>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
