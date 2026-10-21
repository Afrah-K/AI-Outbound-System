import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { PlusIcon, QueueListIcon, TrashIcon, PencilSquareIcon } from '@heroicons/react/24/outline'
import { api } from '../services/apiClient'
import Button from '../components/common/Button'
import Card from '../components/common/Card'
import LoadingSpinner from '../components/common/LoadingSpinner'
import EmptyState from '../components/common/EmptyState'
import toast from 'react-hot-toast'

export default function SequencesPage() {
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['sequences'],
    queryFn: async () => {
      const response = await api.sequences.list()
      return response.data
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => api.sequences.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries(['sequences'])
      toast.success('Sequence deleted')
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
          <h1 className="text-3xl font-medium tracking-tight text-gray-900">Sequences</h1>
          <p className="mt-1 text-sm text-gray-500">
            Create and manage email sequences
          </p>
        </div>
        <Link to="/sequences/new">
          <Button icon={PlusIcon}>New Sequence</Button>
        </Link>
      </div>

      {data?.sequences?.length === 0 ? (
        <Card>
          <EmptyState
            icon={QueueListIcon}
            title="No sequences yet"
            description="Create an email sequence to use in your campaigns"
            action={
              <Link to="/sequences/new">
                <Button icon={PlusIcon}>Create Sequence</Button>
              </Link>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data?.sequences?.map((sequence) => (
            <Card key={sequence.id}>
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-full bg-primary-600 flex items-center justify-center">
                    <QueueListIcon className="h-5 w-5 text-white" />
                  </div>
                  <div>
                    <Link
                      to={`/sequences/${sequence.id}`}
                      className="font-medium text-gray-900 hover:text-primary-600"
                    >
                      {sequence.name}
                    </Link>
                    <p className="text-sm text-gray-500">
                      {sequence.step_count} step{sequence.step_count !== 1 ? 's' : ''}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <Link to={`/sequences/${sequence.id}/edit`} title="Edit sequence">
                    <Button variant="ghost" size="sm">
                      <PencilSquareIcon className="h-4 w-4 text-gray-400 hover:text-primary-600" />
                    </Button>
                  </Link>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      if (confirm('Delete this sequence?')) {
                        deleteMutation.mutate(sequence.id)
                      }
                    }}
                  >
                    <TrashIcon className="h-4 w-4 text-gray-400 hover:text-red-500" />
                  </Button>
                </div>
              </div>
              {sequence.description && (
                <p className="mt-3 text-sm text-gray-500">{sequence.description}</p>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
