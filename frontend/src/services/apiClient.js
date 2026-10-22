import axios from 'axios'
import toast from 'react-hot-toast'

// Fired when the API says the session is gone - the auth context sends you to sign-in
export const UNAUTHORIZED_EVENT = 'outbound:unauthorized'

export const apiClient = axios.create({
  baseURL: '',
  withCredentials: true, // the login session is an HttpOnly cookie
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

// FastAPI's `detail` can be a string, a {message, errors} object, or a list of validation errors.
export function formatErrorDetail(detail) {
  if (!detail) return null
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
  if (detail.errors?.length) return `${detail.message}: ${detail.errors.join('; ')}`
  return detail.message || JSON.stringify(detail)
}

// Response interceptor
apiClient.interceptors.response.use(
  (response) => {
    return response
  },
  (error) => {
    const status = error.response?.status
    const url = error.config?.url || ''

    // Signed out or session expired: not an error to toast - go back to sign-in.
    // (Sign-in form errors themselves are shown by the form.)
    if (url.startsWith('/api/v1/auth/')) return Promise.reject(error)
    if (status === 401) {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
      return Promise.reject(error)
    }

    const message = formatErrorDetail(error.response?.data?.detail) || error.message || 'An error occurred'

    // Show error toast for non-404 errors (unless the caller shows the error itself)
    if (status !== 404 && !error.config?.skipErrorToast) {
      toast.error(message)
    }

    return Promise.reject(error)
  }
)

// API helper functions
export const api = {
  auth: {
    me: () => apiClient.get('/api/v1/auth/me'),
    config: () => apiClient.get('/api/v1/auth/config'),
    login: (email, password) => apiClient.post('/api/v1/auth/login', { email, password }),
    signup: (name, email, password) => apiClient.post('/api/v1/auth/signup', { name, email, password }),
    logout: () => apiClient.post('/api/v1/auth/logout'),
    // Full-page navigation (not XHR): Google's sign-in page, then back to `next`
    googleUrl: (next = '/') => `/api/v1/auth/google/start?next=${encodeURIComponent(next)}`,
  },

  // Inboxes
  inboxes: {
    list: () => apiClient.get('/api/v1/inboxes'),
    get: (id) => apiClient.get(`/api/v1/inboxes/${id}`),
    delete: (id) => apiClient.delete(`/api/v1/inboxes/${id}`),
    initiateOAuth: () => apiClient.get('/api/v1/inboxes/oauth/initiate'),
    // SMTP/IMAP inboxes - the form shows login errors itself (which server failed and why)
    connectSmtp: (data) => apiClient.post('/api/v1/inboxes/smtp', data, { skipErrorToast: true }),
    updateSmtp: (id, data) => apiClient.put(`/api/v1/inboxes/${id}/smtp`, data, { skipErrorToast: true }),
    test: (id) => apiClient.post(`/api/v1/inboxes/${id}/test`),
    sendTest: (id, to) =>
      apiClient.post(`/api/v1/inboxes/${id}/send-test`, null, { params: { to } }),
  },

  // Leads
  leads: {
    listCompanies: (params) => apiClient.get('/api/v1/leads/companies', { params }),
    getCompany: (id) => apiClient.get(`/api/v1/leads/companies/${id}`),
    listPeople: (params) => apiClient.get('/api/v1/leads/people', { params }),
    getPerson: (id) => apiClient.get(`/api/v1/leads/people/${id}`),
    // filters = the Prospects page's { search, status, list_id }; dryRun only reports counts
    bulkDelete: (filters, dryRun = false) =>
      apiClient.post('/api/v1/leads/people/bulk-delete', { ...filters, dry_run: dryRun }),
    bulkUpdateStatus: (personIds, status) =>
      apiClient.post('/api/v1/leads/people/bulk-status', { person_ids: personIds, status }),
    updatePersonStatus: (id, status) =>
      apiClient.patch(`/api/v1/leads/people/${id}/status`, null, { params: { status } }),
    listLists: () => apiClient.get('/api/v1/leads/lists'),
    deleteList: (id) => apiClient.delete(`/api/v1/leads/lists/${id}`),
    renameList: (id, name) => apiClient.patch(`/api/v1/leads/lists/${id}`, { name }),
    // entries: [{ email, company_id }]
    createList: (name, entries) => apiClient.post('/api/v1/leads/lists', { name, entries }),
    importCSV: (formData, updateExisting = false, listName = '') =>
      apiClient.post('/api/v1/leads/import', formData, {
        params: { update_existing: updateExisting, list_name: listName || undefined },
        headers: { 'Content-Type': 'multipart/form-data' },
      }),
    enrichUpload: (formData) =>
      apiClient.post('/api/v1/leads/enrich/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      }),
    getEnrichJob: (jobId) => apiClient.get(`/api/v1/leads/enrich/jobs/${jobId}`),
    rescanEnrich: (companyIds, forceIds, sourceName = null) =>
      apiClient.post('/api/v1/leads/enrich/rescan', { company_ids: companyIds, force_ids: forceIds, source_name: sourceName }),
    // emails: [{ email, previous }] - previous = the address an edited email replaces
    setCompanyEmails: (companyId, emails) => apiClient.put(`/api/v1/leads/companies/${companyId}/emails`, { emails }),
    createPerson: (data) => apiClient.post('/api/v1/leads/people', data),
    pickEmail: (companyId, email) =>
      apiClient.post(`/api/v1/leads/companies/${companyId}/emails/pick`, { email }),
    startVerifyJob: (results) => apiClient.post('/api/v1/leads/verify/jobs', { results }),
    getVerifyJob: (jobId) => apiClient.get(`/api/v1/leads/verify/jobs/${jobId}`),
    enrichCompany: (id) => apiClient.post(`/api/v1/leads/companies/${id}/enrich`),
    verify: (results) =>
      apiClient.post('/api/v1/leads/verify', { results }, { timeout: 2 * 60 * 1000 }),
    personalize: (leads, offer) =>
      apiClient.post('/api/v1/leads/personalize', { leads, offer }),
    getPersonalizeJob: (jobId) => apiClient.get(`/api/v1/leads/personalize/jobs/${jobId}`),
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
    // listId = null adds every prospect
    addLeadList: (id, listId) => apiClient.post(`/api/v1/campaigns/${id}/leads/from-list`, { list_id: listId }),
    uploadLeads: (id, formData) =>
      apiClient.post(`/api/v1/campaigns/${id}/leads/upload`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      }),
    removeLeads: (id, personIds) => apiClient.delete(`/api/v1/campaigns/${id}/leads`, { data: personIds }),
    removeAllLeads: (id) => apiClient.delete(`/api/v1/campaigns/${id}/leads/all`),
    getStats: (id) => apiClient.get(`/api/v1/campaigns/${id}/stats`),
    preview: (id, params) => apiClient.get(`/api/v1/campaigns/${id}/preview`, { params }),
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

  // Unibox
  unibox: {
    listReplies: (days = 30) => apiClient.get('/api/v1/unibox/replies', { params: { days }, timeout: 2 * 60 * 1000 }),
    // folder: 'all' | 'replied' | 'awaiting' - every conversation with a lead, from the email log
    listConversations: (folder = 'all', days = 90) =>
      apiClient.get('/api/v1/unibox/conversations', { params: { folder, days } }),
    listMessages: (perInbox = 15) =>
      apiClient.get('/api/v1/unibox/messages', { params: { per_inbox: perInbox } }),
    getThread: (inboxId, threadId) =>
      apiClient.get(`/api/v1/unibox/threads/${inboxId}/${threadId}`),
    reply: (inboxId, threadId, data) =>
      apiClient.post(`/api/v1/unibox/threads/${inboxId}/${threadId}/reply`, data),
    runAgent: () => apiClient.post('/api/v1/unibox/agent/run', {}, { timeout: 5 * 60 * 1000 }),
    draftThread: (inboxId, threadId, guidance = '') =>
      apiClient.post(`/api/v1/unibox/agent/threads/${inboxId}/${threadId}/draft`, { guidance }, { timeout: 2 * 60 * 1000 }),
    getAgentSettings: () => apiClient.get('/api/v1/unibox/agent/settings'),
    updateAgentSettings: (data) => apiClient.put('/api/v1/unibox/agent/settings', data),
    testAlert: () => apiClient.post('/api/v1/unibox/agent/test-alert'),
    listDrafts: (status = 'pending') => apiClient.get('/api/v1/unibox/agent/drafts', { params: { status } }),
    updateDraft: (id, data) => apiClient.put(`/api/v1/unibox/agent/drafts/${id}`, data),
    sendDraft: (id, body) => apiClient.post(`/api/v1/unibox/agent/drafts/${id}/send`, { body }),
    dismissDraft: (id) => apiClient.post(`/api/v1/unibox/agent/drafts/${id}/dismiss`),
  },

  // Calendar / booking (Calendly)
  calendar: {
    getSettings: () => apiClient.get('/api/v1/calendar/settings'),
    updateSettings: (data) => apiClient.put('/api/v1/calendar/settings', data),
    events: (params) => apiClient.get('/api/v1/calendar/events', { params, timeout: 60 * 1000 }),
  },

  // Scrapers
  scrapers: {
    list: () => apiClient.get('/api/v1/scrapers'),
    runClutch: (data) =>
      apiClient.post('/api/v1/scrapers/clutch/run', data, { timeout: 20 * 60 * 1000 }),
    startClutchJob: (data) => apiClient.post('/api/v1/scrapers/clutch/jobs', data),
    startAwwwardsJob: (data) => apiClient.post('/api/v1/scrapers/awwwards/jobs', data),
    startGoogleMapsJob: (data) => apiClient.post('/api/v1/scrapers/google-maps/jobs', data),
    saveGoogleMapsKey: (apiKey) => apiClient.put('/api/v1/scrapers/google-maps/key', { api_key: apiKey }),
    getJob: (jobId) => apiClient.get(`/api/v1/scrapers/jobs/${jobId}`),
    runAwwwards: (data) =>
      apiClient.post('/api/v1/scrapers/awwwards/run', data, { timeout: 20 * 60 * 1000 }),
    parseClutchFiles: (formData) =>
      apiClient.post('/api/v1/scrapers/clutch/parse', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 60 * 1000,
      }),
  },

  // Analytics
  analytics: {
    dashboard: () => apiClient.get('/api/v1/analytics/dashboard'),
    inboxes: (params) => apiClient.get('/api/v1/analytics/inboxes', { params }),
    campaigns: (params) => apiClient.get('/api/v1/analytics/campaigns', { params }),
    daily: (params) => apiClient.get('/api/v1/analytics/daily', { params }),
    healthScores: () => apiClient.get('/api/v1/analytics/health-scores'),
    // period: 'hour' | 'day' | 'month' | 'year'
    timeseries: (period) => apiClient.get('/api/v1/analytics/timeseries', { params: { period } }),
    placement: (period, source = 'all') => apiClient.get('/api/v1/analytics/placement', { params: { period, source } }),
    runPlacementTest: (campaignId) =>
      apiClient.post('/api/v1/analytics/placement/test', { campaign_id: campaignId || null }, { timeout: 5 * 60 * 1000 }),
  },

  // System
  system: {
    health: () => apiClient.get('/api/v1/system/health'),
    status: () => apiClient.get('/api/v1/system/status'),
    config: () => apiClient.get('/api/v1/system/config'),
  },
}
