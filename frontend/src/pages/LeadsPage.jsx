import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { UserGroupIcon, BuildingOfficeIcon, ArrowUpTrayIcon, XMarkIcon } from '@heroicons/react/24/outline'
import { api } from '../services/apiClient'
import Button from '../components/common/Button'
import Card from '../components/common/Card'
import StatusBadge from '../components/common/StatusBadge'
import LoadingSpinner from '../components/common/LoadingSpinner'
import EmptyState from '../components/common/EmptyState'
import toast from 'react-hot-toast'

export default function LeadsPage() {
  const [activeTab, setActiveTab] = useState('people')
  const [search, setSearch] = useState('')
  const [showImportModal, setShowImportModal] = useState(false)
  const [selectedFile, setSelectedFile] = useState(null)
  const [updateExisting, setUpdateExisting] = useState(true)
  const fileInputRef = useRef(null)
  const queryClient = useQueryClient()

  const { data: peopleData, isLoading: loadingPeople } = useQuery({
    queryKey: ['people', search],
    queryFn: async () => {
      const response = await api.leads.listPeople({ search, limit: 50 })
      return response.data
    },
    enabled: activeTab === 'people',
  })

  const { data: companiesData, isLoading: loadingCompanies } = useQuery({
    queryKey: ['companies', search],
    queryFn: async () => {
      const response = await api.leads.listCompanies({ search, limit: 50 })
      return response.data
    },
    enabled: activeTab === 'companies',
  })

  const importMutation = useMutation({
    mutationFn: async ({ file, updateExisting }) => {
      const formData = new FormData()
      formData.append('file', file)
      return api.leads.importCSV(formData, updateExisting)
    },
    onSuccess: (response) => {
      const data = response.data
      const messages = []
      if (data.imported_people > 0) messages.push(`${data.imported_people} new`)
      if (data.updated_people > 0) messages.push(`${data.updated_people} updated`)
      if (data.imported_companies > 0) messages.push(`${data.imported_companies} companies`)
      toast.success(`Import complete: ${messages.join(', ')}`)
      console.log('Import result:', data)
      queryClient.invalidateQueries(['people'])
      queryClient.invalidateQueries(['companies'])
      setShowImportModal(false)
      setSelectedFile(null)
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || 'Failed to import CSV')
    },
  })

  const handleFileSelect = (e) => {
    const file = e.target.files?.[0]
    if (file) {
      if (!file.name.endsWith('.csv')) {
        toast.error('Please select a CSV file')
        return
      }
      setSelectedFile(file)
    }
  }

  const handleImport = () => {
    if (selectedFile) {
      importMutation.mutate({ file: selectedFile, updateExisting })
    }
  }

  const isLoading = activeTab === 'people' ? loadingPeople : loadingCompanies
  const data = activeTab === 'people' ? peopleData : companiesData

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Leads</h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage your lead database
          </p>
        </div>
        <Button icon={ArrowUpTrayIcon} onClick={() => setShowImportModal(true)}>
          Import CSV
        </Button>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex gap-6">
          <button
            onClick={() => setActiveTab('people')}
            className={`pb-4 text-sm font-medium border-b-2 ${
              activeTab === 'people'
                ? 'border-primary-500 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <UserGroupIcon className="h-5 w-5 inline mr-2" />
            People ({peopleData?.total || 0})
          </button>
          <button
            onClick={() => setActiveTab('companies')}
            className={`pb-4 text-sm font-medium border-b-2 ${
              activeTab === 'companies'
                ? 'border-primary-500 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <BuildingOfficeIcon className="h-5 w-5 inline mr-2" />
            Companies ({companiesData?.total || 0})
          </button>
        </nav>
      </div>

      {/* Search */}
      <div>
        <input
          type="text"
          placeholder={`Search ${activeTab}...`}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full max-w-md rounded-lg border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
        />
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <LoadingSpinner size="lg" />
        </div>
      ) : data?.people?.length === 0 && data?.companies?.length === 0 ? (
        <Card>
          <EmptyState
            icon={UserGroupIcon}
            title={`No ${activeTab} found`}
            description="Import leads from a CSV file to get started"
            action={
              <Button icon={ArrowUpTrayIcon} onClick={() => setShowImportModal(true)}>
                Import CSV
              </Button>
            }
          />
        </Card>
      ) : (
        <Card padding={false}>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  {activeTab === 'people' ? (
                    <>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                        First Name
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                        Last Name
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                        Email
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                        Role
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                        Company
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                        LinkedIn
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                        Status
                      </th>
                    </>
                  ) : (
                    <>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                        Company
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                        Website
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                        Industry
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                        Location
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                        LinkedIn
                      </th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {activeTab === 'people'
                  ? data?.people?.map((person) => (
                      <tr key={person.id} className="hover:bg-gray-50">
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                          {person.first_name || '-'}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                          {person.last_name || '-'}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          {person.email}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          {person.role || '-'}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          {person.company_name || '-'}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          {person.linkedin_url ? (
                            <a
                              href={person.linkedin_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-primary-600 hover:text-primary-800 hover:underline"
                            >
                              View
                            </a>
                          ) : '-'}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <StatusBadge status={person.status} />
                        </td>
                      </tr>
                    ))
                  : data?.companies?.map((company) => (
                      <tr key={company.id} className="hover:bg-gray-50">
                        <td className="px-6 py-4 whitespace-nowrap">
                          <p className="text-sm font-medium text-gray-900">{company.name}</p>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          {company.website ? (
                            <a
                              href={company.website.startsWith('http') ? company.website : `https://${company.website}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-primary-600 hover:text-primary-800 hover:underline"
                            >
                              {company.domain || 'Visit'}
                            </a>
                          ) : company.domain || '-'}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          {company.industry || '-'}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          {company.location || '-'}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          {company.linkedin_url ? (
                            <a
                              href={company.linkedin_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-primary-600 hover:text-primary-800 hover:underline"
                            >
                              View
                            </a>
                          ) : '-'}
                        </td>
                      </tr>
                    ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Import Modal */}
      {showImportModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-full items-center justify-center p-4">
            <div
              className="fixed inset-0 bg-gray-500 bg-opacity-75"
              onClick={() => setShowImportModal(false)}
            />
            <div className="relative bg-white rounded-lg shadow-xl max-w-md w-full p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-gray-900">Import CSV</h3>
                <button
                  onClick={() => setShowImportModal(false)}
                  className="text-gray-400 hover:text-gray-500"
                >
                  <XMarkIcon className="h-5 w-5" />
                </button>
              </div>

              <div className="space-y-4">
                <div>
                  <p className="text-sm text-gray-600 mb-3">
                    Upload a CSV file with your leads. Expected columns:
                  </p>
                  <ul className="text-xs text-gray-500 list-disc list-inside space-y-1">
                    <li><strong>email</strong> (required)</li>
                    <li>first_name, last_name</li>
                    <li>company, domain</li>
                    <li>role / title</li>
                    <li>linkedin, phone</li>
                  </ul>
                </div>

                <div
                  onClick={() => fileInputRef.current?.click()}
                  className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center cursor-pointer hover:border-primary-500 transition-colors"
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".csv"
                    onChange={handleFileSelect}
                    className="hidden"
                  />
                  {selectedFile ? (
                    <div>
                      <p className="text-sm font-medium text-gray-900">{selectedFile.name}</p>
                      <p className="text-xs text-gray-500 mt-1">
                        {(selectedFile.size / 1024).toFixed(1)} KB
                      </p>
                    </div>
                  ) : (
                    <div>
                      <ArrowUpTrayIcon className="h-8 w-8 mx-auto text-gray-400" />
                      <p className="mt-2 text-sm text-gray-600">
                        Click to select a CSV file
                      </p>
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-2 p-3 bg-gray-50 rounded-lg">
                  <input
                    type="checkbox"
                    id="updateExisting"
                    checked={updateExisting}
                    onChange={(e) => setUpdateExisting(e.target.checked)}
                    className="h-4 w-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500"
                  />
                  <label htmlFor="updateExisting" className="text-sm text-gray-700">
                    Update existing leads (match by email)
                  </label>
                </div>

                <div className="flex gap-3 pt-2">
                  <Button
                    variant="secondary"
                    className="flex-1"
                    onClick={() => {
                      setShowImportModal(false)
                      setSelectedFile(null)
                    }}
                  >
                    Cancel
                  </Button>
                  <Button
                    className="flex-1"
                    onClick={handleImport}
                    loading={importMutation.isLoading}
                    disabled={!selectedFile}
                  >
                    Import
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
