/**
 * GM-5.1: парсинг «Мои отклики» getmatch.ru (`/applications`).
 * DOM-референс: plans/«Отклики — getmatch.html» (2026-07-06).
 */

import { extractGetmatchVacancyIdFromUrl, GM_VACANCY_ID_PREFIX } from './selectors-getmatch'

const FUNNEL_APPLIED = 'Отклик'
const FUNNEL_REJECTED = 'Отказ'
const FUNNEL_SCREENING = 'Скрининг'

/** Вакансии без активности дольше этого срока → «Отказ» (воронка). */
export const STALE_INTERACTION_DAYS = 90

export type GetmatchApplicationStatus = 'waiting' | 'approved' | 'rejected' | 'unknown'

export type ParsedGetmatchApplication = {
  vacancy_id: string
  title: string
  company: string
  salary: string
  url: string
  gm_status_raw: string
  gm_meta_status: string
  gm_status: GetmatchApplicationStatus
  is_archived: boolean
  is_stale: boolean
  skip_stage_update: boolean
  applied_at: string | null
  employer_viewed: boolean | null
  hh_status_raw: string
  hh_status: string
  funnel_status_preview: string
  needs_interview_tracking: boolean
  sync_state?: string
  is_discrepancy?: boolean
  current_status?: string | null
  needs_vacancy_text?: boolean
}

const GM_APP_SELECTORS = {
  card: 'article[class*="applicationCard_card"]',
  titleLink: 'a[class*="applicationCard_titleLink"], a[href*="/vacancies/"]',
  subtitle: '[class*="applicationCard_subtitle"]',
  salary: '[class*="applicationCard_salary"]',
  /** Основной статус в statusGroup (не metaStatus). */
  status:
    '[class*="applicationCard_statusGroup"] > span[class*="applicationCard_status__"]:not([class*="metaStatus"])',
  metaStatus: '[class*="applicationCard_metaStatus"]',
  date: '[class*="applicationCard_date"]',
  logo: 'img[class*="applicationCard_logo"]',
}

const RU_MONTH_PREFIXES: [string, number][] = [
  ['янв', 0],
  ['фев', 1],
  ['мар', 2],
  ['апр', 3],
  ['мая', 4],
  ['май', 4],
  ['июн', 5],
  ['июл', 6],
  ['авг', 7],
  ['сен', 8],
  ['окт', 9],
  ['ноя', 10],
  ['дек', 11],
]

function queryAll(root: ParentNode, selector: string): Element[] {
  try {
    return Array.from(root.querySelectorAll(selector))
  } catch {
    return []
  }
}

function queryText(root: ParentNode, selector: string): string {
  const el = root.querySelector(selector)
  return (el?.textContent || '').replace(/\s+/g, ' ').trim()
}

function formatAppliedAt(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** Дата с карточки → YYYY-MM-DD HH:MM (как negotiations). */
export function normalizeGetmatchAppliedAt(raw: string | null | undefined): string | null {
  if (!raw || !String(raw).trim()) return null
  const s = String(raw)
    .trim()
    .replace(/\u00a0/g, ' ')
    .replace(/\s*г\.?\s*$/i, '')
    .trim()
  const low = s.toLowerCase()
  const now = new Date()
  if (low === 'сегодня' || low === 'today') return formatAppliedAt(now)
  if (low === 'вчера' || low === 'yesterday') {
    const d = new Date(now)
    d.setDate(d.getDate() - 1)
    return formatAppliedAt(d)
  }
  const dot = s.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2}))?/)
  if (dot) {
    const d = new Date(
      Number(dot[3]),
      Number(dot[2]) - 1,
      Number(dot[1]),
      Number(dot[4] || 12),
      Number(dot[5] || 0),
    )
    if (!Number.isNaN(d.getTime())) return formatAppliedAt(d)
  }
  const ru = s.match(/(\d{1,2})\s+([а-яёa-z]+)(?:\s+(\d{4}))?/i)
  if (ru) {
    const day = Number(ru[1])
    const monTxt = ru[2].toLowerCase()
    const year = Number(ru[3] || now.getFullYear())
    for (const [prefix, m] of RU_MONTH_PREFIXES) {
      if (monTxt.startsWith(prefix)) {
        const d = new Date(year, m, day, 12, 0)
        if (!Number.isNaN(d.getTime())) return formatAppliedAt(d)
        break
      }
    }
  }
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.replace('T', ' ').slice(0, 16)
  return s.slice(0, 19)
}

