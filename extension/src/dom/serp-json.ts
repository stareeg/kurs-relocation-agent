/**
 * HH SERP: vacancy list from embedded JSON already in the rendered document.
 * No extra request to hh.ru. Port of `extract_vacancies_from_html` (hh.py).
 *
 * Live hh (2026-08-18) encodes the blob as HTML entities (`&#34;`) and sometimes
 * double-escapes quotes inside `mapData`. Same two fixes as the Python parser.
 *
 * SPA pagination (plan 4.3): if JSON ids and DOM card ids are disjoint, the blob is
 * stale (page-1 JSON left in the document) — callers must skip it and use DOM.
 */
import { competitionLevel } from '../../../shared/criteria'
import {
  DEFAULT_HH_FALLBACKS,
  DEFAULT_HH_SERP_SELECTORS,
  parseSerpCardsFromDom,
} from './selectors'
import { getSelectors, type HhSelectorPack } from './selectors-config'

export const SERP_VACANCIES_MARKERS = [',"vacancies":', '"vacancies":'] as const

export type SerpParseMethod = 'serp_json' | 'config' | 'default'

export type SerpListingItem = {
  vacancy_id: string
  title: string
  company: string
  salary: string
  location: string
  url: string
  letter_required_hint: boolean
  letter_required: boolean
  already_responded_hint: boolean
  area: string
  work_schedule: string
  employer_id: string | null
  total_responses_count: number | null
  competition: string | null
  source: string
  el?: Element | null
  parse_method?: SerpParseMethod
}

export type SerpListingResult = {
  items: SerpListingItem[]
  method: SerpParseMethod | null
}

