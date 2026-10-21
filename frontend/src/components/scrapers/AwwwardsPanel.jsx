import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { PlayIcon, InformationCircleIcon, XMarkIcon } from '@heroicons/react/24/outline'
import toast from 'react-hot-toast'
import { api } from '../../services/apiClient'
import Button from '../common/Button'
import Card from '../common/Card'
import { useTask } from '../../context/BackgroundTasks'
import { WebsiteLink } from './ScrapeResults'
import { ScrapeProgress, Toggle, errorMessage, formatDuration, inputClass, loadCached, saveCached } from './shared'

const OPTIONS_CACHE_KEY = 'scraper_awwwards_options'
const SECONDS_PER_PAGE = 2.5
const SECONDS_PER_PROFILE = 1.5

const DEFAULT_FILTERS = {
  countries: [],
  min_total_awards: 0,
  min_sotd: 0,
  pro_only: false,
  require_website: true,
  with_profiles: false,
  active_within_months: 0,
  max_results: 0,
}

const ACTIVITY_OPTIONS = [
  { value: 0, label: 'Any time' },
  { value: 6, label: 'Last 6 months' },
  { value: 12, label: 'Last 12 months' },
  { value: 24, label: 'Last 2 years' },
]

function Award({ label, value }) {
  return (
    <span className={`inline-flex items-baseline gap-0.5 ${value ? 'text-gray-700' : 'text-gray-300'}`}>
      <span className="text-[10px] uppercase">{label}</span>
      <span className="font-medium">{value || 0}</span>
    </span>
  )
}

export const AWWWARDS_COLUMNS = [
  {
    key: 'name',
    label: 'Name',
    sortValue: (r) => (r.name || '').toLowerCase(),
    className: 'max-w-[220px] font-medium text-gray-900',
    render: (r) => (
      <div title={r.bio || undefined}>
        <div className="flex items-center gap-1">
          <a href={r.profile_url} target="_blank" rel="noopener noreferrer" className="hover:underline truncate">
            {r.name || '-'}
          </a>
          {r.pro && <span className="text-[10px] font-semibold text-gray-700 bg-gray-100 rounded px-1">PRO</span>}
        </div>
        {r.listing && <div className="text-xs font-normal text-gray-400 truncate">{r.listing}</div>}
      </div>
    ),
  },
  { key: 'website', label: 'Website', className: 'whitespace-nowrap max-w-[200px] truncate', render: (r) => <WebsiteLink url={r.website} /> },
  {
    key: 'location',
    label: 'Location',
    sortValue: (r) => (r.location || '').toLowerCase(),
    render: (r) => [r.city, r.location].filter(Boolean).join(', ') || '-',
  },
  {
    key: 'total_awards',
    label: 'Awards',
    sortValue: (r) => Number(r.total_awards) || 0,
    render: (r) => (
      <div className="flex gap-2 text-xs">
        <Award label="SOTY" value={r.soty} />
        <Award label="SOTM" value={r.sotm} />
        <Award label="SOTD" value={r.sotd} />
        <Award label="HM" value={r.honorable_mentions} />
      </div>
    ),
  },
  { key: 'last_award_date', label: 'Last award', sortValue: (r) => r.last_award_date || '' },
  { key: 'budget', label: 'Budget' },
  {
    key: 'linkedin',
    label: 'Social',
    render: (r) => {
      const links = [['LinkedIn', r.linkedin], ['Instagram', r.instagram], ['X', r.twitter]].filter(([, url]) => url)
      if (!links.length) return '-'
      return (
        <div className="flex gap-2 text-xs">
          {links.map(([label, url]) => (
            <a key={label} href={url} target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:underline">
              {label}
            </a>
          ))}
        </div>
      )
    },
  },
]
export const AWWWARDS_SEARCH_KEYS = ['name', 'website', 'location', 'city', 'bio', 'listing']

function CountryPicker({ countries, selected, onAdd, placeholder }) {
  const remaining = countries.filter((c) => !selected.includes(c))
  return (
    <select
      value=""
      onChange={(e) => e.target.value && onAdd(e.target.value)}
      className={inputClass}
    >
      <option value="">{placeholder}</option>
      {remaining.map((c) => (
        <option key={c} value={c}>{c}</option>
      ))}
    </select>
  )
}