function parseAppliedAtDate(raw: string | null | undefined): Date | null {
  const norm = normalizeGetmatchAppliedAt(raw)
  if (!norm) return null
  const iso = norm.length >= 10 ? norm.slice(0, 10) : norm
  const d = new Date(`${iso}T12:00:00`)
  return Number.isNaN(d.getTime()) ? null : d
}

/** Последнее взаимодействие старше порога → архив (не участвует в активной воронке). */
export function isStaleInteraction(
  applied_at: string | null | undefined,
  days = STALE_INTERACTION_DAYS,
): boolean {
  const d = parseAppliedAtDate(applied_at)
  if (!d) return false
  const cutoff = new Date()
  cutoff.setDate(cutoff.getDate() - days)
  cutoff.setHours(0, 0, 0, 0)
  return d < cutoff
}

export function cleanApplicationTitle(title: string): string {
  return String(title || '')
    .replace(/\s*\(в\s+архиве\)\s*/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

export function gmStatusDisplayLabel(gmStatus: GetmatchApplicationStatus): string {
  if (gmStatus === 'rejected') return 'Отказ'
  if (gmStatus === 'approved') return 'Одобрение'
  if (gmStatus === 'waiting') return 'Ожидание'
  return 'Неизвестно'
}

function parseStatusRaw(text: string): GetmatchApplicationStatus {
  const t = String(text || '').toLowerCase()
  if (/отказ/.test(t)) return 'rejected'
  if (/одобр/.test(t)) return 'approved'
  if (/ожид/.test(t)) return 'waiting'
  return 'unknown'
}

function detectArchived(metaStatus: string, cardText: string): boolean {
  const blob = `${metaStatus} ${cardText}`.toLowerCase()
  return /вакансия\s+снята|снята\s+с\s+публикац|в\s+архив|archived/.test(blob)
}

function detectEmployerViewed(metaStatus: string): boolean | null {
  const t = String(metaStatus || '').toLowerCase()
  if (!t) return null
  if (/не\s+просмотрен/.test(t)) return false
  if (/просмотрен/.test(t)) return true
  return null
}

/** getmatch UI → hh_status + funnel (бэкенд negotiations-sync). */
export function mapGetmatchStatusToFunnel(
  gmStatus: GetmatchApplicationStatus,
  metaStatus: string,
  isArchived: boolean,
): {
  funnel_status_preview: string
  hh_status: string
  hh_status_raw: string
  skip_stage_update: boolean
  employer_viewed: boolean | null
  needs_interview_tracking: boolean
} {
  const statusLabel =
    gmStatus === 'rejected'
      ? 'Отказ'
      : gmStatus === 'approved'
        ? 'Одобрение'
        : gmStatus === 'waiting'
          ? 'Ожидание'
          : 'Неизвестно'
  const hh_status_raw = [statusLabel, metaStatus].filter(Boolean).join(' · ')
  const employer_viewed = detectEmployerViewed(metaStatus)

  if (gmStatus === 'rejected') {
    return {
      funnel_status_preview: FUNNEL_REJECTED,
      hh_status: 'rejected',
      hh_status_raw,
      skip_stage_update: false,
      employer_viewed: employer_viewed ?? true,
      needs_interview_tracking: false,
    }
  }

  if (gmStatus === 'approved') {
    if (isArchived) {
      return {
        funnel_status_preview: FUNNEL_APPLIED,
        hh_status: 'viewed_by_employer',
        hh_status_raw,
        skip_stage_update: true,
        employer_viewed: employer_viewed ?? true,
        needs_interview_tracking: false,
      }
    }
    return {
      funnel_status_preview: FUNNEL_SCREENING,
      hh_status: 'invitation',
      hh_status_raw,
      skip_stage_update: false,
      employer_viewed: employer_viewed ?? true,
      needs_interview_tracking: false,
    }
  }

  if (gmStatus === 'waiting') {
    // metaStatus «просмотрен/не просмотрен» может отсутствовать — тогда факт просмотра
    // неизвестен, и кодировать его как «не просмотрено» (не-просмотр) нельзя: это ложный признак.
    const viewed_hh =
      employer_viewed === true
        ? 'viewed_by_employer'
        : employer_viewed === false
          ? 'not_viewed_by_employer'
          : 'unknown'
    return {
      funnel_status_preview: FUNNEL_APPLIED,
      hh_status: viewed_hh,
      hh_status_raw,
      skip_stage_update: isArchived,
      employer_viewed,
      needs_interview_tracking: false,
    }
  }

  return {
    funnel_status_preview: FUNNEL_APPLIED,
    hh_status: 'unknown',
    hh_status_raw,
    skip_stage_update: isArchived,
    employer_viewed,
    needs_interview_tracking: false,
  }
}

function parseCompanyFromSubtitle(subtitle: string): string {
  const raw = String(subtitle || '').trim()
  const m = raw.match(/^в\s+(.+)$/i)
  return m ? m[1].trim() : raw
}

function resolveApplicationUrl(link: HTMLAnchorElement | null): string {
  if (!link) return ''
  const raw = link.getAttribute('href') || link.href || ''
  try {
    return new URL(raw, 'https://getmatch.ru').href.split('?')[0]
  } catch {
    return raw.split('?')[0]
  }
}

function vacancyIdFromLink(link: HTMLAnchorElement | null): string | null {
  if (!link) return null
  const raw = link.getAttribute('href') || link.href || ''
  return extractGetmatchVacancyIdFromUrl(raw)
}

function parseCompanyFromCard(cardEl: Element, subtitle: string): string {
  const fromSubtitle = parseCompanyFromSubtitle(subtitle)
  if (fromSubtitle) return fromSubtitle
  const logo = cardEl.querySelector(GM_APP_SELECTORS.logo) as HTMLImageElement | null
  const alt = (logo?.getAttribute('alt') || '').trim()
  return alt || ''
}

function parseStatusFromCard(cardEl: Element): string {
  const statusEl =
    cardEl.querySelector(GM_APP_SELECTORS.status) ||
    cardEl.querySelector('[class*="applicationCard_statusGroup"] span')
  const direct = (statusEl?.textContent || '').replace(/\s+/g, ' ').trim()
  if (direct && !/просмотрен|работодател/i.test(direct)) return direct

  const group = cardEl.querySelector('[class*="applicationCard_statusGroup"]')
  if (group) {
    for (const span of Array.from(group.querySelectorAll('span'))) {
      const cls = span.className || ''
      if (cls.includes('metaStatus')) continue
      const t = (span.textContent || '').replace(/\s+/g, ' ').trim()
      if (t && /^(ожидан|одобр|отказ)/i.test(t)) return t
    }
  }

  const blob = (cardEl.textContent || '').replace(/\s+/g, ' ')
  if (/\bотказ\b/i.test(blob)) return 'Отказ'
  if (/\bодобрен/i.test(blob)) return 'Одобрение'
  if (/\bожидан/i.test(blob)) return 'Ожидание'
  return ''
}

export function parseGetmatchApplicationCard(cardEl: Element): ParsedGetmatchApplication | null {
  if (!cardEl) return null

  const titleLink = cardEl.querySelector(GM_APP_SELECTORS.titleLink) as HTMLAnchorElement | null
  const vacancy_id = vacancyIdFromLink(titleLink)
  if (!vacancy_id) return null

  const url = resolveApplicationUrl(titleLink)
  const rawTitle = (titleLink?.textContent || '').replace(/\s+/g, ' ').trim()
  const title = cleanApplicationTitle(rawTitle)
  const subtitle = queryText(cardEl, GM_APP_SELECTORS.subtitle)
  const company = parseCompanyFromCard(cardEl, subtitle)
  const salary = queryText(cardEl, GM_APP_SELECTORS.salary)
  const gm_status_raw = parseStatusFromCard(cardEl)
  const gm_meta_status = queryText(cardEl, GM_APP_SELECTORS.metaStatus)
  const cardText = (cardEl.textContent || '').replace(/\s+/g, ' ')
  const gm_status = parseStatusRaw(gm_status_raw)
  const is_archived = detectArchived(gm_meta_status, cardText) || /\(в архиве\)/i.test(rawTitle)
  const applied_at = normalizeGetmatchAppliedAt(queryText(cardEl, GM_APP_SELECTORS.date))
  const is_stale = isStaleInteraction(applied_at)

  if (is_stale) {
    const statusLabel = gmStatusDisplayLabel(gm_status)
    const hh_status_raw = [statusLabel, gm_meta_status].filter(Boolean).join(' · ')
    return {
      vacancy_id,
      title,
      company,
      salary,
      url,
      gm_status_raw: gm_status_raw || statusLabel,
      gm_meta_status,
      gm_status,
      is_archived: true,
      is_stale: true,
      applied_at,
      funnel_status_preview: FUNNEL_REJECTED,
      hh_status: 'unknown',
      hh_status_raw,
      skip_stage_update: false,
      employer_viewed: detectEmployerViewed(gm_meta_status),
      needs_interview_tracking: false,
    }
  }

  const mapped = mapGetmatchStatusToFunnel(gm_status, gm_meta_status, is_archived)

  return {
    vacancy_id,
    title,
    company,
    salary,
    url,
    gm_status_raw,
    gm_meta_status,
    gm_status,
    is_archived,
    is_stale: false,
    applied_at,
    ...mapped,
  }
}

/** Fingerprint списка откликов — не дергаем preview, пока DOM не изменился. */
export function getmatchApplicationsDomFingerprint(root: Document | Element = document): string {
  const parts: string[] = [getmatchApplicationsPageKey()]
  for (const card of queryAll(root, GM_APP_SELECTORS.card)) {
    const link = card.querySelector(GM_APP_SELECTORS.titleLink) as HTMLAnchorElement | null
    const id = vacancyIdFromLink(link) || ''
    const status = parseStatusFromCard(card)
    parts.push(`${id}|${status}`)
  }
  if (parts.length === 1) {
    for (const link of queryAll(root, GM_APP_SELECTORS.titleLink)) {
      parts.push(vacancyIdFromLink(link as HTMLAnchorElement) || link.getAttribute('href') || '')
    }
  }
  return parts.join(';')
}

export function parseGetmatchApplicationCardsFromDom(root: Document | Element = document): ParsedGetmatchApplication[] {
  const byId = new Map<string, ParsedGetmatchApplication>()
  for (const card of queryAll(root, GM_APP_SELECTORS.card)) {
    const item = parseGetmatchApplicationCard(card)
    if (item) byId.set(item.vacancy_id, item)
  }

  if (byId.size === 0) {
    for (const link of queryAll(root, GM_APP_SELECTORS.titleLink)) {
      const card =
        link.closest('article') ||
        link.closest('[class*="applicationCard"]') ||
        link.parentElement?.parentElement
      if (!card) continue
      const item = parseGetmatchApplicationCard(card)
      if (item) byId.set(item.vacancy_id, item)
    }
  }

  return Array.from(byId.values())
}

/** Числовой `vacancy.id` (или url `/vacancies/{id}-…`) из JSON-элемента → `gm_{id}` или null. */
function vacancyIdFromJsonVacancy(vac: Record<string, unknown> | null): string | null {
  if (!vac) return null
  const id = vac.id
  if (typeof id === 'number' && Number.isFinite(id)) return `${GM_VACANCY_ID_PREFIX}${Math.trunc(id)}`
  if (typeof id === 'string' && /^\d+$/.test(id.trim())) return `${GM_VACANCY_ID_PREFIX}${id.trim()}`
  const url = String(vac.url ?? '')
  return extractGetmatchVacancyIdFromUrl(url)
}

function strValue(raw: unknown): string {
  if (raw == null) return ''
  if (typeof raw === 'string') return raw.replace(/\s+/g, ' ').trim()
  if (typeof raw === 'number' || typeof raw === 'boolean') return String(raw)
  return ''
}

/** Статус JSON-API `/api/applications/candidate` (`new|approved|rejected`) → внутренний токен
 *  DOM-парсера (`waiting|approved|rejected`). `new` = «Не просмотрен» = ожидание. */
function mapJsonStatusToGmStatus(status: unknown): GetmatchApplicationStatus {
  const t = String(status ?? '').toLowerCase()
  if (t === 'approved' || t === 'одобр') return 'approved'
  if (t === 'rejected' || t === 'отказ') return 'rejected'
  if (t === 'new' || t === 'waiting' || t === 'awaiting' || t === 'не просмотрен') return 'waiting'
  return 'unknown'
}

function companyFromJsonVacancy(vac: Record<string, unknown> | null): string {
  if (!vac) return ''
  const c = vac.company
  if (c && typeof c === 'object' && !Array.isArray(c)) {
    const name = strValue((c as Record<string, unknown>).name)
    if (name) return name
  }
  return strValue(vac.company_name)
}

function urlFromJsonVacancy(vac: Record<string, unknown> | null, vacancyId: string | null): string {
  const href = vac ? strValue(vac.url) : ''
  if (href) {
    try {
      return new URL(href, 'https://getmatch.ru').href.split('?')[0]
    } catch {
      return href.split('?')[0]
    }
  }
  const numeric = vacancyId?.replace(GM_VACANCY_ID_PREFIX, '')
  return numeric ? `https://getmatch.ru/vacancies/${numeric}` : ''
}

function salaryFromJsonItem(obj: Record<string, unknown>): string {
  const parts: string[] = []
  const min = obj.salary_min
  const comfort = obj.salary_comfort
  const currency = strValue(obj.salary_currency)
  const num = typeof comfort === 'number' ? comfort : typeof min === 'number' ? min : null
  if (num != null) parts.push(String(num))
  if (currency) parts.push(currency)
  return parts.join(' ')
}

/** Один отклик из JSON-ответа `/api/applications/candidate?section=all`. Статусная таксономия
 *  API — `status: new|approved|rejected` + `status_readable` («Не просмотрен»/«Одобрен»/«Отказ»);
 *  «вакансия снята» — `vacancy.is_active === false` (аналог DOM-признака `в архиве`). */
export function parseGetmatchApplicationFromJsonItem(
  item: unknown,
): ParsedGetmatchApplication | null {
  if (!item || typeof item !== 'object' || Array.isArray(item)) return null
  const obj = item as Record<string, unknown>

  const vac =
    obj.vacancy && typeof obj.vacancy === 'object' && !Array.isArray(obj.vacancy)
      ? (obj.vacancy as Record<string, unknown>)
      : null

  const vacancy_id = vacancyIdFromJsonVacancy(vac)
  if (!vacancy_id) return null

  const gm_status = mapJsonStatusToGmStatus(obj.status)
  const gm_meta_status = strValue(obj.status_readable)
  const is_archived = vac?.is_active === false
  const applied_at = normalizeGetmatchAppliedAt(strValue(obj.applied_at))
  const is_stale = isStaleInteraction(applied_at)

  const title = strValue(vac?.position ?? obj.position)
  const company = companyFromJsonVacancy(vac)
  const salary = salaryFromJsonItem(obj)
  const url = urlFromJsonVacancy(vac, vacancy_id)

  if (is_stale) {
    const statusLabel = gmStatusDisplayLabel(gm_status)
    const hh_status_raw = [statusLabel, gm_meta_status].filter(Boolean).join(' · ')
    return {
      vacancy_id,
      title,
      company,
      salary,
      url,
      gm_status_raw: statusLabel,
      gm_meta_status,
      gm_status,
      is_archived: true,
      is_stale: true,
      applied_at,
      funnel_status_preview: FUNNEL_REJECTED,
      hh_status: 'unknown',
      hh_status_raw,
      skip_stage_update: false,
      employer_viewed: detectEmployerViewed(gm_meta_status),
      needs_interview_tracking: false,
    }
  }

  const mapped = mapGetmatchStatusToFunnel(gm_status, gm_meta_status, is_archived)

  return {
    vacancy_id,
    title,
    company,
    salary,
    url,
    gm_status_raw: gm_status,
    gm_meta_status,
    gm_status,
    is_archived,
    is_stale: false,
    applied_at,
    ...mapped,
  }
}

/** Список откликов из JSON-ответа `/api/applications/candidate` (массив `applications`). */
export function parseGetmatchApplicationsFromJson(payload: unknown): ParsedGetmatchApplication[] {
  let list: unknown[] = []
  if (Array.isArray(payload)) {
    list = payload
  } else if (payload && typeof payload === 'object') {
    const obj = payload as Record<string, unknown>
    if (Array.isArray(obj.applications)) list = obj.applications as unknown[]
    else if (Array.isArray(obj.items)) list = obj.items as unknown[]
  }
  const byId = new Map<string, ParsedGetmatchApplication>()
  for (const item of list) {
    const parsed = parseGetmatchApplicationFromJsonItem(item)
    if (parsed) byId.set(parsed.vacancy_id, parsed)
  }
  return Array.from(byId.values())
}

/** Отпечаток JSON-списка откликов — не дёргаем preview/sync, пока список не изменился. */
export function getmatchApplicationsJsonFingerprint(payload: unknown): string {
  const parts: string[] = [getmatchApplicationsPageKey()]
  const items = parseGetmatchApplicationsFromJson(payload)
  for (const item of items) {
    parts.push(`${item.vacancy_id}|${item.gm_status}`)
  }
  return parts.join(';')
}

/** Ключ страницы для SPA (pathname + query — фильтры getmatch). */
export function getmatchApplicationsPageKey(url = location.href): string {
  try {
    const u = new URL(String(url), 'https://getmatch.ru')
    return `${u.pathname}|${u.search}`
  } catch {
    return `${String(url).split('#')[0]}|search=`
  }
}
