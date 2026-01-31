import { useQuery } from '@tanstack/react-query'
import { BellIcon, Cog6ToothIcon } from '@heroicons/react/24/outline'
import { apiClient } from '../../services/apiClient'

export default function Header() {
  const { data: status } = useQuery({
    queryKey: ['system-status'],
    queryFn: async () => {
      const response = await apiClient.get('/api/v1/system/status')
      return response.data
    },
    refetchInterval: 30000, // Refresh every 30 seconds
  })

  return (
    <header className="sticky top-0 z-10 flex h-16 shrink-0 items-center border-b border-gray-200 bg-white px-6">
      <div className="flex flex-1 items-center justify-between">
        {/* Page title will be injected here */}
        <div></div>

        {/* Right side actions */}
        <div className="flex items-center gap-4">
          {/* Quick stats */}
          {status && (
            <div className="hidden md:flex items-center gap-4 text-sm">
              <div className="flex items-center gap-2">
                <span className="text-gray-500">Inboxes:</span>
                <span className="font-medium text-gray-900">
                  {status.counts?.active_inboxes || 0}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-gray-500">Queue:</span>
                <span className="font-medium text-gray-900">
                  {status.counts?.queue_pending || 0}
                </span>
              </div>
            </div>
          )}

          {/* Notification bell */}
          <button
            type="button"
            className="rounded-full p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-500"
          >
            <BellIcon className="h-5 w-5" />
          </button>

          {/* Settings */}
          <button
            type="button"
            className="rounded-full p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-500"
          >
            <Cog6ToothIcon className="h-5 w-5" />
          </button>
        </div>
      </div>
    </header>
  )
}