function Chip({ label, onRemove }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-primary-50 border border-primary-200 px-2.5 py-1 text-xs text-primary-800">
      {label}
      <button type="button" onClick={onRemove} className="hover:text-primary-950" aria-label={`Remove ${label}`}>
        <XMarkIcon className="h-3 w-3" />
      </button>
    </span>
  )
}

export default function AwwwardsPanel({ scraper, onBusyChange }) {
  const cached = loadCached(OPTIONS_CACHE_KEY)
  const [listings, setListings] = useState(cached?.listings || [''])
  const [pages, setPages] = useState(cached?.pages || 2)
  const [filters, setFilters] = useState({ ...DEFAULT_FILTERS, ...(cached?.filters || {}) })

  useEffect(() => {
    saveCached(OPTIONS_CACHE_KEY, { listings, pages, filters })
  }, [listings, pages, filters])

  const groups = scraper?.listing_groups || []
  const countries = scraper?.countries || []
  const maxUrls = scraper?.max_urls || 10
  const cardsPerPage = scraper?.cards_per_page || 24
  const chipGroups = groups.filter((g) => g.group !== 'Country')
  const listingCountries = listings.filter((l) => countries.includes(l))

  const setFilter = (key, value) => setFilters((prev) => ({ ...prev, [key]: value }))
  const toggleListing = (value) =>
    setListings((prev) => (prev.includes(value) ? prev.filter((l) => l !== value) : [...prev, value]))

  const tooMany = listings.length > maxUrls
  const profilesOn = filters.with_profiles || filters.active_within_months > 0
  const pagesToFetch = listings.length * pages
  const profileCount = profilesOn
    ? Math.min(scraper?.max_profiles || 300, Number(filters.max_results) || pagesToFetch * cardsPerPage)
    : 0
  const estimatedSeconds = pagesToFetch * SECONDS_PER_PAGE + profileCount * SECONDS_PER_PROFILE

  const { task, isRunning, start } = useTask('awwwards')

  // Starts a server-side job and returns at once - see ClutchPanel
  const runMutation = useMutation({
    mutationFn: () =>
      api.scrapers.startAwwwardsJob({
        listings,
        pages,
        filters: {
          ...filters,
          with_profiles: profilesOn,
          min_total_awards: Number(filters.min_total_awards) || 0,
          min_sotd: Number(filters.min_sotd) || 0,
          active_within_months: Number(filters.active_within_months) || 0,
          max_results: Number(filters.max_results) || 0,
        },
      }),
    onSuccess: (response) => {
      start(response.data, { label: `Awwwards: ${listings.length} listing${listings.length === 1 ? '' : 's'}` })
      toast.success('Scrape started - you can keep using other pages')
    },
    onError: (error) => toast.error(errorMessage(error, 'Could not start the scraper')),
  })

  const scraping = runMutation.isPending || isRunning

  useEffect(() => {
    onBusyChange?.(scraping)
  }, [scraping, onBusyChange])

  return (
    <>
      <Card>
        <Card.Header>
          <Card.Title>{scraper?.name || 'Awwwards'}</Card.Title>
          <Card.Description>{scraper?.description}</Card.Description>
        </Card.Header>

        {scraper?.live_fetch_note && (
          <div className="flex gap-2 rounded-lg bg-blue-50 border border-blue-200 p-3 mb-4">
            <InformationCircleIcon className="h-5 w-5 text-blue-500 shrink-0" />
            <p className="text-sm text-blue-800">{scraper.live_fetch_note}</p>
          </div>
        )}

        <div className="space-y-6">
          {/* Listings */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="block text-sm font-medium text-gray-700">Listings to browse</label>
              <span className={`text-xs ${tooMany ? 'text-red-600 font-medium' : 'text-gray-500'}`}>
                {listings.length} / {maxUrls} selected
              </span>
            </div>
            <div className="space-y-3">
              {chipGroups.map(({ group, listings: options }) => (
                <div key={group}>
                  <span className="block text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1.5">{group}</span>
                  <div className="flex flex-wrap gap-2">
                    {options.map((o) => {
                      const active = listings.includes(o.value)
                      return (
                        <button
                          key={o.value || 'all'}
                          type="button"
                          onClick={() => toggleListing(o.value)}
                          className={`rounded-full border px-3 py-1 text-sm ${
                            active ? 'border-primary-400 bg-primary-50 text-primary-800' : 'border-gray-200 text-gray-700 hover:bg-gray-50'
                          }`}
                        >
                          {o.label}
                        </button>
                      )
                    })}
                  </div>
                </div>
              ))}
              <div>
                <span className="block text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1.5">Country</span>
                <div className="flex flex-wrap items-center gap-2">
                  <div className="w-64">
                    <CountryPicker countries={countries} selected={listings} onAdd={toggleListing} placeholder="Browse a country's listing..." />
                  </div>
                  {listingCountries.map((c) => (
                    <Chip key={c} label={c} onRemove={() => toggleListing(c)} />
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Filters */}
          <div>
            <h4 className="text-sm font-medium text-gray-900">Filters</h4>
            <p className="text-xs text-gray-500 mb-3">Applied to the studios found in the listings above</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="sm:col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1">Only these countries</label>
                <CountryPicker
                  countries={countries}
                  selected={filters.countries}
                  onAdd={(c) => setFilter('countries', [...filters.countries, c])}
                  placeholder={filters.countries.length ? 'Add another country...' : 'Any country'}
                />
                {filters.countries.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {filters.countries.map((c) => (
                      <Chip key={c} label={c} onRemove={() => setFilter('countries', filters.countries.filter((x) => x !== c))} />
                    ))}
                  </div>
                )}
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Min Sites of the Day</label>
                <input type="number" min={0} value={filters.min_sotd} onChange={(e) => setFilter('min_sotd', e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Min total awards</label>
                <input type="number" min={0} value={filters.min_total_awards} onChange={(e) => setFilter('min_total_awards', e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Pages per listing</label>
                <input
                  type="number"
                  min={1}
                  max={scraper?.max_pages || 10}
                  value={pages}
                  onChange={(e) => setPages(Math.max(1, Math.min(scraper?.max_pages || 10, Number(e.target.value) || 1)))}
                  className={inputClass}
                />
                <p className="mt-1 text-xs text-gray-500">{cardsPerPage} studios per page, most-awarded first</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Won an award in</label>
                <select
                  value={filters.active_within_months}
                  onChange={(e) => setFilter('active_within_months', Number(e.target.value))}
                  className={inputClass}
                >
                  {ACTIVITY_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-gray-500">Turns on profile details</p>
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
              <Toggle label="PRO members only" hint="Paid Awwwards profiles - usually established studios" checked={filters.pro_only} onChange={(v) => setFilter('pro_only', v)} />
              <Toggle
                label="Fetch profile details"
                hint={`City, budget, languages, LinkedIn/Instagram, bio, last award (max ${scraper?.max_profiles || 300})`}
                checked={profilesOn}
                disabled={filters.active_within_months > 0}
                onChange={(v) => setFilter('with_profiles', v)}
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-100 pt-4">
            <p className="text-xs text-gray-500">
              Up to {pagesToFetch} page{pagesToFetch === 1 ? '' : 's'}
              {profilesOn && <> + up to {profileCount} profiles</>}
              {listings.length > 0 && <> · estimated {formatDuration(estimatedSeconds)}</>}
              {tooMany && <span className="text-red-600"> · pick at most {maxUrls} listings</span>}
            </p>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                onClick={() => {
                  setFilters(DEFAULT_FILTERS)
                  setListings([''])
                  setPages(2)
                }}
              >
                Reset
              </Button>
              <Button
                icon={PlayIcon}
                onClick={() => runMutation.mutate()}
                loading={scraping}
                disabled={listings.length === 0 || tooMany}
              >
                {scraping
                  ? 'Scraping listings...'
                  : `Run scraper (${listings.length} listing${listings.length === 1 ? '' : 's'})`}
              </Button>
            </div>
          </div>
        </div>
      </Card>

      {scraping && (
        <ScrapeProgress
          title={`Scraping leads from ${task?.label?.replace('Awwwards: ', '') || 'Awwwards'}...`}
          detail={`Up to ${pagesToFetch} page${pagesToFetch === 1 ? '' : 's'}${profilesOn ? `, then up to ${profileCount} profile pages` : ''}`}
          message={task?.message}
          done={task?.processed}
          total={task?.total}
          startedAt={task?.startedAt}
          estimatedSeconds={estimatedSeconds}
        />
      )}
    </>
  )
}
