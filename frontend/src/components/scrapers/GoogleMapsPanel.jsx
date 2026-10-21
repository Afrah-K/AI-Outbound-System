import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { PlayIcon, InformationCircleIcon, KeyIcon, StarIcon } from '@heroicons/react/24/outline'
import toast from 'react-hot-toast'
import { api } from '../../services/apiClient'
import Button from '../common/Button'
import Card from '../common/Card'
import { useTask } from '../../context/BackgroundTasks'
import { WebsiteLink } from './ScrapeResults'
import { ScrapeProgress, Toggle, errorMessage, inputClass, loadCached, saveCached } from './shared'

const OPTIONS_CACHE_KEY = 'scraper_google_maps_options'
const SECONDS_PER_REQUEST = 1.5

const DEFAULT_OPTIONS = {
  queriesText: '',
  locationsText: '',
  perSearch: 20,
  filters: {
    min_rating: 0,
    min_reviews: 0,
    require_website: true,
    exclude_closed: true,
    max_results: 0,
  },
}

const lines = (text) => text.split('\n').map((l) => l.trim()).filter(Boolean)

export const GOOGLE_MAPS_COLUMNS = [
  {
    key: 'name',
    label: 'Name',
    sortValue: (r) => (r.name || '').toLowerCase(),
    className: 'max-w-[240px] font-medium text-gray-900',
    render: (r) => (
      <div>
        {r.maps_url ? (
          <a href={r.maps_url} target="_blank" rel="noopener noreferrer" className="hover:underline truncate block" title="Open in Google Maps">
            {r.name || '-'}
          </a>
        ) : (
          <span className="truncate block">{r.name || '-'}</span>
        )}
        {r.category && <div className="text-xs font-normal text-gray-400 truncate">{r.category}</div>}
      </div>
    ),
  },
  { key: 'website', label: 'Website', className: 'whitespace-nowrap max-w-[200px] truncate', render: (r) => <WebsiteLink url={r.website} /> },
  { key: 'phone', label: 'Phone' },
  { key: 'location', label: 'Address', sortValue: (r) => (r.location || '').toLowerCase(), className: 'text-xs min-w-[200px]' },
  {
    key: 'rating',
    label: 'Rating',
    sortValue: (r) => Number(r.rating) || 0,
    render: (r) =>
      r.rating ? (
        <span className="inline-flex items-center gap-1">
          <StarIcon className="h-3.5 w-3.5 text-amber-500" />
          {Number(r.rating).toFixed(1)}
        </span>
      ) : '-',
  },
  { key: 'reviews', label: 'Reviews', sortValue: (r) => Number(r.reviews) || 0 },
]
export const GOOGLE_MAPS_SEARCH_KEYS = ['name', 'website', 'location', 'category', 'phone', 'search']

function KeySetup({ scraper }) {
  const queryClient = useQueryClient()
  const [key, setKey] = useState('')
  const [editing, setEditing] = useState(false)

  const saveMutation = useMutation({
    mutationFn: (value) => api.scrapers.saveGoogleMapsKey(value),
    onSuccess: (_response, value) => {
      toast.success(value ? 'API key saved' : 'API key removed')
      setKey('')
      setEditing(false)
      queryClient.invalidateQueries({ queryKey: ['scrapers'] })
    },
  })

  if (scraper?.configured && !editing) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
        <KeyIcon className="h-4 w-4 text-green-600" />
        <span>
          Google API key {scraper.key_source === 'env' ? 'set in backend/.env (GOOGLE_MAPS_API_KEY)' : 'saved'}
        </span>
        {scraper.key_source === 'saved' && (
          <>
            <button type="button" onClick={() => setEditing(true)} className="text-primary-600 hover:underline">Change</button>
            <button type="button" onClick={() => saveMutation.mutate('')} className="text-gray-500 hover:text-red-600 hover:underline">Remove</button>
          </>
        )}
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
      <div className="flex items-center gap-2">
        <KeyIcon className="h-5 w-5 text-amber-600" />
        <p className="text-sm font-medium text-gray-900">{editing ? 'Change the Google API key' : 'Add a Google API key to start'}</p>
      </div>
      <ol className="mt-2 ml-7 list-decimal space-y-1 text-xs text-gray-600">
        <li>
          In{' '}
          <a href="https://console.cloud.google.com/apis/library/places.googleapis.com" target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:underline">
            Google Cloud Console
          </a>
          , enable <strong>Places API (New)</strong> on a project with billing turned on.
        </li>
        <li>
          Create an API key under{' '}
          <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:underline">
            Credentials
          </a>{' '}
          (restricting it to Places API (New) is a good idea).
        </li>
        <li>Paste it below - or put it in backend/.env as GOOGLE_MAPS_API_KEY.</li>
      </ol>
      <form
        className="mt-3 ml-7 flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (key.trim()) saveMutation.mutate(key.trim())
        }}
      >
        <input
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="AIza..."
          autoComplete="off"
          className="w-80 max-w-full rounded-lg border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 text-sm font-mono"
        />
        <Button type="submit" size="sm" loading={saveMutation.isPending} disabled={!key.trim()}>
          Save key
        </Button>
        {editing && (
          <Button type="button" size="sm" variant="secondary" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        )}
      </form>
    </div>
  )
}

