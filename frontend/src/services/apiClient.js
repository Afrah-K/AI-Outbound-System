import axios from 'axios'
import toast from 'react-hot-toast'

export const apiClient = axios.create({
  baseURL: '',
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor
apiClient.interceptors.request.use(
  (config) => {
    // Add any auth headers here if needed in the future
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor
apiClient.interceptors.response.use(
  (response) => {
    return response
  },
  (error) => {
    const message = error.response?.data?.detail || error.message || 'An error occurred'

    // Show error toast for non-404 errors
    if (error.response?.status !== 404) {
      toast.error(message)
    }

    return Promise.reject(error)
  }
)

// API helper functions
export const api = {
  // Inboxes
  inboxes: {
    list: () => apiClient.get('/api/v1/inboxes'),
    get: (id) => apiClient.get(`/api/v1/inboxes/${id}`),
    delete: (id) => apiClient.delete(`/api/v1/inboxes/${id}`),
    initiateOAuth: () => apiClient.get('/api/v1/inboxes/oauth/initiate'),
  },

  // Leads
  leads: {
    listCompanies: (params) => apiClient.get('/api/v1/leads/companies', { params }),
    getCompany: (id) => apiClient.get(`/api/v1/leads/companies/${id}`),
    listPeople: (params) => apiClient.get('/api/v1/leads/people', { params }),
    getPerson: (id) => apiClient.get(`/api/v1/leads/people/${id}`),
    updatePersonStatus: (id, status) =>
      apiClient.patch(`/api/v1/leads/people/${id}/status`, null, { params: { status } }),
    importCSV: (formData, updateExisting = false) =>
      apiClient.post(`/api/v1/leads/import?update_existing=${updateExisting}`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      }),
  },

  // Campaigns
  campaigns: {
    list: (params) => apiClient.get('/api/v1/campaigns', { params }),
    create: (data) => apiClient.post('/api/v1/campaigns', data),
    get: (id) => apiClient.get(`/api/v1/campaigns/${id}`),
    update: (id, data) => apiClient.put(`/api/v1/campaigns/${id}`, data),
    delete: (id) => apiClient.delete(`/api/v1/campaigns/${id}`),
    start: (id) => apiClient.post(`/api/v1/campaigns/${id}/start`),
    pause: (id) => apiClient.post(`/api/v1/campaigns/${id}/pause`),
    resume: (id) => apiClient.post(`/api/v1/campaigns/${id}/resume`),
    getLeads: (id, params) => apiClient.get(`/api/v1/campaigns/${id}/leads`, { params }),
    addLeads: (id, personIds) => apiClient.post(`/api/v1/campaigns/${id}/leads`, personIds),
    assignInboxes: (id, inboxIds) => apiClient.post(`/api/v1/campaigns/${id}/inboxes`, inboxIds),
  },

  // Sequences
  sequences: {
    list: (params) => apiClient.get('/api/v1/sequences', { params }),
    create: (data) => apiClient.post('/api/v1/sequences', data),
    get: (id) => apiClient.get(`/api/v1/sequences/${id}`),
    update: (id, data) => apiClient.put(`/api/v1/sequences/${id}`, data),
    delete: (id) => apiClient.delete(`/api/v1/sequences/${id}`),
    addStep: (id, data) => apiClient.post(`/api/v1/sequences/${id}/steps`, data),
    updateStep: (sequenceId, stepId, data) =>
      apiClient.put(`/api/v1/sequences/${sequenceId}/steps/${stepId}`, data),
    deleteStep: (sequenceId, stepId) =>
      apiClient.delete(`/api/v1/sequences/${sequenceId}/steps/${stepId}`),
    reorderSteps: (id, stepIds) =>
      apiClient.post(`/api/v1/sequences/${id}/steps/reorder`, stepIds),
  },

  // Analytics
  analytics: {
    dashboard: () => apiClient.get('/api/v1/analytics/dashboard'),
    inboxes: (params) => apiClient.get('/api/v1/analytics/inboxes', { params }),
    campaigns: (params) => apiClient.get('/api/v1/analytics/campaigns', { params }),
    daily: (params) => apiClient.get('/api/v1/analytics/daily', { params }),
    healthScores: () => apiClient.get('/api/v1/analytics/health-scores'),
  },

  // System
  system: {
    health: () => apiClient.get('/api/v1/system/health'),
    status: () => apiClient.get('/api/v1/system/status'),
    config: () => apiClient.get('/api/v1/system/config'),
  },
}
