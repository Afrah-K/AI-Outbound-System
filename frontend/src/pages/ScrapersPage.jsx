import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { GlobeAltIcon } from '@heroicons/react/24/outline'
import { useNavigate } from 'react-router-dom'
import { api } from '../services/apiClient'
import Card from '../components/common/Card'
import ScrapeResults from '../components/scrapers/ScrapeResults'
import ClutchPanel, { CLUTCH_COLUMNS, CLUTCH_SEARCH_KEYS } from '../components/scrapers/ClutchPanel'
import AwwwardsPanel, { AWWWARDS_COLUMNS, AWWWARDS_SEARCH_KEYS } from '../components/scrapers/AwwwardsPanel'
import GoogleMapsPanel, { GOOGLE_MAPS_COLUMNS, GOOGLE_MAPS_SEARCH_KEYS } from '../components/scrapers/GoogleMapsPanel'
import { loadCached, saveCached } from '../components/scrapers/shared'
import { useTask } from '../context/BackgroundTasks'

const ACTIVE_TAB_KEY = 'scraper_active_tab'

const SOURCES = {
  clutch: {
    Panel: ClutchPanel,
    columns: CLUTCH_COLUMNS,
    searchKeys: CLUTCH_SEARCH_KEYS,
    cacheKey: 'scraper_last_results',
    filename: 'clutch_leads.csv',
  },
  awwwards: {
    Panel: AwwwardsPanel,
    columns: AWWWARDS_COLUMNS,
    searchKeys: AWWWARDS_SEARCH_KEYS,
    cacheKey: 'scraper_last_results_awwwards',
    filename: 'awwwards_leads.csv',
  },
  google_maps: {
    Panel: GoogleMapsPanel,
    columns: GOOGLE_MAPS_COLUMNS,
    searchKeys: GOOGLE_MAPS_SEARCH_KEYS,
    cacheKey: 'scraper_last_results_google_maps',
    filename: 'google_maps_leads.csv',
  },
}

// Older cached Clutch results were a bare array of rows
function loadResults(key) {
  const cached = loadCached(key)
  if (!cached) return null
  return Array.isArray(cached) ? { rows: cached, stats: [] } : cached
}

export default function ScrapersPage() {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState(() => {
    const saved = loadCached(ACTIVE_TAB_KEY)
    return SOURCES[saved] ? saved : 'clutch'
  })
  const [busy, setBusy] = useState(false)
  const [resultsBySource, setResultsBySource] = useState(() =>
    Object.fromEntries(Object.entries(SOURCES).map(([id, s]) => [id, loadResults(s.cacheKey)]))
  )

  // Scrapes run as background jobs; when one finishes (even while you were
  // on another page) the tracker caches its rows - pick them up from there.
  const reloadResults = (sourceId) => () =>
    setResultsBySource((prev) => ({ ...prev, [sourceId]: loadResults(SOURCES[sourceId].cacheKey) }))
  useTask('clutch', { onComplete: reloadResults('clutch') })
  useTask('awwwards', { onComplete: reloadResults('awwwards') })
  useTask('google_maps', { onComplete: reloadResults('google_maps') })

  const { data: scrapersData } = useQuery({
    queryKey: ['scrapers'],
    queryFn: async () => {
      const response = await api.scrapers.list()
      return response.data
    },
  })

  const scrapers = (scrapersData?.scrapers || []).filter((s) => SOURCES[s.id])
  const scraper = scrapers.find((s) => s.id === activeTab)
  const source = SOURCES[activeTab]
  const results = resultsBySource[activeTab]

  const selectTab = (id) => {
    setBusy(false)
    setActiveTab(id)
    saveCached(ACTIVE_TAB_KEY, id)
  }

  // Bound to the tab that started the run, so results still land in the right
  // place if you switch tabs before a scrape finishes
  const handleResults = (sourceId) => (data) => {
    setResultsBySource((prev) => ({ ...prev, [sourceId]: data }))
    saveCached(SOURCES[sourceId].cacheKey, data)
  }

  const { Panel } = source

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-medium tracking-tight text-gray-900">Scrapers</h1>
        <p className="mt-1 text-sm text-gray-500">
          Pull raw lead lists from directory sites, ready to hand off to the Enricher
        </p>
      </div>

      <div className="border-b border-gray-200">
        <nav className="-mb-px flex gap-6" aria-label="Scraper sources">
          {(scrapers.length ? scrapers : Object.keys(SOURCES).map((id) => ({ id, name: id }))).map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => selectTab(s.id)}
              className={`whitespace-nowrap border-b-2 px-1 py-3 text-sm font-medium ${
                activeTab === s.id
                  ? 'border-primary-500 text-primary-600'
                  : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
              }`}
            >
              {s.name}
              {resultsBySource[s.id]?.rows?.length > 0 && (
                <span className="ml-2 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                  {resultsBySource[s.id].rows.length}
                </span>
              )}
            </button>
          ))}
        </nav>
      </div>

      {/* key: remount so each source keeps its own form state */}
      <Panel key={activeTab} scraper={scraper} onResults={handleResults(activeTab)} onBusyChange={setBusy} />

      {results?.rows?.length > 0 ? (
        <ScrapeResults
          results={results}
          columns={source.columns}
          csvFields={scraper?.fields || source.columns.map((c) => c.key)}
          filename={source.filename}
          searchKeys={source.searchKeys}
          onSendToEnricher={(rows) => navigate('/enricher', { state: { scrapedRows: rows } })}
        />
      ) : busy ? null : (
        <Card>
          <div className="text-center py-12">
            <GlobeAltIcon className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-4 text-lg font-medium text-gray-900">No results yet</h3>
            <p className="mt-2 text-sm text-gray-500">Run a scraper above to pull a lead list</p>
          </div>
        </Card>
      )}
    </div>
  )
}
