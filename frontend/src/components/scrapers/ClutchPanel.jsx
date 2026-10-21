import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { PlayIcon, ArrowUpTrayIcon, InformationCircleIcon, CheckBadgeIcon } from '@heroicons/react/24/outline'
import toast from 'react-hot-toast'
import { api } from '../../services/apiClient'
import Button from '../common/Button'
import Card from '../common/Card'
import { useTask } from '../../context/BackgroundTasks'
import { WebsiteLink } from './ScrapeResults'
import { ScrapeProgress, SelectField, Toggle, errorMessage, formatDuration, inputClass, loadCached, saveCached } from './shared'

const OPTIONS_CACHE_KEY = 'scraper_clutch_options'
const SECONDS_PER_PAGE = 14

const DEFAULT_FILTERS = {
  location: '',
  sort_by: '',
  hourly_rate: '',
  budget: '',
  industry: '',
  min_rating: 0,
  min_reviews: 0,
  verified_only: false,
  require_website: true,
  include_sponsored: false,
  max_results: 0,
}

const numberFrom = (value) => Number(String(value || '').replace(/\D/g, '')) || 0

export const CLUTCH_COLUMNS = [
  {
    key: 'name',
    label: 'Name',
    sortValue: (r) => (r.name || '').toLowerCase(),
    className: 'max-w-[220px] font-medium text-gray-900',
    render: (r) => (
      <div title={r.summary || undefined}>
        <div className="flex items-center gap-1">
          {r.profile_url ? (
            <a href={r.profile_url} target="_blank" rel="noopener noreferrer" className="hover:underline truncate">
              {r.name || '-'}
            </a>
          ) : (
            <span className="truncate">{r.name || '-'}</span>
          )}
          {r.verification && <CheckBadgeIcon className="h-4 w-4 text-green-600 shrink-0" title={r.verification} />}
          {r.sponsored && <span className="text-[10px] uppercase text-amber-700 bg-amber-50 rounded px-1">Ad</span>}
        </div>
        {r.category && <div className="text-xs font-normal text-gray-400 truncate">{r.category}</div>}
      </div>
    ),
  },
  { key: 'website', label: 'Website', className: 'whitespace-nowrap max-w-[200px] truncate', render: (r) => <WebsiteLink url={r.website} /> },
  { key: 'location', label: 'Location', sortValue: (r) => (r.location || '').toLowerCase() },
  { key: 'rating', label: 'Rating', sortValue: (r) => Number(r.rating) || 0 },
  { key: 'reviews', label: 'Reviews', sortValue: (r) => Number(r.reviews) || 0 },
  { key: 'hourly_rate', label: 'Rate', sortValue: (r) => numberFrom(String(r.hourly_rate || '').split('-')[0]) },
  { key: 'min_project_size', label: 'Min project', sortValue: (r) => numberFrom(r.min_project_size) },
  { key: 'employees', label: 'Team' },
  { key: 'services', label: 'Services', className: 'text-xs min-w-[200px]' },
]
export const CLUTCH_SEARCH_KEYS = ['name', 'website', 'location', 'services', 'category']

