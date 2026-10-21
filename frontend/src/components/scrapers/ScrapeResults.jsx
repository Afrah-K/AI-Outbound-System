import { useEffect, useMemo, useState } from 'react'
import {
  ArrowDownTrayIcon,
  MagnifyingGlassCircleIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ChevronUpIcon,
  ChevronDownIcon,
  ExclamationTriangleIcon,
} from '@heroicons/react/24/outline'
import Button from '../common/Button'
import Card from '../common/Card'

const RESULTS_PAGE_SIZE = 40

function rowsToCSV(rows, fields) {
  const lines = rows.map((r) => fields.map((k) => `"${String(r[k] ?? '').replace(/"/g, '""')}"`).join(','))
  return [fields.join(','), ...lines].join('\n')
}

export function downloadCSV(rows, fields, filename) {
  const blob = new Blob([rowsToCSV(rows, fields)], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export function WebsiteLink({ url }) {
  if (!url) return '-'
  return (
    <a
      href={url.startsWith('http') ? url : `https://${url}`}
      target="_blank"
      rel="noopener noreferrer"
      className="text-primary-600 hover:text-primary-800 hover:underline"
    >
      {url.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')}
    </a>
  )
}

/**
 * Per-source stat cards + a searchable, sortable, selectable results table.
 *
 * columns: [{ key, label, sortValue?(row), render?(row), className? }]
 * A column is sortable when it has a sortValue.
 */
export default function ScrapeResults({ results, columns, csvFields, filename, searchKeys, onSendToEnricher }) {
  const [resultsPage, setResultsPage] = useState(1)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState({ key: null, dir: 'desc' })
  const [checkedRows, setCheckedRows] = useState(new Set())

  const allRows = results?.rows || []

  useEffect(() => {
    setResultsPage(1)
    setCheckedRows(new Set())
    setSearch('')
  }, [results])

  useEffect(() => {
    setResultsPage(1)
  }, [search, sort])

  const visibleRows = useMemo(() => {
    const q = search.trim().toLowerCase()
    let rows = allRows.map((r, i) => ({ ...r, _i: i }))
    if (q) {
      rows = rows.filter((r) => searchKeys.some((k) => String(r[k] || '').toLowerCase().includes(q)))
    }
    const column = columns.find((c) => c.key === sort.key)
    if (column?.sortValue) {
      rows.sort((a, b) => {
        const av = column.sortValue(a)
        const bv = column.sortValue(b)
        const cmp = av < bv ? -1 : av > bv ? 1 : 0
        return sort.dir === 'asc' ? cmp : -cmp
      })
    }
    return rows
  }, [allRows, search, sort, columns, searchKeys])

  if (allRows.length === 0) return null

  const totalPages = Math.max(1, Math.ceil(visibleRows.length / RESULTS_PAGE_SIZE))
  const pageResults = visibleRows.slice((resultsPage - 1) * RESULTS_PAGE_SIZE, resultsPage * RESULTS_PAGE_SIZE)
  const checkedList = allRows.filter((_, i) => checkedRows.has(i))
  const withWebsite = allRows.filter((r) => r.website)
  const allVisibleChecked = visibleRows.length > 0 && visibleRows.every((r) => checkedRows.has(r._i))
  const exportRows = checkedList.length > 0 ? checkedList : visibleRows
  const enrichSource = checkedList.length > 0 ? checkedList : allRows

  const toggleSort = (column) => {
    const textual = typeof column.sortValue(allRows[0] || {}) === 'string'
    setSort((prev) =>
      prev.key === column.key
        ? { key: column.key, dir: prev.dir === 'desc' ? 'asc' : 'desc' }
        : { key: column.key, dir: textual ? 'asc' : 'desc' }
    )
  }

  const toggleRow = (i) => {
    setCheckedRows((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })
  }

  const toggleAllVisible = () => {
    setCheckedRows((prev) => {
      const next = new Set(prev)
      visibleRows.forEach((r) => (allVisibleChecked ? next.delete(r._i) : next.add(r._i)))
      return next
    })
  }

  return (
    <>
      {results?.stats?.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {results.stats.map((s) => (
            <div key={s.url} className="rounded-lg border border-gray-200 bg-white p-3">
              <div className="flex items-center justify-between gap-2">
                <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-sm font-medium text-gray-900 hover:underline truncate">
                  {s.category}
                </a>
                {s.error && <ExclamationTriangleIcon className="h-4 w-4 text-amber-500 shrink-0" title={s.error} />}
              </div>
              <p className="mt-1 text-xs text-gray-500">
                {s.listings} listings from {s.pages_fetched} page{s.pages_fetched === 1 ? '' : 's'} · {s.new} new
                {s.total_available ? ` · ${s.total_available.toLocaleString()} available` : ''}
              </p>
              {s.error && <p className="mt-1 text-xs text-amber-700">{s.error}</p>}
            </div>
          ))}
        </div>
      )}

      <Card padding={false}>
        <div className="flex flex-wrap items-center justify-between gap-3 p-6 pb-0">
          <div>
            <Card.Title>{allRows.length} listings found</Card.Title>
            <p className="text-xs text-gray-500 mt-0.5">
              {withWebsite.length} with a website
              {checkedList.length > 0 && <> · {checkedList.length} selected</>}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search results..."
              className="w-64 rounded-lg border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 text-sm"
            />
            <Button variant="secondary" size="sm" icon={ArrowDownTrayIcon} onClick={() => downloadCSV(exportRows, csvFields, filename)}>
              Export {checkedList.length > 0 ? `${checkedList.length} selected` : search ? `${visibleRows.length} shown` : 'CSV'}
            </Button>
            <Button
              size="sm"
              icon={MagnifyingGlassCircleIcon}
              onClick={() => onSendToEnricher(enrichSource.filter((r) => r.website))}
              disabled={enrichSource.every((r) => !r.website)}
            >
              Find emails for {enrichSource.filter((r) => r.website).length}
              {checkedList.length > 0 ? ' selected' : ''}
            </Button>
          </div>
        </div>
        <div className="overflow-x-auto mt-4">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="pl-6 pr-2 py-3">
                  <input
                    type="checkbox"
                    checked={allVisibleChecked}
                    onChange={toggleAllVisible}
                    className="h-4 w-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500"
                  />
                </th>
                {columns.map((column) => (
                  <th key={column.key} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    {column.sortValue ? (
                      <button type="button" onClick={() => toggleSort(column)} className="inline-flex items-center gap-1 uppercase hover:text-gray-800">
                        {column.label}
                        {sort.key === column.key && (sort.dir === 'asc' ? <ChevronUpIcon className="h-3 w-3" /> : <ChevronDownIcon className="h-3 w-3" />)}
                      </button>
                    ) : (
                      column.label
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {pageResults.map((r) => (
                <tr key={r._i} className={`hover:bg-gray-50 ${checkedRows.has(r._i) ? 'bg-primary-50/40' : ''}`}>
                  <td className="pl-6 pr-2 py-3">
                    <input
                      type="checkbox"
                      checked={checkedRows.has(r._i)}
                      onChange={() => toggleRow(r._i)}
                      className="h-4 w-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500"
                    />
                  </td>
                  {columns.map((column) => (
                    <td key={column.key} className={`px-4 py-3 text-sm text-gray-500 ${column.className || 'whitespace-nowrap'}`}>
                      {column.render ? column.render(r) : r[column.key] || '-'}
                    </td>
                  ))}
                </tr>
              ))}
              {pageResults.length === 0 && (
                <tr>
                  <td colSpan={columns.length + 1} className="px-6 py-8 text-center text-sm text-gray-500">No listings match "{search}"</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {totalPages > 1 && (
          <div className="flex items-center justify-between px-6 py-4 border-t border-gray-200">
            <p className="text-sm text-gray-500">
              Page {resultsPage} of {totalPages}
            </p>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                size="sm"
                icon={ChevronLeftIcon}
                onClick={() => setResultsPage((p) => Math.max(1, p - 1))}
                disabled={resultsPage === 1}
              >
                Prev
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setResultsPage((p) => Math.min(totalPages, p + 1))}
                disabled={resultsPage === totalPages}
              >
                Next
                <ChevronRightIcon className="h-4 w-4 ml-2 -mr-1" />
              </Button>
            </div>
          </div>
        )}
      </Card>
    </>
  )
}