export default function GoogleMapsPanel({ scraper, onBusyChange }) {
  const cached = loadCached(OPTIONS_CACHE_KEY)
  const [queriesText, setQueriesText] = useState(cached?.queriesText ?? DEFAULT_OPTIONS.queriesText)
  const [locationsText, setLocationsText] = useState(cached?.locationsText ?? DEFAULT_OPTIONS.locationsText)
  const [perSearch, setPerSearch] = useState(cached?.perSearch || DEFAULT_OPTIONS.perSearch)
  const [filters, setFilters] = useState({ ...DEFAULT_OPTIONS.filters, ...(cached?.filters || {}) })

  useEffect(() => {
    saveCached(OPTIONS_CACHE_KEY, { queriesText, locationsText, perSearch, filters })
  }, [queriesText, locationsText, perSearch, filters])

  const setFilter = (key, value) => setFilters((prev) => ({ ...prev, [key]: value }))

  const queries = lines(queriesText)
  const locations = lines(locationsText)
  const searchCount = queries.length * Math.max(1, locations.length)
  const maxSearches = scraper?.max_searches || 10
  const tooMany = searchCount > maxSearches
  const requests = searchCount * Math.ceil(perSearch / 20)
  const preview = queries.length ? `${queries[0]}${locations.length ? ` in ${locations[0]}` : ''}` : ''

  const { task, isRunning, start } = useTask('google_maps')

  const runMutation = useMutation({
    mutationFn: () =>
      api.scrapers.startGoogleMapsJob({
        queries,
        locations,
        per_search: perSearch,
        filters: {
          ...filters,
          min_rating: Number(filters.min_rating) || 0,
          min_reviews: Number(filters.min_reviews) || 0,
          max_results: Number(filters.max_results) || 0,
        },
      }),
    onSuccess: (response) => {
      start(response.data, { label: `Google Maps: ${searchCount} search${searchCount === 1 ? '' : 'es'}` })
      toast.success('Search started - you can keep using other pages')
    },
    onError: (error) => toast.error(errorMessage(error, 'Could not start the search')),
  })

  const searching = runMutation.isPending || isRunning

  useEffect(() => {
    onBusyChange?.(searching)
  }, [searching, onBusyChange])

  return (
    <>
      <Card>
        <Card.Header>
          <Card.Title>{scraper?.name || 'Google Maps'}</Card.Title>
          <Card.Description>{scraper?.description}</Card.Description>
        </Card.Header>

        {scraper?.live_fetch_note && (
          <div className="flex gap-2 rounded-lg bg-blue-50 border border-blue-200 p-3 mb-4">
            <InformationCircleIcon className="h-5 w-5 text-blue-500 shrink-0" />
            <p className="text-sm text-blue-800">{scraper.live_fetch_note}</p>
          </div>
        )}

        <div className="space-y-6">
          <KeySetup scraper={scraper} />

          {/* Searches */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">What to search for</label>
              <textarea
                value={queriesText}
                onChange={(e) => setQueriesText(e.target.value)}
                rows={4}
                placeholder={'web design agency\nbranding studio\nmarketing agency'}
                className={inputClass}
              />
              <p className="mt-1 text-xs text-gray-500">One search per line - like you'd type into Google Maps</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Where <span className="font-normal text-gray-400">(optional)</span>
              </label>
              <textarea
                value={locationsText}
                onChange={(e) => setLocationsText(e.target.value)}
                rows={4}
                placeholder={'Austin, TX\nDenver, CO\nLondon, UK'}
                className={inputClass}
              />
              <p className="mt-1 text-xs text-gray-500">One per line - each search runs in each location</p>
            </div>
          </div>

          {/* Filters */}
          <div>
            <h4 className="text-sm font-medium text-gray-900">Filters</h4>
            <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Results per search</label>
                <select value={perSearch} onChange={(e) => setPerSearch(Number(e.target.value))} className={inputClass}>
                  {(scraper?.per_search_options || [20, 40, 60]).map((n) => (
                    <option key={n} value={n}>
                      Up to {n} ({n / 20} request{n === 20 ? '' : 's'})
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-gray-500">60 is Google's maximum per search</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Min rating</label>
                <select value={filters.min_rating} onChange={(e) => setFilter('min_rating', Number(e.target.value))} className={inputClass}>
                  {(scraper?.min_rating_options || [0, 3.5, 4, 4.5, 4.8]).map((v) => (
                    <option key={v} value={v}>{v === 0 ? 'Any rating' : `${Number(v).toFixed(1)}+ stars`}</option>
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
              <Toggle label="Skip closed businesses" hint="Permanently or temporarily closed" checked={filters.exclude_closed} onChange={(v) => setFilter('exclude_closed', v)} />
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-100 pt-4">
            <p className="text-xs text-gray-500">
              {searchCount > 0 ? (
                <>
                  {searchCount} search{searchCount === 1 ? '' : 'es'} · up to {requests} API request{requests === 1 ? '' : 's'}
                  {preview && <> · e.g. "{preview}"</>}
                </>
              ) : (
                'Enter at least one search'
              )}
              {tooMany && <span className="text-red-600"> · max {maxSearches} searches per run (searches × locations)</span>}
            </p>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                onClick={() => {
                  setFilters(DEFAULT_OPTIONS.filters)
                  setPerSearch(DEFAULT_OPTIONS.perSearch)
                }}
              >
                Reset filters
              </Button>
              <Button
                icon={PlayIcon}
                onClick={() => runMutation.mutate()}
                loading={searching}
                disabled={!scraper?.configured || searchCount === 0 || tooMany}
              >
                {searching ? 'Searching...' : `Search Google Maps (${searchCount})`}
              </Button>
            </div>
          </div>
        </div>
      </Card>

      {searching && (
        <ScrapeProgress
          title={`Searching ${task?.label?.replace('Google Maps: ', '') || 'Google Maps'}...`}
          detail={`Up to ${requests} API request${requests === 1 ? '' : 's'}`}
          message={task?.message}
          done={task?.processed}
          total={task?.total}
          startedAt={task?.startedAt}
          estimatedSeconds={(task?.total || requests) * SECONDS_PER_REQUEST}
        />
      )}
    </>
  )
}