export default function ClutchPanel({ scraper, onResults, onBusyChange }) {
  const cachedOptions = loadCached(OPTIONS_CACHE_KEY)
  const [selectedCategories, setSelectedCategories] = useState(
    cachedOptions?.categories ? new Set(cachedOptions.categories) : null
  )
  const [customUrlsText, setCustomUrlsText] = useState('')
  const [pages, setPages] = useState(cachedOptions?.pages || 1)
  const [filters, setFilters] = useState({ ...DEFAULT_FILTERS, ...(cachedOptions?.filters || {}) })
  const [customLocation, setCustomLocation] = useState(cachedOptions?.customLocation || '')
  const [selectedFiles, setSelectedFiles] = useState([])
  const [dragActive, setDragActive] = useState(false)
  const fileInputRef = useRef(null)

  const groups = scraper?.category_groups || [{ group: 'Categories', categories: scraper?.categories || [] }]
  const filterOptions = scraper?.filter_options || {}
  const maxUrls = scraper?.max_urls || 10
  const locationPresets = filterOptions.location || [{ value: '', label: 'Anywhere' }]
  const isPresetLocation = locationPresets.some((o) => o.value === filters.location) && !customLocation

  useEffect(() => {
    if (scraper && selectedCategories === null) {
      setSelectedCategories(new Set(scraper.default_urls || []))
    }
  }, [scraper, selectedCategories])

  useEffect(() => {
    saveCached(OPTIONS_CACHE_KEY, {
      categories: selectedCategories ? [...selectedCategories] : undefined,
      pages,
      filters,
      customLocation,
    })
  }, [selectedCategories, pages, filters, customLocation])

  const setFilter = (key, value) => setFilters((prev) => ({ ...prev, [key]: value }))

  const toggleCategory = (url) => {
    setSelectedCategories((prev) => {
      const next = new Set(prev)
      if (next.has(url)) next.delete(url)
      else next.add(url)
      return next
    })
  }

  const setGroupSelected = (categories, selected) => {
    setSelectedCategories((prev) => {
      const next = new Set(prev)
      categories.forEach((c) => (selected ? next.add(c.url) : next.delete(c.url)))
      return next
    })
  }

  const customUrls = customUrlsText.split('\n').map((u) => u.trim()).filter(Boolean)
  const selectedUrls = [...new Set([...(selectedCategories || []), ...customUrls])]
  const tooManyUrls = selectedUrls.length > maxUrls
  const estimatedSeconds = selectedUrls.length * pages * SECONDS_PER_PAGE

  const handleSuccess = (response) => {
    onResults({ rows: response.data.rows, stats: response.data.stats || [] })
    toast.success(`Found ${response.data.count} listings`)
  }

  const { task, isRunning, start } = useTask('clutch')

  // Starts a server-side job and returns at once; the app-wide task tracker
  // polls it, so the scrape keeps going if you switch pages.
  const runMutation = useMutation({
    mutationFn: () =>
      api.scrapers.startClutchJob({
        urls: selectedUrls,
        pages,
        filters: {
          ...filters,
          location: customLocation.trim() || filters.location,
          min_rating: Number(filters.min_rating) || 0,
          min_reviews: Number(filters.min_reviews) || 0,
          max_results: Number(filters.max_results) || 0,
        },
      }),
    onSuccess: (response) => {
      start(response.data, {
        label: `Clutch: ${selectedUrls.length} categor${selectedUrls.length === 1 ? 'y' : 'ies'}`,
      })
      toast.success('Scrape started - you can keep using other pages')
    },
    onError: (error) => toast.error(errorMessage(error, 'Could not start the scraper')),
  })

  const parseMutation = useMutation({
    mutationFn: (files) => {
      const formData = new FormData()
      files.forEach((f) => formData.append('files', f))
      formData.append('include_sponsored', String(filters.include_sponsored))
      formData.append('require_website', String(filters.require_website))
      return api.scrapers.parseClutchFiles(formData)
    },
    onSuccess: handleSuccess,
    onError: (error) => toast.error(errorMessage(error, 'Failed to parse the uploaded page(s)')),
  })

  const handleFiles = (fileList) => {
    const files = Array.from(fileList || []).filter((f) => /\.html?$/i.test(f.name))
    if (files.length === 0) {
      toast.error('Please select saved .html page(s)')
      return
    }
    setSelectedFiles(files)
  }

  // React Query v5: in-flight mutations report isPending (isLoading no longer exists)
  const scraping = runMutation.isPending || isRunning
  const isBusy = scraping || parseMutation.isPending

  useEffect(() => {
    onBusyChange?.(isBusy)
  }, [isBusy, onBusyChange])

  return (
    <>
      <Card>
        <Card.Header>
          <Card.Title>{scraper?.name || 'Clutch'}</Card.Title>
          <Card.Description>{scraper?.description}</Card.Description>
        </Card.Header>

        {scraper?.live_fetch_note && (
          <div className="flex gap-2 rounded-lg bg-blue-50 border border-blue-200 p-3 mb-4">
            <InformationCircleIcon className="h-5 w-5 text-blue-500 shrink-0" />
            <p className="text-sm text-blue-800">{scraper.live_fetch_note}</p>
          </div>
        )}

        <div className="space-y-6">
          {/* Categories */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="block text-sm font-medium text-gray-700">Categories</label>
              <span className={`text-xs ${tooManyUrls ? 'text-red-600 font-medium' : 'text-gray-500'}`}>
                {selectedUrls.length} / {maxUrls} selected
              </span>
            </div>
            <div className="space-y-4">
              {groups.map(({ group, categories }) => {
                const selectedInGroup = categories.filter((c) => selectedCategories?.has(c.url)).length
                return (
                  <div key={group}>
                    <div className="flex items-center gap-3 mb-1.5">
                      <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">{group}</span>
                      <button
                        type="button"
                        onClick={() => setGroupSelected(categories, selectedInGroup < categories.length)}
                        className="text-xs text-primary-600 hover:text-primary-800"
                      >
                        {selectedInGroup < categories.length ? 'Select all' : 'Clear'}
                      </button>
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
                      {categories.map((c) => (
                        <label
                          key={c.url}
                          className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm cursor-pointer hover:bg-gray-50 ${
                            selectedCategories?.has(c.url) ? 'border-primary-300 bg-primary-50/40' : 'border-gray-200'
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={selectedCategories?.has(c.url) || false}
                            onChange={() => toggleCategory(c.url)}
                            className="h-4 w-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500"
                          />
                          {c.label}
                        </label>
                      ))}
                    </div>
                  </div>
                )
              })}
            </div>

            <details className="mt-3">
              <summary className="cursor-pointer text-xs font-medium text-gray-500 hover:text-gray-700">
                Add a custom category URL
              </summary>
              <textarea
                value={customUrlsText}
                onChange={(e) => setCustomUrlsText(e.target.value)}
                rows={2}
                placeholder="https://clutch.co/agencies/&lt;category&gt; (one per line)"
                className="mt-2 w-full rounded-lg border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 font-mono text-xs"
              />
            </details>
          </div>

          {/* Clutch-side filters */}
          <div>
            <h4 className="text-sm font-medium text-gray-900">Search filters</h4>
            <p className="text-xs text-gray-500 mb-3">Applied by Clutch itself, so each page you fetch is already targeted</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Location</label>
                <select
                  value={isPresetLocation ? filters.location : '__custom'}
                  onChange={(e) => {
                    if (e.target.value === '__custom') {
                      setCustomLocation(customLocation || ' ')
                      setFilter('location', '')
                    } else {
                      setCustomLocation('')
                      setFilter('location', e.target.value)
                    }
                  }}
                  className={inputClass}
                >
                  {locationPresets.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                  <option value="__custom">Other city / region...</option>
                </select>
                {!isPresetLocation && (
                  <input
                    type="text"
                    value={customLocation.trimStart()}
                    onChange={(e) => setCustomLocation(e.target.value)}
                    placeholder="US city: seattle · elsewhere: uk/manchester, ca/vancouver"
                    className={`${inputClass} mt-2`}
                  />
                )}
              </div>
              <SelectField label="Sort by" value={filters.sort_by} onChange={(v) => setFilter('sort_by', v)} options={filterOptions.sort_by} />
              <SelectField label="Industry focus" value={filters.industry} onChange={(v) => setFilter('industry', v)} options={filterOptions.industry} />
              <SelectField label="Hourly rate" value={filters.hourly_rate} onChange={(v) => setFilter('hourly_rate', v)} options={filterOptions.hourly_rate} />
              <SelectField label="Client budget" value={filters.budget} onChange={(v) => setFilter('budget', v)} options={filterOptions.budget} />
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Pages per category</label>
                <input
                  type="number"
                  min={1}
                  max={scraper?.max_pages || 1}
                  value={pages}
                  onChange={(e) => setPages(Math.max(1, Math.min(scraper?.max_pages || 1, Number(e.target.value) || 1)))}
                  className={inputClass}
                />
                <p className="mt-1 text-xs text-gray-500">~50 listings per page</p>
              </div>
            </div>
          </div>

          {/* Local quality filters */}
          <div>
            <h4 className="text-sm font-medium text-gray-900">Lead quality</h4>
            <p className="text-xs text-gray-500 mb-3">Applied to the scraped results before they're returned</p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Min rating</label>
                <select value={filters.min_rating} onChange={(e) => setFilter('min_rating', Number(e.target.value))} className={inputClass}>
                  {[0, 4, 4.5, 4.7, 4.8, 4.9, 5].map((v) => (
                    <option key={v} value={v}>{v === 0 ? 'Any rating' : `${v.toFixed(1)}+`}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Min reviews</label>
                <input type="number" min={0} value={filters.min_reviews} onChange={(e) => setFilter('min_reviews', e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Stop after (results)</label>
                <input
                  type="number"
                  min={0}
                  max={scraper?.max_results}
                  value={filters.max_results}
                  onChange={(e) => setFilter('max_results', e.target.value)}
                  className={inputClass}
                />
                <p className="mt-1 text-xs text-gray-500">0 = no limit</p>
              </div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-4">
              <Toggle label="Has a website" hint="Needed to find emails later" checked={filters.require_website} onChange={(v) => setFilter('require_website', v)} />
              <Toggle label="Clutch-verified only" hint="Verified or Premier Verified" checked={filters.verified_only} onChange={(v) => setFilter('verified_only', v)} />
              <Toggle
                label="Include sponsored listings"
                hint="Ads ignore your filters and hide their website"
                checked={filters.include_sponsored}
                onChange={(v) => setFilter('include_sponsored', v)}
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-100 pt-4">
            <p className="text-xs text-gray-500">
              {selectedUrls.length * pages} page{selectedUrls.length * pages === 1 ? '' : 's'} to fetch
              {selectedUrls.length > 0 && <> · estimated {formatDuration(estimatedSeconds)}</>}
              {tooManyUrls && <span className="text-red-600"> · pick at most {maxUrls} categories</span>}
            </p>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                onClick={() => {
                  setFilters(DEFAULT_FILTERS)
                  setCustomLocation('')
                  setPages(1)
                }}
              >
                Reset filters
              </Button>
              <Button
                icon={PlayIcon}
                onClick={() => runMutation.mutate()}
                loading={scraping}
                disabled={selectedUrls.length === 0 || tooManyUrls || isBusy}
              >
                {scraping
                  ? 'Scraping listings...'
                  : `Run scraper (${selectedUrls.length} categor${selectedUrls.length === 1 ? 'y' : 'ies'})`}
              </Button>
            </div>
          </div>
        </div>
      </Card>

      <details className="group">
        <summary className="cursor-pointer text-sm font-medium text-gray-500 hover:text-gray-700">
          Upload saved page(s) instead (fallback, if live fetch stops working)
        </summary>
        <Card className="mt-3">
          <div
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragActive(true) }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(e) => { e.preventDefault(); setDragActive(false); handleFiles(e.dataTransfer.files) }}
            className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
              dragActive ? 'border-primary-500 bg-primary-50' : 'border-gray-300 hover:border-primary-500'
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".html,.htm"
              multiple
              onChange={(e) => handleFiles(e.target.files)}
              className="hidden"
            />
            {selectedFiles.length > 0 ? (
              <div>
                <p className="text-sm font-medium text-gray-900">
                  {selectedFiles.length} file{selectedFiles.length > 1 ? 's' : ''} selected
                </p>
                <p className="text-xs text-gray-500 mt-1">{selectedFiles.map((f) => f.name).join(', ')}</p>
              </div>
            ) : (
              <div>
                <ArrowUpTrayIcon className="h-8 w-8 mx-auto text-gray-400" />
                <p className="mt-2 text-sm text-gray-600">Click to select, or drag and drop saved .html pages</p>
              </div>
            )}
          </div>

          <div className="flex items-center justify-between mt-4">
            <p className="text-xs text-gray-500">Uses the "Has a website" and "Include sponsored" options above</p>
            <Button
              variant="secondary"
              icon={PlayIcon}
              onClick={() => parseMutation.mutate(selectedFiles)}
              loading={parseMutation.isPending}
              disabled={selectedFiles.length === 0 || isBusy}
            >
              {parseMutation.isPending ? 'Parsing...' : 'Parse page(s)'}
            </Button>
          </div>
        </Card>
      </details>

      {scraping && (
        <ScrapeProgress
          title={`Scraping leads from ${task?.label?.replace('Clutch: ', '') || 'Clutch'}...`}
          detail="Runs in the background - about 10-15 seconds per page"
          message={task?.message}
          done={task?.processed}
          total={task?.total}
          startedAt={task?.startedAt}
          estimatedSeconds={(task?.total || selectedUrls.length * pages) * SECONDS_PER_PAGE}
        />
      )}
      {parseMutation.isPending && (
        <ScrapeProgress title="Parsing uploaded page(s)..." estimatedSeconds={Math.max(2, selectedFiles.length)} background={false} />
      )}
    </>
  )
}