function decodeHtmlEntities(raw: string): string {
  const collapsed = raw.replace(/\\\\&#34;/g, '\\&#34;')
  if (typeof document !== 'undefined') {
    try {
      const ta = document.createElement('textarea')
      ta.innerHTML = collapsed
      return ta.value
    } catch {
      /* linkedom / detached */
    }
  }
  return collapsed
    .replace(/&#34;/g, '"')
    .replace(/&#x22;/gi, '"')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
}

function sliceJsonValue(source: string, start: number): string | null {
  const pairs: Record<string, string> = { '[': ']', '{': '}' }
  if (!(source[start] in pairs)) return null
  const stack: string[] = []
  let inStr = false
  let escape = false
  for (let i = start; i < source.length; i++) {
    const ch = source[i]
    if (inStr) {
      if (escape) {
        escape = false
        continue
      }
      if (ch === '\\') {
        escape = true
        continue
      }
      if (ch === '"') inStr = false
      continue
    }
    if (ch === '"') {
      inStr = true
      continue
    }
    if (ch === '[' || ch === '{') stack.push(pairs[ch])
    else if (ch === ']' || ch === '}') {
      if (stack.pop() !== ch) return null
      if (!stack.length) return source.slice(start, i + 1)
    }
  }
  return null
}

function compensationText(comp: Record<string, unknown> | null | undefined): string {
  if (!comp) return ''
  const parts: string[] = []
  for (const key of ['from', 'to'] as const) {
    const val = comp[key]
    if (val != null) parts.push(String(val))
  }
  const currency = (comp.currencyCode || comp.currency) as string | undefined
  if (parts.length) {
    let s = parts.length === 2 ? parts.join(' – ') : parts[0]
    if (currency) s = `${s} ${currency}`
    return s
  }
  return String(comp.text || comp['@summary'] || '')
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }
  return null
}

function mapVacancyDict(raw: unknown): SerpListingItem | null {
  const obj = asRecord(raw)
  if (!obj) return null
  const vid = obj.vacancyId ?? obj.id
  if (vid == null) return null
  const vacancy_id = String(vid)
  const links = asRecord(obj.links) || {}
  const url = String(
    links.desktop || links.mobile || `https://hh.ru/vacancy/${vacancy_id}`,
  )
  const company = asRecord(obj.company) || {}
  const company_name = String(company.name || company['@title'] || company.title || '')
  const employerRaw = company.id
  const employer_id = employerRaw == null ? null : String(employerRaw)
  const area = asRecord(obj.area) || {}
  const area_name = String(area.name || area['@title'] || '')
  let letter = obj['@responseLetterRequired']
  if (letter === undefined) letter = obj.responseLetterRequired
  const letterRequired = letter == null ? false : Boolean(letter)
  const totalRaw = obj.totalResponsesCount
  const total_responses_count =
    typeof totalRaw === 'number' && Number.isFinite(totalRaw) ? totalRaw : null

  return {
    vacancy_id,
    title: String(obj.name || obj.title || '').trim(),
    company: company_name.trim(),
    salary: compensationText(asRecord(obj.compensation)),
    location: area_name.trim(),
    url: url.split('?')[0],
    letter_required_hint: letterRequired,
    letter_required: letterRequired,
    already_responded_hint: false,
    area: area_name.trim(),
    work_schedule: String(obj['@workSchedule'] || obj.workSchedule || ''),
    employer_id,
    total_responses_count,
    competition: competitionLevel(total_responses_count),
    source: 'serp_json',
    el: null,
    parse_method: 'serp_json',
  }
}

/** Pure HTML string → vacancy list. Same contract as Python `extract_vacancies_from_html`. */
export function extractSerpVacanciesFromHtml(html: string): SerpListingItem[] {
  if (!html) return []
  const decoded = decodeHtmlEntities(html)
  for (const marker of SERP_VACANCIES_MARKERS) {
    const idx = decoded.indexOf(marker)
    if (idx < 0) continue
    let cursor = idx + marker.length
    while (cursor < decoded.length && /\s/.test(decoded[cursor])) cursor += 1
    const slice = sliceJsonValue(decoded, cursor)
    if (!slice) continue
    try {
      const rawList = JSON.parse(slice)
      if (!Array.isArray(rawList)) continue
      const out: SerpListingItem[] = []
      for (const item of rawList) {
        const mapped = mapVacancyDict(item)
        if (mapped) out.push(mapped)
      }
      if (out.length) return out
    } catch {
      /* try next marker */
    }
  }
  return []
}

function serializeRoot(root: Document | Element): string {
  const el = root as Element
  const tag = (el.tagName || '').toUpperCase()
  if (tag === 'SCRIPT' || tag === 'TEMPLATE') {
    return el.textContent || el.innerHTML || ''
  }
  const parts: string[] = []
  const scope: ParentNode = (root as Document).documentElement || el
  try {
    for (const node of Array.from(scope.querySelectorAll('*'))) {
      const attrs = (node as Element).attributes
      if (!attrs) continue
      for (const attr of Array.from(attrs)) {
        const val = attr.value || ''
        if (val.length > 20 && (val.includes('vacancies') || val.includes('vacancyId'))) {
          parts.push(val)
        }
      }
    }
  } catch {
    /* querySelectorAll на обрывке */
  }
  for (const node of Array.from(scope.querySelectorAll('script:not([src]), template'))) {
    parts.push((node as HTMLElement).textContent || (node as HTMLElement).innerHTML || '')
  }
  const docEl = (root as Document).documentElement
  if (docEl?.outerHTML) parts.push(docEl.outerHTML)
  else parts.push(el.outerHTML || el.innerHTML || '')
  return parts.join('\n')
}

/** Live document (or a specific script/template node) — no network. */
export function extractSerpVacanciesFromDom(
  root: Document | Element = document,
): SerpListingItem[] {
  return extractSerpVacanciesFromHtml(serializeRoot(root))
}

function jsonLooksStale(jsonIds: Set<string>, domIds: Set<string>): boolean {
  if (!jsonIds.size || !domIds.size) return false
  for (const id of jsonIds) {
    if (domIds.has(id)) return false
  }
  return true
}

function attachDomEls(
  jsonItems: SerpListingItem[],
  domItems: SerpListingItem[],
): SerpListingItem[] {
  const byId = new Map<string, Element>()
  for (const card of domItems) {
    if (card.el && card.vacancy_id) byId.set(card.vacancy_id, card.el)
  }
  if (!byId.size) return jsonItems
  return jsonItems.map((item) => ({
    ...item,
    el: byId.get(item.vacancy_id) || item.el || null,
  }))
}

function withMethod(items: SerpListingItem[], method: SerpParseMethod): SerpListingItem[] {
  return items.map((item) => ({ ...item, parse_method: method }))
}

/**
 * Plan 4.2 chain: embedded JSON → DOM by config pack → DOM by baked-in defaults.
 * Stale JSON (disjoint ids vs visible cards) is skipped — SPA left page-1 blob in the document.
 */
export function parseSerpListingFromDom(
  root: Document | Element = document,
  sel: HhSelectorPack = getSelectors(),
): SerpListingResult {
  const jsonItems = extractSerpVacanciesFromDom(root)
  const configItems = parseSerpCardsFromDom(root, sel) as SerpListingItem[]
  let defaultItems: SerpListingItem[] = []
  if (!configItems.length && sel.origin !== 'builtin') {
    defaultItems = parseSerpCardsFromDom(root, {
      ...sel,
      serp: DEFAULT_HH_SERP_SELECTORS,
      fallbacks: DEFAULT_HH_FALLBACKS,
    }) as SerpListingItem[]
  }

  const domItems = configItems.length ? configItems : defaultItems
  const jsonIds = new Set(jsonItems.map((i) => i.vacancy_id))
  const domIds = new Set(domItems.map((i) => i.vacancy_id))

  if (jsonItems.length && !jsonLooksStale(jsonIds, domIds)) {
    return { items: attachDomEls(jsonItems, domItems), method: 'serp_json' }
  }
  if (configItems.length) {
    const method: SerpParseMethod = sel.origin === 'builtin' ? 'default' : 'config'
    return { items: withMethod(configItems, method), method }
  }
  if (defaultItems.length) {
    return { items: withMethod(defaultItems, 'default'), method: 'default' }
  }
  return { items: [], method: null }
}
