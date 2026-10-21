// Human-readable names for scraped/enriched lead lists, used both as the
// exported CSV's file name and - when that file is imported again, or the
// results are saved to Prospects - as the lead list's name. One name follows a
// list from scrape to enrich to Prospects.

export function shortDate(date = new Date()) {
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

/** "Clutch - UI/UX Design, Branding +2 more - Oct 21" */
export function describeRun(source, labels = []) {
  const unique = [...new Set(labels.filter(Boolean))]
  const shown = unique.slice(0, 2).join(', ')
  const more = unique.length > 2 ? ` +${unique.length - 2} more` : ''
  return [source, shown ? shown + more : null, shortDate()].filter(Boolean).join(' - ')
}

/** A name safe to use as a file name on any OS ("UI/UX" -> "UI-UX"). */
export function toFileName(name, extension = 'csv') {
  const clean = (name || 'leads')
    .replace(/[\\/:*?"<>|]+/g, '-')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 120)
  return `${clean || 'leads'}.${extension}`
}

/** The list name a file's name suggests: "clutch_leads (2).csv" -> "clutch leads (2)". Mirrors the backend. */
export function nameFromFile(fileName) {
  return (fileName || '')
    .replace(/\.(csv|tsv|txt)$/i, '')
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}
